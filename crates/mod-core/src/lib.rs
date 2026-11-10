//! Core of the Soul Reaver PT-BR mod: hash-verified, journaled and reversible
//! changes to a supported installation.
//!
//! | Module | Responsibility |
//! | --- | --- |
//! | [`voices`] | Dubbing: `voices.dat` slot table, journal, apply and restore |
//! | [`assets`] | Localization and video files with per-component journals |
//! | [`external`] | Textures, interface and companion files with external backups |
//! | [`graphics`] | dgVoodoo wrapper, render profile and widescreen patch |
//! | [`operation`] | Progress events and cooperative pause/cancel |
//! | [`process`] | Running-game detection |
//! | `fsx` | Guarded I/O, streaming SHA-256, atomic writes and the operation lock |

use serde::{Deserialize, Serialize};
use std::path::Path;

pub mod assets;
pub mod external;
mod fsx;
pub mod graphics;
pub mod operation;
pub mod process;
#[cfg(test)]
mod test_support;
pub mod voices;

pub use operation::{OperationControl, Progress};
pub use process::is_game_running;
pub use voices::{
    Coverage, Manifest, PackageInfo, Patch, apply_package, apply_package_with_control, exe_sha256,
    inspect_game, inspect_package, restore_game, restore_game_with_control,
};

pub const EXE_SHA256: &str = "9793031080e606075d7af51d7232c12494449a87fe120675e0c80c318c89a30a";
pub const EXE_WIDESCREEN_SHA256: &str =
    "396a757334daa8fdf8930de70a63929bbe0cb0d6bc3250ce5a2dd50056c1e243";
pub const VOICES_SHA256: &str = "e2a193b62f9723f5f477f705c53a56f895375ce2d980d276d0d0fceeb2645df5";
/// Directory inside the installation that holds journals, the lock and the voice backup.
pub(crate) const MANAGER: &str = ".soul-reaver-ptbr";

pub type Result<T> = std::result::Result<T, String>;

/// Lowercase hexadecimal SHA-256, the encoding used by every manifest and journal.
pub fn sha256_hex(bytes: &[u8]) -> String {
    fsx::sha(bytes)
}

/// True when `hash` identifies one of the supported `kain2.exe` builds.
pub fn is_supported_exe(hash: &str) -> bool {
    hash == EXE_SHA256 || hash == EXE_WIDESCREEN_SHA256
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

pub fn apply_graphics(
    game: &Path,
    graphics_source: &Path,
    request: graphics::Request,
    progress: impl FnMut(&str),
) -> Result<()> {
    graphics::apply(game, graphics_source, request, progress).map(drop)
}

pub fn restore_graphics(game: &Path, progress: impl FnMut(&str)) -> Result<()> {
    graphics::restore(game, progress).map(drop)
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
