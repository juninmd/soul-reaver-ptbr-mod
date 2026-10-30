use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::{
        Condvar, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

pub mod assets;
pub mod external;
pub mod graphics;

pub const EXE_SHA256: &str = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a";
pub const EXE_WIDESCREEN_SHA256: &str =
    "396a757334daa8fdf8930de70a63929bbe0cb0d6bc3250ce5a2dd50056c1e243";
pub const VOICES_SHA256: &str = "e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5";
const TABLE: usize = 0xfc210;
const COUNT: usize = 479;
const VOICES_BYTES: u64 = 152_028_822;
const MANAGER: &str = ".soul-reaver-ptbr";
const FOV_OFFSET: usize = 0xeb354;
const FOV_ORIGINAL: [u8; 4] = [0x00, 0x00, 0x20, 0x3f];
const FOV_16_9: [u8; 4] = [0x00, 0x00, 0xf0, 0x3e];
pub type Result<T> = std::result::Result<T, String>;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    pub stage: String,
    pub current: usize,
    pub total: usize,
    pub message: String,
}

impl Progress {
    pub fn percent(&self) -> u8 {
        if self.total == 0 {
            return 0;
        }
        (((self.current.min(self.total) as u128 * 100) / self.total as u128).min(100)) as u8
    }
}

/// Cooperative control checked only at safe boundaries between work units.
#[derive(Default)]
pub struct OperationControl {
    canceled: AtomicBool,
    paused: Mutex<bool>,
    resumed: Condvar,
}

impl OperationControl {
    pub fn cancel(&self) {
        self.canceled.store(true, Ordering::Release);
        self.resumed.notify_all();
    }

    pub fn pause(&self) {
        *self.paused.lock().unwrap_or_else(|e| e.into_inner()) = true;
    }

    pub fn resume(&self) {
        *self.paused.lock().unwrap_or_else(|e| e.into_inner()) = false;
        self.resumed.notify_all();
    }

    pub fn is_paused(&self) -> bool {
        *self.paused.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn checkpoint(&self) -> Result<()> {
        let mut paused = self.paused.lock().unwrap_or_else(|e| e.into_inner());
        while *paused && !self.canceled.load(Ordering::Acquire) {
            let (next, _) = self
                .resumed
                .wait_timeout(paused, Duration::from_millis(200))
                .unwrap_or_else(|e| e.into_inner());
            paused = next;
        }
        if self.canceled.load(Ordering::Acquire) {
            Err("Operação cancelada entre unidades de trabalho.".into())
        } else {
            Ok(())
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GameInfo {
    pub path: String,
    pub status: String,
    pub replaced: usize,
    pub total: usize,
    pub message: String,
    #[serde(default)]
    pub graphics_installed: bool,
    #[serde(default)]
    pub localization: assets::AssetsInfo,
    #[serde(default)]
    pub video: external::ExternalInfo,
    #[serde(default)]
    pub graphics: graphics::GraphicsInfo,
    #[serde(default)]
    pub textures: external::ExternalInfo,
    #[serde(default)]
    pub ui: external::ExternalInfo,
}

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

struct Policy<'a> {
    exe: &'a str,
    voices: &'a str,
}
const BASE: Policy<'static> = Policy {
    exe: EXE_SHA256,
    voices: VOICES_SHA256,
};

fn sha(data: &[u8]) -> String {
    use std::fmt::Write;
    let mut out = String::with_capacity(64);
    for b in Sha256::digest(data) {
        let _ = write!(out, "{:02x}", b);
    }
    out
}
fn io<T>(value: std::io::Result<T>) -> Result<T> {
    value.map_err(|e| e.to_string())
}

fn plain(path: &Path) -> Result<()> {
    let metadata = io(fs::symlink_metadata(path))?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err("Links e junctions não são aceitos nos arquivos gerenciados.".into());
        }
    }
    if metadata.file_type().is_symlink() {
        return Err("Links não são aceitos nos arquivos gerenciados.".into());
    }
    Ok(())
}

fn read(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    plain(path)?;
    let file = io(File::open(path))?;
    if io(file.metadata())?.len() > maximum {
        return Err("Arquivo excede o limite permitido.".into());
    }
    let mut data = Vec::new();
    io(file.take(maximum + 1).read_to_end(&mut data))?;
    if data.len() as u64 > maximum {
        return Err("Arquivo cresceu durante a leitura.".into());
    }
    Ok(data)
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        plain(path)?;
    }
    let parent = path.parent().ok_or("Destino sem diretório pai.")?;
    plain(parent)?;
    let mut temporary = io(tempfile::NamedTempFile::new_in(parent))?;
    io(temporary.write_all(bytes))?;
    io(temporary.as_file().sync_all())?;
    temporary.persist(path).map_err(|e| e.to_string())?;
    Ok(())
}

fn slots(exe: &[u8], bytes: usize) -> Result<Vec<(usize, usize)>> {
    let data = exe
        .get(TABLE..TABLE + COUNT * 8)
        .ok_or("Executável sem tabela de vozes.")?;
    let mut cursor = 0;
    let mut entries = Vec::new();
    for item in data.chunks_exact(8) {
        let offset = u32::from_le_bytes(item[..4].try_into().unwrap()) as usize;
        let length = u32::from_le_bytes(item[4..].try_into().unwrap()) as usize;
        if offset != cursor
            || length == 0
            || offset % 2 != 0
            || length % 2 != 0
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
    let state_path = root.join("state.json");
    if !state_path.exists() {
        return Ok(None);
    }
    let state: Journal = serde_json::from_slice(&read(&state_path, 65_536)?)
        .map_err(|e| format!("Registro de instalação inválido: {e}"))?;
    if state.schema != 1
        || state.original_sha256 != policy.voices
        || state.replaced > COUNT
        || ![
            "original",
            "preparing",
            "installed",
            "restoring",
            "restored",
        ]
        .contains(&state.phase.as_str())
    {
        return Err("Registro de instalação incompatível. Nenhum arquivo foi restaurado.".into());
    }
    Ok(Some(state))
}

fn validated_game(game: &Path, policy: &Policy) -> Result<(PathBuf, Vec<u8>, Vec<u8>)> {
    let game = io(game.canonicalize())?;
    let exe = read(&game.join("kain2.exe"), 4 * 1024 * 1024)?;
    let exe_hash = sha(&exe);
    if exe_hash != policy.exe && exe_hash != EXE_WIDESCREEN_SHA256 {
        return Err("Edição não suportada: hash de kain2.exe diferente da base validada.".into());
    }
    let voices = read(&game.join("voices.dat"), VOICES_BYTES)?;
    slots(&exe, voices.len())?;
    Ok((game, exe, voices))
}

fn inspect_with(game: &Path, policy: &Policy) -> Result<GameInfo> {
    let (game, exe, voices) = validated_game(game, policy)?;
    let current = sha(&voices);
    let state = journal(&game, policy)?;
    let (status, replaced, message) = if current == policy.voices {
        (
            "original",
            0,
            "Base original compatível. Pronta para receber modificações.",
        )
    } else if let Some(state) = state {
        let backup = read(
            &game.join(MANAGER).join("voices.original.dat"),
            VOICES_BYTES,
        )?;
        if current != state.installed_sha256 || sha(&backup) != policy.voices {
            return Err("Conflito: o áudio ou o backup foi alterado fora do instalador. Arquivos preservados.".into());
        }
        let changed = slots(&exe, voices.len())?
            .iter()
            .filter(|&&(offset, length)| {
                voices[offset..offset + length] != backup[offset..offset + length]
            })
            .count();
        (
            "installed",
            changed,
            "Dublagem aplicada e verificada contra o backup.",
        )
    } else {
        return Err(
            "voices.dat foi modificado por outro processo ou mod. Arquivo preservado.".into(),
        );
    };
    let localization = assets::inspect(&game)?;
    let video_assets = assets::inspect_component(&game, &assets::VIDEO)?;
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
    let graphics = graphics::inspect(&game)?;
    let textures = external::inspect(&game, &external::TEXTURES)?;
    let ui = external::inspect(&game, &external::UI)?;
    let graphics_installed = graphics.installed;
    Ok(GameInfo {
        path: game.to_string_lossy().into(),
        status: status.into(),
        replaced,
        total: COUNT,
        message: message.into(),
        graphics_installed,
        localization,
        video,
        graphics,
        textures,
        ui,
    })
}

pub fn inspect_game(game: &Path) -> Result<GameInfo> {
    inspect_with(game, &BASE)
}

/// SHA-256 of the managed executable, so callers can report it without
/// depending on the hashing crate directly.
pub fn exe_sha256(game: &Path) -> Result<String> {
    Ok(sha(&read(&game.join("kain2.exe"), 4 * 1024 * 1024)?))
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
        || !["sr1-ptbr-pilot", "sr1-ptbr-full", "sr1-ptbr-review"].contains(&manifest.id.as_str())
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
    let mut seen = HashSet::new();
    let mut payloads = Vec::new();
    for patch in &manifest.patches {
        if patch.id >= COUNT
            || !seen.insert(patch.id)
            || patch.file != format!("voice-{:04}.pcm", patch.id)
        {
            return Err("ID duplicado/inválido ou caminho de pacote não permitido.".into());
        }
        let payload = read(&parent.join(&patch.file), 4 * 1024 * 1024)?;
        if payload.len() != patch.length || sha(&payload) != patch.sha256 {
            return Err("Áudio do pacote falhou na verificação de integridade.".into());
        }
        if policy.voices == VOICES_SHA256 && source_hashes.get(patch.id) == Some(&patch.sha256) {
            return Err(format!(
                "Entrada {} contém o áudio inglês original; cobertura de dublagem inválida.",
                patch.id
            ));
        }
        payloads.push(payload);
    }
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

struct Manager {
    root: PathBuf,
    _lock: File,
}
impl Manager {
    fn open(game: &Path, policy: &Policy) -> Result<Self> {
        let root = game.join(MANAGER);
        if !root.exists() {
            io(fs::create_dir(&root))?;
        }
        plain(&root)?;
        let path = root.join("operation.lock");
        if path.exists() {
            plain(&path)?;
        }
        let lock = io(OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path))?;
        lock.try_lock_exclusive()
            .map_err(|_| "Outra instalação está em andamento.".to_string())?;
        let manager = Self { root, _lock: lock };
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
            &self.root.join("state.json"),
            &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
        )
    }
    fn backup(&self, source: &[u8], policy: &Policy) -> Result<()> {
        let path = self.root.join("voices.original.dat");
        if path.exists() {
            if sha(&read(&path, VOICES_BYTES)?) != policy.voices {
                return Err("Backup existente diferente do original. Preservado.".into());
            }
        } else {
            if sha(source) != policy.voices {
                return Err("Só é permitido criar backup de uma base original.".into());
            }
            let mut file = io(OpenOptions::new().write(true).create_new(true).open(path))?;
            io(file.write_all(source))?;
            io(file.sync_all())?;
        }
        Ok(())
    }
}

fn ensure_closed(game: &Path) -> Result<()> {
    if is_game_running(game)? {
        return Err("Feche o jogo antes de aplicar ou restaurar a dublagem.".into());
    }
    Ok(())
}

/// True when the managed executable is currently loaded by any process.
pub fn is_game_running(game: &Path) -> Result<bool> {
    let expected = io(game.join("kain2.exe").canonicalize())?;
    let mut system = sysinfo::System::new();
    system.refresh_processes_specifics(
        sysinfo::ProcessesToUpdate::All,
        true,
        sysinfo::ProcessRefreshKind::nothing()
            .with_exe(sysinfo::UpdateKind::Always)
            .without_tasks(),
    );
    Ok(system.processes().values().any(|p| {
        p.name()
            .to_str()
            .is_some_and(|n| n.eq_ignore_ascii_case("kain2.exe"))
            && p.exe()
                .and_then(|e| e.canonicalize().ok())
                .is_some_and(|e| e == expected)
    }))
}

fn apply_with_control(
    game: &Path,
    manifest_path: &Path,
    policy: &Policy,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    progress(Progress {
        stage: "verificacao".into(),
        current: 0,
        total: 1,
        message: "Verificando jogo e pacote".into(),
    });
    let (manifest, payloads, manifest_hash) = package(manifest_path, policy)?;
    let (game, exe, original) = validated_game(game, policy)?;
    ensure_closed(&game)?;
    let current = sha(&original);
    if current != policy.voices {
        let state = journal(&game, policy)?.ok_or("Áudio alterado sem registro de instalação.")?;
        if current == state.installed_sha256 && manifest_hash == state.manifest_sha256 {
            return inspect_with(&game, policy);
        }
        return Err("Restaure a instalação anterior antes de aplicar outro pacote. Conflitos foram preservados.".into());
    }
    let table = slots(&exe, original.len())?;
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
        progress(Progress {
            stage: "preparacao-dublagem".into(),
            current: index + 1,
            total: patch_count,
            message: format!("Preparando fala {} de {}", index + 1, patch_count),
        });
    }
    if sha(&candidate) != manifest.result_sha256 {
        return Err("Resultado do pacote difere do hash declarado.".into());
    }
    let manager = Manager::open(&game, policy)?;
    control.checkpoint()?;
    progress(Progress {
        stage: "backup".into(),
        current: 0,
        total: 1,
        message: "Criando e verificando backup".into(),
    });
    manager.backup(&original, policy)?;
    let mut state = Journal {
        schema: 1,
        phase: "preparing".into(),
        original_sha256: policy.voices.into(),
        installed_sha256: manifest.result_sha256,
        manifest_sha256: manifest_hash,
        replaced: manifest.patches.len(),
    };
    manager.save(&state)?;
    progress(Progress {
        stage: "instalacao".into(),
        current: 0,
        total: 1,
        message: "Aplicando dublagem".into(),
    });
    control.checkpoint()?;
    ensure_closed(&game)?;
    if sha(&read(&game.join("voices.dat"), VOICES_BYTES)?) != current {
        return Err("Arquivo mudou durante a instalação. Preservado.".into());
    }
    atomic_write(&game.join("voices.dat"), &candidate)?;
    if sha(&read(&game.join("voices.dat"), VOICES_BYTES)?) != state.installed_sha256 {
        return Err("Falha ao verificar o áudio instalado; backup preservado.".into());
    }
    state.phase = "installed".into();
    manager.save(&state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: 1,
        total: 1,
        message: "Dublagem verificada".into(),
    });
    inspect_with(&game, policy)
}

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

pub fn apply_package_with_control(
    game: &Path,
    manifest: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    apply_with_control(game, manifest, &BASE, control, progress)
}

pub fn apply_package(game: &Path, manifest: &Path, progress: impl FnMut(&str)) -> Result<GameInfo> {
    apply_with(game, manifest, &BASE, progress)
}

fn restore_with_control(
    game: &Path,
    policy: &Policy,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GameInfo> {
    progress(Progress {
        stage: "verificacao".into(),
        current: 0,
        total: 1,
        message: "Verificando restauração".into(),
    });
    let (game, _, current) = validated_game(game, policy)?;
    ensure_closed(&game)?;
    let mut state =
        journal(&game, policy)?.ok_or("Nenhuma instalação gerenciada para restaurar.")?;
    let manager = Manager::open(&game, policy)?;
    let backup = read(&manager.root.join("voices.original.dat"), VOICES_BYTES)?;
    if sha(&backup) != policy.voices {
        return Err("Backup alterado. Restauração bloqueada.".into());
    }
    let current_hash = sha(&current);
    if current_hash != policy.voices && current_hash != state.installed_sha256 {
        return Err(
            "Áudio alterado após a instalação. Restauração bloqueada; arquivos preservados.".into(),
        );
    }
    state.phase = "restoring".into();
    manager.save(&state)?;
    progress(Progress {
        stage: "restauracao".into(),
        current: 0,
        total: 1,
        message: "Restaurando áudio original".into(),
    });
    control.checkpoint()?;
    ensure_closed(&game)?;
    if sha(&read(&game.join("voices.dat"), VOICES_BYTES)?) != current_hash {
        return Err("Arquivo mudou durante a restauração. Preservado.".into());
    }
    atomic_write(&game.join("voices.dat"), &backup)?;
    if sha(&read(&game.join("voices.dat"), VOICES_BYTES)?) != policy.voices {
        return Err("Falha ao verificar a restauração.".into());
    }
    state.phase = "restored".into();
    manager.save(&state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: 1,
        total: 1,
        message: "Original restaurado e verificado".into(),
    });
    inspect_with(&game, policy)
}

fn restore_with(game: &Path, policy: &Policy, mut progress: impl FnMut(&str)) -> Result<GameInfo> {
    restore_with_control(game, policy, &OperationControl::default(), |p| {
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

pub fn restore_game(game: &Path, progress: impl FnMut(&str)) -> Result<GameInfo> {
    restore_with(game, &BASE, progress)
}

pub fn apply_graphics(
    game: &Path,
    graphics_source: &Path,
    request: graphics::Request,
    progress: impl FnMut(&str),
) -> Result<()> {
    graphics::apply(game, graphics_source, request, progress)?;
    Ok(())
}

pub fn restore_graphics(game: &Path, progress: impl FnMut(&str)) -> Result<()> {
    graphics::restore(game, progress)?;
    Ok(())
}

/// Aggregate per-component status for the installer dashboard.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ComponentsInfo {
    pub localization: assets::AssetsInfo,
    pub video: external::ExternalInfo,
    pub graphics: graphics::GraphicsInfo,
    pub textures: external::ExternalInfo,
    pub ui: external::ExternalInfo,
}

pub fn inspect_components(game: &Path) -> Result<ComponentsInfo> {
    let info = inspect_game(game)?;
    Ok(ComponentsInfo {
        localization: info.localization,
        video: info.video,
        graphics: info.graphics,
        textures: info.textures,
        ui: info.ui,
    })
}

pub fn apply_textures(
    game: &Path,
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<external::ExternalInfo> {
    external::apply(game, &external::TEXTURES, manifest, backups, progress)
}

pub fn restore_textures(game: &Path, progress: impl FnMut(&str)) -> Result<external::ExternalInfo> {
    external::restore(game, &external::TEXTURES, progress)
}

pub fn apply_ui(
    game: &Path,
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<external::ExternalInfo> {
    external::apply(game, &external::UI, manifest, backups, progress)
}

pub fn restore_ui(game: &Path, progress: impl FnMut(&str)) -> Result<external::ExternalInfo> {
    external::restore(game, &external::UI, progress)
}

#[cfg(test)]
mod tests;
