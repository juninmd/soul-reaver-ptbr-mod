//! Detection of a running game, so no managed file is replaced under it.

use crate::{Result, fsx::io};
use std::{
    cell::Cell,
    ffi::OsStr,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

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
    Ok(system
        .processes()
        .values()
        .any(|p| is_managed_game(p.name(), p.exe(), &expected)))
}

/// A `kain2.exe` whose path cannot be read (e.g. an elevated game seen from a
/// non-elevated installer) counts as running: writing under it is not safe.
fn is_managed_game(name: &OsStr, exe: Option<&Path>, expected: &Path) -> bool {
    if !name
        .to_str()
        .is_some_and(|n| n.eq_ignore_ascii_case("kain2.exe"))
    {
        return false;
    }
    match exe.map(Path::canonicalize) {
        Some(Ok(path)) => path == expected,
        _ => true,
    }
}

pub(crate) fn ensure_closed(game: &Path) -> Result<()> {
    if is_game_running(game)? {
        return Err("Feche o jogo antes de aplicar ou restaurar a dublagem.".into());
    }
    Ok(())
}

/// Closed-game check for loops that write many files.
///
/// Enumerating every process costs milliseconds, and a texture package creates
/// hundreds of small files. Two strengths are offered so the cost is only
/// saved where it is safe to:
///
/// - [`ClosedGame::recheck`] scans now. It guards every write that replaces or
///   restores a file the game itself ships and may hold open.
/// - [`ClosedGame::ensure`] reuses a scan made within the last 250 ms. It
///   guards files that only this mod creates or removes.
pub(crate) struct ClosedGame {
    game: PathBuf,
    checked: Cell<Option<Instant>>,
}

impl ClosedGame {
    const WINDOW: Duration = Duration::from_millis(250);

    /// Checks immediately, so an operation never starts against a running game.
    pub(crate) fn new(game: &Path) -> Result<Self> {
        let guard = Self {
            game: game.to_path_buf(),
            checked: Cell::new(None),
        };
        guard.recheck()?;
        Ok(guard)
    }

    /// Scans the processes now, whatever the last answer was.
    pub(crate) fn recheck(&self) -> Result<()> {
        ensure_closed(&self.game)?;
        self.checked.set(Some(Instant::now()));
        Ok(())
    }

    /// Accepts an answer obtained within the window; scans otherwise.
    pub(crate) fn ensure(&self) -> Result<()> {
        if self
            .checked
            .get()
            .is_some_and(|at| at.elapsed() < Self::WINDOW)
        {
            return Ok(());
        }
        self.recheck()
    }

    /// The check owed before writing a file: fresh when `ships_with_game`.
    pub(crate) fn before_write(&self, ships_with_game: bool) -> Result<()> {
        if ships_with_game {
            self.recheck()
        } else {
            self.ensure()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unreadable_game_path_counts_as_running() {
        let dir = tempfile::tempdir().unwrap();
        let expected = dir.path().canonicalize().unwrap();
        assert!(is_managed_game(OsStr::new("KAIN2.EXE"), None, &expected));
        assert!(is_managed_game(
            OsStr::new("kain2.exe"),
            Some(&dir.path().join("missing.exe")),
            &expected
        ));
    }

    #[test]
    fn readable_paths_are_matched_exactly() {
        let dir = tempfile::tempdir().unwrap();
        let other = tempfile::tempdir().unwrap();
        let expected = dir.path().canonicalize().unwrap();
        assert!(is_managed_game(
            OsStr::new("kain2.exe"),
            Some(dir.path()),
            &expected
        ));
        assert!(!is_managed_game(
            OsStr::new("kain2.exe"),
            Some(other.path()),
            &expected
        ));
        assert!(!is_managed_game(OsStr::new("notepad.exe"), None, &expected));
    }
}
