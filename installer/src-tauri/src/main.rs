#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Desktop installer: a Tauri shell around `soul-reaver-mod-core`.
//!
//! | Module | Responsibility |
//! | --- | --- |
//! | `commands` | IPC surface called by the React interface |
//! | `transactions` | Order and pre-validation of install, restore and repair |
//! | `diagnostics` | Single-pass report of an installation |
//! | `operation` | Operation slot, worker pool helpers and progress events |
//! | `bundle` | Package location, layouts and verified description |
//! | `detect` | Steam library discovery |
//! | `controller`, `game_launch` | DualSense companion and game start |
//! | `cli` | Command-line modes for automated checks |
//! | `paths` | Per-user backup and log locations |

mod bundle;
mod cli;
mod commands;
mod controller;
mod detect;
mod diagnostics;
mod game_launch;
mod operation;
mod paths;
mod transactions;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if let Some(code) = cli::run(&args) {
        std::process::exit(code);
    }
    tauri::Builder::default()
        .manage(operation::OperationState::default())
        .manage(bundle::BundleCache::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::detect_game,
            commands::get_display_profile,
            commands::get_bundle_info,
            commands::inspect_installation,
            commands::apply_mod,
            commands::restore_component,
            commands::restore_mod,
            commands::repair_mod,
            commands::pause_operation,
            commands::resume_operation,
            commands::cancel_operation,
            commands::install_controller,
            commands::remove_controller,
            commands::launch_game,
            commands::launch_controller_game,
            commands::open_logs_folder
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
