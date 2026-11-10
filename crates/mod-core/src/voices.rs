//! Dubbing: the `voices.dat` slot table, its journal and the apply/restore transaction.
//!
//! The archive is ~150 MB and every step is hash-verified, so the hot paths are
//! organized around how many times those bytes are read: verification-only
//! reads are streamed, and independent reads run on separate threads.

use crate::{
    EXE_WIDESCREEN_SHA256, GameInfo, MANAGER, Result, VOICES_SHA256, assets, external,
    fsx::{
        EXE_LIMIT, atomic_write, chain, io, lock_operation, plain, read, sha, sha_file, write_new,
    },
    graphics,
    operation::{OperationControl, PHASES, Progress},
    process::ensure_closed,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fs::{self, File},
    path::{Path, PathBuf},
    thread,
};

const TABLE: usize = 0xfc210;
const COUNT: usize = 479;
const VOICES_BYTES: u64 = 152_028_822;
const VOICES: &str = "voices.dat";
const BACKUP: &str = "voices.original.dat";
const STATE: &str = "state.json";
const PACKAGE_IDS: [&str; 3] = ["sr1-ptbr-pilot", "sr1-ptbr-full", "sr1-ptbr-review"];
/// Payload verification is I/O plus hashing; more threads than this stop helping.
const MAX_VERIFIERS: usize = 8;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Patch {
    id: usize,
    file: String,
    sha256: String,
    length: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Coverage {
    replaced: usize,
    total: usize,
    complete: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    schema: u32,
    id: String,
    name: String,
    version: String,
    exe_sha256: String,
    source_sha256: String,
    result_sha256: String,
    patches: Vec<Patch>,
    coverage: Coverage,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PackageInfo {
    pub name: String,
    pub version: String,
    pub replaced: usize,
    pub total: usize,
    pub bytes: usize,
    pub localization: assets::AssetsInfo,
    pub graphics_available: bool,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Journal {
    schema: u32,
    phase: String,
    original_sha256: String,
    installed_sha256: String,
    manifest_sha256: String,
    replaced: usize,
}

/// Hashes that identify the supported base. Tests substitute synthetic fixtures.
struct Policy<'a> {
    exe: &'a str,
    voices: &'a str,
}

const BASE: Policy<'static> = Policy {
    exe: crate::EXE_SHA256,
    voices: VOICES_SHA256,
};

/// `(offset, length)` of each voice inside `voices.dat`.
type SlotTable = Vec<(usize, usize)>;

fn slots(exe: &[u8], bytes: usize) -> Result<SlotTable> {
    let data = exe
        .get(TABLE..TABLE + COUNT * 8)
        .ok_or("Executável sem tabela de vozes.")?;
    let mut cursor = 0;
    let mut entries = Vec::with_capacity(COUNT);
    for item in data.chunks_exact(8) {
        let offset = u32::from_le_bytes(item[..4].try_into().unwrap()) as usize;
        let length = u32::from_le_bytes(item[4..].try_into().unwrap()) as usize;
        if offset != cursor
            || length == 0
            || !offset.is_multiple_of(2)
            || !length.is_multiple_of(2)
            || length > bytes.saturating_sub(offset)
        {
            return Err("Tabela de vozes inválida.".into());
        }
        cursor += length;
        entries.push((offset, length));
    }
    if cursor != bytes {
        return Err("Tabela não cobre todo o arquivo de vozes.".into());
    }
    Ok(entries)
}

fn journal(game: &Path, policy: &Policy) -> Result<Option<Journal>> {
    let root = game.join(MANAGER);
    if !root.exists() {
        return Ok(None);
    }
    plain(&root)?;
    // UI/video/subtitle assets share this directory but own separate journals.
    let state_path = root.join(STATE);
    if !state_path.exists() {
        return Ok(None);
    }
    let state: Journal = serde_json::from_slice(&read(&state_path, 65_536)?)
        .map_err(|e| format!("Registro de instalação inválido: {e}"))?;
    if state.schema != 1
        || state.original_sha256 != policy.voices
        || state.replaced > COUNT
        || !PHASES.contains(&state.phase.as_str())
    {
        return Err("Registro de instalação incompatível. Nenhum arquivo foi restaurado.".into());
    }
    Ok(Some(state))
}

/// Canonical directory and executable bytes of a supported installation.
fn supported_exe(game: &Path, policy: &Policy) -> Result<(PathBuf, Vec<u8>)> {
    let game = game
        .canonicalize()
        .map_err(|error| format!("Pasta do jogo indisponível: {error}"))?;
    let exe = read(&game.join("kain2.exe"), EXE_LIMIT)?;
    let exe_hash = sha(&exe);
    if exe_hash != policy.exe && exe_hash != EXE_WIDESCREEN_SHA256 {
        return Err("Edição não suportada: hash de kain2.exe diferente da base validada.".into());
    }
    Ok((game, exe))
}

/// File contents together with their hash.
fn hashed(path: &Path) -> Result<(Vec<u8>, String)> {
    let bytes = read(path, VOICES_BYTES)?;
    let hash = sha(&bytes);
    Ok((bytes, hash))
}

fn joined<T>(result: thread::Result<Result<T>>) -> Result<T> {
    result.unwrap_or_else(|_| Err("Falha interna na verificação paralela.".into()))
}

#[derive(Clone, Copy)]
struct VoiceStatus {
    status: &'static str,
    replaced: usize,
    message: &'static str,
}

const ORIGINAL: VoiceStatus = VoiceStatus {
    status: "original",
    replaced: 0,
    message: "Base original compatível. Pronta para receber modificações.",
};

/// Classifies `voices.dat` against the base and the journal, straight from disk.
fn voice_status(game: &Path, exe: &[u8], policy: &Policy) -> Result<VoiceStatus> {
    let voices_path = game.join(VOICES);
    let backup_path = game.join(MANAGER).join(BACKUP);
    let state = journal(game, policy);
    // A journal that records an applied package predicts the slow case, where
    // both archives are compared. Only then are they loaded, and in parallel.
    let modified_expected = matches!(&state, Ok(Some(state))
        if state.installed_sha256 != policy.voices
            && matches!(state.phase.as_str(), "preparing" | "installed"))
        && backup_path.is_file();
    if !modified_expected {
        let (current, length) = sha_file(&voices_path, VOICES_BYTES)?;
        slots(exe, length as usize)?;
        let known = state.as_ref().map_err(Clone::clone)?.is_some();
        if current == policy.voices {
            return Ok(ORIGINAL);
        }
        if !known {
            return Err(
                "voices.dat foi modificado por outro processo ou mod. Arquivo preservado.".into(),
            );
        }
    }
    let (voices, backup) = thread::scope(|scope| {
        let backup = scope.spawn(|| hashed(&backup_path));
        (hashed(&voices_path), joined(backup.join()))
    });
    let (voices, current) = voices?;
    let table = slots(exe, voices.len())?;
    let state = state?;
    if current == policy.voices {
        return Ok(ORIGINAL);
    }
    let Some(state) = state else {
        return Err(
            "voices.dat foi modificado por outro processo ou mod. Arquivo preservado.".into(),
        );
    };
    let (backup, backup_hash) = backup?;
    if current != state.installed_sha256 || backup_hash != policy.voices {
        return Err(
            "Conflito: o áudio ou o backup foi alterado fora do instalador. Arquivos preservados."
                .into(),
        );
    }
    let replaced = table
        .iter()
        .filter(|&&(offset, length)| {
            voices[offset..offset + length] != backup[offset..offset + length]
        })
        .count();
    Ok(VoiceStatus {
        status: "installed",
        replaced,
        message: "Dublagem aplicada e verificada contra o backup.",
    })
}

/// Completes a voice status with the state of every other component.
fn game_info(game: &Path, voice: VoiceStatus) -> Result<GameInfo> {
    let localization = assets::inspect(game)?;
    let video_assets = assets::inspect_component(game, &assets::VIDEO)?;
    let video = external::ExternalInfo {
        id: "video".into(),
        installed: video_assets.videos > 0,
        files: video_assets.videos,
        message: if video_assets.videos > 0 {
            format!(
                "Vídeos PT-BR instalados ({} arquivo(s)); runtime não validado.",
                video_assets.videos
            )
        } else {
            "Vídeos PT-BR não instalados.".into()
        },
    };
    let graphics = graphics::inspect(game)?;
    let textures = external::inspect(game, &external::TEXTURES)?;
    let ui = external::inspect(game, &external::UI)?;
    Ok(GameInfo {
        path: game.to_string_lossy().into(),
        status: voice.status.into(),
        replaced: voice.replaced,
        total: COUNT,
        message: voice.message.into(),
        graphics_installed: graphics.installed,
        localization,
        video,
        graphics,
        textures,
        ui,
    })
}

fn inspect_with(game: &Path, policy: &Policy) -> Result<GameInfo> {
    let (game, exe) = supported_exe(game, policy)?;
    let voice = voice_status(&game, &exe, policy)?;
    game_info(&game, voice)
}

/// SHA-256 of the managed executable, so callers can report it without
/// depending on the hashing crate directly.
pub fn exe_sha256(game: &Path) -> Result<String> {
    Ok(sha_file(&game.join("kain2.exe"), EXE_LIMIT)?.0)
}

/// Reads and verifies one payload. `Ok(None)` marks a declaration that must be
/// rejected before any file named by it is opened.
fn load_payload(
    parent: &Path,
    patch: &Patch,
    declared: bool,
    source_hashes: Option<&[String]>,
) -> Result<Vec<u8>> {
    if !declared {
        return Err("ID duplicado/inválido ou caminho de pacote não permitido.".into());
    }
    let payload = read(&parent.join(&patch.file), 4 * 1024 * 1024)?;
    if payload.len() != patch.length || sha(&payload) != patch.sha256 {
        return Err("Áudio do pacote falhou na verificação de integridade.".into());
    }
    if source_hashes.and_then(|hashes| hashes.get(patch.id)) == Some(&patch.sha256) {
        return Err(format!(
            "Entrada {} contém o áudio inglês original; cobertura de dublagem inválida.",
            patch.id
        ));
    }
    Ok(payload)
}

fn package(manifest_path: &Path, policy: &Policy) -> Result<(Manifest, Vec<Vec<u8>>, String)> {
    // Canonical hashes contain no audio. Reject copied English payloads even
    // during package inspection, before an installation is selected.
    let source_hashes: Vec<String> =
        serde_json::from_str(include_str!("original_voice_hashes.json"))
            .map_err(|e| format!("Catálogo de integridade inválido: {e}"))?;
    let bytes = read(manifest_path, 1024 * 1024)?;
    let manifest: Manifest =
        serde_json::from_slice(&bytes).map_err(|e| format!("Manifesto inválido: {e}"))?;
    if manifest.schema != 1
        || !PACKAGE_IDS.contains(&manifest.id.as_str())
        || manifest.exe_sha256 != policy.exe
        || manifest.source_sha256 != policy.voices
        || manifest.patches.is_empty()
        || manifest.patches.len() > COUNT
        || manifest.coverage.replaced != manifest.patches.len()
        || manifest.coverage.total != COUNT
        || manifest.coverage.complete != (manifest.patches.len() == COUNT)
        || manifest.name.len() > 200
        || manifest.version.len() > 64
        || manifest.result_sha256.len() != 64
    {
        return Err("Pacote incompatível com a base ou cobertura declarada inválida.".into());
    }
    let parent = io(manifest_path
        .parent()
        .ok_or("Pacote sem pasta.")?
        .canonicalize())?;
    // Declarations are judged in order, so a duplicate is always the later entry.
    let mut seen = HashSet::new();
    let declared: Vec<bool> = manifest
        .patches
        .iter()
        .map(|patch| {
            patch.id < COUNT
                && seen.insert(patch.id)
                && patch.file == format!("voice-{:04}.pcm", patch.id)
        })
        .collect();
    let source_hashes = (policy.voices == VOICES_SHA256).then_some(source_hashes.as_slice());
    let workers = thread::available_parallelism()
        .map_or(1, usize::from)
        .min(MAX_VERIFIERS);
    let batch = manifest.patches.len().div_ceil(workers);
    let parent = parent.as_path();
    let verified: Vec<Result<Vec<u8>>> = thread::scope(|scope| {
        let tasks: Vec<_> = manifest
            .patches
            .chunks(batch)
            .zip(declared.chunks(batch))
            .map(|(patches, declared)| {
                scope.spawn(move || {
                    patches
                        .iter()
                        .zip(declared)
                        .map(|(patch, &declared)| {
                            load_payload(parent, patch, declared, source_hashes)
                        })
                        .collect::<Vec<_>>()
                })
            })
            .collect();
        tasks
            .into_iter()
            .flat_map(|task| {
                task.join()
                    .unwrap_or_else(|_| vec![Err("Falha interna na verificação do pacote.".into())])
            })
            .collect()
    });
    // The first failure in manifest order is reported, as a sequential scan would.
    let payloads = verified.into_iter().collect::<Result<Vec<_>>>()?;
    Ok((manifest, payloads, sha(&bytes)))
}

pub fn inspect_package(path: &Path) -> Result<PackageInfo> {
    let (manifest, payloads, _) = package(path, &BASE)?;
    let companion = path.with_file_name("assets.json");
    let localization = if companion.exists() {
        assets::inspect_package(&companion)?
    } else {
        assets::AssetsInfo::default()
    };
    let graphics_available = path.parent().is_some_and(|parent| {
        ["DDraw.dll", "D3DImm.dll", "dgVoodoo.conf"]
            .iter()
            .all(|name| parent.join("graphics").join(name).is_file())
    });
    Ok(PackageInfo {
        name: manifest.name,
        version: manifest.version,
        replaced: manifest.patches.len(),
        total: COUNT,
        bytes: payloads.iter().map(Vec::len).sum(),
        localization,
        graphics_available,
    })
}

/// Owner of the journal and backup; holds the installation lock while alive.
struct Manager {
    root: PathBuf,
    _lock: File,
}

impl Manager {
    fn open(game: &Path, policy: &Policy) -> Result<Self> {
        let lock = lock_operation(game)?;
        let manager = Self {
            root: game.join(MANAGER),
            _lock: lock,
        };
        if journal(game, policy)?.is_none() {
            manager.save(&Journal {
                schema: 1,
                phase: "original".into(),
                original_sha256: policy.voices.into(),
                installed_sha256: policy.voices.into(),
                manifest_sha256: String::new(),
                replaced: 0,
            })?;
        }
        Ok(manager)
    }

    fn save(&self, state: &Journal) -> Result<()> {
        atomic_write(
            &self.root.join(STATE),
            &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
        )
    }

    fn backup_path(&self) -> PathBuf {
        self.root.join(BACKUP)
    }

    /// Keeps an existing verified backup, or creates one from `source`, whose
    /// hash the caller has already computed.
    fn backup(&self, source: &[u8], source_hash: &str, policy: &Policy) -> Result<()> {
        let path = self.backup_path();
        if path.exists() {
            if sha_file(&path, VOICES_BYTES)?.0 != policy.voices {
                return Err("Backup existente diferente do original. Preservado.".into());
            }
            return Ok(());
        }
        if source_hash != policy.voices {
            return Err("Só é permitido criar backup de uma base original.".into());
        }
        write_new(&path, source)
    }
}

fn apply_with_control(
    game: &Path,
    manifest_path: &Path,
    policy: &Policy,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    progress(Progress::new(
        "verificacao",
        0,
        1,
        "Verificando jogo e pacote",
    ));
    // The package and the installed base are independent inputs: verify both at once.
    let (packaged, base) = thread::scope(|scope| {
        let packaged = scope.spawn(|| package(manifest_path, policy));
        let base = supported_exe(game, policy).and_then(|(game, exe)| {
            let (original, current) = hashed(&game.join(VOICES))?;
            let table = slots(&exe, original.len())?;
            Ok((game, exe, table, original, current))
        });
        (joined(packaged.join()), base)
    });
    let (manifest, payloads, manifest_hash) = packaged?;
    let (game, exe, table, original, current) = base?;
    ensure_closed(&game)?;
    if current != policy.voices {
        let state = journal(&game, policy)?.ok_or("Áudio alterado sem registro de instalação.")?;
        if current == state.installed_sha256 && manifest_hash == state.manifest_sha256 {
            drop(original);
            return game_info(&game, voice_status(&game, &exe, policy)?);
        }
        return Err("Restaure a instalação anterior antes de aplicar outro pacote. Conflitos foram preservados.".into());
    }
    let mut candidate = original.clone();
    let patch_count = manifest.patches.len();
    for (index, (patch, payload)) in manifest.patches.iter().zip(payloads.iter()).enumerate() {
        control.checkpoint()?;
        let (offset, length) = table[patch.id];
        if payload.len() != length {
            return Err("Áudio não tem o tamanho exato da entrada original.".into());
        }
        if payload == &original[offset..offset + length] {
            return Err(format!(
                "Entrada {} é idêntica ao áudio original. O pacote declara uma substituição inexistente.",
                patch.id
            ));
        }
        candidate[offset..offset + length].copy_from_slice(payload);
        progress(Progress::new(
            "preparacao-dublagem",
            index + 1,
            patch_count,
            format!("Preparando fala {} de {}", index + 1, patch_count),
        ));
    }
    drop(payloads);
    if sha(&candidate) != manifest.result_sha256 {
        return Err("Resultado do pacote difere do hash declarado.".into());
    }
    let manager = Manager::open(&game, policy)?;
    control.checkpoint()?;
    progress(Progress::new(
        "backup",
        0,
        1,
        "Criando e verificando backup",
    ));
    manager.backup(&original, &current, policy)?;
    drop(original);
    let mut state = Journal {
        schema: 1,
        phase: "preparing".into(),
        original_sha256: policy.voices.into(),
        installed_sha256: manifest.result_sha256,
        manifest_sha256: manifest_hash,
        replaced: patch_count,
    };
    manager.save(&state)?;
    progress(Progress::new("instalacao", 0, 1, "Aplicando dublagem"));
    control.checkpoint()?;
    ensure_closed(&game)?;
    let voices_path = game.join(VOICES);
    if sha_file(&voices_path, VOICES_BYTES)?.0 != current {
        return Err("Arquivo mudou durante a instalação. Preservado.".into());
    }
    atomic_write(&voices_path, &candidate)?;
    drop(candidate);
    // One pass from disk proves the installed archive and the backup, and is
    // also the inspection returned to the caller.
    let voice = voice_status(&game, &exe, policy)?;
    if voice.status != "installed" {
        return Err("Falha ao verificar o áudio instalado; backup preservado.".into());
    }
    state.phase = "installed".into();
    manager.save(&state)?;
    progress(Progress::new("concluido", 1, 1, "Dublagem verificada"));
    game_info(&game, voice)
}

fn restore_with_control(
    game: &Path,
    policy: &Policy,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    progress(Progress::new(
        "verificacao",
        0,
        1,
        "Verificando restauração",
    ));
    let (game, exe) = supported_exe(game, policy)?;
    let voices_path = game.join(VOICES);
    chain(&voices_path)?;
    let length = io(fs::metadata(&voices_path))?.len();
    if length > VOICES_BYTES {
        return Err("Arquivo excede o limite permitido.".into());
    }
    slots(&exe, length as usize)?;
    ensure_closed(&game)?;
    let mut state =
        journal(&game, policy)?.ok_or("Nenhuma instalação gerenciada para restaurar.")?;
    let manager = Manager::open(&game, policy)?;
    let backup_path = manager.backup_path();
    let (backup, current) = thread::scope(|scope| {
        let current = scope.spawn(|| sha_file(&voices_path, VOICES_BYTES));
        (hashed(&backup_path), joined(current.join()))
    });
    let (backup, backup_hash) = backup?;
    if backup_hash != policy.voices {
        return Err("Backup alterado. Restauração bloqueada.".into());
    }
    let (current_hash, _) = current?;
    if current_hash != policy.voices && current_hash != state.installed_sha256 {
        return Err(
            "Áudio alterado após a instalação. Restauração bloqueada; arquivos preservados.".into(),
        );
    }
    state.phase = "restoring".into();
    manager.save(&state)?;
    progress(Progress::new(
        "restauracao",
        0,
        1,
        "Restaurando áudio original",
    ));
    control.checkpoint()?;
    ensure_closed(&game)?;
    if sha_file(&voices_path, VOICES_BYTES)?.0 != current_hash {
        return Err("Arquivo mudou durante a restauração. Preservado.".into());
    }
    atomic_write(&voices_path, &backup)?;
    drop(backup);
    let voice = voice_status(&game, &exe, policy)?;
    if voice.status != "original" {
        return Err("Falha ao verificar a restauração.".into());
    }
    state.phase = "restored".into();
    manager.save(&state)?;
    progress(Progress::new(
        "concluido",
        1,
        1,
        "Original restaurado e verificado",
    ));
    game_info(&game, voice)
}

pub fn inspect_game(game: &Path) -> Result<GameInfo> {
    inspect_with(game, &BASE)
}

pub fn apply_package_with_control(
    game: &Path,
    manifest: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    apply_with_control(game, manifest, &BASE, control, progress)
}

pub fn apply_package(
    game: &Path,
    manifest: &Path,
    mut progress: impl FnMut(&str),
) -> Result<GameInfo> {
    apply_package_with_control(game, manifest, &OperationControl::default(), |p| {
        progress(&p.message)
    })
}

pub fn restore_game_with_control(
    game: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    restore_with_control(game, &BASE, control, progress)
}

pub fn restore_game(game: &Path, mut progress: impl FnMut(&str)) -> Result<GameInfo> {
    restore_game_with_control(game, &OperationControl::default(), |p| progress(&p.message))
}

#[cfg(test)]
fn apply_with(
    game: &Path,
    manifest_path: &Path,
    policy: &Policy,
    mut progress: impl FnMut(&str),
) -> Result<GameInfo> {
    apply_with_control(
        game,
        manifest_path,
        policy,
        &OperationControl::default(),
        |p| progress(&p.message),
    )
}

#[cfg(test)]
fn restore_with(game: &Path, policy: &Policy, mut progress: impl FnMut(&str)) -> Result<GameInfo> {
    restore_with_control(game, policy, &OperationControl::default(), |p| {
        progress(&p.message)
    })
}

#[cfg(test)]
mod tests;
