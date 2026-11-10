//! Detection of a running game, so no managed file is replaced under it.

use crate::{Result, fsx::io};
use std::{
    cell::Cell,
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
    Ok(system.processes().values().any(|p| {
        p.name()
            .to_str()
            .is_some_and(|n| n.eq_ignore_ascii_case("kain2.exe"))
            && p.exe()
                .and_then(|e| e.canonicalize().ok())
                .is_some_and(|e| e == expected)
    }))
}

pub(crate) fn ensure_closed(game: &Path) -> Result<()> {
    if is_game_running(game)? {
        return Err("Feche o jogo antes de aplicar ou restaurar a dublagem.".into());
    }
    Ok(())
}

/// Repeated closed-game check for loops that write many files.
///
/// Enumerating every process costs milliseconds; a package with hundreds of
/// small files paid that before each one. The answer is reused for a short
/// window instead, which keeps the guard continuous at a bounded cost.
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
        guard.ensure()?;
        Ok(guard)
    }

    pub(crate) fn ensure(&self) -> Result<()> {
        if self
            .checked
            .get()
            .is_some_and(|at| at.elapsed() < Self::WINDOW)
        {
            return Ok(());
        }
        ensure_closed(&self.game)?;
        self.checked.set(Some(Instant::now()));
        Ok(())
    }
}
