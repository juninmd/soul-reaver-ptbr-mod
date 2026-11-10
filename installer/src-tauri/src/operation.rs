//! One mutating operation at a time, with cooperative control and progress events.

use soul_reaver_mod_core::{OperationControl, Progress};
use std::{
    cell::RefCell,
    sync::{Arc, Mutex, MutexGuard},
    time::{Duration, Instant},
};
use tauri::Emitter;

#[derive(Default)]
pub struct OperationState {
    current: Mutex<Option<Arc<OperationControl>>>,
}

impl OperationState {
    fn current(&self) -> MutexGuard<'_, Option<Arc<OperationControl>>> {
        self.current.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Claims the single operation slot until the returned guard is dropped.
    pub fn begin(&self) -> Result<OperationGuard<'_>, String> {
        let mut current = self.current();
        if current.is_some() {
            return Err("Já existe uma operação em andamento.".into());
        }
        let control = Arc::new(OperationControl::default());
        *current = Some(control.clone());
        Ok(OperationGuard {
            state: self,
            control,
        })
    }

    /// Runs `action` on the control of the operation in progress.
    pub fn signal(&self, action: impl FnOnce(&OperationControl)) -> Result<(), String> {
        let current = self.current();
        action(current.as_ref().ok_or("Não há operação em andamento.")?);
        Ok(())
    }
}

/// Releases the operation slot on drop, so a failed or panicked worker can
/// never leave the installer permanently busy.
pub struct OperationGuard<'a> {
    state: &'a OperationState,
    control: Arc<OperationControl>,
}

impl OperationGuard<'_> {
    pub fn control(&self) -> Arc<OperationControl> {
        self.control.clone()
    }
}

impl Drop for OperationGuard<'_> {
    fn drop(&mut self) {
        let mut current = self.state.current();
        if current
            .as_ref()
            .is_some_and(|active| Arc::ptr_eq(active, &self.control))
        {
            *current = None;
        }
    }
}

/// Runs blocking `work` on the worker pool while holding the operation slot.
pub async fn exclusive<T: Send + 'static>(
    state: &OperationState,
    task: &str,
    work: impl FnOnce(&OperationControl) -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    let guard = state.begin()?;
    let control = guard.control();
    blocking(task, move || work(&control)).await
}

/// Runs blocking `work` on the worker pool, keeping the webview responsive.
pub async fn blocking<T: Send + 'static>(
    task: &str,
    work: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|error| format!("Falha na tarefa de {task}: {error}"))?
}

/// Forwards progress to the webview at a bounded rate.
///
/// A full dubbing package reports 479 units within milliseconds; sending each
/// one would only queue renders the eye cannot follow. Stage changes and the
/// first and last unit of a stage always pass.
pub struct ProgressSink {
    app: tauri::AppHandle,
    last: RefCell<Option<(String, Instant)>>,
}

impl ProgressSink {
    const INTERVAL: Duration = Duration::from_millis(40);

    pub fn new(app: tauri::AppHandle) -> Self {
        Self {
            app,
            last: RefCell::new(None),
        }
    }

    pub fn emit(&self, progress: Progress) {
        let mut last = self.last.borrow_mut();
        let boundary = progress.current == 0 || progress.current >= progress.total;
        let recent = last
            .as_ref()
            .is_some_and(|(stage, at)| *stage == progress.stage && at.elapsed() < Self::INTERVAL);
        if recent && !boundary {
            return;
        }
        *last = Some((progress.stage.clone(), Instant::now()));
        let _ = self.app.emit("progress", progress);
    }
}
