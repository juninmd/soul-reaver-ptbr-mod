//! Progress reporting and cooperative pause/cancel shared by every operation.

use crate::Result;
use serde::{Deserialize, Serialize};
use std::{
    sync::{
        Condvar, Mutex, MutexGuard,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

/// Journal phases common to every managed component.
pub(crate) const PHASES: [&str; 5] = [
    "original",
    "preparing",
    "installed",
    "restoring",
    "restored",
];

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Progress {
    pub stage: String,
    pub current: usize,
    pub total: usize,
    pub message: String,
}

impl Progress {
    pub fn new(
        stage: impl Into<String>,
        current: usize,
        total: usize,
        message: impl Into<String>,
    ) -> Self {
        Self {
            stage: stage.into(),
            current,
            total,
            message: message.into(),
        }
    }

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
    fn paused(&self) -> MutexGuard<'_, bool> {
        self.paused.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn cancel(&self) {
        self.canceled.store(true, Ordering::Release);
        self.resumed.notify_all();
    }

    pub fn pause(&self) {
        *self.paused() = true;
    }

    pub fn resume(&self) {
        *self.paused() = false;
        self.resumed.notify_all();
    }

    pub fn is_paused(&self) -> bool {
        *self.paused()
    }

    /// Blocks while paused; fails once the operation was canceled.
    pub fn checkpoint(&self) -> Result<()> {
        let mut paused = self.paused();
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
