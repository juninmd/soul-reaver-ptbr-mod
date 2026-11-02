//! Optional external components (HD textures, UI/HUD) with their own journals.
//!
//! Same ownership rules as the localization assets: an external backup is made
//! for replaced originals, created-only files are removed on restore, and any
//! file that changed after installation blocks the operation instead of being
//! overwritten. The loader that consumes these files is still experimental and
//! is not proven inside the game.
use super::*;

const LIMIT: u64 = 512 * 1024 * 1024;
pub const TEXTURES_SHA256: &str =
    "f287fc2b7452aa3f2592c5bab36654ac8ed2aa1be571e607a31e29a3666868fa";

pub struct Component {
    pub id: &'static str,
    pub label: &'static str,
    pub state_file: &'static str,
    /// Older journal name, read-only. Ignored unless it still holds a valid journal.
    pub legacy_state_file: Option<&'static str>,
    /// (file, original source SHA-256) for files that replace a known original.
    pub known: &'static [(&'static str, &'static str)],
    /// Exact paths created by this mod (no original file).
    pub created: &'static [&'static str],
    /// Path prefixes created by this mod (experimental payload trees).
    pub created_prefixes: &'static [&'static str],
    /// Directories removed on restore once every owned file is unmodified.
    pub clean_dirs: &'static [&'static str],
}

pub const TEXTURES: Component = Component {
    id: "textures",
    label: "Texturas HD",
    state_file: "textures-state.json",
    legacy_state_file: None,
    known: &[("textures.big", TEXTURES_SHA256)],
    created: &["hd-texture-cache.dll", "hd-textures/index.json"],
    created_prefixes: &["hd-textures/"],
    clean_dirs: &["hd-textures"],
};

pub const UI: Component = Component {
    id: "ui",
    label: "Interface/HUD",
    state_file: "ui-state.json",
    legacy_state_file: None,
    known: &[],
    created: &["hd-ui-cache.dll", "ui-ptbr.bin"],
    created_prefixes: &[],
    clean_dirs: &[],
};

/// Standalone input companion; never replaces DirectInput or game resources.
/// The journal uses its own name because the subtitle runtime reports the live
/// controller state through `controller-runtime.json` in the same directory
/// (older builds wrote it into `controller-state.json`).
pub const CONTROLLER: Component = Component {
    id: "controller",
    label: "DualSense",
    state_file: "controller-journal.json",
    legacy_state_file: Some("controller-state.json"),
    known: &[],
    created: &["sr-dualsense.exe"],
    created_prefixes: &[],
    clean_dirs: &[],
};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExternalInfo {
    pub id: String,
    pub installed: bool,
    pub files: usize,
    pub message: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Asset {
    file: String,
    source_sha256: Option<String>,
    result_sha256: String,
    payload: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AssetPackage {
    schema: u32,
    assets: Vec<Asset>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    file: String,
    source_sha256: Option<String>,
    result_sha256: String,
    #[serde(default)]
    previous_sha256: Option<String>,
    backup: Option<PathBuf>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    schema: u32,
    game: PathBuf,
    phase: String,
    assets: Vec<Entry>,
}

fn ok_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn created_only(component: &Component, name: &str) -> bool {
    component.created.contains(&name)
        || component
            .created_prefixes
            .iter()
            .any(|prefix| name.starts_with(prefix))
}

fn known_source(component: &Component, name: &str) -> Option<&'static str> {
    component
        .known
        .iter()
        .find(|(file, _)| *file == name)
        .map(|(_, hash)| *hash)
}

fn safe_name(name: &str) -> bool {
    !name.is_empty()
        && !name.starts_with('/')
        && !name.starts_with('\\')
        && !name.contains("..")
        && !name.contains(':')
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.\\/".contains(&b))
}

fn valid_asset(
    component: &Component,
    name: &str,
    source: Option<&str>,
    result: &str,
) -> Result<()> {
    if !safe_name(name)
        || (!created_only(component, name) && known_source(component, name).is_none())
        || source != known_source(component, name)
        || !ok_hash(result)
        || source == Some(result)
    {
        return Err(format!("Arquivo ou base incompatível: {name}"));
    }
    Ok(())
}

fn chain(path: &Path) -> Result<()> {
    for part in path.ancestors() {
        match fs::symlink_metadata(part) {
            Ok(_) => plain(part)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.to_string()),
        }
    }
    Ok(())
}

fn prospective(path: &Path) -> Result<PathBuf> {
    chain(path)?;
    if path
        .components()
        .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return Err("Diretório de backup não pode conter '..'.".into());
    }
    let absolute = io(std::path::absolute(path))?;
    let mut parent = absolute.as_path();
    let mut missing = Vec::new();
    while !parent.exists() {
        missing.push(parent.file_name().ok_or("Diretório inválido")?.to_owned());
        parent = parent.parent().ok_or("Diretório inválido")?;
    }
    let mut result = io(parent.canonicalize())?;
    for name in missing.into_iter().rev() {
        result.push(name);
    }
    Ok(result)
}

fn current(path: &Path) -> Result<Option<String>> {
    chain(path)?;
    if !path.exists() {
        return Ok(None);
    }
    Ok(Some(sha(&read(path, LIMIT)?)))
}

fn game_path(game: &Path) -> Result<PathBuf> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let exe = sha(&read(&game.join("kain2.exe"), 4 * 1024 * 1024)?);
    if exe != EXE_SHA256 && exe != EXE_WIDESCREEN_SHA256 {
        return Err("Executável incompatível com o componente externo.".into());
    }
    Ok(game)
}

pub fn lock(game: &Path) -> Result<File> {
    let root = game.join(MANAGER);
    chain(&root)?;
    if !root.exists() {
        io(fs::create_dir(&root))?;
    }
    let path = root.join("operation.lock");
    chain(&path)?;
    let file = io(OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path))?;
    file.try_lock_exclusive()
        .map_err(|_| "Outra instalação está em andamento.".to_string())?;
    Ok(file)
}

const PHASES: [&str; 5] = [
    "original",
    "preparing",
    "installed",
    "restoring",
    "restored",
];

fn empty_state(game: &Path) -> State {
    State {
        schema: 1,
        game: game.into(),
        phase: "original".into(),
        assets: vec![],
    }
}

fn read_state(game: &Path, component: &Component, path: &Path) -> Result<State> {
    chain(path)?;
    let state: State =
        serde_json::from_slice(&read(path, 512 * 1024)?).map_err(|e| e.to_string())?;
    if state.schema != 1
        || io(state.game.canonicalize())? != game
        || !PHASES.contains(&state.phase.as_str())
    {
        return Err(format!("Registro de {} incompatível.", component.label));
    }
    validate_state(game, component, &state)?;
    Ok(state)
}

/// Reads a legacy journal only while it still describes this installation. Files
/// written by another writer in the same name (the companion runtime status) are
/// ignored, and so is a record that no longer matches the files on disk: only the
/// current journal is authoritative enough to block an operation.
fn read_legacy_state(
    game: &Path,
    component: &Component,
    path: &Path,
) -> Result<Option<State>> {
    chain(path)?;
    let bytes = read(path, 512 * 1024)?;
    let Ok(state) = serde_json::from_slice::<State>(&bytes) else {
        return Ok(None);
    };
    let Ok(canonical) = state.game.canonicalize() else {
        return Ok(None);
    };
    if state.schema != 1 || canonical != game || !PHASES.contains(&state.phase.as_str()) {
        return Ok(None);
    }
    Ok(validate_state(game, component, &state).ok().map(|()| state))
}

fn load_state(game: &Path, component: &Component) -> Result<State> {
    let manager = game.join(MANAGER);
    let path = manager.join(component.state_file);
    chain(&path)?;
    if path.exists() {
        return read_state(game, component, &path);
    }
    // Older builds wrote the journal under a name that another writer later reused.
    if let Some(legacy) = component.legacy_state_file {
        let legacy_path = manager.join(legacy);
        if legacy_path.exists() {
            if let Some(state) = read_legacy_state(game, component, &legacy_path)? {
                return Ok(state);
            }
        }
    }
    Ok(empty_state(game))
}

fn validate_state(game: &Path, component: &Component, state: &State) -> Result<()> {
    let mut seen = HashSet::new();
    for entry in &state.assets {
        valid_asset(
            component,
            &entry.file,
            entry.source_sha256.as_deref(),
            &entry.result_sha256,
        )?;
        if !seen.insert(&entry.file)
            || created_only(component, &entry.file) != entry.backup.is_none()
            || entry.previous_sha256.as_ref().is_some_and(|h| !ok_hash(h))
        {
            return Err("Propriedade de arquivo inválida no registro.".into());
        }
        if let Some(backup) = &entry.backup {
            chain(backup)?;
            if io(backup.canonicalize())?.starts_with(game)
                || current(backup)? != entry.source_sha256
            {
                return Err(format!("Backup inválido: {}", entry.file));
            }
        }
        let hash = current(&game.join(&entry.file))?;
        if hash != entry.source_sha256
            && hash.as_ref() != Some(&entry.result_sha256)
            && !(["preparing", "restoring"].contains(&state.phase.as_str())
                && hash == entry.previous_sha256)
        {
            return Err(format!(
                "Conflito: {} mudou após a instalação; preservado.",
                entry.file
            ));
        }
    }
    Ok(())
}

fn save(game: &Path, component: &Component, state: &State) -> Result<()> {
    atomic_write(
        &game.join(MANAGER).join(component.state_file),
        &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
    )
}

fn package(component: &Component, path: &Path) -> Result<Vec<(Asset, Vec<u8>)>> {
    chain(path)?;
    let plan: AssetPackage =
        serde_json::from_slice(&read(path, 512 * 1024)?).map_err(|e| e.to_string())?;
    if plan.schema != 1 || plan.assets.is_empty() || plan.assets.len() > 2000 {
        return Err(format!("Pacote de {} inválido.", component.label));
    }
    let parent = path.parent().ok_or("Pacote sem diretório")?;
    let mut seen = HashSet::new();
    let mut output = Vec::new();
    for item in plan.assets {
        valid_asset(
            component,
            &item.file,
            item.source_sha256.as_deref(),
            &item.result_sha256,
        )?;
        if !seen.insert(item.file.clone())
            || item.payload.is_empty()
            || !item
                .payload
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_.\\/".contains(&c))
            || item.payload.starts_with('.')
            || item.payload.starts_with('/')
            || item.payload.starts_with('\\')
            || item.payload.contains("..")
        {
            return Err("Arquivo de pacote duplicado ou caminho inválido.".into());
        }
        let target = parent.join(&item.payload);
        chain(&target)?;
        let bytes = read(&target, LIMIT)?;
        if sha(&bytes) != item.result_sha256 {
            return Err(format!("Pacote alterado: {}", item.file));
        }
        output.push((item, bytes));
    }
    Ok(output)
}

pub fn inspect(game: &Path, component: &Component) -> Result<ExternalInfo> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let state = load_state(&game, component)?;
    let mut files = 0usize;
    for entry in &state.assets {
        if current(&game.join(&entry.file))?.as_ref() == Some(&entry.result_sha256) {
            files += 1;
        }
    }
    let installed = files > 0;
    let message = if installed {
        format!(
            "{} instalado ({files} arquivo(s)); runtime não validado.",
            component.label
        )
    } else if state.assets.is_empty() {
        format!("{} não instalado.", component.label)
    } else {
        format!(
            "{} declarado, mas os arquivos não conferem.",
            component.label
        )
    };
    Ok(ExternalInfo {
        id: component.id.into(),
        installed,
        files,
        message,
    })
}

pub fn inspect_package(component: &Component, path: &Path) -> Result<ExternalInfo> {
    let plan = package(component, path)?;
    Ok(ExternalInfo {
        id: component.id.into(),
        installed: false,
        files: plan.len(),
        message: format!(
            "Pacote de {} com {} arquivo(s).",
            component.label,
            plan.len()
        ),
    })
}

fn preflight(
    game: &Path,
    component: &Component,
    state: &State,
    plan: &[(Asset, Vec<u8>)],
    backups: &Path,
) -> Result<Vec<Entry>> {
    let mut changes = Vec::new();
    for (item, _) in plan {
        let previous = state.assets.iter().find(|e| e.file == item.file);
        let hash = current(&game.join(&item.file))?;
        // A created-only file that already holds the exact payload bytes is this
        // mod's own output. Adopting it recovers from a lost or overwritten journal
        // without rewriting, backing up or discarding anything.
        let already_ours = created_only(component, &item.file)
            && hash.as_deref() == Some(item.result_sha256.as_str());
        if !already_ours
            && hash != item.source_sha256
            && !previous.is_some_and(|e| {
                hash.as_ref() == Some(&e.result_sha256)
                    || (state.phase == "preparing" && hash == e.previous_sha256)
            })
        {
            return Err(format!(
                "Arquivo preexistente desconhecido: {}; preservado.",
                item.file
            ));
        }
        let backup = if created_only(component, &item.file) {
            None
        } else {
            Some(previous.and_then(|e| e.backup.clone()).unwrap_or_else(|| {
                backups
                    .join(component.id)
                    .join(format!("{}.original", item.file.replace('/', "_")))
            }))
        };
        if let Some(backup) = &backup {
            chain(backup)?;
            if prospective(backup)?.starts_with(game) {
                return Err("Backup deve ficar fora da instalação.".into());
            }
            if backup.exists() && current(backup)? != item.source_sha256 {
                return Err("Backup preexistente diferente; preservado.".into());
            }
        }
        changes.push(Entry {
            file: item.file.clone(),
            source_sha256: item.source_sha256.clone(),
            result_sha256: item.result_sha256.clone(),
            previous_sha256: hash,
            backup,
        });
    }
    Ok(changes)
}

pub fn validate_install(
    game: &Path,
    component: &Component,
    manifest: &Path,
    backups: &Path,
) -> Result<()> {
    let game = game_path(game)?;
    let _lock = lock(&game)?;
    let backups = prospective(backups)?;
    let state = load_state(&game, component)?;
    preflight(
        &game,
        component,
        &state,
        &package(component, manifest)?,
        &backups,
    )?;
    Ok(())
}

pub fn apply(
    game: &Path,
    component: &Component,
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<ExternalInfo> {
    let game = game_path(game)?;
    apply_checked(&game, component, manifest, backups, progress)
}

pub fn apply_with_control(
    game: &Path,
    component: &Component,
    manifest: &Path,
    backups: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<ExternalInfo> {
    let game = game_path(game)?;
    apply_checked_control(&game, component, manifest, backups, control, progress)
}

fn apply_checked(
    game: &Path,
    component: &Component,
    manifest: &Path,
    backups: &Path,
    mut progress: impl FnMut(&str),
) -> Result<ExternalInfo> {
    apply_checked_control(
        game,
        component,
        manifest,
        backups,
        &OperationControl::default(),
        |p| progress(&p.message),
    )
}

fn apply_checked_control(
    game: &Path,
    component: &Component,
    manifest: &Path,
    backups: &Path,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<ExternalInfo> {
    let _lock = lock(game)?;
    ensure_closed(&game)?;
    let backups = prospective(backups)?;
    let mut state = load_state(&game, component)?;
    let plan = package(component, manifest)?;
    let changes = preflight(&game, component, &state, &plan, &backups)?;
    let backup_total = changes
        .iter()
        .filter(|entry| entry.backup.is_some())
        .count();
    let mut backup_current = 0;
    for entry in &changes {
        control.checkpoint()?;
        if let Some(backup) = &entry.backup {
            if !backup.exists() {
                let bytes = read(&game.join(&entry.file), LIMIT)?;
                if Some(sha(&bytes)) != entry.source_sha256 {
                    return Err("Original mudou durante o backup.".into());
                }
                let parent = backup.parent().ok_or("Backup sem diretório")?;
                chain(parent)?;
                io(fs::create_dir_all(parent))?;
                let mut file = io(OpenOptions::new().create_new(true).write(true).open(backup))?;
                io(file.write_all(&bytes))?;
                io(file.sync_all())?;
            }
            if current(backup)? != entry.source_sha256 {
                return Err("Falha ao verificar backup.".into());
            }
            backup_current += 1;
            progress(Progress {
                stage: format!("backup-{}", component.id),
                current: backup_current,
                total: backup_total,
                message: format!("Backup de {}", entry.file),
            });
        }
    }
    for entry in &changes {
        state.assets.retain(|old| old.file != entry.file);
        state.assets.push(entry.clone());
    }
    state.phase = "preparing".into();
    save(&game, component, &state)?;
    let total = changes.len();
    for (index, (entry, (_, bytes))) in changes.iter().zip(plan.iter()).enumerate() {
        control.checkpoint()?;
        progress(Progress {
            stage: component.id.into(),
            current: index,
            total,
            message: format!("Instalando {}", entry.file),
        });
        ensure_closed(&game)?;
        let target = game.join(&entry.file);
        if current(&target)? != entry.previous_sha256 {
            return Err("Arquivo mudou durante a instalação; preservado.".into());
        }
        if let Some(parent) = target.parent() {
            io(fs::create_dir_all(parent))?;
        }
        atomic_write(&target, bytes)?;
        if current(&target)?.as_ref() != Some(&entry.result_sha256) {
            return Err("Falha na conferência do arquivo instalado.".into());
        }
        progress(Progress {
            stage: component.id.into(),
            current: index + 1,
            total,
            message: format!("Arquivo instalado: {}", entry.file),
        });
    }
    state.phase = "installed".into();
    save(&game, component, &state)?;
    inspect(&game, component)
}

pub fn restore(
    game: &Path,
    component: &Component,
    progress: impl FnMut(&str),
) -> Result<ExternalInfo> {
    let game = game_path(game)?;
    restore_checked(&game, component, progress)
}

pub fn restore_with_control(
    game: &Path,
    component: &Component,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<ExternalInfo> {
    let game = game_path(game)?;
    restore_checked_control(&game, component, control, progress)
}

fn restore_checked(
    game: &Path,
    component: &Component,
    mut progress: impl FnMut(&str),
) -> Result<ExternalInfo> {
    restore_checked_control(game, component, &OperationControl::default(), |p| {
        progress(&p.message)
    })
}

fn restore_checked_control(
    game: &Path,
    component: &Component,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<ExternalInfo> {
    let _lock = lock(game)?;
    ensure_closed(&game)?;
    let mut state = load_state(&game, component)?;
    let expected: Vec<_> = state
        .assets
        .iter()
        .map(|e| current(&game.join(&e.file)))
        .collect::<Result<_>>()?;
    state.phase = "restoring".into();
    save(&game, component, &state)?;
    let mut all_owned = true;
    let total = state.assets.len();
    for (index, (entry, expected)) in state.assets.iter().zip(expected.iter()).enumerate() {
        control.checkpoint()?;
        progress(Progress {
            stage: format!("restauracao-{}", component.id),
            current: index,
            total,
            message: format!("Restaurando {}", entry.file),
        });
        ensure_closed(&game)?;
        let path = game.join(&entry.file);
        if &current(&path)? != expected {
            all_owned = false;
            continue;
        }
        if let Some(backup) = &entry.backup {
            let data = read(backup, LIMIT)?;
            if Some(sha(&data)) != entry.source_sha256 {
                return Err("Backup alterado durante a restauração.".into());
            }
            atomic_write(&path, &data)?;
        } else if path.exists() {
            io(fs::remove_file(&path))?;
        }
        progress(Progress {
            stage: format!("restauracao-{}", component.id),
            current: index + 1,
            total,
            message: format!("Arquivo restaurado: {}", entry.file),
        });
    }
    if all_owned {
        for dir in component.clean_dirs {
            let target = game.join(dir);
            if target.is_dir() {
                let _ = fs::remove_dir_all(&target);
            }
        }
    }
    state.phase = "restored".into();
    state.assets.clear();
    save(&game, component, &state)?;
    inspect(&game, component)
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST: Component = Component {
        id: "textures",
        label: "Texturas HD",
        state_file: "textures-state.json",
        legacy_state_file: None,
        known: &[(
            "textures.big",
            "a09773724ca998fd6ccbbeed7fee193c3ccba39e82a355106776f6cee5eca5fe",
        )],
        created: &["hd-textures/index.json"],
        created_prefixes: &["hd-textures/"],
        clean_dirs: &["hd-textures"],
    };

    /// Same shape as the DualSense companion: a runtime writes its live status
    /// into the journal name used by earlier versions.
    const TEST_LEGACY: Component = Component {
        id: "textures",
        label: "Texturas HD",
        state_file: "textures-journal.json",
        legacy_state_file: Some("textures-state.json"),
        known: TEST.known,
        created: TEST.created,
        created_prefixes: TEST.created_prefixes,
        clean_dirs: TEST.clean_dirs,
    };

    fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf) {
        let root = tempfile::tempdir().unwrap();
        let game = root.path().join("game");
        fs::create_dir(&game).unwrap();
        fs::write(game.join("kain2.exe"), b"fixture executable, never started").unwrap();
        fs::write(game.join("savegame.her"), b"user save").unwrap();
        let original = b"original texture archive".to_vec();
        fs::write(game.join("textures.big"), &original).unwrap();
        let candidate = b"hd texture archive".to_vec();
        fs::write(root.path().join("hd.big"), &candidate).unwrap();
        let manifest = root.path().join("textures.json");
        let assets = vec![
            Asset {
                file: "textures.big".into(),
                payload: "hd.big".into(),
                source_sha256: Some(sha(&original)),
                result_sha256: sha(&candidate),
            },
            Asset {
                file: "hd-textures/index.json".into(),
                payload: "index.json".into(),
                source_sha256: None,
                result_sha256: sha(b"{}"),
            },
        ];
        let package_dir = root.path().join("payload");
        fs::create_dir(&package_dir).unwrap();
        fs::write(package_dir.join("index.json"), b"{}").unwrap();
        let mut assets = assets;
        assets[1].payload = "payload/index.json".into();
        fs::write(
            &manifest,
            serde_json::to_vec(&AssetPackage { schema: 1, assets }).unwrap(),
        )
        .unwrap();
        let backups = root.path().join("backup");
        let game = game.canonicalize().unwrap();
        (root, game, manifest, backups)
    }

    #[test]
    fn textures_apply_and_restore_preserve_save() {
        let (_root, game, manifest, backups) = fixture();
        let info = apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        assert_eq!(info.files, 2);
        assert!(info.installed);
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"hd texture archive"
        );
        assert!(game.join("hd-textures/index.json").exists());
        let repeated = apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        assert_eq!(repeated.files, 2);
        assert_eq!(
            fs::read(backups.join("textures/textures.big.original")).unwrap(),
            b"original texture archive"
        );
        let restored = restore_checked(&game, &TEST, |_| {}).unwrap();
        assert_eq!(restored.files, 0);
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"original texture archive"
        );
        assert!(!game.join("hd-textures").exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
    }

    #[test]
    fn unknown_preexisting_archive_is_preserved() {
        let (_root, game, manifest, backups) = fixture();
        fs::write(game.join("textures.big"), b"foreign texture mod").unwrap();
        assert!(
            apply_checked(&game, &TEST, &manifest, &backups, |_| {})
                .unwrap_err()
                .contains("preexistente")
        );
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"foreign texture mod"
        );
    }

    #[test]
    fn modified_after_install_blocks_restore() {
        let (_root, game, manifest, backups) = fixture();
        apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        fs::write(game.join("textures.big"), b"changed later").unwrap();
        assert!(
            restore_checked(&game, &TEST, |_| {})
                .unwrap_err()
                .contains("Conflito")
        );
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"changed later"
        );
    }

    #[test]
    fn missing_external_backup_blocks_restore() {
        let (_root, game, manifest, backups) = fixture();
        apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        fs::remove_file(backups.join("textures/textures.big.original")).unwrap();

        assert!(restore_checked(&game, &TEST, |_| {}).is_err());
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"hd texture archive"
        );
    }

    #[test]
    fn changed_external_backup_blocks_restore() {
        let (_root, game, manifest, backups) = fixture();
        apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        fs::write(
            backups.join("textures/textures.big.original"),
            b"tampered backup",
        )
        .unwrap();

        let error = restore_checked(&game, &TEST, |_| {}).unwrap_err();
        assert!(error.contains("Backup inválido"), "{error}");
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"hd texture archive"
        );
    }

    #[test]
    fn package_payload_hash_mismatch_is_refused() {
        let (_root, game, manifest, backups) = fixture();
        fs::write(
            manifest.parent().unwrap().join("hd.big"),
            b"payload changed after manifest",
        )
        .unwrap();

        let error = apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap_err();
        assert!(error.contains("Pacote alterado"), "{error}");
        assert_eq!(
            fs::read(game.join("textures.big")).unwrap(),
            b"original texture archive"
        );
        assert!(!game.join("hd-textures/index.json").exists());
    }

    #[test]
    fn created_prefix_with_traversal_name_is_refused() {
        assert!(valid_asset(&TEST, "hd-textures/../evil.raw", None, &sha(b"x")).is_err());
        assert!(valid_asset(&TEST, "hd-textures/index.json", None, &sha(b"x")).is_ok());
    }

    #[test]
    fn runtime_status_in_the_state_file_never_blocks_the_check() {
        let (_root, game, _manifest, _backups) = fixture();
        let manager = game.join(MANAGER);
        fs::create_dir_all(&manager).unwrap();
        fs::write(
            manager.join("textures-state.json"),
            br#"{"connected":true,"realm":0,"health":100,"lightbar":{"r":0,"g":110,"b":255}}"#,
        )
        .unwrap();

        let info = inspect(&game, &TEST_LEGACY).unwrap();
        assert!(!info.installed);
        assert!(info.message.contains("não instalado"), "{}", info.message);
    }

    #[test]
    fn legacy_journal_is_read_and_the_next_write_uses_the_journal_name() {
        let (_root, game, manifest, backups) = fixture();
        apply_checked(&game, &TEST, &manifest, &backups, |_| {}).unwrap();
        let manager = game.join(MANAGER);
        assert!(manager.join(TEST.state_file).is_file());
        assert!(!manager.join(TEST_LEGACY.state_file).exists());

        // The installation is still recognised through the legacy journal name.
        assert!(inspect(&game, &TEST_LEGACY).unwrap().installed);

        // Applying again migrates the journal to its own name.
        apply_checked(&game, &TEST_LEGACY, &manifest, &backups, |_| {}).unwrap();
        assert!(manager.join(TEST_LEGACY.state_file).is_file());

        // A runtime status later written into the legacy name changes nothing and
        // is left untouched.
        fs::write(
            manager.join("textures-state.json"),
            br#"{"connected":true,"realm":0,"souls":3}"#,
        )
        .unwrap();
        assert!(inspect(&game, &TEST_LEGACY).unwrap().installed);
        assert_eq!(
            fs::read(manager.join(TEST.state_file)).unwrap(),
            br#"{"connected":true,"realm":0,"souls":3}"#
        );
    }

    /// Mirrors the DualSense companion: only created files, no original source.
    const TEST_COMPANION: Component = Component {
        id: "companion",
        label: "Acompanhante",
        state_file: "companion-journal.json",
        legacy_state_file: Some("companion-state.json"),
        known: &[],
        created: &["sr-dualsense.exe"],
        created_prefixes: &[],
        clean_dirs: &[],
    };

    /// Mirrors the older build, which wrote the journal straight into the name the
    /// runtime later reused.
    const TEST_COMPANION_OLD: Component = Component {
        id: "companion",
        label: "Acompanhante",
        state_file: "companion-state.json",
        legacy_state_file: None,
        known: &[],
        created: &["sr-dualsense.exe"],
        created_prefixes: &[],
        clean_dirs: &[],
    };

    fn companion_fixture() -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf) {
        let root = tempfile::tempdir().unwrap();
        let game = root.path().join("game");
        fs::create_dir(&game).unwrap();
        fs::write(game.join("kain2.exe"), b"fixture executable, never started").unwrap();
        fs::write(game.join("savegame.her"), b"user save").unwrap();
        let payload = b"companion payload".to_vec();
        fs::write(root.path().join("sr-dualsense.exe"), &payload).unwrap();
        let manifest = root.path().join("companion.json");
        fs::write(
            &manifest,
            serde_json::to_vec(&AssetPackage {
                schema: 1,
                assets: vec![Asset {
                    file: "sr-dualsense.exe".into(),
                    payload: "sr-dualsense.exe".into(),
                    source_sha256: None,
                    result_sha256: sha(&payload),
                }],
            })
            .unwrap(),
        )
        .unwrap();
        let backups = root.path().join("backup");
        let game = game.canonicalize().unwrap();
        (root, game, manifest, backups)
    }

    #[test]
    fn companion_survives_a_runtime_status_file_and_adopts_an_orphaned_payload() {
        let (_root, game, manifest, backups) = companion_fixture();
        assert!(
            apply_checked(&game, &TEST_COMPANION, &manifest, &backups, |_| {})
                .unwrap()
                .installed
        );
        let manager = game.join(MANAGER);

        // The runtime rewrites the legacy name while the game is open.
        fs::write(
            manager.join("companion-state.json"),
            br#"{"connected":true,"realm":0}"#,
        )
        .unwrap();
        assert!(inspect(&game, &TEST_COMPANION).unwrap().installed);

        // Losing the journal must not turn our own untouched payload into a conflict.
        fs::remove_file(manager.join(TEST_COMPANION.state_file)).unwrap();
        assert!(!inspect(&game, &TEST_COMPANION).unwrap().installed);
        let info = apply_checked(&game, &TEST_COMPANION, &manifest, &backups, |_| {}).unwrap();
        assert!(info.installed);
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"companion payload"
        );
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");

        // The adopted file is owned again, so removal deletes only it.
        assert!(!restore_checked(&game, &TEST_COMPANION, |_| {}).unwrap().installed);
        assert!(!game.join("sr-dualsense.exe").exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");

        // A different program in the same path is still refused.
        fs::remove_file(manager.join(TEST_COMPANION.state_file)).unwrap();
        fs::write(game.join("sr-dualsense.exe"), b"foreign companion").unwrap();
        assert!(
            apply_checked(&game, &TEST_COMPANION, &manifest, &backups, |_| {}).is_err()
        );
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"foreign companion"
        );
    }

    #[test]
    fn stale_legacy_journal_blocks_nothing_and_deletes_nothing() {
        let (_root, game, manifest, backups) = companion_fixture();
        apply_checked(&game, &TEST_COMPANION_OLD, &manifest, &backups, |_| {}).unwrap();
        assert!(game.join(MANAGER).join("companion-state.json").is_file());

        // A newer payload arrives and the newer journal is lost: the legacy record
        // no longer describes the disk and must not be trusted.
        fs::write(game.join("sr-dualsense.exe"), b"newer companion").unwrap();
        assert!(!inspect(&game, &TEST_COMPANION).unwrap().installed);
        restore_checked(&game, &TEST_COMPANION, |_| {}).unwrap();
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"newer companion"
        );

        // Installing the current payload still refuses the changed file.
        assert!(
            apply_checked(&game, &TEST_COMPANION, &manifest, &backups, |_| {}).is_err()
        );
        assert_eq!(
            fs::read(game.join("sr-dualsense.exe")).unwrap(),
            b"newer companion"
        );
    }
}
