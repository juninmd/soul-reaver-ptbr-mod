//! Multi-component operations: install, restore and repair.
//!
//! Each component is an independent transaction in the core. This module only
//! decides the order, validates everything it can before the first write, and
//! reports which components were reached when a later one fails.

use crate::{bundle, controller, paths};
use serde::Deserialize;
use soul_reaver_mod_core::{
    GameInfo, OperationControl, Progress, apply_package_with_control, assets, external, graphics,
    inspect_game, restore_game_with_control,
};
use std::path::{Path, PathBuf};

type Emit<'a> = &'a dyn Fn(Progress);

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ApplyOptions {
    dubbing: bool,
    localization: bool,
    #[serde(default = "default_true")]
    video: bool,
    graphics: bool,
    widescreen: bool,
    textures: bool,
    ui: bool,
    #[serde(default = "default_true")]
    vsync: bool,
    #[serde(default = "default_fps_limit")]
    fps_limit: u32,
    #[serde(default)]
    always_on_top: bool,
    #[serde(default)]
    render_resolution: Option<String>,
}

fn default_true() -> bool {
    true
}

fn default_fps_limit() -> u32 {
    60
}

/// The package on disk, located once per operation. A legacy package is split
/// into a temporary directory that lives as long as this value.
struct Sources {
    voices: PathBuf,
    manifests: bundle::AssetManifests,
    graphics_dir: PathBuf,
    textures: PathBuf,
    ui: PathBuf,
}

impl Sources {
    fn locate() -> Result<Self, String> {
        let bundle = bundle::find_bundle()?;
        Ok(Self {
            voices: bundle::module_manifest(&bundle, "voices", "manifest.json"),
            manifests: bundle::asset_manifests(&bundle)?,
            graphics_dir: bundle::module_dir(&bundle, "graphics"),
            textures: bundle::module_manifest(&bundle, "textures", "textures.json"),
            ui: bundle::module_manifest(&bundle, "ui", "ui.json"),
        })
    }
}

pub fn apply(
    game: &Path,
    options: ApplyOptions,
    control: &OperationControl,
    emit: Emit,
) -> Result<GameInfo, String> {
    apply_from(game, &Sources::locate()?, options, control, emit)
}

fn apply_from(
    game: &Path,
    sources: &Sources,
    options: ApplyOptions,
    control: &OperationControl,
    emit: Emit,
) -> Result<GameInfo, String> {
    let Sources {
        voices,
        manifests,
        graphics_dir,
        textures,
        ui,
    } = sources;
    let backups = paths::backups_root()?;
    let localization = manifests
        .localization
        .as_deref()
        .filter(|_| options.localization);
    let video = manifests.video.as_deref().filter(|_| options.video);
    let install_graphics = options.graphics && graphics_dir.exists();
    let install_textures = options.textures && textures.exists();
    let install_ui = options.ui && ui.exists();

    // Graphics files created by a previous, unrecorded session must never be
    // overwritten while installing the localization bundle.
    if install_graphics
        && bundle::GRAPHICS_FILES
            .iter()
            .any(|name| game.join(name).exists())
        && !graphics::inspect(game).is_ok_and(|info| info.installed)
    {
        return Err("Há arquivos gráficos preexistentes sem propriedade comprovada. Preserve-os e desmarque 4K.".into());
    }

    // Everything that can be refused is refused before the first write.
    if let Some(manifest) = localization {
        assets::validate_install(game, manifest, &backups)?;
    }
    if let Some(manifest) = video {
        assets::validate_install_component(game, &assets::VIDEO, manifest, &backups)?;
    }
    if install_textures {
        external::validate_install(game, &external::TEXTURES, textures, &backups)?;
    }

    let mut applied: Vec<&str> = Vec::new();
    if options.dubbing {
        control.checkpoint()?;
        apply_package_with_control(game, voices, control, emit)?;
        applied.push("dublagem");
    }
    if let Some(manifest) = localization {
        control.checkpoint()?;
        assets::apply_with_control(game, manifest, &backups, control, emit)
            .map_err(|e| format!("Vozes aplicadas; localização não concluída: {e}"))?;
        applied.push("localização");
    }
    if let Some(manifest) = video {
        control.checkpoint()?;
        assets::apply_component_with_control(
            game,
            &assets::VIDEO,
            manifest,
            &backups,
            control,
            emit,
        )
        .map_err(|e| format!("Componentes anteriores aplicados; vídeos não concluídos: {e}"))?;
        applied.push("vídeos");
    }
    if install_graphics {
        control.checkpoint()?;
        let request = graphics::Request {
            widescreen: options.widescreen,
            render: graphics::RenderOptions {
                resolution: options.render_resolution.unwrap_or_else(|| "auto".into()),
                vsync: options.vsync,
                fps_limit: options.fps_limit,
                always_on_top: options.always_on_top,
            },
        };
        graphics::apply_with_control(game, graphics_dir, request, control, emit)?;
        applied.push(if options.widescreen {
            "4K + widescreen"
        } else {
            "4K"
        });
    }
    if install_textures {
        control.checkpoint()?;
        external::apply_with_control(game, &external::TEXTURES, textures, &backups, control, emit)?;
        applied.push("texturas HD (experimental)");
    }
    if install_ui {
        control.checkpoint()?;
        external::apply_with_control(game, &external::UI, ui, &backups, control, emit)?;
        applied.push("interface (experimental)");
    }
    if applied.is_empty() {
        return Err("Nenhum componente foi selecionado.".into());
    }
    emit(Progress::new(
        "concluido",
        1,
        1,
        format!("Componentes aplicados: {}.", applied.join(", ")),
    ));
    inspect_game(game)
}

/// Restores one component by its diagnostic identifier.
pub fn restore_component(
    game: &Path,
    component: &str,
    control: &OperationControl,
    emit: Emit,
) -> Result<GameInfo, String> {
    match component {
        "voices" => restore_game_with_control(game, control, emit).map(drop),
        "localization" => assets::restore_with_control(game, control, emit).map(drop),
        "video" => {
            assets::restore_component_with_control(game, &assets::VIDEO, control, emit).map(drop)
        }
        "graphics" => graphics::restore_with_control(game, control, emit).map(drop),
        "textures" => {
            external::restore_with_control(game, &external::TEXTURES, control, emit).map(drop)
        }
        "ui" => external::restore_with_control(game, &external::UI, control, emit).map(drop),
        "controller" => controller::remove(game).map(drop),
        _ => Err("Componente desconhecido.".into()),
    }?;
    inspect_game(game)
}

type Step<'a> = (&'a str, &'a mut dyn FnMut() -> Result<(), String>);

/// Runs every step even after a failure, so one conflicting component never
/// blocks the restoration of the others. Cancellation stops immediately.
fn run_all(steps: &mut [Step], control: &OperationControl) -> Result<(), String> {
    let mut failures = Vec::new();
    for (component, restore) in steps {
        control.checkpoint()?;
        if let Err(error) = restore() {
            if error.contains("cancelada") {
                return Err(error);
            }
            failures.push(format!("{component}: {error}"));
        }
    }
    if failures.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "Restauração incompleta; arquivos conflitantes foram preservados. {}",
            failures.join(" | ")
        ))
    }
}

pub fn restore_all(
    game: &Path,
    control: &OperationControl,
    emit: Emit,
) -> Result<GameInfo, String> {
    // Owned components are restored independently; the executable returns to
    // the original state only in the graphics step, which runs last.
    run_all(
        &mut [
            ("DualSense", &mut || controller::remove(game).map(drop)),
            ("interface", &mut || {
                external::restore_with_control(game, &external::UI, control, emit).map(drop)
            }),
            ("texturas", &mut || {
                external::restore_with_control(game, &external::TEXTURES, control, emit).map(drop)
            }),
            ("localização", &mut || {
                assets::restore_with_control(game, control, emit).map(drop)
            }),
            ("vídeos", &mut || {
                assets::restore_component_with_control(game, &assets::VIDEO, control, emit)
                    .map(drop)
            }),
            ("vozes", &mut || {
                restore_game_with_control(game, control, emit).map(drop)
            }),
            ("gráficos", &mut || {
                graphics::restore_with_control(game, control, emit).map(drop)
            }),
        ],
        control,
    )?;
    inspect_game(game)
}

/// Re-applies every component that the bundle provides, reusing the normal
/// idempotent paths. Useful after an interrupted operation.
pub fn repair(game: &Path, control: &OperationControl, emit: Emit) -> Result<GameInfo, String> {
    let sources = Sources::locate()?;
    let render = graphics::current_render(game);
    let options = ApplyOptions {
        dubbing: true,
        localization: sources.manifests.localization.is_some(),
        video: sources.manifests.video.is_some(),
        graphics: sources.graphics_dir.exists(),
        widescreen: true,
        textures: sources.textures.exists(),
        ui: sources.ui.exists(),
        vsync: render.vsync,
        fps_limit: render.fps_limit,
        always_on_top: render.always_on_top,
        render_resolution: Some(render.resolution),
    };
    // The companion is optional: a failure there is reported after the other
    // components were repaired instead of aborting the whole operation.
    let mut controller_error = None;
    if controller::deployed(game) {
        control.checkpoint()?;
        controller_error = controller::install(game).err();
    }
    let applied = apply_from(game, &sources, options, control, emit)?;
    match controller_error {
        Some(error) => Err(format!("DualSense não pôde ser reparado: {error}")),
        None => Ok(applied),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn restore_reports_every_failure_and_still_attempts_later_components() {
        let attempted = RefCell::new(Vec::new());
        let error = run_all(
            &mut [
                ("interface", &mut || {
                    attempted.borrow_mut().push("interface");
                    Err("conflito de hash".to_string())
                }),
                ("texturas", &mut || {
                    attempted.borrow_mut().push("texturas");
                    Ok(())
                }),
                ("gráficos", &mut || {
                    attempted.borrow_mut().push("gráficos");
                    Err("wrapper alterado".to_string())
                }),
            ],
            &OperationControl::default(),
        )
        .unwrap_err();
        assert_eq!(
            *attempted.borrow(),
            vec!["interface", "texturas", "gráficos"]
        );
        assert!(error.contains("interface: conflito de hash"));
        assert!(error.contains("gráficos: wrapper alterado"));
    }

    #[test]
    fn restore_stops_at_cancellation_without_running_later_components() {
        let control = OperationControl::default();
        let attempted = RefCell::new(Vec::new());
        let error = run_all(
            &mut [
                ("vozes", &mut || {
                    attempted.borrow_mut().push("vozes");
                    control.cancel();
                    Ok(())
                }),
                ("gráficos", &mut || {
                    attempted.borrow_mut().push("gráficos");
                    Ok(())
                }),
            ],
            &control,
        )
        .unwrap_err();
        assert_eq!(*attempted.borrow(), vec!["vozes"]);
        assert!(error.contains("cancelada"));
    }
}
