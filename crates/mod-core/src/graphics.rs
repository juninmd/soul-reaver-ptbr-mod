//! dgVoodoo2 wrapper and Hor+ 16:9 patch under their own ownership journal.
//!
//! Nothing here overwrites a file that this journal does not own, so a graphics
//! wrapper installed by another mod is always preserved. The widescreen patch
//! only rewrites the fixed field-of-view constant of the two supported
//! executables and keeps a byte-exact backup for restoration.
//!
//! The wrapper is always GPU accelerated (dgVoodoo translates DirectDraw/D3D to
//! D3D11/D3D12), but nothing here proves a frame was presented. Resolution,
//! vertical sync, frame limit and window attributes are chosen before installing
//! so the shipped configuration matches the machine instead of a fixed 4K value.
use crate::{
    EXE_SHA256, EXE_WIDESCREEN_SHA256, MANAGER, Result,
    fsx::{
        JOURNAL_LIMIT, atomic_write, chain, io, is_sha256, lock_operation, plain, read, sha,
        supported_game_dir,
    },
    operation::{OperationControl, Progress},
    process::{ClosedGame, ensure_closed},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashSet,
    fs::{self, File},
    path::{Path, PathBuf},
};

const STATE: &str = "graphics-state.json";
/// Field-of-view constant rewritten by the Hor+ 16:9 patch.
const FOV_OFFSET: usize = 0xeb354;
const FOV_ORIGINAL: [u8; 4] = [0x00, 0x00, 0x20, 0x3f];
const FOV_16_9: [u8; 4] = [0x00, 0x00, 0xf0, 0x3e];
const EXE_BACKUP: &str = "kain2.graphics-original.exe";
const WRAPPER: [&str; 5] = [
    "DDraw.dll",
    "D3DImm.dll",
    "dgVoodoo.conf",
    "D3D8.dll",
    "D3D9.dll",
];
const LIMIT: u64 = 4 * 1024 * 1024;
const WIDEST: u32 = 3840;
const TALLEST: u32 = 2160;
const MAX_FPS_LIMIT: u32 = 240;
/// Native 16:9 render modes from largest to smallest. The selected value never
/// exceeds the desktop, so a 4K render is not forced onto a 1080p display.
const MODES: [(u32, u32); 7] = [
    (3840, 2160),
    (2560, 1440),
    (1920, 1080),
    (1600, 900),
    (1280, 720),
    (960, 540),
    (640, 360),
];

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphicsInfo {
    pub installed: bool,
    pub widescreen: bool,
    pub files: usize,
    pub resolution: Option<String>,
    pub message: String,
}

/// Render choices resolved at install time. `resolution` accepts `auto` (use
/// the detected desktop mode) or an explicit `WIDTHxHEIGHT` value.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RenderOptions {
    #[serde(default)]
    pub resolution: String,
    #[serde(default = "default_vsync")]
    pub vsync: bool,
    #[serde(default = "default_fps_limit")]
    pub fps_limit: u32,
    #[serde(default)]
    pub always_on_top: bool,
}

fn default_vsync() -> bool {
    true
}

fn default_fps_limit() -> u32 {
    60
}

impl Default for RenderOptions {
    fn default() -> Self {
        Self {
            resolution: "auto".into(),
            vsync: true,
            fps_limit: 60,
            always_on_top: false,
        }
    }
}

/// Wrapper + widescreen request for one installation.
#[derive(Clone, Debug, Default)]
pub struct Request {
    pub widescreen: bool,
    pub render: RenderOptions,
}

/// What the current machine can do, shown to the user before applying.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DisplayProfile {
    pub desktop: String,
    pub recommended: String,
    pub feature_level: Option<String>,
    pub hardware: bool,
    pub message: String,
}

fn format_mode((width, height): (u32, u32)) -> String {
    format!("{width}x{height}")
}

/// Pick the largest 16:9 mode that fits the desktop, capped at 3840x2160.
pub fn recommended_resolution(desktop: (u32, u32)) -> (u32, u32) {
    let width = desktop.0.min(WIDEST);
    let height = desktop.1.min(TALLEST);
    MODES
        .iter()
        .copied()
        .find(|(mode_width, mode_height)| *mode_width <= width && *mode_height <= height)
        .unwrap_or((640, 360))
}

fn validate_resolution(value: &str) -> Result<(u32, u32)> {
    let (width, height) = value
        .split_once(['x', 'X'])
        .ok_or_else(|| format!("Resolução inválida: {value}. Use LARGURAxALTURA."))?;
    let parse = |part: &str| {
        part.trim()
            .parse::<u32>()
            .map_err(|_| format!("Resolução inválida: {value}. Use LARGURAxALTURA."))
    };
    let (width, height) = (parse(width)?, parse(height)?);
    if !(320..=7680).contains(&width) || !(200..=4320).contains(&height) {
        return Err(format!("Resolução fora do intervalo aceito: {value}."));
    }
    Ok((width, height))
}

fn resolve_resolution(render: &RenderOptions, desktop: (u32, u32)) -> Result<String> {
    if render.resolution.trim().is_empty() || render.resolution.eq_ignore_ascii_case("auto") {
        return Ok(format_mode(recommended_resolution(desktop)));
    }
    let (width, height) = validate_resolution(&render.resolution)?;
    Ok(format!("{width}x{height}"))
}

fn window_attributes(always_on_top: bool) -> String {
    if always_on_top {
        "borderless, fullscreensize, alwaysontop".into()
    } else {
        "borderless, fullscreensize".into()
    }
}

/// Rewrite the dgVoodoo template so the installed wrapper matches the detected
/// desktop instead of a fixed 4K value. Every other line and comment is kept.
pub fn render_config(template: &[u8], resolution: &str, render: &RenderOptions) -> Result<Vec<u8>> {
    validate_resolution(resolution)?;
    if render.fps_limit > MAX_FPS_LIMIT {
        return Err(format!(
            "Limite de FPS inválido: {}. Use até {MAX_FPS_LIMIT}.",
            render.fps_limit
        ));
    }
    let text = std::str::from_utf8(template)
        .map_err(|_| "dgVoodoo.conf não está em UTF-8 válido.".to_string())?;
    let mut section = String::new();
    let mut seen: HashSet<(String, String)> = HashSet::new();
    let mut output = String::with_capacity(text.len());
    for line in text.split_inclusive('\n') {
        let (body, ending) = if let Some(body) = line.strip_suffix("\r\n") {
            (body, "\r\n")
        } else if let Some(body) = line.strip_suffix('\n') {
            (body, "\n")
        } else {
            (line, "")
        };
        let trimmed = body.trim();
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            section = trimmed[1..trimmed.len() - 1].trim().to_ascii_lowercase();
            output.push_str(body);
            output.push_str(ending);
            continue;
        }
        let Some(equals) = body.find('=') else {
            output.push_str(body);
            output.push_str(ending);
            continue;
        };
        let key = body[..equals].trim().to_ascii_lowercase();
        let value = match (section.as_str(), key.as_str()) {
            ("directx", "resolution") => resolution.to_string(),
            ("directx", "forceverticalsync") => render.vsync.to_string(),
            ("generalext", "fpslimit") => render.fps_limit.to_string(),
            ("generalext", "windowedattributes") => window_attributes(render.always_on_top),
            ("generalext", "resampling") => "bilinear".into(),
            ("general", "scalingmode") => "stretched_ar".into(),
            _ => {
                output.push_str(body);
                output.push_str(ending);
                continue;
            }
        };
        if !seen.insert((section.clone(), key.clone())) {
            return Err(format!(
                "dgVoodoo.conf repete a configuração [{section}] {key}."
            ));
        }
        output.push_str(&body[..equals]);
        output.push_str("= ");
        output.push_str(&value);
        output.push_str(ending);
    }
    let required = [
        ("directx", "resolution"),
        ("directx", "forceverticalsync"),
        ("generalext", "fpslimit"),
        ("generalext", "windowedattributes"),
        ("generalext", "resampling"),
        ("general", "scalingmode"),
    ];
    if let Some((section, key)) = required
        .iter()
        .find(|(section, key)| !seen.contains(&(section.to_string(), key.to_string())))
    {
        return Err(format!(
            "dgVoodoo.conf sem a configuração obrigatória [{section}] {key}."
        ));
    }
    Ok(output.into_bytes())
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RenderRecord {
    resolution: String,
    vsync: bool,
    fps_limit: u32,
    always_on_top: bool,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Item {
    file: String,
    result_sha256: String,
    previous_sha256: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExeRecord {
    original_sha256: String,
    patched_sha256: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    schema: u32,
    game: PathBuf,
    phase: String,
    widescreen: bool,
    files: Vec<Item>,
    exe: Option<ExeRecord>,
    #[serde(default)]
    render: Option<RenderRecord>,
}

fn lock(game: &Path) -> Result<File> {
    lock_operation(game)
}

fn game_path(game: &Path) -> Result<PathBuf> {
    supported_game_dir(game, || {
        "Executável incompatível com o perfil gráfico.".into()
    })
}

fn load(game: &Path) -> Result<State> {
    let path = game.join(MANAGER).join(STATE);
    if !path.exists() {
        return Ok(State {
            schema: 1,
            game: game.into(),
            phase: "original".into(),
            widescreen: false,
            files: vec![],
            exe: None,
            render: None,
        });
    }
    let state: State = serde_json::from_slice(&read(&path, JOURNAL_LIMIT)?)
        .map_err(|e| format!("Registro gráfico inválido: {e}"))?;
    if state.schema != 1
        || io(state.game.canonicalize())? != game
        || !["original", "preparing", "installed", "restored"].contains(&state.phase.as_str())
        || state.files.iter().any(|i| {
            !WRAPPER.contains(&i.file.as_str())
                || !is_sha256(&i.result_sha256)
                || i.previous_sha256.as_ref().is_some_and(|h| !is_sha256(h))
        })
        || state
            .exe
            .as_ref()
            .is_some_and(|e| !is_sha256(&e.original_sha256) || !is_sha256(&e.patched_sha256))
        || state.render.as_ref().is_some_and(|r| {
            validate_resolution(&r.resolution).is_err() || r.fps_limit > MAX_FPS_LIMIT
        })
    {
        return Err("Registro gráfico incompatível. Nada foi alterado.".into());
    }
    Ok(state)
}

fn save(game: &Path, state: &State) -> Result<()> {
    atomic_write(
        &game.join(MANAGER).join(STATE),
        &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
    )
}

pub fn inspect(game: &Path) -> Result<GraphicsInfo> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let state = load(&game)?;
    let mut installed = 0usize;
    let mut conf_installed = false;
    for item in &state.files {
        let path = game.join(&item.file);
        if path.exists() && sha(&read(&path, LIMIT)?) == item.result_sha256 {
            installed += 1;
            conf_installed |= item.file == "dgVoodoo.conf";
        }
    }
    let widescreen = match &state.exe {
        Some(record) => sha(&read(&game.join("kain2.exe"), LIMIT)?) == record.patched_sha256,
        None => false,
    };
    let active = installed > 0 || widescreen;
    let resolution = conf_installed
        .then(|| state.render.as_ref().map(|r| r.resolution.clone()))
        .flatten();
    let message = if active {
        format!(
            "Wrapper dgVoodoo2 aplicado ({installed} arquivo(s)){}{}.",
            resolution
                .as_ref()
                .map(|r| format!(" em {r}"))
                .unwrap_or_default(),
            if widescreen { " com Hor+ 16:9" } else { "" }
        )
    } else {
        "Perfil gráfico (dgVoodoo2) não instalado.".into()
    };
    Ok(GraphicsInfo {
        installed: active,
        widescreen,
        files: installed,
        resolution,
        message,
    })
}

/// Install the wrapper files present in `source` and, when requested, patch the
/// executable to Hor+ 16:9. Refuses any unowned preexisting wrapper file.
pub fn apply(
    game: &Path,
    source: &Path,
    request: Request,
    progress: impl FnMut(&str),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    apply_checked(&game, source, request, progress)
}

pub fn apply_with_control(
    game: &Path,
    source: &Path,
    request: Request,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    apply_checked_control(&game, source, request, control, progress)
}

fn apply_checked(
    game: &Path,
    source: &Path,
    request: Request,
    mut progress: impl FnMut(&str),
) -> Result<GraphicsInfo> {
    apply_checked_control(game, source, request, &OperationControl::default(), |p| {
        progress(&p.message)
    })
}

fn apply_checked_control(
    game: &Path,
    source: &Path,
    request: Request,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let widescreen = request.widescreen;
    let _lock = lock(game)?;
    let closed = ClosedGame::new(game)?;
    let source = io(source.canonicalize())?;
    chain(&source)?;
    let mut state = load(game)?;

    let desktop = windows_api::desktop().unwrap_or((1920, 1080));
    let resolution = resolve_resolution(&request.render, desktop)?;

    // Collect the wrapper files the package actually provides. The dgVoodoo
    // template is rewritten for this machine instead of being copied verbatim.
    let mut plan: Vec<(String, Vec<u8>)> = Vec::new();
    for name in WRAPPER {
        let path = source.join(name);
        if path.is_file() {
            let bytes = read(&path, LIMIT)?;
            let bytes = if name == "dgVoodoo.conf" {
                render_config(&bytes, &resolution, &request.render)?
            } else {
                bytes
            };
            plan.push((name.to_string(), bytes));
        }
    }
    if plan.is_empty() {
        return Err("Pacote gráfico sem arquivos DDraw/D3DImm/dgVoodoo.".into());
    }

    // Conflict check before any mutation: the target must be absent, still match
    // what this journal installed before (so render settings can be changed), or
    // already be byte-identical to the new file. Anything else belongs to another
    // mod and is preserved.
    for (name, bytes) in &plan {
        let target = game.join(name);
        if target.exists() {
            plain(&target)?;
            let current = sha(&read(&target, LIMIT)?);
            let owned = state
                .files
                .iter()
                .any(|i| i.file == *name && i.result_sha256 == current);
            if !owned && current != sha(bytes) {
                return Err(format!(
                    "Arquivo gráfico preexistente sem propriedade comprovada: {name}. Preservado."
                ));
            }
        }
    }

    state.files = plan
        .iter()
        .map(|(name, bytes)| Item {
            file: name.clone(),
            result_sha256: sha(bytes),
            previous_sha256: None,
        })
        .collect();
    state.phase = "preparing".into();
    state.render = Some(RenderRecord {
        resolution: resolution.clone(),
        vsync: request.render.vsync,
        fps_limit: request.render.fps_limit,
        always_on_top: request.render.always_on_top,
    });
    save(game, &state)?;
    let total = plan.len() + usize::from(widescreen || state.exe.is_some());
    for (index, (name, bytes)) in plan.iter().enumerate() {
        control.checkpoint()?;
        progress(Progress {
            stage: "graficos".into(),
            current: index,
            total,
            message: if name == "dgVoodoo.conf" {
                format!(
                    "Configurando dgVoodoo em {resolution} (VSync {}, {} FPS)",
                    if request.render.vsync { "on" } else { "off" },
                    if request.render.fps_limit == 0 {
                        "ilimitado".to_string()
                    } else {
                        request.render.fps_limit.to_string()
                    }
                )
            } else {
                format!("Instalando {name}")
            },
        });
        closed.ensure()?;
        atomic_write(&game.join(name), bytes)?;
        progress(Progress {
            stage: "graficos".into(),
            current: index + 1,
            total,
            message: format!("Arquivo instalado: {name}"),
        });
    }

    // Widescreen patch: only touch the executable when the profile asks for it
    // or a previous record has to be undone.
    let exe_path = game.join("kain2.exe");
    let backup_path = game.join(MANAGER).join(EXE_BACKUP);
    let mut record = state.exe.clone().unwrap_or(ExeRecord {
        original_sha256: String::new(),
        patched_sha256: String::new(),
    });
    if widescreen {
        control.checkpoint()?;
        let current_exe = read(&exe_path, LIMIT)?;
        if record.original_sha256.is_empty() {
            if sha(&current_exe) == EXE_SHA256 {
                record.original_sha256 = EXE_SHA256.into();
                atomic_write(&backup_path, &current_exe)?;
            } else {
                return Err("Executável incompatível para o patch widescreen.".into());
            }
        }
        let mut patched = read(&exe_path, LIMIT)?;
        if patched.len() > FOV_OFFSET + 4 && patched[FOV_OFFSET..FOV_OFFSET + 4] == FOV_ORIGINAL {
            patched[FOV_OFFSET..FOV_OFFSET + 4].copy_from_slice(&FOV_16_9);
            record.patched_sha256 = sha(&patched);
            state.exe = Some(record.clone());
            state.widescreen = true;
            save(game, &state)?;
            control.checkpoint()?;
            progress(Progress {
                stage: "graficos".into(),
                current: plan.len(),
                total,
                message: "Aplicando patch de aspect ratio Hor+ 16:9...".into(),
            });
            atomic_write(&exe_path, &patched)?;
        } else if patched[FOV_OFFSET..FOV_OFFSET + 4] != FOV_16_9 {
            return Err("Offset de FOV inesperado; patch widescreen não aplicado.".into());
        }
        record.patched_sha256 = sha(&read(&exe_path, LIMIT)?);
    } else {
        if backup_path.exists() {
            let original = read(&backup_path, LIMIT)?;
            if sha(&original) != EXE_SHA256 {
                return Err("Backup do executável alterado.".into());
            }
            control.checkpoint()?;
            atomic_write(&exe_path, &original)?;
            io(fs::remove_file(&backup_path))?;
        }
        record = ExeRecord {
            original_sha256: String::new(),
            patched_sha256: String::new(),
        };
    }

    state.files = plan
        .iter()
        .map(|(name, bytes)| Item {
            file: name.clone(),
            result_sha256: sha(bytes),
            previous_sha256: None,
        })
        .collect();
    state.widescreen = widescreen;
    state.exe = if record.patched_sha256.is_empty() && record.original_sha256.is_empty() {
        None
    } else {
        Some(record)
    };
    state.phase = "installed".into();
    save(game, &state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: total,
        total,
        message: "Configuração 4K concluída.".into(),
    });
    inspect(game)
}

pub fn restore(game: &Path, progress: impl FnMut(&str)) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    restore_checked(&game, progress)
}

pub fn restore_with_control(
    game: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    restore_checked_control(&game, control, progress)
}

fn restore_checked(game: &Path, mut progress: impl FnMut(&str)) -> Result<GraphicsInfo> {
    restore_checked_control(game, &OperationControl::default(), |p| progress(&p.message))
}

fn restore_checked_control(
    game: &Path,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let _lock = lock(game)?;
    ensure_closed(game)?;
    let mut state = load(game)?;

    // Conflict check before any mutation: the journal only removes files it still
    // owns. A file or executable changed after installation blocks the restore
    // instead of being silently orphaned.
    for item in &state.files {
        let target = game.join(&item.file);
        if target.exists() && sha(&read(&target, LIMIT)?) != item.result_sha256 {
            return Err(format!(
                "Conflito: {} mudou após a instalação; preservado.",
                item.file
            ));
        }
    }
    if let Some(record) = &state.exe {
        let current = sha(&read(&game.join("kain2.exe"), LIMIT)?);
        if current != record.patched_sha256
            && current != EXE_SHA256
            && current != EXE_WIDESCREEN_SHA256
        {
            return Err("Conflito: kain2.exe mudou após a instalação; preservado.".into());
        }
    }

    // Restore the executable before removing wrapper files.
    let total = state.files.len() + usize::from(state.exe.is_some());
    let mut progress_current = 0;
    if let Some(record) = state.exe.clone() {
        let backup_path = game.join(MANAGER).join(EXE_BACKUP);
        let current = sha(&read(&game.join("kain2.exe"), LIMIT)?);
        if backup_path.exists()
            && (current == record.patched_sha256
                || current == EXE_SHA256
                || current == EXE_WIDESCREEN_SHA256)
        {
            let original = read(&backup_path, LIMIT)?;
            if sha(&original) != EXE_SHA256 {
                return Err("Backup do executável alterado; restauração bloqueada.".into());
            }
            if current != EXE_SHA256 {
                control.checkpoint()?;
                progress(Progress {
                    stage: "restauracao-graficos".into(),
                    current: progress_current,
                    total,
                    message: "Restaurando executável original...".into(),
                });
                atomic_write(&game.join("kain2.exe"), &original)?;
            }
            io(fs::remove_file(&backup_path))?;
        }
        progress_current += 1;
    }

    // Every remaining owned file matched its installed hash above.
    for item in &state.files {
        let target = game.join(&item.file);
        if !target.exists() {
            continue;
        }
        control.checkpoint()?;
        progress(Progress {
            stage: "restauracao-graficos".into(),
            current: progress_current,
            total,
            message: format!("Removendo {}", item.file),
        });
        io(fs::remove_file(&target))?;
        progress_current += 1;
        progress(Progress {
            stage: "restauracao-graficos".into(),
            current: progress_current,
            total,
            message: format!("Removido {}", item.file),
        });
    }
    state.files.clear();
    state.exe = None;
    state.render = None;
    state.widescreen = false;
    state.phase = "restored".into();
    save(game, &state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: total,
        total,
        message: "Gráficos restaurados ao original.".into(),
    });
    inspect(game)
}

fn feature_level_name(level: u32) -> &'static str {
    match level {
        0xb100 => "11_1",
        0xb000 => "11_0",
        0xa100 => "10_1",
        0xa000 => "10_0",
        0x9300 => "9_3",
        0x9200 => "9_2",
        0x9100 => "9_1",
        _ => "desconhecido",
    }
}

/// Render settings recorded by the last installation, so repairs keep them.
pub fn current_render(game: &Path) -> RenderOptions {
    io(game.canonicalize())
        .ok()
        .and_then(|game| load(&game).ok())
        .and_then(|state| state.render)
        .map(|record| RenderOptions {
            resolution: record.resolution,
            vsync: record.vsync,
            fps_limit: record.fps_limit,
            always_on_top: record.always_on_top,
        })
        .unwrap_or_default()
}

/// Inspect the desktop and the GPU without changing anything. The probe creates
/// a throwaway D3D11 device, so a machine without a usable adapter is reported
/// before installing instead of after launching the game.
pub fn display_profile() -> DisplayProfile {
    let desktop = windows_api::desktop().unwrap_or((1920, 1080));
    let recommended = recommended_resolution(desktop);
    match windows_api::probe() {
        Some(level) => DisplayProfile {
            desktop: format_mode(desktop),
            recommended: format_mode(recommended),
            feature_level: Some(feature_level_name(level).into()),
            hardware: true,
            message: format!(
                "GPU Direct3D {} detectada. Resolução interna recomendada: {}.",
                feature_level_name(level),
                format_mode(recommended)
            ),
        },
        None => DisplayProfile {
            desktop: format_mode(desktop),
            recommended: format_mode(recommended),
            feature_level: None,
            hardware: false,
            message: format!(
                "Não foi possível sondar a GPU; usando {} por segurança. O wrapper ainda depende do driver em tempo de execução.",
                format_mode(recommended)
            ),
        },
    }
}

#[cfg(windows)]
mod windows_api {
    use std::ffi::c_void;

    const SM_CXSCREEN: i32 = 0;
    const SM_CYSCREEN: i32 = 1;
    const D3D_DRIVER_TYPE_HARDWARE: u32 = 1;
    const D3D11_SDK_VERSION: u32 = 7;

    #[link(name = "user32")]
    unsafe extern "system" {
        fn GetSystemMetrics(index: i32) -> i32;
    }

    #[link(name = "d3d11")]
    unsafe extern "system" {
        fn D3D11CreateDevice(
            adapter: *mut c_void,
            driver_type: u32,
            software: *mut c_void,
            flags: u32,
            feature_levels: *const u32,
            feature_level_count: u32,
            sdk_version: u32,
            device: *mut *mut c_void,
            feature_level: *mut u32,
            context: *mut *mut c_void,
        ) -> i32;
    }

    pub fn desktop() -> Option<(u32, u32)> {
        // The installer is per-monitor DPI aware, so these are physical pixels.
        let width = unsafe { GetSystemMetrics(SM_CXSCREEN) };
        let height = unsafe { GetSystemMetrics(SM_CYSCREEN) };
        (width > 0 && height > 0).then_some((width as u32, height as u32))
    }

    pub fn probe() -> Option<u32> {
        let mut device: *mut c_void = std::ptr::null_mut();
        let mut level = 0u32;
        let code = unsafe {
            D3D11CreateDevice(
                std::ptr::null_mut(),
                D3D_DRIVER_TYPE_HARDWARE,
                std::ptr::null_mut(),
                0,
                std::ptr::null(),
                0,
                D3D11_SDK_VERSION,
                &mut device,
                &mut level,
                std::ptr::null_mut(),
            )
        };
        if code < 0 || device.is_null() {
            return None;
        }
        unsafe { release(device) };
        Some(level)
    }

    unsafe fn release(object: *mut c_void) {
        let vtable = unsafe { *(object as *mut *const *mut c_void) };
        let release: unsafe extern "system" fn(*mut c_void) -> u32 =
            unsafe { std::mem::transmute(*vtable.add(2)) };
        unsafe { release(object) };
    }
}

#[cfg(not(windows))]
mod windows_api {
    pub fn desktop() -> Option<(u32, u32)> {
        None
    }

    pub fn probe() -> Option<u32> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEMPLATE: &str = "; fixture template\n\
[General]\n\
ScalingMode                          = unspecified\n\
\n\
[GeneralExt]\n\
WindowedAttributes                   = borderless, fullscreensize, alwaysontop\n\
FPSLimit                             = 0\n\
Resampling                           = bilinear\n\
\n\
[DirectX]\n\
Resolution                           = 3840x2160\n\
ForceVerticalSync                   = false\n";

    fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf) {
        let root = tempfile::tempdir().unwrap();
        let game = root.path().join("game");
        let source = root.path().join("graphics");
        fs::create_dir(&game).unwrap();
        fs::create_dir(&source).unwrap();
        fs::write(game.join("kain2.exe"), b"fixture executable, never started").unwrap();
        fs::write(game.join("savegame.her"), b"user save").unwrap();
        fs::write(source.join("DDraw.dll"), b"dgvoodoo ddraw wrapper").unwrap();
        fs::write(source.join("D3DImm.dll"), b"dgvoodoo d3dimm wrapper").unwrap();
        fs::write(source.join("dgVoodoo.conf"), TEMPLATE).unwrap();
        let game = game.canonicalize().unwrap();
        (root, game, source)
    }

    fn request(resolution: &str, vsync: bool, fps_limit: u32, always_on_top: bool) -> Request {
        Request {
            widescreen: false,
            render: RenderOptions {
                resolution: resolution.into(),
                vsync,
                fps_limit,
                always_on_top,
            },
        }
    }

    fn config_value(game: &Path, key: &str) -> String {
        let text = String::from_utf8(fs::read(game.join("dgVoodoo.conf")).unwrap()).unwrap();
        text.lines()
            .find(|line| line.trim_start().starts_with(key))
            .and_then(|line| line.split_once('='))
            .map(|(_, value)| value.trim().to_string())
            .unwrap_or_default()
    }

    #[test]
    fn render_config_rewrites_only_the_render_keys() {
        let rewritten = render_config(
            TEMPLATE.as_bytes(),
            "1920x1080",
            &RenderOptions {
                resolution: "auto".into(),
                vsync: false,
                fps_limit: 0,
                always_on_top: false,
            },
        )
        .unwrap();
        let text = String::from_utf8(rewritten).unwrap();
        assert!(text.starts_with("; fixture template"));
        assert!(text.contains("Resolution                           = 1920x1080"));
        assert!(text.contains("ForceVerticalSync                   = false"));
        assert!(text.contains("FPSLimit                             = 0"));
        assert!(text.contains("ScalingMode                          = stretched_ar"));
        assert!(text.contains("Resampling                           = bilinear"));
        assert!(
            text.contains("WindowedAttributes                   = borderless, fullscreensize\n")
        );
        assert!(!text.contains("alwaysontop"));
    }

    #[test]
    fn render_config_rejects_unknown_keys_and_values() {
        let missing = TEMPLATE.replace("FPSLimit                             = 0\n", "");
        assert!(
            render_config(missing.as_bytes(), "1920x1080", &RenderOptions::default())
                .unwrap_err()
                .contains("fpslimit")
        );
        let options = RenderOptions::default();
        assert!(
            render_config(TEMPLATE.as_bytes(), "1080p", &options)
                .unwrap_err()
                .contains("Resolução inválida")
        );
        assert!(
            render_config(
                TEMPLATE.as_bytes(),
                "1920x1080",
                &request("auto", true, 999, false).render
            )
            .unwrap_err()
            .contains("Limite de FPS")
        );
    }

    fn section_value<'a>(text: &'a str, section: &str, key: &str) -> &'a str {
        let mut current = "";
        for line in text.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with('[') && trimmed.ends_with(']') {
                current = &trimmed[1..trimmed.len() - 1];
                continue;
            }
            if current.eq_ignore_ascii_case(section)
                && line
                    .split_once('=')
                    .is_some_and(|(name, _)| name.trim().eq_ignore_ascii_case(key))
            {
                return line.split_once('=').unwrap().1.trim();
            }
        }
        ""
    }

    #[test]
    fn shipped_dgvoodoo_template_can_be_rewritten() {
        // `modules/` is not tracked in Git; skip the check on a bare checkout.
        let path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../modules/graphics/dgVoodoo.conf");
        let Ok(template) = fs::read(&path) else {
            return;
        };
        let rewritten = render_config(&template, "2560x1440", &RenderOptions::default()).unwrap();
        let text = String::from_utf8(rewritten).unwrap();
        assert_eq!(section_value(&text, "DirectX", "Resolution"), "2560x1440");
        assert_eq!(section_value(&text, "DirectX", "ForceVerticalSync"), "true");
        assert_eq!(section_value(&text, "GeneralExt", "FPSLimit"), "60");
        assert_eq!(
            section_value(&text, "General", "ScalingMode"),
            "stretched_ar"
        );
        assert_eq!(
            section_value(&text, "GeneralExt", "WindowedAttributes"),
            "borderless, fullscreensize"
        );
        // Glide's own Resolution is not a DirectX render setting and stays intact.
        assert_eq!(section_value(&text, "Glide", "Resolution"), "unforced");
    }

    #[test]
    fn display_profile_reports_a_supported_mode() {
        let profile = display_profile();
        assert!(
            MODES
                .iter()
                .any(|mode| format_mode(*mode) == profile.recommended),
            "modo fora da lista: {}",
            profile.recommended
        );
        assert!(profile.desktop.contains('x'));
    }

    #[test]
    fn recommended_resolution_never_exceeds_the_desktop() {
        assert_eq!(recommended_resolution((3840, 2160)), (3840, 2160));
        assert_eq!(recommended_resolution((2560, 1440)), (2560, 1440));
        assert_eq!(recommended_resolution((1920, 1080)), (1920, 1080));
        assert_eq!(recommended_resolution((1366, 768)), (1280, 720));
        assert_eq!(recommended_resolution((5120, 2880)), (3840, 2160));
        assert_eq!(recommended_resolution((3440, 1440)), (2560, 1440));
        assert_eq!(recommended_resolution((800, 600)), (640, 360));
    }

    #[test]
    fn wrapper_apply_and_restore_preserve_save() {
        let (_root, game, source) = fixture();
        let info = apply_checked(
            &game,
            &source,
            request("1920x1080", true, 60, false),
            |_| {},
        )
        .unwrap();
        assert_eq!(info.resolution.as_deref(), Some("1920x1080"));
        assert_eq!(info.files, 3);
        assert!(info.installed);
        assert!(!info.widescreen);
        assert!(game.join("DDraw.dll").exists());
        let restored = restore_checked(&game, |_| {}).unwrap();
        assert_eq!(restored.files, 0);
        assert!(!game.join("DDraw.dll").exists());
        assert!(!game.join("dgVoodoo.conf").exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
    }

    #[test]
    fn applying_the_same_wrapper_package_twice_is_idempotent() {
        let (_root, game, source) = fixture();
        let first = apply_checked(
            &game,
            &source,
            request("1920x1080", true, 60, false),
            |_| {},
        )
        .unwrap();
        let first_state = fs::read(game.join(MANAGER).join(STATE)).unwrap();
        let second = apply_checked(
            &game,
            &source,
            request("1920x1080", true, 60, false),
            |_| {},
        )
        .unwrap();

        assert_eq!(first.files, second.files);
        assert!(second.installed);
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"dgvoodoo ddraw wrapper"
        );
        assert_eq!(
            fs::read(game.join(MANAGER).join(STATE)).unwrap(),
            first_state
        );
    }

    #[test]
    fn applying_new_render_settings_over_an_owned_wrapper_is_allowed() {
        let (_root, game, source) = fixture();
        apply_checked(
            &game,
            &source,
            request("1920x1080", true, 60, false),
            |_| {},
        )
        .unwrap();
        apply_checked(&game, &source, request("2560x1440", false, 0, true), |_| {}).unwrap();
        assert_eq!(config_value(&game, "Resolution"), "2560x1440");
        assert_eq!(config_value(&game, "ForceVerticalSync"), "false");
        assert_eq!(config_value(&game, "FPSLimit"), "0");
        assert_eq!(
            config_value(&game, "WindowedAttributes"),
            "borderless, fullscreensize, alwaysontop"
        );
        assert_eq!(
            inspect(&game).unwrap().resolution.as_deref(),
            Some("2560x1440")
        );
        let remembered = current_render(&game);
        assert_eq!(remembered.resolution, "2560x1440");
        assert!(!remembered.vsync);
        assert_eq!(remembered.fps_limit, 0);
        assert!(remembered.always_on_top);
    }

    #[test]
    fn foreign_wrapper_is_preserved() {
        let (_root, game, source) = fixture();
        fs::write(game.join("DDraw.dll"), b"another graphics mod").unwrap();
        assert!(
            apply_checked(
                &game,
                &source,
                request("1920x1080", true, 60, false),
                |_| {}
            )
            .unwrap_err()
            .contains("preexistente")
        );
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"another graphics mod"
        );
    }

    #[test]
    fn modified_owned_wrapper_blocks_restore_and_is_preserved() {
        let (_root, game, source) = fixture();
        apply_checked(
            &game,
            &source,
            request("1920x1080", true, 60, false),
            |_| {},
        )
        .unwrap();
        fs::write(game.join("DDraw.dll"), b"changed after install").unwrap();
        let error = restore_checked(&game, |_| {}).unwrap_err();
        assert!(error.contains("Conflito"), "erro inesperado: {error}");
        // The modified file is preserved and the journal keeps ownership.
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"changed after install"
        );
        assert_eq!(load(&game).unwrap().files.len(), 3);
        // Putting the file back to the installed bytes allows the restore.
        fs::write(game.join("DDraw.dll"), b"dgvoodoo ddraw wrapper").unwrap();
        assert_eq!(restore_checked(&game, |_| {}).unwrap().files, 0);
        assert!(!game.join("DDraw.dll").exists());
    }
}
