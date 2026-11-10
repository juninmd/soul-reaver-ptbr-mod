//! Location and layout of the distributable package ("bundle") next to the installer.
//!
//! Two layouts are accepted: the modular tree (`modules/` with one folder per
//! component) and the older flat staging package, whose combined asset manifest
//! is split per component on the fly.

use serde::{Deserialize, Serialize};
use soul_reaver_mod_core::{PackageInfo, assets, inspect_package};
use std::{
    path::{Path, PathBuf},
    sync::Mutex,
};

/// Files that make the graphics module installable.
pub const GRAPHICS_FILES: [&str; 3] = ["DDraw.dll", "D3DImm.dll", "dgVoodoo.conf"];

const BUNDLES: [&str; 7] = [
    "local-full-v1",
    "local-review-v6",
    "local-review-v5",
    "local-review-v4",
    "local-review-v3",
    "local-review-v2",
    "tutorial-review-v1",
];

/// How far above the executable a package is looked for: enough to reach the
/// repository root from `target/<profile>/`, and no further.
const EXECUTABLE_ANCESTORS: usize = 3;

/// Directories that may hold `modules/` or `staging/packages/`, most specific
/// first: the explicit override, then around the executable, then around the
/// working directory. Nothing here names a particular machine.
fn root_candidates(executable: Option<&Path>) -> Vec<PathBuf> {
    let mut roots = Vec::new();
    if let Some(value) = std::env::var_os("SRMOD_REPO") {
        roots.push(PathBuf::from(value));
    }
    if let Some(directory) = executable.and_then(Path::parent) {
        roots.extend(
            directory
                .ancestors()
                .take(EXECUTABLE_ANCESTORS)
                .map(Path::to_path_buf),
        );
    }
    roots.extend([".", "..", "../.."].map(PathBuf::from));
    roots
}

fn repo_root_candidates() -> Vec<PathBuf> {
    root_candidates(std::env::current_exe().ok().as_deref())
}

pub fn find_bundle() -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os("SRMOD_MODULES") {
        let path = PathBuf::from(value);
        if is_modules_bundle(&path) {
            return Ok(path);
        }
    }
    for root in repo_root_candidates() {
        let modules = root.join("modules");
        if is_modules_bundle(&modules) {
            return Ok(modules);
        }
    }
    if let Some(value) = std::env::var_os("SRMOD_BUNDLE") {
        let path = PathBuf::from(value);
        if path.join("manifest.json").is_file() || is_modules_bundle(&path) {
            return Ok(path);
        }
    }
    for root in repo_root_candidates() {
        for name in BUNDLES {
            let candidate = root.join("staging").join("packages").join(name);
            if candidate.join("manifest.json").is_file() {
                return Ok(candidate);
            }
        }
    }
    Err("Pacote de dublagem não encontrado nos caminhos padrão.".into())
}

fn is_modules_bundle(bundle: &Path) -> bool {
    let Ok(bytes) = std::fs::read(bundle.join("bundle.json")) else {
        return false;
    };
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        return false;
    };
    value.get("schema").and_then(|schema| schema.as_u64()) == Some(2)
        && value
            .get("modules")
            .and_then(|modules| modules.as_object())
            .is_some()
        && bundle.join("voices").join("manifest.json").is_file()
}

pub fn module_dir(bundle: &Path, name: &str) -> PathBuf {
    if is_modules_bundle(bundle) {
        bundle.join(name)
    } else {
        bundle.to_path_buf()
    }
}

pub fn module_manifest(bundle: &Path, module: &str, filename: &str) -> PathBuf {
    module_dir(bundle, module).join(filename)
}

/// Per-component asset manifests; a legacy package is split into a temporary
/// directory that lives as long as this value.
pub struct AssetManifests {
    _temporary: Option<tempfile::TempDir>,
    pub localization: Option<PathBuf>,
    pub video: Option<PathBuf>,
}

pub fn asset_manifests(bundle: &Path) -> Result<AssetManifests, String> {
    if is_modules_bundle(bundle) {
        let localization = module_manifest(bundle, "localization", "assets.json");
        let video = module_manifest(bundle, "video", "video.json");
        return Ok(AssetManifests {
            _temporary: None,
            localization: localization.is_file().then_some(localization),
            video: video.is_file().then_some(video),
        });
    }

    let combined = bundle.join("assets.json");
    if !combined.is_file() {
        return Ok(AssetManifests {
            _temporary: None,
            localization: None,
            video: None,
        });
    }
    let bytes = std::fs::read(&combined).map_err(|error| error.to_string())?;
    let mut value: serde_json::Value =
        serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    let assets = value
        .get_mut("assets")
        .and_then(serde_json::Value::as_array_mut)
        .ok_or("Manifesto legado de assets inválido.")?;
    let temporary = tempfile::tempdir().map_err(|error| error.to_string())?;
    let mut split = [Vec::new(), Vec::new()];
    for (index, mut item) in assets.drain(..).enumerate() {
        let file = item
            .get("file")
            .and_then(serde_json::Value::as_str)
            .ok_or("Arquivo inválido no manifesto legado.")?;
        let is_video = file.ends_with(".bik");
        let payload = item
            .get("payload")
            .and_then(serde_json::Value::as_str)
            .ok_or("Payload inválido no manifesto legado.")?;
        if payload.is_empty()
            || payload.starts_with('.')
            || !payload
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
            || payload.contains("..")
        {
            return Err("Caminho de payload legado inseguro.".into());
        }
        let source = bundle.join(payload);
        let metadata = std::fs::symlink_metadata(&source).map_err(|error| error.to_string())?;
        if !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() > 512 * 1024 * 1024
        {
            return Err(format!("Payload legado ausente ou inseguro: {payload}"));
        }
        let destination_dir =
            temporary
                .path()
                .join(if is_video { "video" } else { "localization" });
        std::fs::create_dir_all(&destination_dir).map_err(|error| error.to_string())?;
        let destination_name = format!("payload-{index}.bin");
        let destination = destination_dir.join(&destination_name);
        std::fs::copy(&source, &destination).map_err(|error| error.to_string())?;
        item["payload"] = serde_json::Value::String(destination_name);
        split[usize::from(is_video)].push(item);
    }

    let mut paths = [None, None];
    for (index, (module, filename)) in [("localization", "assets.json"), ("video", "video.json")]
        .into_iter()
        .enumerate()
    {
        if split[index].is_empty() {
            continue;
        }
        let manifest = temporary.path().join(module).join(filename);
        std::fs::write(
            &manifest,
            serde_json::to_vec(&serde_json::json!({ "schema": 1, "assets": split[index] }))
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        paths[index] = Some(manifest);
    }
    Ok(AssetManifests {
        _temporary: Some(temporary),
        localization: paths[0].take(),
        video: paths[1].take(),
    })
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BundleInfo {
    pub path: String,
    pub name: String,
    pub version: String,
    pub voices: PackageInfo,
    pub graphics_available: bool,
    pub widescreen_available: bool,
    pub textures_available: bool,
    pub ui_available: bool,
    pub video_available: bool,
    pub video_files: usize,
    pub resolution: Option<String>,
    pub experimental: Vec<String>,
    pub localized_files: usize,
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase", default)]
struct BundleManifest {
    resolution: Option<String>,
    experimental: Vec<String>,
}

/// Verifies the whole package: every payload is hashed against its manifest.
pub fn bundle_info() -> Result<BundleInfo, String> {
    let bundle = find_bundle()?;
    let voices_path = module_manifest(&bundle, "voices", "manifest.json");
    let asset_manifests = asset_manifests(&bundle)?;
    let graphics_dir = module_dir(&bundle, "graphics");
    let textures_path = module_manifest(&bundle, "textures", "textures.json");
    let ui_path = module_manifest(&bundle, "ui", "ui.json");
    let voices = inspect_package(&voices_path)?;
    let graphics_available = GRAPHICS_FILES
        .iter()
        .all(|name| graphics_dir.join(name).is_file());
    let video_files = if let Some(video_path) = &asset_manifests.video {
        assets::inspect_package_component(&assets::VIDEO, video_path)?.videos
    } else {
        0
    };
    let localized_files = if let Some(localization_path) = &asset_manifests.localization {
        assets::inspect_package_component(&assets::LOCALIZATION, localization_path)?.files
    } else {
        0
    };
    let manifest: BundleManifest = std::fs::read(bundle.join("bundle.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or_default();
    Ok(BundleInfo {
        path: bundle.to_string_lossy().into(),
        name: voices.name.clone(),
        version: voices.version.clone(),
        graphics_available,
        widescreen_available: graphics_available,
        textures_available: textures_path.is_file(),
        ui_available: ui_path.is_file(),
        video_available: video_files > 0,
        video_files,
        resolution: manifest.resolution,
        experimental: manifest.experimental,
        localized_files,
        voices,
    })
}

/// Last verified package description.
///
/// Verifying a package hashes every payload, so the inspections that follow an
/// operation reuse the description obtained when the package was last checked.
/// The interface asks for a fresh verification whenever the user requests the
/// current state. Installing never trusts this cache: each component verifies
/// its own payloads again before writing.
#[derive(Default)]
pub struct BundleCache(Mutex<Option<BundleInfo>>);

impl BundleCache {
    /// Verifies the package now and remembers a successful description.
    pub fn refresh(&self) -> Result<BundleInfo, String> {
        let result = bundle_info();
        *self.0.lock().unwrap_or_else(|e| e.into_inner()) = result.as_ref().ok().cloned();
        result
    }

    /// The remembered description, verifying the package only when none exists.
    pub fn get(&self) -> Result<BundleInfo, String> {
        let cached = self.0.lock().unwrap_or_else(|e| e.into_inner()).clone();
        cached.map_or_else(|| self.refresh(), Ok)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_package_is_found_next_to_the_executable_or_at_the_repository_root() {
        let executable = Path::new("/opt/sr/target/release/soul-reaver-mod-installer");
        let roots = root_candidates(Some(executable));
        let around_executable: Vec<_> = ["/opt/sr/target/release", "/opt/sr/target", "/opt/sr"]
            .map(PathBuf::from)
            .into();
        assert!(
            roots
                .windows(around_executable.len())
                .any(|window| window == around_executable),
            "{roots:?}"
        );
        // The search stops at the repository root instead of walking to `/`.
        assert!(!roots.contains(&PathBuf::from("/opt")));
        assert!(root_candidates(None).ends_with(&[".", "..", "../.."].map(PathBuf::from)));
    }
}
