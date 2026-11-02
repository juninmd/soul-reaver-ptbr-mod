//! Deploy the embedded companion through the same ownership journal as other components.
use serde::Serialize;
use sha2::{Digest, Sha256};
use soul_reaver_mod_core::{
    EXE_SHA256, EXE_WIDESCREEN_SHA256, exe_sha256, external, is_game_running,
};
use std::{fs, path::Path, process::Command};

#[cfg(windows)]
const COMPANION: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/sr-dualsense.exe"));
#[cfg(not(windows))]
const COMPANION: &[u8] = &[];

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
        "result_sha256": digest(COMPANION), "payload": "sr-dualsense.exe"
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
    remove_orphaned_companion(game)?;
    status(game)
}

/// An older runtime overwrote the journal name, so a companion installed by this
/// mod can exist without ownership records. Only the exact embedded bytes are
/// removed; any other file is reported and preserved.
fn remove_orphaned_companion(game: &Path) -> Result<(), String> {
    let companion = game.join("sr-dualsense.exe");
    if !companion.exists() {
        return Ok(());
    }
    // Lock before hashing so the decision and the deletion happen under the same
    // guard, and never follow a link placed at the companion path.
    let _lock = external::lock(game)?;
    let meta = fs::symlink_metadata(&companion).map_err(|e| e.to_string())?;
    if meta.file_type().is_symlink() || !meta.is_file() {
        return Err("sr-dualsense.exe é um link ou não é um arquivo regular; recusado.".into());
    }
    if !companion_matches(game) {
        return Err(
            "sr-dualsense.exe presente não pertence a esta versão do instalador; remova manualmente."
                .into(),
        );
    }
    fs::remove_file(&companion).map_err(|e| e.to_string())
}

fn companion_matches(game: &Path) -> bool {
    !COMPANION.is_empty()
        && fs::read(game.join("sr-dualsense.exe"))
            .map(|bytes| digest(&bytes) == digest(COMPANION))
            .unwrap_or(false)
}

/// Installed according to the journal, or present with exactly the embedded bytes,
/// which is what remains after an older runtime overwrote the journal.
pub fn deployed(game: &Path) -> bool {
    status(game).map(|status| status.installed).unwrap_or(false) || companion_matches(game)
}

pub fn launch(game: &Path) -> Result<Status, String> {
    let _lock = external::lock(game)?;
    let state = status(game)?;
    if state.running {
        return Err("O jogo já está aberto. Feche-o antes de iniciar com DualSense.".into());
    }
    if !state.installed && !companion_matches(game) {
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
    if digest(&fs::read(&companion).map_err(|e| e.to_string())?) != digest(COMPANION) {
        return Err("Acompanhante difere desta versão do instalador; remova e habilite o suporte novamente.".into());
    }
    let mut child = Command::new(game.join("kain2.exe"))
        .args(["under", "1", "-mainmenu", "-voice", "-inspectral"])
        .current_dir(game)
        .spawn()
        .map_err(|e| format!("Não foi possível abrir o jogo: {e}"))?;
    let mut bridge = Command::new(companion);
    bridge.args(["--attach", &child.id().to_string()]);
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let logs = std::path::PathBuf::from(local).join("SoulReaverPTBR/logs");
        if fs::create_dir_all(&logs).is_ok() {
            bridge
                .arg("--log")
                .arg(logs.join(format!("dualsense-{}.jsonl", child.id())));
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        bridge.creation_flags(0x08000000);
    }
    let bridge_result = bridge
        .spawn()
        .map_err(|e| e.to_string())
        .and_then(|mut process| {
            let start = std::time::Instant::now();
            let timeout = std::time::Duration::from_secs(1);
            let step = std::time::Duration::from_millis(50);
            loop {
                if let Some(code) = process.try_wait().map_err(|e| e.to_string())? {
                    return Err(format!("O acompanhante encerrou na inicialização: {code}"));
                }
                if start.elapsed() >= timeout {
                    return Ok(());
                }
                std::thread::sleep(step);
            }
        });
    if let Err(error) = bridge_result {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "Falha ao iniciar o acompanhante; jogo encerrado: {error}"
        ));
    }
    let mut result = status(game)?;
    result.message = "Jogo iniciado com acompanhante DualSense. Create confirma menus; Options pausa. Use teclado padrão nas opções do jogo. A faixa com ícones aparece em janela; tela cheia exclusiva não é compatível com a faixa.".into();
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(windows)]
    fn orphaned_companion_is_removed_only_when_the_bytes_match() {
        let dir = tempfile::tempdir().unwrap();
        let game = dir.path();
        fs::write(game.join("sr-dualsense.exe"), b"foreign companion").unwrap();
        assert!(remove_orphaned_companion(game).is_err());
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"foreign companion"
        );

        fs::write(game.join("sr-dualsense.exe"), COMPANION).unwrap();
        assert!(companion_matches(game));
        remove_orphaned_companion(game).unwrap();
        assert!(!game.join("sr-dualsense.exe").exists());
        // Nothing left to remove.
        remove_orphaned_companion(game).unwrap();
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
