use soul_reaver_mod_core::{exe_sha256, is_game_running, is_supported_exe};
use std::{path::Path, process::Command};

// Preparing a command validates the selected copy without executing anything.
fn prepare(game: &Path) -> Result<Command, String> {
    let game = game
        .canonicalize()
        .map_err(|error| format!("Pasta do jogo indisponível: {error}"))?;
    if !is_supported_exe(&exe_sha256(&game)?) {
        return Err("Executável incompatível; inicialização recusada.".into());
    }
    if is_game_running(&game)? {
        return Err("O jogo já está aberto.".into());
    }
    let mut command = Command::new(game.join("kain2.exe"));
    command
        .args(["under", "1", "-mainmenu", "-voice", "-inspectral"])
        .current_dir(game);
    Ok(command)
}

pub fn launch(game: &Path) -> Result<(), String> {
    prepare(game)?
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Não foi possível abrir o jogo: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn missing_and_foreign_executables_are_refused_without_changes() {
        let temp = tempfile::tempdir().unwrap();
        assert!(prepare(&temp.path().join("missing")).is_err());
        assert!(prepare(temp.path()).is_err());
        let exe = temp.path().join("kain2.exe");
        fs::write(&exe, b"foreign executable; never run").unwrap();
        assert_eq!(
            prepare(temp.path()).unwrap_err(),
            "Executável incompatível; inicialização recusada."
        );
        assert_eq!(fs::read(exe).unwrap(), b"foreign executable; never run");
        assert_eq!(fs::read_dir(temp.path()).unwrap().count(), 1);
    }

    #[test]
    #[ignore = "Requires SRMOD_TEST_EXE; validates launch preparation only, never launches the game"]
    fn supported_copies_prepare_the_selected_executable_and_working_directory() {
        let source = std::env::var_os("SRMOD_TEST_EXE").expect("Set SRMOD_TEST_EXE");
        let temp = tempfile::tempdir().unwrap();
        let game = temp.path().join("Soul Reaver cópia isolada");
        fs::create_dir(&game).unwrap();
        let mut bytes = fs::read(source).unwrap();
        for widescreen in [false, true] {
            if widescreen {
                bytes[0xeb354..0xeb358].copy_from_slice(&[0x00, 0x00, 0xf0, 0x3e]);
            }
            fs::write(game.join("kain2.exe"), &bytes).unwrap();
            let command = prepare(&game).unwrap();
            let absolute = game.canonicalize().unwrap();
            assert_eq!(command.get_program(), absolute.join("kain2.exe"));
            assert_eq!(command.get_current_dir(), Some(absolute.as_path()));
            assert_eq!(
                command.get_args().collect::<Vec<_>>(),
                ["under", "1", "-mainmenu", "-voice", "-inspectral"]
            );
            assert_eq!(fs::read(game.join("kain2.exe")).unwrap(), bytes);
            assert_eq!(fs::read_dir(&game).unwrap().count(), 1);
        }
    }
}
