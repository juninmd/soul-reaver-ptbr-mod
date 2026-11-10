//! Command-line modes of the installer executable, used for automated checks.

use crate::controller;
use std::path::{Path, PathBuf};

const USAGE: &str = "Uso: --controller-[status|install|remove|launch] <pasta-jogo>";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControllerCommand {
    Status,
    Install,
    Remove,
    Launch,
}

impl ControllerCommand {
    fn parse(flag: &str) -> Option<Self> {
        match flag {
            "--controller-status" => Some(Self::Status),
            "--controller-install" => Some(Self::Install),
            "--controller-remove" => Some(Self::Remove),
            "--controller-launch" => Some(Self::Launch),
            _ => None,
        }
    }

    fn run(self, game: &Path) -> Result<controller::Status, String> {
        match self {
            Self::Status => controller::status(game),
            Self::Install => controller::install(game),
            Self::Remove => controller::remove(game),
            Self::Launch => controller::launch(game),
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum CliAction {
    Gui,
    Help,
    Controller(ControllerCommand, PathBuf),
    UsageError(String),
}

pub fn parse(args: &[String]) -> CliAction {
    let Some(first) = args.get(1) else {
        return CliAction::Gui;
    };
    if args[1..]
        .iter()
        .any(|arg| matches!(arg.as_str(), "--help" | "-h" | "--version" | "-V"))
    {
        return CliAction::Help;
    }
    if !first.starts_with("--controller-") {
        return CliAction::Gui;
    }
    match (ControllerCommand::parse(first), args.get(2)) {
        (Some(command), Some(path)) if !path.is_empty() => {
            CliAction::Controller(command, PathBuf::from(path))
        }
        _ => CliAction::UsageError(USAGE.into()),
    }
}

#[cfg(windows)]
fn attach_console() {
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn AttachConsole(dwProcessId: u32) -> i32;
    }
    const ATTACH_PARENT_PROCESS: u32 = 0xFFFFFFFF;
    // SAFETY: plain Win32 call without pointers; failure only means no parent console.
    unsafe {
        let _ = AttachConsole(ATTACH_PARENT_PROCESS);
    }
}

#[cfg(not(windows))]
fn attach_console() {}

fn print_help() {
    println!(
        "Instalador do Mod Soul Reaver PT-BR\n\n\
         Uso:\n  \
           soul-reaver-mod-installer [opções]\n\n\
         Opções CLI:\n  \
           --controller-status <pasta-jogo>   Exibe o status do suporte ao DualSense\n  \
           --controller-install <pasta-jogo>  Instala o acompanhante DualSense\n  \
           --controller-remove <pasta-jogo>   Remove o acompanhante DualSense\n  \
           --controller-launch <pasta-jogo>   Inicia o jogo com acompanhante DualSense\n  \
           --help, -h                         Exibe esta mensagem de ajuda\n  \
           --version, -V                      Exibe esta mensagem de ajuda"
    );
}

/// Handles a command-line mode. Returns the process exit code, or `None` when
/// the graphical interface should start.
pub fn run(args: &[String]) -> Option<i32> {
    let action = parse(args);
    if action == CliAction::Gui {
        return None;
    }
    // Release builds use the windows subsystem: without this, output is lost.
    attach_console();
    let outcome = match action {
        CliAction::Gui => return None,
        CliAction::Help => {
            print_help();
            return Some(0);
        }
        CliAction::UsageError(usage) => Err(usage),
        CliAction::Controller(command, game) => command.run(&game).and_then(|status| {
            serde_json::to_string(&status).map_err(|e| format!("Erro ao serializar status: {e}"))
        }),
    };
    Some(match outcome {
        Ok(json) => {
            println!("{json}");
            0
        }
        Err(error) => {
            eprintln!("{error}");
            1
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_args(args: &[&str]) -> CliAction {
        parse(&args.iter().map(|arg| arg.to_string()).collect::<Vec<_>>())
    }

    #[test]
    fn test_parse_cli() {
        let usage = CliAction::UsageError(USAGE.to_string());
        let game = PathBuf::from("D:\\Game");

        assert_eq!(parse_args(&[]), CliAction::Gui);
        assert_eq!(parse_args(&["app.exe"]), CliAction::Gui);
        for flag in ["--help", "-h", "--version", "-V"] {
            assert_eq!(parse_args(&["app.exe", flag]), CliAction::Help);
        }
        assert_eq!(parse_args(&["app.exe", "--controller-foo", "game"]), usage);
        assert_eq!(parse_args(&["app.exe", "--controller-status"]), usage);
        assert_eq!(parse_args(&["app.exe", "--controller-status", ""]), usage);
        for (flag, command) in [
            ("--controller-status", ControllerCommand::Status),
            ("--controller-install", ControllerCommand::Install),
            ("--controller-remove", ControllerCommand::Remove),
            ("--controller-launch", ControllerCommand::Launch),
        ] {
            assert_eq!(
                parse_args(&["app.exe", flag, "D:\\Game"]),
                CliAction::Controller(command, game.clone())
            );
        }
        assert_eq!(parse_args(&["app.exe", "--some-other-arg"]), CliAction::Gui);
    }

    #[test]
    #[cfg(windows)]
    #[ignore = "Requires release binary built with cargo build --release -p soul-reaver-mod-installer"]
    fn test_release_binary_controller_status_nonexistent_path() {
        use std::process::Command;

        let exe = std::env::var_os("CARGO_BIN_EXE_soul-reaver-mod-installer")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("../../target/release/soul-reaver-mod-installer.exe")
            });

        let output = Command::new(&exe)
            .args(["--controller-status", r"C:\caminho\inexistente"])
            .output()
            .expect("Falha ao executar o binário de release");

        assert_eq!(
            output.status.code(),
            Some(1),
            "Exit code esperado 1, obteve {:?}",
            output.status.code()
        );

        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            !stderr.trim().is_empty(),
            "stderr não deveria estar vazio no modo release para pasta inexistente"
        );
    }
}
