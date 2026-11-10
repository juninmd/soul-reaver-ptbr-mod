//! Read-only report of one installation: game state, per-component diagnosis
//! and controller support, gathered in a single pass.

use crate::{bundle::BundleInfo, controller};
use serde::Serialize;
use soul_reaver_mod_core::{GameInfo, exe_sha256, inspect_game, is_game_running, is_supported_exe};
use std::path::Path;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticItem {
    id: &'static str,
    ok: bool,
    detail: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostics {
    path: String,
    exe_sha256: String,
    exe_supported: bool,
    game_closed: bool,
    items: Vec<DiagnosticItem>,
}

/// Everything the interface shows about an installation.
///
/// The archives are hashed once here. The interface used to ask for the game
/// state, the diagnosis and the controller separately, and each answer
/// inspected the same files again.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InstallationReport {
    game: Option<GameInfo>,
    /// Why the installation could not be inspected, when `game` is absent.
    error: Option<String>,
    diagnostics: Option<Diagnostics>,
    controller: Option<controller::Status>,
    /// Secondary checks that failed without invalidating the inspection.
    warnings: Vec<String>,
}

fn availability(available: bool) -> &'static str {
    if available {
        "disponível"
    } else {
        "indisponível"
    }
}

fn diagnose(
    game: &Path,
    info: &GameInfo,
    bundle: &Result<BundleInfo, String>,
    controller: &Result<controller::Status, String>,
) -> Result<Diagnostics, String> {
    let exe_sha256 = exe_sha256(game)?;
    let game_closed = match controller {
        Ok(status) => !status.running,
        Err(_) => !is_game_running(game).unwrap_or(true),
    };
    let item = |id, ok, detail| DiagnosticItem { id, ok, detail };
    let mut items = vec![
        item(
            "voices",
            info.status == "installed",
            format!(
                "{} / {} falas confirmadas contra o backup",
                info.replaced, info.total
            ),
        ),
        item(
            "localization",
            info.localization.menus,
            format!(
                "menus={}, legendas={}, arquivos={}",
                info.localization.menus, info.localization.subtitles, info.localization.files
            ),
        ),
    ];
    // One unavailable module must not blank the whole report: each check that can
    // fail on its own is reported as an item instead of aborting the diagnosis.
    match bundle {
        Ok(bundle) => {
            items.push(item(
                "video",
                info.video.installed,
                format!(
                    "{}; módulo no bundle: {} ({} arquivos)",
                    info.video.message,
                    availability(bundle.video_available),
                    bundle.video_files
                ),
            ));
            items.push(item(
                "bundle",
                bundle.localized_files > 0 && bundle.video_available,
                format!(
                    "modules/: localização={}, vídeo={}, gráficos={}, texturas={}, UI={}; resolução={}; experimentais={}",
                    bundle.localized_files > 0,
                    bundle.video_available,
                    bundle.graphics_available,
                    bundle.textures_available,
                    bundle.ui_available,
                    bundle.resolution.as_deref().unwrap_or("não declarada"),
                    if bundle.experimental.is_empty() {
                        "nenhum".to_string()
                    } else {
                        bundle.experimental.join(", ")
                    }
                ),
            ));
        }
        Err(error) => {
            items.push(item(
                "video",
                info.video.installed,
                format!(
                    "{}; módulo no bundle: não foi possível ler.",
                    info.video.message
                ),
            ));
            items.push(item(
                "bundle",
                false,
                format!("Pacote indisponível: {error}"),
            ));
        }
    }
    items.push(item(
        "graphics",
        info.graphics.installed,
        info.graphics.message.clone(),
    ));
    items.push(item(
        "textures",
        info.textures.installed,
        info.textures.message.clone(),
    ));
    items.push(item("ui", info.ui.installed, info.ui.message.clone()));
    items.push(match controller {
        Ok(status) => item(
            "controller",
            status.installed && status.connected,
            status.message.clone(),
        ),
        Err(error) => item(
            "controller",
            false,
            format!("Não foi possível verificar o suporte ao DualSense: {error}"),
        ),
    });
    Ok(Diagnostics {
        path: info.path.clone(),
        exe_supported: is_supported_exe(&exe_sha256),
        exe_sha256,
        game_closed,
        items,
    })
}

/// Inspects the installation once and derives every view from that result.
pub fn report(game: &Path, bundle: Result<BundleInfo, String>) -> InstallationReport {
    let controller = controller::status(game);
    let mut warnings = Vec::new();
    let (game_info, error, diagnostics) = match inspect_game(game) {
        Ok(info) => {
            let diagnostics = diagnose(game, &info, &bundle, &controller)
                .map_err(|error| warnings.push(error))
                .ok();
            (Some(info), None, diagnostics)
        }
        Err(error) => (None, Some(error), None),
    };
    let controller = controller.map_err(|error| warnings.push(error)).ok();
    warnings.dedup();
    InstallationReport {
        game: game_info,
        error,
        diagnostics,
        controller,
        warnings,
    }
}
