use std::path::Path;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let progress = |message: &str| eprintln!("{message}");
    let result = match args.get(1).map(String::as_str) {
        Some("inspect") if args.len() == 3 => {
            soul_reaver_mod_core::inspect_game(Path::new(&args[2]))
        }
        Some("apply") if args.len() == 4 => {
            soul_reaver_mod_core::apply_package(Path::new(&args[2]), Path::new(&args[3]), progress)
        }
        Some("restore") if args.len() == 3 => {
            soul_reaver_mod_core::restore_game(Path::new(&args[2]), progress)
        }
        Some("assets-apply") if args.len() == 5 => {
            finish(soul_reaver_mod_core::assets::apply(
                Path::new(&args[2]),
                Path::new(&args[3]),
                Path::new(&args[4]),
                progress,
            ));
            return;
        }
        Some("assets-restore") if args.len() == 3 => {
            finish(soul_reaver_mod_core::assets::restore(
                Path::new(&args[2]),
                progress,
            ));
            return;
        }
        Some("video-apply") if args.len() == 5 => {
            finish(soul_reaver_mod_core::assets::apply_component(
                Path::new(&args[2]),
                &soul_reaver_mod_core::assets::VIDEO,
                Path::new(&args[3]),
                Path::new(&args[4]),
                progress,
            ));
            return;
        }
        Some("video-restore") if args.len() == 3 => {
            finish(soul_reaver_mod_core::assets::restore_component(
                Path::new(&args[2]),
                &soul_reaver_mod_core::assets::VIDEO,
                progress,
            ));
            return;
        }
        Some("graphics-apply") if args.len() >= 4 => {
            let widescreen = args.get(4).map(String::as_str) == Some("widescreen");
            finish(soul_reaver_mod_core::graphics::apply(
                Path::new(&args[2]),
                Path::new(&args[3]),
                widescreen,
                progress,
            ));
            return;
        }
        Some("graphics-restore") if args.len() == 3 => {
            finish(soul_reaver_mod_core::graphics::restore(
                Path::new(&args[2]),
                progress,
            ));
            return;
        }
        Some("textures-apply") if args.len() == 5 => {
            finish(soul_reaver_mod_core::external::apply(
                Path::new(&args[2]),
                &soul_reaver_mod_core::external::TEXTURES,
                Path::new(&args[3]),
                Path::new(&args[4]),
                progress,
            ));
            return;
        }
        Some("textures-restore") if args.len() == 3 => {
            finish(soul_reaver_mod_core::external::restore(
                Path::new(&args[2]),
                &soul_reaver_mod_core::external::TEXTURES,
                progress,
            ));
            return;
        }
        Some("ui-apply") if args.len() == 5 => {
            finish(soul_reaver_mod_core::external::apply(
                Path::new(&args[2]),
                &soul_reaver_mod_core::external::UI,
                Path::new(&args[3]),
                Path::new(&args[4]),
                progress,
            ));
            return;
        }
        Some("ui-restore") if args.len() == 3 => {
            finish(soul_reaver_mod_core::external::restore(
                Path::new(&args[2]),
                &soul_reaver_mod_core::external::UI,
                progress,
            ));
            return;
        }
        Some("components") if args.len() == 3 => {
            finish(soul_reaver_mod_core::inspect_components(Path::new(
                &args[2],
            )));
            return;
        }
        _ => {
            eprintln!(
                "Usage: srmod inspect GAME | apply GAME MANIFEST | restore GAME | assets-apply GAME ASSETS BACKUPS | assets-restore GAME | video-apply GAME VIDEO BACKUPS | video-restore GAME | graphics-apply GAME GRAPHICS_DIR [widescreen] | graphics-restore GAME | textures-apply GAME MANIFEST BACKUPS | textures-restore GAME | ui-apply GAME MANIFEST BACKUPS | ui-restore GAME | components GAME"
            );
            std::process::exit(2);
        }
    };
    finish(result);
}

fn finish<T: serde::Serialize>(result: Result<T, String>) {
    match result {
        Ok(value) => println!("{}", serde_json::to_string(&value).unwrap()),
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
