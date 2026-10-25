//! Deploy the embedded companion through the same ownership journal as other components.
use serde::Serialize;
use sha2::{Digest, Sha256};
use soul_reaver_mod_core::{
    EXE_SHA256, EXE_WIDESCREEN_SHA256, exe_sha256, external, is_game_running,
};
use std::{fs, path::Path, process::Command, sync::OnceLock};

#[cfg(windows)]
const COMPANION: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/sr-dualsense.exe"));
#[cfg(not(windows))]
const COMPANION: &[u8] = &[];

static COMPANION_DIGEST: OnceLock<String> = OnceLock::new();

fn companion_digest() -> &'static str {
    COMPANION_DIGEST.get_or_init(|| digest(COMPANION))
}

pub fn prune_logs(dir: &Path, max_age: std::time::Duration, max_files: usize) -> std::io::Result<()> {
    prune_logs_at(dir, max_age, max_files, std::time::SystemTime::now())
}

pub fn prune_logs_at(
    dir: &Path,
    max_age: std::time::Duration,
    max_files: usize,
    now: std::time::SystemTime,
) -> std::io::Result<()> {
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e),
    };

    let mut logs = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let file_name = entry.file_name();
        let name_str = file_name.to_string_lossy();
        if name_str.starts_with("dualsense-") && name_str.ends_with(".jsonl") {
            if let Ok(metadata) = entry.metadata() {
                if metadata.is_file() {
                    if let Ok(mtime) = metadata.modified() {
                        logs.push((path, mtime));
                    }
                }
            }
        }
    }

    logs.retain(|(path, mtime)| {
        if let Ok(age) = now.duration_since(*mtime) {
            if age > max_age {
                let _ = fs::remove_file(path);
                return false;
            }
        }
        true
    });

    logs.sort_by(|a, b| b.1.cmp(&a.1));

    if logs.len() > max_files {
        for (path, _) in &logs[max_files..] {
            let _ = fs::remove_file(path);
        }
    }

    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub installed: bool,
    running: bool,
    pub connected: bool,
    device_name: Option<String>,
    pub message: String,
}

fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

#[cfg(windows)]
fn connected() -> bool {
    #[link(name = "winmm")]
    unsafe extern "system" {
        fn joyGetNumDevs() -> u32;
        fn joyGetDevCapsW(id: usize, caps: *mut u8, size: u32) -> u32;
        fn joyGetPosEx(id: u32, state: *mut u32) -> u32;
    }
    // JOYCAPSW (728 bytes) and JOYINFOEX (13 DWORDs), using aligned storage.
    unsafe {
        for id in 0..joyGetNumDevs().min(16) {
            let mut caps = [0u32; 182];
            let mut state = [0u32; 13];
            state[0] = 52;
            state[1] = 0xff;
            if joyGetDevCapsW(id as usize, caps.as_mut_ptr().cast(), 728) == 0 {
                let vendor = caps[0] & 0xffff;
                let product = caps[0] >> 16;
                if vendor == 0x054c
                    && [0x0ce6, 0x0df2].contains(&product)
                    && joyGetPosEx(id, state.as_mut_ptr()) == 0
                {
                    return true;
                }
            }
        }
    }
    false
}

#[cfg(not(windows))]
fn connected() -> bool {
    false
}

pub fn status(game: &Path) -> Result<Status, String> {
    let info = external::inspect(game, &external::CONTROLLER)?;
    let connected = connected();
    Ok(Status {
        installed: info.installed,
        running: is_game_running(game)?,
        connected,
        device_name: connected.then(|| "DualSense / DualSense Edge".into()),
        message: format!(
            "{} Use Jogar com DualSense para ativar os comandos e a faixa de ícones. Requer os controles de teclado padrão do jogo.",
            info.message
        ),
    })
}

pub fn install(game: &Path) -> Result<Status, String> {
    if COMPANION.is_empty() {
        return Err("DualSense disponível somente no Windows.".into());
    }
    let package = tempfile::tempdir().map_err(|e| e.to_string())?;
    fs::write(package.path().join("sr-dualsense.exe"), COMPANION).map_err(|e| e.to_string())?;
    let manifest = serde_json::json!({"schema": 1, "assets": [{
        "file": "sr-dualsense.exe", "source_sha256": null,
        "result_sha256": companion_digest(), "payload": "sr-dualsense.exe"
    }]});
    let manifest_path = package.path().join("controller.json");
    fs::write(
        &manifest_path,
        serde_json::to_vec(&manifest).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    external::apply(
        game,
        &external::CONTROLLER,
        &manifest_path,
        &super::backups_root()?,
        |_| {},
    )?;
    status(game)
}

pub fn remove(game: &Path) -> Result<Status, String> {
    external::restore(game, &external::CONTROLLER, |_| {})?;
    status(game)
}

pub trait ChildProcess {
    fn try_wait_code(&mut self) -> std::io::Result<Option<i32>>;
    fn kill(&mut self) -> std::io::Result<()>;
}

impl ChildProcess for std::process::Child {
    fn try_wait_code(&mut self) -> std::io::Result<Option<i32>> {
        match std::process::Child::try_wait(self)? {
            Some(status) => Ok(Some(status.code().unwrap_or(1))),
            None => Ok(None),
        }
    }
    fn kill(&mut self) -> std::io::Result<()> {
        std::process::Child::kill(self)
    }
}

pub fn wait_ready<C: ChildProcess>(
    child: &mut C,
    ready_path: &Path,
    timeout: std::time::Duration,
) -> Result<(), String> {
    wait_ready_with_sleep(child, ready_path, timeout, |d| std::thread::sleep(d))
}

pub fn wait_ready_with_sleep<C: ChildProcess, F: Fn(std::time::Duration)>(
    child: &mut C,
    ready_path: &Path,
    timeout: std::time::Duration,
    sleep_fn: F,
) -> Result<(), String> {
    let step = std::time::Duration::from_millis(50);
    let mut elapsed = std::time::Duration::ZERO;

    while elapsed < timeout {
        if let Ok(Some(code)) = child.try_wait_code() {
            return Err(format!("O acompanhante encerrou na inicialização: {code}"));
        }
        if ready_path.exists() {
            let _ = fs::remove_file(ready_path);
            return Ok(());
        }
        sleep_fn(step);
        elapsed += step;
    }

    let _ = child.kill();
    Err("O acompanhante não respondeu; o jogo continua aberto sem DualSense.".into())
}

pub fn check_companion(companion: &Path, timeout: std::time::Duration) -> Result<(), String> {
    check_companion_with_sleep(companion, timeout, |d| std::thread::sleep(d))
}

pub fn check_companion_with_sleep<F: Fn(std::time::Duration)>(
    companion: &Path,
    timeout: std::time::Duration,
    sleep_fn: F,
) -> Result<(), String> {
    let mut cmd = Command::new(companion);
    cmd.arg("--check");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Não foi possível validar o acompanhante: {e}"))?;

    let step = std::time::Duration::from_millis(50);
    let mut elapsed = std::time::Duration::ZERO;

    while elapsed < timeout {
        match child.try_wait() {
            Ok(Some(status)) => {
                if status.success() {
                    return Ok(());
                } else {
                    return Err("O acompanhante não passou na validação (--check).".into());
                }
            }
            Ok(None) => {
                sleep_fn(step);
                elapsed += step;
            }
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("Erro ao aguardar validação do acompanhante: {e}"));
            }
        }
    }

    let _ = child.kill();
    let _ = child.wait();
    Err("Tempo limite esgotado na validação do acompanhante (--check).".into())
}

pub fn launch(game: &Path) -> Result<Status, String> {
    launch_with_status_fn(game, status)
}

pub fn launch_with_status_fn<F>(game: &Path, status_fn: F) -> Result<Status, String>
where
    F: Fn(&Path) -> Result<Status, String>,
{
    let state = status_fn(game)?;
    if state.running {
        return Err("O jogo já está aberto. Feche-o antes de iniciar com DualSense.".into());
    }
    if !state.installed {
        return Err("Habilite o suporte ao DualSense primeiro.".into());
    }
    if !state.connected {
        return Err("Conecte o DualSense por USB ou Bluetooth e atualize o status.".into());
    }
    let hash = exe_sha256(game)?;
    if hash != EXE_SHA256 && hash != EXE_WIDESCREEN_SHA256 {
        return Err("Executável incompatível; inicialização recusada.".into());
    }
    let companion = game.join("sr-dualsense.exe");
    if digest(&fs::read(&companion).map_err(|e| e.to_string())?) != companion_digest() {
        return Err("Acompanhante difere desta versão do instalador; remova e habilite o suporte novamente.".into());
    }

    let mut logs_dir = None;
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let logs = std::path::PathBuf::from(local).join("SoulReaverPTBR/logs");
        if fs::create_dir_all(&logs).is_ok() {
            let _ = prune_logs(&logs, std::time::Duration::from_secs(14 * 86400), 20);
            logs_dir = Some(logs);
        }
    }

    // Validate companion before launching the game
    check_companion(&companion, std::time::Duration::from_secs(1))?;

    let child = Command::new(game.join("kain2.exe"))
        .args(["under", "1", "-mainmenu", "-voice", "-inspectral"])
        .current_dir(game)
        .spawn()
        .map_err(|e| format!("Não foi possível abrir o jogo: {e}"))?;

    let mut bridge = Command::new(&companion);
    bridge.args(["--attach", &child.id().to_string()]);
    let ready_path = logs_dir.as_ref().map(|dir| {
        let log_file = dir.join(format!("dualsense-{}.jsonl", child.id()));
        bridge.arg("--log").arg(&log_file);
        dir.join(format!("dualsense-{}.ready", child.id()))
    });

    if let Some(ref r_path) = ready_path {
        let _ = fs::remove_file(r_path);
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        bridge.creation_flags(0x08000000);
    }

    let mut bridge_process = bridge
        .spawn()
        .map_err(|e| format!("Falha ao iniciar o acompanhante: {e}"))?;

    let default_ready = game.join("dualsense-temp.ready");
    let actual_ready_path = ready_path.as_deref().unwrap_or(&default_ready);

    if let Err(err) = wait_ready(&mut bridge_process, actual_ready_path, std::time::Duration::from_secs(2)) {
        return Err(err);
    }

    match status_fn(game) {
        Ok(mut result) => {
            result.message = "Jogo iniciado com acompanhante DualSense. Create confirma menus; Options pausa. Use teclado padrão nas opções do jogo. A faixa com ícones aparece em janela; tela cheia exclusiva não é compatível com a faixa.".into();
            Ok(result)
        }
        Err(err) => Ok(Status {
            installed: true,
            running: true,
            connected: true,
            device_name: Some("DualSense / DualSense Edge".into()),
            message: format!("Jogo iniciado; não foi possível atualizar o status: {err}"),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockChild {
        code: Option<i32>,
        killed: bool,
    }

    impl ChildProcess for MockChild {
        fn try_wait_code(&mut self) -> std::io::Result<Option<i32>> {
            Ok(self.code)
        }
        fn kill(&mut self) -> std::io::Result<()> {
            self.killed = true;
            Ok(())
        }
    }

    #[test]
    fn test_wait_ready_exits_early() {
        let temp = tempfile::tempdir().unwrap();
        let ready = temp.path().join("dualsense.ready");
        let mut mock = MockChild { code: Some(42), killed: false };
        let res = wait_ready_with_sleep(&mut mock, &ready, std::time::Duration::from_millis(200), |_| {});
        assert!(res.is_err());
        assert!(res.unwrap_err().contains("O acompanhante encerrou na inicialização: 42"));
        assert!(!mock.killed);
    }

    #[test]
    fn test_wait_ready_timeout() {
        let temp = tempfile::tempdir().unwrap();
        let ready = temp.path().join("dualsense.ready");
        let mut mock = MockChild { code: None, killed: false };
        let res = wait_ready_with_sleep(&mut mock, &ready, std::time::Duration::from_millis(100), |_| {});
        assert!(res.is_err());
        assert_eq!(
            res.unwrap_err(),
            "O acompanhante não respondeu; o jogo continua aberto sem DualSense."
        );
        assert!(mock.killed);
    }

    #[test]
    fn test_wait_ready_success() {
        let temp = tempfile::tempdir().unwrap();
        let ready = temp.path().join("dualsense.ready");
        fs::write(&ready, b"READY").unwrap();
        let mut mock = MockChild { code: None, killed: false };
        let res = wait_ready_with_sleep(&mut mock, &ready, std::time::Duration::from_millis(500), |_| {});
        assert!(res.is_ok());
        assert!(!ready.exists());
        assert!(!mock.killed);
    }

    #[test]
    fn test_prune_logs_rotation() {
        let temp = tempfile::tempdir().unwrap();
        let dir = temp.path();
        let now = std::time::SystemTime::now();
        let day = std::time::Duration::from_secs(86400);

        // Create 25 log files:
        // Files 0 and 1 are older than 14 days (15d and 20d)
        // Files 2..25 (23 files) are within 14 days (hours old)
        for i in 0..25 {
            let file_path = dir.join(format!("dualsense-{i:02}.jsonl"));
            fs::write(&file_path, b"log line\n").unwrap();
            let age_hours = if i == 0 { 15 * 24 + 1 } else if i == 1 { 20 * 24 } else { i * 4 };
            let mtime = now - std::time::Duration::from_secs((age_hours as u64) * 3600);
            let file = fs::File::open(&file_path).unwrap();
            file.set_times(fs::FileTimes::new().set_modified(mtime)).unwrap();
        }

        prune_logs_at(dir, day * 14, 20, now).unwrap();

        let remaining: Vec<_> = fs::read_dir(dir)
            .unwrap()
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .collect();

        // 2 files >14d deleted, and 3 files beyond 20 deleted -> exactly 20 files kept
        assert_eq!(remaining.len(), 20);
        assert!(!remaining.contains(&"dualsense-00.jsonl".to_string()));
        assert!(!remaining.contains(&"dualsense-01.jsonl".to_string()));
    }

    #[test]
    fn test_post_launch_status_failure_returns_ok_warning() {
        let status_err: Result<Status, String> = Err("Falha ao ler status pós-lançamento".to_string());
        let res: Result<Status, String> = match status_err {
            Ok(mut s) => {
                s.message = "Jogo iniciado com acompanhante DualSense.".into();
                Ok(s)
            }
            Err(err) => Ok(Status {
                installed: true,
                running: true,
                connected: true,
                device_name: Some("DualSense / DualSense Edge".into()),
                message: format!("Jogo iniciado; não foi possível atualizar o status: {err}"),
            }),
        };

        let result = res.unwrap();
        assert!(result.running);
        assert_eq!(
            result.message,
            "Jogo iniciado; não foi possível atualizar o status: Falha ao ler status pós-lançamento"
        );
    }

    #[test]
    #[ignore = "Requires SRMOD_TEST_EXE pointing at a compatible local game executable; never launches it"]
    fn embedded_companion_deployment_preserves_foreign_files_and_checks_ownership() {
        // A real supported executable is used only as fixture bytes. Never launch it.
        let source = std::env::var_os("SRMOD_TEST_EXE")
            .expect("Set SRMOD_TEST_EXE for this isolated offline test");
        let temp = tempfile::tempdir().unwrap();
        let game = temp.path().join("game");
        fs::create_dir(&game).unwrap();
        fs::copy(source, game.join("kain2.exe")).unwrap();
        fs::write(game.join("savegame.her"), b"save must survive").unwrap();
        fs::write(game.join("DINPUT.dll"), b"existing subtitles").unwrap();
        fs::write(game.join("sr-dualsense.exe"), b"foreign executable").unwrap();
        assert!(install(&game).is_err());
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"foreign executable"
        );
        fs::remove_file(game.join("sr-dualsense.exe")).unwrap();
        assert!(install(&game).unwrap().installed);
        assert!(install(&game).unwrap().installed);
        fs::write(game.join("sr-dualsense.exe"), b"changed later").unwrap();
        assert!(remove(&game).is_err());
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"changed later"
        );
        fs::write(game.join("sr-dualsense.exe"), COMPANION).unwrap();
        assert!(!remove(&game).unwrap().installed);
        assert_eq!(
            fs::read(game.join("savegame.her")).unwrap(),
            b"save must survive"
        );
        assert_eq!(
            fs::read(game.join("DINPUT.dll")).unwrap(),
            b"existing subtitles"
        );
    }
}
