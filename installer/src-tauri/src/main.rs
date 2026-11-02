#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use soul_reaver_mod_core::{GameInfo, OperationControl, PackageInfo, Progress, external, graphics};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use tauri::Emitter;

mod controller;
mod game_launch;

#[tauri::command]
async fn launch_game(
    game_path: String,
    state: tauri::State<'_, OperationState>,
) -> Result<(), String> {
    let control = begin_operation(&state)?;
    let joined =
        tauri::async_runtime::spawn_blocking(move || game_launch::launch(Path::new(&game_path)))
            .await;
    finish_operation(&state, &control);
    joined.map_err(|error| format!("Falha na tarefa de inicialização: {error}"))?
}

#[tauri::command]
async fn get_controller_status(game_path: String) -> Result<controller::Status, String> {
    tauri::async_runtime::spawn_blocking(move || controller::status(Path::new(&game_path)))
        .await
        .map_err(|error| format!("Falha na tarefa de status do controle: {error}"))?
}

#[tauri::command]
async fn install_controller(
    game_path: String,
    state: tauri::State<'_, OperationState>,
) -> Result<controller::Status, String> {
    let control = begin_operation(&state)?;
    let result = tauri::async_runtime::spawn_blocking(move || controller::install(Path::new(&game_path)))
        .await
        .map_err(|error| format!("Falha na tarefa de instalação do controle: {error}"))?;
    finish_operation(&state, &control);
    result
}

#[tauri::command]
fn open_logs_folder() -> Result<(), String> {
    let local = std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA não encontrado")?;
    let logs = std::path::PathBuf::from(local).join("SoulReaverPTBR/logs");
    std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let mut cmd = std::process::Command::new("explorer");
        cmd.arg(&logs);
        cmd.creation_flags(0x08000000);
        cmd.spawn().map_err(|e| e.to_string())?;
    }
    #[cfg(not(windows))]
    {
        std::process::Command::new("xdg-open")
            .arg(&logs)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn remove_controller(
    game_path: String,
    state: tauri::State<'_, OperationState>,
) -> Result<controller::Status, String> {
    let control = begin_operation(&state)?;
    let result = tauri::async_runtime::spawn_blocking(move || controller::remove(Path::new(&game_path)))
        .await
        .map_err(|error| format!("Falha na tarefa de remoção do controle: {error}"))?;
    finish_operation(&state, &control);
    result
}

#[tauri::command]
async fn launch_controller_game(
    game_path: String,
    state: tauri::State<'_, OperationState>,
) -> Result<controller::Status, String> {
    let control = begin_operation(&state)?;
    let result = tauri::async_runtime::spawn_blocking(move || controller::launch(Path::new(&game_path)))
        .await
        .map_err(|error| format!("Falha na tarefa de inicialização com controle: {error}"))?;
    finish_operation(&state, &control);
    result
}

#[derive(Default)]
struct OperationState {
    current: Mutex<Option<Arc<OperationControl>>>,
}

fn begin_operation(state: &OperationState) -> Result<Arc<OperationControl>, String> {
    let mut current = state.current.lock().unwrap_or_else(|e| e.into_inner());
    if current.is_some() {
        return Err("Já existe uma operação em andamento.".into());
    }
    let control = Arc::new(OperationControl::default());
    *current = Some(control.clone());
    Ok(control)
}

fn finish_operation(state: &OperationState, control: &Arc<OperationControl>) {
    let mut current = state.current.lock().unwrap_or_else(|e| e.into_inner());
    if current
        .as_ref()
        .is_some_and(|active| Arc::ptr_eq(active, control))
    {
        *current = None;
    }
}

fn emit_progress(app: &tauri::AppHandle, progress: Progress) {
    let _ = app.emit("progress-message", progress.message.clone());
    let _ = app.emit("progress", progress);
}

fn structured_reporter(app: &tauri::AppHandle) -> impl FnMut(Progress) + '_ {
    move |progress| emit_progress(app, progress)
}

const BUNDLES: [&str; 7] = [
    "local-full-v1",
    "local-review-v6",
    "local-review-v5",
    "local-review-v4",
    "local-review-v3",
    "local-review-v2",
    "tutorial-review-v1",
];

fn repo_root_candidates() -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(value) = std::env::var_os("SRMOD_REPO") {
        roots.push(PathBuf::from(value));
    }
    roots.push(PathBuf::from(r"D:\Solutions\pessoal\soul-reaver-ptbr-mod"));
    roots.push(PathBuf::from("."));
    roots.push(PathBuf::from(".."));
    roots.push(PathBuf::from("../.."));
    roots
}

fn find_bundle() -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os("SRMOD_MODULES") {
        let path = PathBuf::from(value);
        if is_modules_bundle(&path) {
            return Ok(path);
        }
    }
    for root in repo_root_candidates() {
        let modules = root.join("modules");
        if is_modules_bundle(&modules) {
            return Ok(modules);
        }
    }
    if let Some(value) = std::env::var_os("SRMOD_BUNDLE") {
        let path = PathBuf::from(value);
        if path.join("manifest.json").is_file() || is_modules_bundle(&path) {
            return Ok(path);
        }
    }
    for root in repo_root_candidates() {
        for name in BUNDLES {
            let candidate = root.join("staging").join("packages").join(name);
            if candidate.join("manifest.json").is_file() {
                return Ok(candidate);
            }
        }
    }
    Err("Pacote de dublagem não encontrado nos caminhos padrão.".into())
}

fn is_modules_bundle(bundle: &Path) -> bool {
    let Ok(bytes) = std::fs::read(bundle.join("bundle.json")) else {
        return false;
    };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        return false;
    };
    value.get("schema").and_then(|schema| schema.as_u64()) == Some(2)
        && value
            .get("modules")
            .and_then(|modules| modules.as_object())
            .is_some()
        && bundle.join("voices").join("manifest.json").is_file()
}

fn module_dir(bundle: &Path, name: &str) -> PathBuf {
    if is_modules_bundle(bundle) {
        bundle.join(name)
    } else {
        bundle.to_path_buf()
    }
}

fn module_manifest(bundle: &Path, module: &str, filename: &str) -> PathBuf {
    module_dir(bundle, module).join(filename)
}

struct AssetManifests {
    _temporary: Option<tempfile::TempDir>,
    localization: Option<PathBuf>,
    video: Option<PathBuf>,
}

fn asset_manifests(bundle: &Path) -> Result<AssetManifests, String> {
    if is_modules_bundle(bundle) {
        let localization = module_manifest(bundle, "localization", "assets.json");
        let video = module_manifest(bundle, "video", "video.json");
        return Ok(AssetManifests {
            _temporary: None,
            localization: localization.is_file().then_some(localization),
            video: video.is_file().then_some(video),
        });
    }

    let combined = bundle.join("assets.json");
    if !combined.is_file() {
        return Ok(AssetManifests {
            _temporary: None,
            localization: None,
            video: None,
        });
    }
    let bytes = std::fs::read(&combined).map_err(|error| error.to_string())?;
    let mut value: serde_json::Value =
        serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    let assets = value
        .get_mut("assets")
        .and_then(serde_json::Value::as_array_mut)
        .ok_or("Manifesto legado de assets inválido.")?;
    let temporary = tempfile::tempdir().map_err(|error| error.to_string())?;
    let mut split = [Vec::new(), Vec::new()];
    for (index, mut item) in assets.drain(..).enumerate() {
        let file = item
            .get("file")
            .and_then(serde_json::Value::as_str)
            .ok_or("Arquivo inválido no manifesto legado.")?;
        let is_video = file.ends_with(".bik");
        let payload = item
            .get("payload")
            .and_then(serde_json::Value::as_str)
            .ok_or("Payload inválido no manifesto legado.")?;
        if payload.is_empty()
            || payload.starts_with('.')
            || !payload
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
            || payload.contains("..")
        {
            return Err("Caminho de payload legado inseguro.".into());
        }
        let source = bundle.join(payload);
        let metadata = std::fs::symlink_metadata(&source).map_err(|error| error.to_string())?;
        if !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() > 512 * 1024 * 1024
        {
            return Err(format!("Payload legado ausente ou inseguro: {payload}"));
        }
        let destination_dir =
            temporary
                .path()
                .join(if is_video { "video" } else { "localization" });
        std::fs::create_dir_all(&destination_dir).map_err(|error| error.to_string())?;
        let destination_name = format!("payload-{index}.bin");
        let destination = destination_dir.join(&destination_name);
        std::fs::copy(&source, &destination).map_err(|error| error.to_string())?;
        item["payload"] = serde_json::Value::String(destination_name);
        split[usize::from(is_video)].push(item);
    }

    let mut paths = [None, None];
    for (index, (module, filename)) in [("localization", "assets.json"), ("video", "video.json")]
        .into_iter()
        .enumerate()
    {
        if split[index].is_empty() {
            continue;
        }
        let manifest = temporary.path().join(module).join(filename);
        std::fs::write(
            &manifest,
            serde_json::to_vec(&serde_json::json!({ "schema": 1, "assets": split[index] }))
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        paths[index] = Some(manifest);
    }
    Ok(AssetManifests {
        _temporary: Some(temporary),
        localization: paths[0].take(),
        video: paths[1].take(),
    })
}

fn backups_root() -> Result<PathBuf, String> {
    let base = std::env::var_os("LOCALAPPDATA")
        .ok_or("LOCALAPPDATA não encontrado para backup externo")?;
    Ok(PathBuf::from(base)
        .join("SoulReaverPTBR")
        .join("backups")
        .join("steam-classic-en"))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BundleInfo {
    path: String,
    name: String,
    version: String,
    voices: PackageInfo,
    graphics_available: bool,
    widescreen_available: bool,
    textures_available: bool,
    ui_available: bool,
    video_available: bool,
    video_files: usize,
    resolution: Option<String>,
    experimental: Vec<String>,
    localized_files: usize,
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase", default)]
struct BundleManifest {
    resolution: Option<String>,
    experimental: Vec<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ApplyOptions {
    dubbing: bool,
    localization: bool,
    #[serde(default = "default_true")]
    video: bool,
    graphics: bool,
    widescreen: bool,
    textures: bool,
    ui: bool,
    #[serde(default = "default_true")]
    vsync: bool,
    #[serde(default = "default_fps_limit")]
    fps_limit: u32,
    #[serde(default)]
    always_on_top: bool,
    #[serde(default)]
    render_resolution: Option<String>,
}

fn default_true() -> bool {
    true
}

fn default_fps_limit() -> u32 {
    60
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DiagnosticItem {
    id: String,
    ok: bool,
    detail: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Diagnostics {
    path: String,
    exe_sha256: String,
    exe_supported: bool,
    game_closed: bool,
    items: Vec<DiagnosticItem>,
}

#[tauri::command]
async fn detect_game() -> Option<String> {
    tauri::async_runtime::spawn_blocking(detect_game_blocking)
        .await
        .ok()
        .flatten()
}

fn detect_game_blocking() -> Option<String> {
    let steam_paths = [
        r"D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver",
        r"C:\Program Files (x86)\Steam\steamapps\common\Legacy of Kain Soul Reaver",
        r"C:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver",
        r"E:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver",
    ];
    for path in &steam_paths {
        if Path::new(path).join("kain2.exe").is_file() {
            return Some(path.to_string());
        }
    }
    None
}

#[tauri::command]
fn get_display_profile() -> graphics::DisplayProfile {
    graphics::display_profile()
}

#[tauri::command]
async fn inspect_game(path: String) -> Result<GameInfo, String> {
    tauri::async_runtime::spawn_blocking(move || {
        soul_reaver_mod_core::inspect_game(Path::new(&path))
    })
    .await
    .map_err(|error| format!("Falha na inspeção: {error}"))?
}

#[tauri::command]
async fn get_default_package_info() -> Result<PackageInfo, String> {
    tauri::async_runtime::spawn_blocking(get_default_package_info_blocking)
        .await
        .map_err(|error| format!("Falha na tarefa de inspeção do pacote padrão: {error}"))?
}

fn get_default_package_info_blocking() -> Result<PackageInfo, String> {
    let bundle = find_bundle()?;
    soul_reaver_mod_core::inspect_package(&module_manifest(&bundle, "voices", "manifest.json"))
}

#[tauri::command]
async fn get_bundle_info() -> Result<BundleInfo, String> {
    tauri::async_runtime::spawn_blocking(bundle_info)
        .await
        .map_err(|error| format!("Falha na inspeção do pacote: {error}"))?
}

fn bundle_info() -> Result<BundleInfo, String> {
    let bundle = find_bundle()?;
    let voices_path = module_manifest(&bundle, "voices", "manifest.json");
    let asset_manifests = asset_manifests(&bundle)?;
    let graphics_dir = module_dir(&bundle, "graphics");
    let textures_path = module_manifest(&bundle, "textures", "textures.json");
    let ui_path = module_manifest(&bundle, "ui", "ui.json");
    let voices = soul_reaver_mod_core::inspect_package(&voices_path)?;
    let graphics_available = ["DDraw.dll", "D3DImm.dll", "dgVoodoo.conf"]
        .iter()
        .all(|name| graphics_dir.join(name).is_file());
    let video_files = if let Some(video_path) = &asset_manifests.video {
        soul_reaver_mod_core::assets::inspect_package_component(
            &soul_reaver_mod_core::assets::VIDEO,
            video_path,
        )?
        .videos
    } else {
        0
    };
    let localized_files = if let Some(localization_path) = &asset_manifests.localization {
        soul_reaver_mod_core::assets::inspect_package_component(
            &soul_reaver_mod_core::assets::LOCALIZATION,
            localization_path,
        )?
        .files
    } else {
        0
    };
    let manifest: BundleManifest = std::fs::read(bundle.join("bundle.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default();
    Ok(BundleInfo {
        path: bundle.to_string_lossy().into(),
        name: voices.name.clone(),
        version: voices.version.clone(),
        graphics_available,
        widescreen_available: graphics_available,
        textures_available: textures_path.is_file(),
        ui_available: ui_path.is_file(),
        video_available: video_files > 0,
        video_files,
        resolution: manifest.resolution,
        experimental: manifest.experimental,
        localized_files,
        voices,
    })
}

#[tauri::command]
async fn apply_mod(
    app: tauri::AppHandle,
    state: tauri::State<'_, OperationState>,
    game_path: String,
    options: ApplyOptions,
) -> Result<GameInfo, String> {
    let control = begin_operation(&state)?;
    let worker_control = control.clone();
    let worker_app = app.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        apply_mod_blocking(worker_app, game_path, options, &worker_control)
    })
    .await;
    finish_operation(&state, &control);
    joined.map_err(|e| format!("Falha na tarefa de instalação: {e}"))?
}

fn apply_mod_blocking(
    app: tauri::AppHandle,
    game_path: String,
    options: ApplyOptions,
    control: &OperationControl,
) -> Result<GameInfo, String> {
    let bundle = find_bundle()?;
    let game = Path::new(&game_path);
    let backups = backups_root()?;
    let voices = module_manifest(&bundle, "voices", "manifest.json");
    let asset_manifests = asset_manifests(&bundle)?;
    let graphics_dir = module_dir(&bundle, "graphics");
    let textures = module_manifest(&bundle, "textures", "textures.json");
    let ui = module_manifest(&bundle, "ui", "ui.json");

    // Graphics files created by a previous, unrecorded session must never be
    // overwritten while installing the localization bundle.
    if options.graphics
        && graphics_dir.exists()
        && ["DDraw.dll", "D3DImm.dll", "dgVoodoo.conf"]
            .iter()
            .any(|name| game.join(name).exists())
    {
        let info = graphics::inspect(game);
        if info.map(|i| !i.installed).unwrap_or(true) {
            return Err("Há arquivos gráficos preexistentes sem propriedade comprovada. Preserve-os e desmarque 4K.".into());
        }
    }

    if options.localization {
        if let Some(assets) = &asset_manifests.localization {
            soul_reaver_mod_core::assets::validate_install(game, assets, &backups)?;
        }
    }
    if options.video {
        if let Some(video) = &asset_manifests.video {
            soul_reaver_mod_core::assets::validate_install_component(
                game,
                &soul_reaver_mod_core::assets::VIDEO,
                video,
                &backups,
            )?;
        }
    }
    if options.textures && textures.exists() {
        external::validate_install(game, &external::TEXTURES, &textures, &backups)?;
    }

    let mut messages: Vec<String> = Vec::new();
    if options.dubbing {
        control.checkpoint()?;
        soul_reaver_mod_core::apply_package_with_control(
            game,
            &voices,
            control,
            structured_reporter(&app),
        )?;
        messages.push("dublagem".into());
    }
    if options.localization {
        if let Some(assets) = &asset_manifests.localization {
            control.checkpoint()?;
            soul_reaver_mod_core::assets::apply_with_control(
                game,
                assets,
                &backups,
                control,
                structured_reporter(&app),
            )
            .map_err(|e| format!("Vozes aplicadas; localização não concluída: {e}"))?;
            messages.push("localização".into());
        }
    }
    if options.video {
        if let Some(video) = &asset_manifests.video {
            control.checkpoint()?;
            soul_reaver_mod_core::assets::apply_component_with_control(
                game,
                &soul_reaver_mod_core::assets::VIDEO,
                video,
                &backups,
                control,
                structured_reporter(&app),
            )
            .map_err(|e| format!("Componentes anteriores aplicados; vídeos não concluídos: {e}"))?;
            messages.push("vídeos".into());
        }
    }
    if options.graphics && graphics_dir.exists() {
        control.checkpoint()?;
        let render = graphics::RenderOptions {
            resolution: options
                .render_resolution
                .clone()
                .unwrap_or_else(|| "auto".into()),
            vsync: options.vsync,
            fps_limit: options.fps_limit,
            always_on_top: options.always_on_top,
        };
        graphics::apply_with_control(
            game,
            &graphics_dir,
            graphics::Request {
                widescreen: options.widescreen,
                render,
            },
            control,
            structured_reporter(&app),
        )?;
        messages.push(
            if options.widescreen {
                "4K + widescreen"
            } else {
                "4K"
            }
            .into(),
        );
    }
    if options.textures && textures.exists() {
        control.checkpoint()?;
        external::apply_with_control(
            game,
            &external::TEXTURES,
            &textures,
            &backups,
            control,
            structured_reporter(&app),
        )?;
        messages.push("texturas HD (experimental)".into());
    }
    if options.ui && ui.exists() {
        control.checkpoint()?;
        external::apply_with_control(
            game,
            &external::UI,
            &ui,
            &backups,
            control,
            structured_reporter(&app),
        )?;
        messages.push("interface (experimental)".into());
    }
    if messages.is_empty() {
        return Err("Nenhum componente foi selecionado.".into());
    }
    emit_progress(
        &app,
        Progress {
            stage: "concluido".into(),
            current: 1,
            total: 1,
            message: format!("Componentes aplicados: {}.", messages.join(", ")),
        },
    );
    soul_reaver_mod_core::inspect_game(game)
}

#[tauri::command]
async fn restore_component(
    app: tauri::AppHandle,
    state: tauri::State<'_, OperationState>,
    game_path: String,
    component: String,
) -> Result<GameInfo, String> {
    let control = begin_operation(&state)?;
    let worker_control = control.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        restore_component_blocking(app, game_path, component, &worker_control)
    })
    .await;
    finish_operation(&state, &control);
    joined.map_err(|e| format!("Falha na tarefa de restauração: {e}"))?
}

fn restore_component_blocking(
    app: tauri::AppHandle,
    game_path: String,
    component: String,
    control: &OperationControl,
) -> Result<GameInfo, String> {
    let game = Path::new(&game_path);
    match component.as_str() {
        "voices" => {
            soul_reaver_mod_core::restore_game_with_control(
                game,
                control,
                structured_reporter(&app),
            )?;
        }
        "localization" => {
            soul_reaver_mod_core::assets::restore_with_control(
                game,
                control,
                structured_reporter(&app),
            )?;
        }
        "video" => {
            soul_reaver_mod_core::assets::restore_component_with_control(
                game,
                &soul_reaver_mod_core::assets::VIDEO,
                control,
                structured_reporter(&app),
            )?;
        }
        "graphics" => {
            graphics::restore_with_control(game, control, structured_reporter(&app))?;
        }
        "textures" => {
            external::restore_with_control(
                game,
                &external::TEXTURES,
                control,
                structured_reporter(&app),
            )?;
        }
        "ui" => {
            external::restore_with_control(
                game,
                &external::UI,
                control,
                structured_reporter(&app),
            )?;
        }
        "controller" => {
            controller::remove(game)?;
        }
        _ => return Err("Componente desconhecido.".into()),
    }
    soul_reaver_mod_core::inspect_game(game)
}

#[tauri::command]
async fn restore_mod(
    app: tauri::AppHandle,
    state: tauri::State<'_, OperationState>,
    game_path: String,
) -> Result<GameInfo, String> {
    let control = begin_operation(&state)?;
    let worker_control = control.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        restore_mod_blocking(app, game_path, &worker_control)
    })
    .await;
    finish_operation(&state, &control);
    joined.map_err(|e| format!("Falha na tarefa de restauração: {e}"))?
}

fn restore_mod_blocking(
    app: tauri::AppHandle,
    game_path: String,
    control: &OperationControl,
) -> Result<GameInfo, String> {
    let game = Path::new(&game_path);
    // Owned components are restored independently; the executable returns to
    // the original state only in the graphics step, which runs last.
    let mut ui = || {
        external::restore_with_control(game, &external::UI, control, structured_reporter(&app))
            .map(|_| ())
    };
    let mut textures = || {
        external::restore_with_control(
            game,
            &external::TEXTURES,
            control,
            structured_reporter(&app),
        )
        .map(|_| ())
    };
    let mut localization = || {
        soul_reaver_mod_core::assets::restore_with_control(game, control, structured_reporter(&app))
            .map(|_| ())
    };
    let mut video = || {
        soul_reaver_mod_core::assets::restore_component_with_control(
            game,
            &soul_reaver_mod_core::assets::VIDEO,
            control,
            structured_reporter(&app),
        )
        .map(|_| ())
    };
    let mut voices = || {
        soul_reaver_mod_core::restore_game_with_control(game, control, structured_reporter(&app))
            .map(|_| ())
    };
    let mut graphics =
        || graphics::restore_with_control(game, control, structured_reporter(&app)).map(|_| ());
    let mut controller = || controller::remove(game).map(|_| ());
    let mut steps: [(&str, &mut dyn FnMut() -> Result<(), String>); 7] = [
        ("DualSense", &mut controller),
        ("interface", &mut ui),
        ("texturas", &mut textures),
        ("localização", &mut localization),
        ("vídeos", &mut video),
        ("vozes", &mut voices),
        ("gráficos", &mut graphics),
    ];
    restore_all_steps_control(&mut steps, control)?;
    soul_reaver_mod_core::inspect_game(game)
}

fn restore_all_steps(
    steps: &mut [(&str, &mut dyn FnMut() -> Result<(), String>)],
) -> Result<(), String> {
    let mut failures = Vec::new();
    for (component, restore) in steps {
        if let Err(error) = restore() {
            failures.push(format!("{component}: {error}"));
        }
    }
    if failures.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "Restauração incompleta; arquivos conflitantes foram preservados. {}",
            failures.join(" | ")
        ))
    }
}

fn restore_all_steps_control(
    steps: &mut [(&str, &mut dyn FnMut() -> Result<(), String>)],
    control: &OperationControl,
) -> Result<(), String> {
    let mut failures = Vec::new();
    for (component, restore) in steps {
        if let Err(error) = control.checkpoint() {
            return Err(error);
        }
        if let Err(error) = restore() {
            if error.contains("cancelada") {
                return Err(error);
            }
            failures.push(format!("{component}: {error}"));
        }
    }
    if failures.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "Restauração incompleta; arquivos conflitantes foram preservados. {}",
            failures.join(" | ")
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn test_parse_cli() {
        let usage = "Uso: --controller-[status|install|remove|launch] <pasta-jogo>".to_string();

        assert_eq!(parse_cli(&[]), CliAction::Gui);
        assert_eq!(
            parse_cli(&["app.exe".to_string()]),
            CliAction::Gui
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "--help".to_string()]),
            CliAction::Help
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "-h".to_string()]),
            CliAction::Help
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "--version".to_string()]),
            CliAction::Help
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "-V".to_string()]),
            CliAction::Help
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "--controller-foo".to_string(), "game".to_string()]),
            CliAction::UsageError(usage.clone())
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "--controller-status".to_string()]),
            CliAction::UsageError(usage.clone())
        );
        assert_eq!(
            parse_cli(&[
                "app.exe".to_string(),
                "--controller-status".to_string(),
                "D:\\Game".to_string()
            ]),
            CliAction::ControllerStatus(PathBuf::from("D:\\Game"))
        );
        assert_eq!(
            parse_cli(&[
                "app.exe".to_string(),
                "--controller-install".to_string(),
                "D:\\Game".to_string()
            ]),
            CliAction::ControllerInstall(PathBuf::from("D:\\Game"))
        );
        assert_eq!(
            parse_cli(&[
                "app.exe".to_string(),
                "--controller-remove".to_string(),
                "D:\\Game".to_string()
            ]),
            CliAction::ControllerRemove(PathBuf::from("D:\\Game"))
        );
        assert_eq!(
            parse_cli(&[
                "app.exe".to_string(),
                "--controller-launch".to_string(),
                "D:\\Game".to_string()
            ]),
            CliAction::ControllerLaunch(PathBuf::from("D:\\Game"))
        );
        assert_eq!(
            parse_cli(&["app.exe".to_string(), "--some-other-arg".to_string()]),
            CliAction::Gui
        );
    }

    #[test]
    #[cfg(windows)]
    #[ignore = "Requires release binary built with cargo build --release -p soul-reaver-mod-installer"]
    fn test_release_binary_controller_status_nonexistent_path() {
        use std::process::Command;

        let exe = std::env::var_os("CARGO_BIN_EXE_soul-reaver-mod-installer")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../target/release/soul-reaver-mod-installer.exe")
            });

        let output = Command::new(&exe)
            .args(["--controller-status", r"C:\caminho\inexistente"])
            .output()
            .expect("Falha ao executar o binário de release");

        assert_eq!(
            output.status.code(),
            Some(1),
            "Exit code esperado 1, obteve {:?}",
            output.status.code()
        );

        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            !stderr.trim().is_empty(),
            "stderr não deveria estar vazio no modo release para pasta inexistente"
        );
    }

    #[test]
    fn restore_reports_every_failure_and_still_attempts_later_components() {
        let attempted = RefCell::new(Vec::new());
        let mut ui = || {
            attempted.borrow_mut().push("interface");
            Err("conflito de hash".to_string())
        };
        let mut textures = || {
            attempted.borrow_mut().push("texturas");
            Ok(())
        };
        let mut graphics = || {
            attempted.borrow_mut().push("gráficos");
            Err("wrapper alterado".to_string())
        };
        let mut steps: [(&str, &mut dyn FnMut() -> Result<(), String>); 3] = [
            ("interface", &mut ui),
            ("texturas", &mut textures),
            ("gráficos", &mut graphics),
        ];

        let error = restore_all_steps(&mut steps).unwrap_err();
        assert_eq!(
            *attempted.borrow(),
            vec!["interface", "texturas", "gráficos"]
        );
        assert!(error.contains("interface: conflito de hash"));
        assert!(error.contains("gráficos: wrapper alterado"));
    }
}

/// Re-apply every component that the bundle provides, reusing the normal
/// idempotent paths. Useful after an interrupted operation.
#[tauri::command]
async fn repair_mod(
    app: tauri::AppHandle,
    state: tauri::State<'_, OperationState>,
    game_path: String,
) -> Result<GameInfo, String> {
    let control = begin_operation(&state)?;
    let worker_control = control.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        repair_mod_blocking(app, game_path, &worker_control)
    })
    .await;
    finish_operation(&state, &control);
    joined.map_err(|e| format!("Falha na tarefa de reparo: {e}"))?
}

fn repair_mod_blocking(
    app: tauri::AppHandle,
    game_path: String,
    control: &OperationControl,
) -> Result<GameInfo, String> {
    let bundle = find_bundle()?;
    let asset_manifests = asset_manifests(&bundle)?;
    let graphics_dir = module_dir(&bundle, "graphics");
    let textures = module_manifest(&bundle, "textures", "textures.json");
    let ui = module_manifest(&bundle, "ui", "ui.json");
    let render = graphics::current_render(Path::new(&game_path));
    let options = ApplyOptions {
        dubbing: true,
        localization: asset_manifests.localization.is_some(),
        video: asset_manifests.video.is_some(),
        graphics: graphics_dir.exists(),
        widescreen: true,
        textures: textures.exists(),
        ui: ui.exists(),
        vsync: render.vsync,
        fps_limit: render.fps_limit,
        always_on_top: render.always_on_top,
        render_resolution: Some(render.resolution),
    };
    // The companion is optional: a failure there is reported after the other
    // components were repaired instead of aborting the whole operation.
    let mut controller_error = None;
    if controller::deployed(Path::new(&game_path)) {
        control.checkpoint()?;
        if let Err(error) = controller::install(Path::new(&game_path)) {
            controller_error = Some(error);
        }
    }
    let applied = apply_mod_blocking(app, game_path, options, control)?;
    match controller_error {
        Some(error) => Err(format!("DualSense não pôde ser reparado: {error}")),
        None => Ok(applied),
    }
}

#[tauri::command]
fn pause_operation(state: tauri::State<'_, OperationState>) -> Result<(), String> {
    let current = state.current.lock().unwrap_or_else(|e| e.into_inner());
    let control = current.as_ref().ok_or("Não há operação em andamento.")?;
    control.pause();
    Ok(())
}

#[tauri::command]
fn resume_operation(state: tauri::State<'_, OperationState>) -> Result<(), String> {
    let current = state.current.lock().unwrap_or_else(|e| e.into_inner());
    let control = current.as_ref().ok_or("Não há operação em andamento.")?;
    control.resume();
    Ok(())
}

#[tauri::command]
fn cancel_operation(state: tauri::State<'_, OperationState>) -> Result<(), String> {
    let current = state.current.lock().unwrap_or_else(|e| e.into_inner());
    let control = current.as_ref().ok_or("Não há operação em andamento.")?;
    control.cancel();
    Ok(())
}

#[tauri::command]
async fn diagnose(game_path: String) -> Result<Diagnostics, String> {
    tauri::async_runtime::spawn_blocking(move || diagnose_blocking(game_path))
        .await
        .map_err(|error| format!("Falha no diagnóstico: {error}"))?
}

fn diagnose_blocking(game_path: String) -> Result<Diagnostics, String> {
    let game = Path::new(&game_path);
    let info = soul_reaver_mod_core::inspect_game(game)?;
    let exe_sha256 = soul_reaver_mod_core::exe_sha256(game)?;
    let exe_supported = exe_sha256 == soul_reaver_mod_core::EXE_SHA256
        || exe_sha256 == soul_reaver_mod_core::EXE_WIDESCREEN_SHA256;
    let game_closed = !soul_reaver_mod_core::is_game_running(game).unwrap_or(true);
    let mut items = Vec::new();
    items.push(DiagnosticItem {
        id: "voices".into(),
        ok: info.status == "installed",
        detail: format!(
            "{} / {} falas confirmadas contra o backup",
            info.replaced, info.total
        ),
    });
    items.push(DiagnosticItem {
        id: "localization".into(),
        ok: info.localization.menus,
        detail: format!(
            "menus={}, legendas={}, arquivos={}",
            info.localization.menus, info.localization.subtitles, info.localization.files
        ),
    });
    // One unavailable module must not blank the whole report: each check that can
    // fail on its own is reported as an item instead of aborting the diagnosis.
    match bundle_info() {
        Ok(bundle) => {
            items.push(DiagnosticItem {
                id: "video".into(),
                ok: info.video.installed,
                detail: format!(
                    "{}; módulo no bundle: {} ({} arquivos)",
                    info.video.message,
                    if bundle.video_available {
                        "disponível"
                    } else {
                        "indisponível"
                    },
                    bundle.video_files
                ),
            });
            items.push(DiagnosticItem {
                id: "bundle".into(),
                ok: bundle.localized_files > 0 && bundle.video_available,
                detail: format!(
                    "modules/: localização={}, vídeo={}, gráficos={}, texturas={}, UI={}; resolução={}; experimentais={}",
                    bundle.localized_files > 0,
                    bundle.video_available,
                    bundle.graphics_available,
                    bundle.textures_available,
                    bundle.ui_available,
                    bundle.resolution.as_deref().unwrap_or("não declarada"),
                    if bundle.experimental.is_empty() { "nenhum".to_string() } else { bundle.experimental.join(", ") }
                ),
            });
        }
        Err(error) => {
            items.push(DiagnosticItem {
                id: "video".into(),
                ok: info.video.installed,
                detail: format!("{}; módulo no bundle: não foi possível ler.", info.video.message),
            });
            items.push(DiagnosticItem {
                id: "bundle".into(),
                ok: false,
                detail: format!("Pacote indisponível: {error}"),
            });
        }
    }
    items.push(DiagnosticItem {
        id: "graphics".into(),
        ok: info.graphics.installed,
        detail: info.graphics.message.clone(),
    });
    items.push(DiagnosticItem {
        id: "textures".into(),
        ok: info.textures.installed,
        detail: info.textures.message.clone(),
    });
    items.push(DiagnosticItem {
        id: "ui".into(),
        ok: info.ui.installed,
        detail: info.ui.message.clone(),
    });
    match controller::status(Path::new(&game_path)) {
        Ok(controller) => items.push(DiagnosticItem {
            id: "controller".into(),
            ok: controller.installed && controller.connected,
            detail: controller.message,
        }),
        Err(error) => items.push(DiagnosticItem {
            id: "controller".into(),
            ok: false,
            detail: format!("Não foi possível verificar o suporte ao DualSense: {error}"),
        }),
    }
    Ok(Diagnostics {
        path: info.path,
        exe_sha256,
        exe_supported,
        game_closed,
        items,
    })
}

#[derive(Debug, PartialEq, Eq)]
enum CliAction {
    Gui,
    Help,
    ControllerStatus(PathBuf),
    ControllerInstall(PathBuf),
    ControllerRemove(PathBuf),
    ControllerLaunch(PathBuf),
    UsageError(String),
}

fn parse_cli(args: &[String]) -> CliAction {
    if args.len() <= 1 {
        return CliAction::Gui;
    }

    if args
        .iter()
        .skip(1)
        .any(|a| a == "--help" || a == "-h" || a == "--version" || a == "-V")
    {
        return CliAction::Help;
    }

    let first = &args[1];
    if first.starts_with("--controller-") {
        let usage = "Uso: --controller-[status|install|remove|launch] <pasta-jogo>".to_string();
        let path = match args.get(2) {
            Some(p) if !p.is_empty() => PathBuf::from(p),
            _ => return CliAction::UsageError(usage),
        };

        match first.as_str() {
            "--controller-status" => CliAction::ControllerStatus(path),
            "--controller-install" => CliAction::ControllerInstall(path),
            "--controller-remove" => CliAction::ControllerRemove(path),
            "--controller-launch" => CliAction::ControllerLaunch(path),
            _ => CliAction::UsageError(usage),
        }
    } else {
        CliAction::Gui
    }
}

#[cfg(windows)]
fn attach_console() {
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn AttachConsole(dwProcessId: u32) -> i32;
    }
    const ATTACH_PARENT_PROCESS: u32 = 0xFFFFFFFF;
    unsafe {
        let _ = AttachConsole(ATTACH_PARENT_PROCESS);
    }
}

#[cfg(not(windows))]
fn attach_console() {}

fn print_cli_help() {
    println!(
        "Instalador do Mod Soul Reaver PT-BR\n\n\
         Uso:\n  \
           soul-reaver-mod-installer [opções]\n\n\
         Opções CLI:\n  \
           --controller-status <pasta-jogo>   Exibe o status do suporte ao DualSense\n  \
           --controller-install <pasta-jogo>  Instala o acompanhante DualSense\n  \
           --controller-remove <pasta-jogo>   Remove o acompanhante DualSense\n  \
           --controller-launch <pasta-jogo>   Inicia o jogo com acompanhante DualSense\n  \
           --help, -h                         Exibe esta mensagem de ajuda\n  \
           --version, -V                      Exibe esta mensagem de ajuda"
    );
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let action = parse_cli(&args);
    if action != CliAction::Gui {
        attach_console();
    }
    match action {
        CliAction::Gui => {}
        CliAction::Help => {
            print_cli_help();
            return;
        }
        CliAction::UsageError(err) => {
            eprintln!("{err}");
            std::process::exit(1);
        }
        CliAction::ControllerStatus(game) => {
            match controller::status(&game) {
                Ok(status) => match serde_json::to_string(&status) {
                    Ok(json) => println!("{json}"),
                    Err(e) => {
                        eprintln!("Erro ao serializar status: {e}");
                        std::process::exit(1);
                    }
                },
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            }
            return;
        }
        CliAction::ControllerInstall(game) => {
            match controller::install(&game) {
                Ok(status) => match serde_json::to_string(&status) {
                    Ok(json) => println!("{json}"),
                    Err(e) => {
                        eprintln!("Erro ao serializar status: {e}");
                        std::process::exit(1);
                    }
                },
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            }
            return;
        }
        CliAction::ControllerRemove(game) => {
            match controller::remove(&game) {
                Ok(status) => match serde_json::to_string(&status) {
                    Ok(json) => println!("{json}"),
                    Err(e) => {
                        eprintln!("Erro ao serializar status: {e}");
                        std::process::exit(1);
                    }
                },
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            }
            return;
        }
        CliAction::ControllerLaunch(game) => {
            match controller::launch(&game) {
                Ok(status) => match serde_json::to_string(&status) {
                    Ok(json) => println!("{json}"),
                    Err(e) => {
                        eprintln!("Erro ao serializar status: {e}");
                        std::process::exit(1);
                    }
                },
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            }
            return;
        }
    }
    tauri::Builder::default()
        .manage(OperationState::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            detect_game,
            get_display_profile,
            inspect_game,
            get_default_package_info,
            get_bundle_info,
            apply_mod,
            restore_component,
            restore_mod,
            repair_mod,
            diagnose,
            pause_operation,
            resume_operation,
            cancel_operation,
            get_controller_status,
            install_controller,
            remove_controller,
            launch_game,
            launch_controller_game,
            open_logs_folder
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
