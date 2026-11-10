//! IPC surface of the installer. Every command is a thin wrapper: blocking
//! work runs on the worker pool and mutations hold the single operation slot.

use crate::{
    bundle::{BundleCache, BundleInfo},
    controller, detect,
    diagnostics::{self, InstallationReport},
    game_launch,
    operation::{OperationState, ProgressSink, blocking, exclusive},
    paths,
    transactions::{self, ApplyOptions},
};
use soul_reaver_mod_core::{GameInfo, graphics};
use std::path::{Path, PathBuf};
use tauri::{AppHandle, State};

type Operations<'a> = State<'a, OperationState>;

// ---- Read-only queries

#[tauri::command]
pub async fn detect_game() -> Option<String> {
    blocking("detecção", || Ok(detect::detect_game()))
        .await
        .ok()
        .flatten()
}

#[tauri::command]
pub fn get_display_profile() -> graphics::DisplayProfile {
    graphics::display_profile()
}

/// Verifies the package on disk. This is the only query that refreshes the
/// description reused by [`inspect_installation`].
#[tauri::command]
pub async fn get_bundle_info(app: AppHandle) -> Result<BundleInfo, String> {
    blocking("inspeção do pacote", move || {
        tauri::Manager::state::<BundleCache>(&app).refresh()
    })
    .await
}

#[tauri::command]
pub async fn inspect_installation(
    app: AppHandle,
    game_path: String,
) -> Result<InstallationReport, String> {
    blocking("inspeção", move || {
        let bundle = tauri::Manager::state::<BundleCache>(&app).get();
        Ok(diagnostics::report(Path::new(&game_path), bundle))
    })
    .await
}

// ---- Component operations

#[tauri::command]
pub async fn apply_mod(
    app: AppHandle,
    state: Operations<'_>,
    game_path: String,
    options: ApplyOptions,
) -> Result<GameInfo, String> {
    exclusive(&state, "instalação", move |control| {
        let progress = ProgressSink::new(app);
        transactions::apply(Path::new(&game_path), options, control, &|p| {
            progress.emit(p)
        })
    })
    .await
}

#[tauri::command]
pub async fn restore_component(
    app: AppHandle,
    state: Operations<'_>,
    game_path: String,
    component: String,
) -> Result<GameInfo, String> {
    exclusive(&state, "restauração", move |control| {
        let progress = ProgressSink::new(app);
        transactions::restore_component(Path::new(&game_path), &component, control, &|p| {
            progress.emit(p)
        })
    })
    .await
}

#[tauri::command]
pub async fn restore_mod(
    app: AppHandle,
    state: Operations<'_>,
    game_path: String,
) -> Result<GameInfo, String> {
    exclusive(&state, "restauração", move |control| {
        let progress = ProgressSink::new(app);
        transactions::restore_all(Path::new(&game_path), control, &|p| progress.emit(p))
    })
    .await
}

#[tauri::command]
pub async fn repair_mod(
    app: AppHandle,
    state: Operations<'_>,
    game_path: String,
) -> Result<GameInfo, String> {
    exclusive(&state, "reparo", move |control| {
        let progress = ProgressSink::new(app);
        transactions::repair(Path::new(&game_path), control, &|p| progress.emit(p))
    })
    .await
}

#[tauri::command]
pub fn pause_operation(state: Operations<'_>) -> Result<(), String> {
    state.signal(|control| control.pause())
}

#[tauri::command]
pub fn resume_operation(state: Operations<'_>) -> Result<(), String> {
    state.signal(|control| control.resume())
}

#[tauri::command]
pub fn cancel_operation(state: Operations<'_>) -> Result<(), String> {
    state.signal(|control| control.cancel())
}

// ---- Game and controller

#[tauri::command]
pub async fn launch_game(state: Operations<'_>, game_path: String) -> Result<(), String> {
    exclusive(&state, "inicialização", move |_| {
        game_launch::launch(Path::new(&game_path))
    })
    .await
}

async fn controller_operation(
    state: &OperationState,
    task: &str,
    game_path: String,
    action: fn(&Path) -> Result<controller::Status, String>,
) -> Result<controller::Status, String> {
    exclusive(state, task, move |_| action(&PathBuf::from(game_path))).await
}

#[tauri::command]
pub async fn install_controller(
    state: Operations<'_>,
    game_path: String,
) -> Result<controller::Status, String> {
    controller_operation(
        &state,
        "instalação do controle",
        game_path,
        controller::install,
    )
    .await
}

#[tauri::command]
pub async fn remove_controller(
    state: Operations<'_>,
    game_path: String,
) -> Result<controller::Status, String> {
    controller_operation(&state, "remoção do controle", game_path, controller::remove).await
}

#[tauri::command]
pub async fn launch_controller_game(
    state: Operations<'_>,
    game_path: String,
) -> Result<controller::Status, String> {
    controller_operation(
        &state,
        "inicialização com controle",
        game_path,
        controller::launch,
    )
    .await
}

#[tauri::command]
pub fn open_logs_folder() -> Result<(), String> {
    let logs = paths::logs_dir()?;
    std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
    #[cfg(windows)]
    let mut command = {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let mut command = std::process::Command::new("explorer");
        command.creation_flags(CREATE_NO_WINDOW);
        command
    };
    #[cfg(not(windows))]
    let mut command = std::process::Command::new("xdg-open");
    command
        .arg(&logs)
        .spawn()
        .map(drop)
        .map_err(|e| e.to_string())
}
