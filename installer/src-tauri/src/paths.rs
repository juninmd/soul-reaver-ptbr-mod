//! Per-user locations outside the game folder.

use std::path::PathBuf;

fn data_root() -> Result<PathBuf, String> {
    let base = std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA não encontrado")?;
    Ok(PathBuf::from(base).join("SoulReaverPTBR"))
}

/// Backups of replaced originals: never inside the installation.
pub fn backups_root() -> Result<PathBuf, String> {
    Ok(data_root()
        .map_err(|error| format!("{error} para backup externo"))?
        .join("backups")
        .join("steam-classic-en"))
}

pub fn logs_dir() -> Result<PathBuf, String> {
    Ok(data_root()?.join("logs"))
}
