//! Localization and video assets use independent journals and a shared operation lock.
use super::*;

const LIMIT: u64 = 512 * 1024 * 1024;

#[derive(Clone, Copy, Debug)]
pub struct AssetsComponent {
    pub id: &'static str,
    pub label: &'static str,
    pub state_file: &'static str,
    pub known: &'static [(&'static str, &'static str)],
    pub created: &'static [&'static str],
    pub max_files: usize,
}

pub const LOCALIZATION: AssetsComponent = AssetsComponent {
    id: "localization",
    label: "Localização",
    state_file: "assets-state.json",
    known: &[
        (
            "locals.pc",
            "2244304cbf1d89f7aaee44c534cf185c0ffd037272deee909247727be1d54d84",
        ),
        (
            "bigfile.dat",
            "30295bb8bdd059a3001f4b30d68973fd2e6a3ae50ea444087c8a17e94adeb035",
        ),
    ],
    created: &[
        "DINPUT.dll",
        ".soul-reaver-ptbr/subtitles.tsv",
        ".soul-reaver-ptbr/unicode-runtime-overlay.dll",
        ".soul-reaver-ptbr/unicode-runtime-bridge.js",
        ".soul-reaver-ptbr/subtitles-unicode-v1.json",
    ],
    max_files: 7,
};

pub const VIDEO: AssetsComponent = AssetsComponent {
    id: "video",
    label: "Vídeos",
    state_file: "video-state.json",
    known: &[
        (
            "crylogo.bik",
            "de25840d0e384908489709b993847ec4b04b4d9806f2538256bc1bb6b50cc402",
        ),
        (
            "publogo.bik",
            "25ca73fa5b7d8794bfba3b607363142ba08fc512ef2452aa302d527fdbfc3cc2",
        ),
        (
            "intro.bik",
            "8786078e1cd9f5938c766fb1e84db35fcde51f1f253ff463192e6314bad753ef",
        ),
        (
            "verse.bik",
            "5739b6f6bee1d90c0d264070d4a904422b78ee0960c761ca569c4b7df0d7d427",
        ),
        (
            "chrono3.bik",
            "521963432abe905c3a4c4372177567d7b7efd05d9d9cfc143bd20a6756b21fe1",
        ),
        (
            "chrono5.bik",
            "f87adc6d60ccbe3365a489afdf0174d934e02cc787f91e20fa01eda4eb15a99d",
        ),
        (
            "chrono7.bik",
            "87e3fd51cb87a7525d66dd3ee50872d93711a49f49e361be1ee40ecd009a2f75",
        ),
        (
            "chrono9.bik",
            "918440f18e69f51e4a0e14f1c612f9d79f6d2361ebd5961c073d50fcc7e171f7",
        ),
        (
            "chrono11.bik",
            "2f4b92c6f98d46831e66de440fc3dbe0d5b1461595ff307289593b0714a5f8c2",
        ),
        (
            "chrono13.bik",
            "347df0233db681bb0c23f3c95d68a40f7cf56db1e14f493707eccf2038d8f0cb",
        ),
    ],
    created: &[],
    max_files: 10,
};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AssetsInfo {
    pub menus: bool,
    pub videos: usize,
    pub subtitles: bool,
    pub files: usize,
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

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    file: String,
    source_sha256: Option<String>,
    result_sha256: String,
    #[serde(default)]
    previous_sha256: Option<String>,
    backup: Option<PathBuf>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    schema: u32,
    game: PathBuf,
    phase: String,
    assets: Vec<Entry>,
}

fn new_file(component: &AssetsComponent, name: &str) -> bool {
    component.created.contains(&name)
}

fn known_source(component: &AssetsComponent, name: &str) -> Option<&'static str> {
    component
        .known
        .iter()
        .find(|(file, _)| *file == name)
        .map(|(_, hash)| *hash)
}

fn hash_valid(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn valid_asset(
    component: &AssetsComponent,
    name: &str,
    source: Option<&str>,
    result: &str,
) -> Result<()> {
    if (!new_file(component, name) && known_source(component, name).is_none())
        || source != known_source(component, name)
        || !hash_valid(result)
        || source == Some(result)
    {
        return Err(format!(
            "Arquivo ou base de {} incompatível: {name}",
            component.label
        ));
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

fn game_path(game: &Path, component: &AssetsComponent) -> Result<PathBuf> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let exe = sha(&read(&game.join("kain2.exe"), 4 * 1024 * 1024)?);
    if exe != EXE_SHA256 && exe != EXE_WIDESCREEN_SHA256 {
        return Err(format!(
            "Executável incompatível com o componente {}.",
            component.label
        ));
    }
    Ok(game)
}

fn lock(game: &Path) -> Result<File> {
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

fn read_state_record(game: &Path, component: &AssetsComponent) -> Result<Option<(State, Vec<u8>)>> {
    let path = game.join(MANAGER).join(component.state_file);
    chain(&path)?;
    if !path.exists() {
        return Ok(None);
    }
    let bytes = read(&path, 128 * 1024)?;
    let state: State = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
    if state.schema != 1
        || io(state.game.canonicalize())? != game
        || ![
            "original",
            "preparing",
            "installed",
            "restoring",
            "restored",
        ]
        .contains(&state.phase.as_str())
    {
        return Err(format!("Registro de {} incompatível.", component.label));
    }
    Ok(Some((state, bytes)))
}

struct LegacyViews {
    original: Vec<u8>,
    localization: State,
    video: State,
    existing_video: Option<Vec<u8>>,
}

fn belongs_to(component: &AssetsComponent, file: &str) -> bool {
    new_file(component, file) || known_source(component, file).is_some()
}

/// Project a legacy combined journal without modifying it. Every entry is still
/// validated against its own allowlist, source, result, backup and current hash.
fn legacy_views(game: &Path, video: &AssetsComponent) -> Result<Option<LegacyViews>> {
    let Some((state, original)) = read_state_record(game, &LOCALIZATION)? else {
        return Ok(None);
    };
    if !state
        .assets
        .iter()
        .any(|entry| belongs_to(video, &entry.file))
    {
        return Ok(None);
    }
    let mut localization = state.clone();
    let mut video_state = state;
    localization
        .assets
        .retain(|entry| !belongs_to(video, &entry.file));
    video_state
        .assets
        .retain(|entry| belongs_to(video, &entry.file));
    validate_state(game, &LOCALIZATION, &localization)?;
    validate_state(game, video, &video_state)?;
    let existing_video = if let Some((existing, bytes)) = read_state_record(game, video)? {
        validate_state(game, video, &existing)?;
        // The only accepted overlap is an identical projection left by a crash
        // after writing video-state and before replacing the combined journal.
        if existing.phase != video_state.phase
            || existing.assets.len() != video_state.assets.len()
            || !existing
                .assets
                .iter()
                .all(|entry| video_state.assets.contains(entry))
        {
            return Err(
                "Registros legado e de vídeos têm propriedades divergentes; arquivos preservados."
                    .into(),
            );
        }
        Some(bytes)
    } else {
        None
    };
    Ok(Some(LegacyViews {
        original,
        localization,
        video: video_state,
        existing_video,
    }))
}

fn load_state(game: &Path, component: &AssetsComponent) -> Result<State> {
    if component.id == LOCALIZATION.id || component.id == VIDEO.id {
        let video = if component.id == VIDEO.id {
            component
        } else {
            &VIDEO
        };
        if let Some(views) = legacy_views(game, video)? {
            return Ok(if component.id == VIDEO.id {
                views.video
            } else {
                views.localization
            });
        }
    }
    let state = match read_state_record(game, component)? {
        Some((state, _)) => state,
        None => State {
            schema: 1,
            game: game.into(),
            phase: "original".into(),
            assets: vec![],
        },
    };
    validate_state(game, component, &state)?;
    Ok(state)
}

/// Atomic create-only metadata persistence: never clobber a different backup or
/// video journal if one appeared after validation.
fn persist_identical_or_new(path: &Path, bytes: &[u8]) -> Result<()> {
    chain(path)?;
    if path.exists() {
        return if read(path, 128 * 1024)? == bytes {
            Ok(())
        } else {
            Err("Registro de migração preexistente diferente; preservado.".into())
        };
    }
    let parent = path.parent().ok_or("Registro sem diretório pai")?;
    let mut temporary = io(tempfile::NamedTempFile::new_in(parent))?;
    io(temporary.write_all(bytes))?;
    io(temporary.as_file().sync_all())?;
    match temporary.persist_noclobber(path) {
        Ok(_) => Ok(()),
        Err(error) if error.error.kind() == std::io::ErrorKind::AlreadyExists => {
            if read(path, 128 * 1024)? == bytes {
                Ok(())
            } else {
                Err("Registro de migração mudou; preservado.".into())
            }
        }
        Err(error) => Err(error.to_string()),
    }
}

/// Called only by save while the shared operation lock is held. Video is saved
/// first; interruption leaves the full legacy journal and a matching duplicate,
/// which legacy_views accepts and a later operation can finish safely.
fn migrate_legacy_state(game: &Path, video: &AssetsComponent) -> Result<()> {
    let Some(views) = legacy_views(game, video)? else {
        return Ok(());
    };
    let manager = game.join(MANAGER);
    let legacy_path = manager.join(LOCALIZATION.state_file);
    let video_path = manager.join(video.state_file);
    let snapshot = manager.join(format!("assets-state.legacy-{}.json", sha(&views.original)));
    persist_identical_or_new(&snapshot, &views.original)?;
    if let Some(expected) = views.existing_video {
        if read(&video_path, 128 * 1024)? != expected {
            return Err("Registro de vídeos mudou durante a migração; preservado.".into());
        }
    } else {
        persist_identical_or_new(
            &video_path,
            &serde_json::to_vec_pretty(&views.video).map_err(|e| e.to_string())?,
        )?;
    }
    if read(&legacy_path, 128 * 1024)? != views.original {
        return Err("Registro legado mudou durante a migração; preservado.".into());
    }
    atomic_write(
        &legacy_path,
        &serde_json::to_vec_pretty(&views.localization).map_err(|e| e.to_string())?,
    )
}

fn validate_state(game: &Path, component: &AssetsComponent, state: &State) -> Result<()> {
    let mut seen = HashSet::new();
    for entry in &state.assets {
        valid_asset(
            component,
            &entry.file,
            entry.source_sha256.as_deref(),
            &entry.result_sha256,
        )?;
        if !seen.insert(&entry.file)
            || new_file(component, &entry.file) != entry.backup.is_none()
            || entry
                .previous_sha256
                .as_ref()
                .is_some_and(|h| !hash_valid(h))
        {
            return Err("Propriedade de arquivo inválida no registro.".into());
        }
        if let Some(backup) = &entry.backup {
            chain(backup)?;
            if io(backup.canonicalize())?.starts_with(game)
                || current(backup)? != entry.source_sha256
            {
                return Err(format!(
                    "Backup de {} inválido: {}",
                    component.label, entry.file
                ));
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

fn save(game: &Path, component: &AssetsComponent, state: &State) -> Result<()> {
    if component.id == LOCALIZATION.id || component.id == VIDEO.id {
        migrate_legacy_state(
            game,
            if component.id == VIDEO.id {
                component
            } else {
                &VIDEO
            },
        )?;
    }
    atomic_write(
        &game.join(MANAGER).join(component.state_file),
        &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
    )
}

fn package(component: &AssetsComponent, path: &Path) -> Result<Vec<(Asset, Vec<u8>)>> {
    chain(path)?;
    let plan: AssetPackage =
        serde_json::from_slice(&read(path, 128 * 1024)?).map_err(|e| e.to_string())?;
    if plan.schema != 1 || plan.assets.is_empty() || plan.assets.len() > component.max_files {
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
        // Keep payloads in the package; never follow absolute paths or traversal.
        if !seen.insert(item.file.clone())
            || item.payload.is_empty()
            || !item
                .payload
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c))
            || item.payload.starts_with('.')
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

fn info<'a>(component: &AssetsComponent, files: impl Iterator<Item = &'a str>) -> AssetsInfo {
    let mut result = AssetsInfo::default();
    let mut proxy = false;
    let mut captions = false;
    for name in files {
        result.files += 1;
        result.menus |= component.id == LOCALIZATION.id && name == "locals.pc";
        result.videos += usize::from(component.id == VIDEO.id && name.ends_with(".bik"));
        proxy |= component.id == LOCALIZATION.id && name == "DINPUT.dll";
        captions |= component.id == LOCALIZATION.id && name == ".soul-reaver-ptbr/subtitles.tsv";
    }
    result.subtitles = proxy && captions;
    result
}

pub fn inspect_package(path: &Path) -> Result<AssetsInfo> {
    inspect_package_component(&LOCALIZATION, path)
}

pub fn inspect_package_component(component: &AssetsComponent, path: &Path) -> Result<AssetsInfo> {
    Ok(info(
        component,
        package(component, path)?
            .iter()
            .map(|(a, _)| a.file.as_str()),
    ))
}

pub fn inspect(game: &Path) -> Result<AssetsInfo> {
    inspect_component(game, &LOCALIZATION)
}

pub fn inspect_component(game: &Path, component: &AssetsComponent) -> Result<AssetsInfo> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let state = load_state(&game, component)?;
    let mut files = Vec::new();
    for entry in &state.assets {
        if current(&game.join(&entry.file))?.as_ref() == Some(&entry.result_sha256) {
            files.push(entry.file.as_str());
        }
    }
    Ok(info(component, files.into_iter()))
}

fn preflight(
    game: &Path,
    component: &AssetsComponent,
    state: &State,
    plan: &[(Asset, Vec<u8>)],
    backups: &Path,
) -> Result<Vec<Entry>> {
    let mut changes = Vec::new();
    for (item, _) in plan {
        let previous = state.assets.iter().find(|e| e.file == item.file);
        let hash = current(&game.join(&item.file))?;
        if hash != item.source_sha256
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
        let backup = if new_file(component, &item.file) {
            None
        } else {
            Some(
                previous
                    .and_then(|e| e.backup.clone())
                    .unwrap_or_else(|| backups.join(format!("{}.original", item.file))),
            )
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

/// Validate a component operation before another installer component mutates anything.
pub fn validate_install(game: &Path, manifest: &Path, backups: &Path) -> Result<()> {
    validate_install_component(game, &LOCALIZATION, manifest, backups)
}

pub fn validate_install_component(
    game: &Path,
    component: &AssetsComponent,
    manifest: &Path,
    backups: &Path,
) -> Result<()> {
    let game = game_path(game, component)?;
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
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<AssetsInfo> {
    apply_component(game, &LOCALIZATION, manifest, backups, progress)
}

pub fn apply_component(
    game: &Path,
    component: &AssetsComponent,
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<AssetsInfo> {
    let game = game_path(game, component)?;
    apply_checked(&game, component, manifest, backups, progress)
}

pub fn apply_with_control(
    game: &Path,
    manifest: &Path,
    backups: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    apply_component_with_control(game, &LOCALIZATION, manifest, backups, control, progress)
}

pub fn apply_component_with_control(
    game: &Path,
    component: &AssetsComponent,
    manifest: &Path,
    backups: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    let game = game_path(game, component)?;
    apply_checked_control(&game, component, manifest, backups, control, progress)
}

fn apply_checked(
    game: &Path,
    component: &AssetsComponent,
    manifest: &Path,
    backups: &Path,
    progress: impl FnMut(&str),
) -> Result<AssetsInfo> {
    let mut progress = progress;
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
    component: &AssetsComponent,
    manifest: &Path,
    backups: &Path,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    let _lock = lock(&game)?;
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
    inspect_component(&game, component)
}

pub fn restore(game: &Path, mut progress: impl FnMut(&str)) -> Result<AssetsInfo> {
    restore_component(game, &LOCALIZATION, &mut progress)
}

pub fn restore_component(
    game: &Path,
    component: &AssetsComponent,
    progress: impl FnMut(&str),
) -> Result<AssetsInfo> {
    let game = game_path(game, component)?;
    restore_checked(&game, component, progress)
}

pub fn restore_with_control(
    game: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    restore_component_with_control(game, &LOCALIZATION, control, progress)
}

pub fn restore_component_with_control(
    game: &Path,
    component: &AssetsComponent,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    let game = game_path(game, component)?;
    restore_checked_control(&game, component, control, progress)
}

fn restore_checked(
    game: &Path,
    component: &AssetsComponent,
    mut progress: impl FnMut(&str),
) -> Result<AssetsInfo> {
    restore_checked_control(game, component, &OperationControl::default(), |p| {
        progress(&p.message)
    })
}

fn restore_checked_control(
    game: &Path,
    component: &AssetsComponent,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<AssetsInfo> {
    let _lock = lock(&game)?;
    ensure_closed(&game)?;
    let mut state = load_state(&game, component)?;
    let expected: Vec<_> = state
        .assets
        .iter()
        .map(|e| current(&game.join(&e.file)))
        .collect::<Result<_>>()?;
    state.phase = "restoring".into();
    save(&game, component, &state)?;
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
            return Err("Arquivo mudou durante a restauração; preservado.".into());
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
        if current(&path)? != entry.source_sha256 {
            return Err("Falha na conferência da restauração.".into());
        }
        progress(Progress {
            stage: format!("restauracao-{}", component.id),
            current: index + 1,
            total,
            message: format!("Arquivo restaurado: {}", entry.file),
        });
    }
    state.phase = "restored".into();
    save(&game, component, &state)?;
    inspect_component(&game, component)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn menu_background_requires_the_supported_archive_base() {
        let source = "30295bb8bdd059a3001f4b30d68973fd2e6a3ae50ea444087c8a17e94adeb035";
        let result = sha(b"menu candidate");
        valid_asset(&LOCALIZATION, "bigfile.dat", Some(source), &result).unwrap();
        assert!(valid_asset(&LOCALIZATION, "bigfile.dat", None, &result).is_err());
        assert!(valid_asset(&LOCALIZATION, "bigfile.dat", Some(&result), source).is_err());
        assert!(valid_asset(&LOCALIZATION, "other.dat", Some(source), &result).is_err());
        assert!(valid_asset(&LOCALIZATION, "bigfile.dat", Some(source), source).is_err());
    }

    #[test]
    fn company_openings_require_known_originals_and_stay_in_video_component() {
        let result = sha(b"new project opening");
        for (file, source) in [
            (
                "crylogo.bik",
                "de25840d0e384908489709b993847ec4b04b4d9806f2538256bc1bb6b50cc402",
            ),
            (
                "publogo.bik",
                "25ca73fa5b7d8794bfba3b607363142ba08fc512ef2452aa302d527fdbfc3cc2",
            ),
        ] {
            valid_asset(&VIDEO, file, Some(source), &result).unwrap();
            assert!(valid_asset(&VIDEO, file, None, &result).is_err());
            assert!(valid_asset(&VIDEO, file, Some(&result), source).is_err());
            assert!(valid_asset(&LOCALIZATION, file, Some(source), &result).is_err());
        }
    }

    #[test]
    fn unicode_subtitle_payload_paths_are_allowlisted_as_new_files() {
        let result = sha(b"candidate payload");
        for file in [
            ".soul-reaver-ptbr/unicode-runtime-overlay.dll",
            ".soul-reaver-ptbr/unicode-runtime-bridge.js",
            ".soul-reaver-ptbr/subtitles-unicode-v1.json",
        ] {
            valid_asset(&LOCALIZATION, file, None, &result).unwrap();
        }
        assert!(
            valid_asset(
                &LOCALIZATION,
                ".soul-reaver-ptbr/unicode/unapproved.dll",
                None,
                &result,
            )
            .is_err()
        );
    }

    const TEST_VIDEO_CREATED: &[&str] = &["intro.bik"];
    const TEST_VIDEO: AssetsComponent = AssetsComponent {
        known: &[],
        created: TEST_VIDEO_CREATED,
        ..VIDEO
    };

    fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf, PathBuf) {
        let root = tempfile::tempdir().unwrap();
        let game = root.path().join("game");
        fs::create_dir(&game).unwrap();
        fs::write(game.join("kain2.exe"), b"fixture executable, never started").unwrap();
        fs::write(game.join("savegame.her"), b"user save").unwrap();
        fs::write(game.join("DDraw.dll"), b"other graphics mod").unwrap();
        let manifest = root.path().join("assets.json");
        let mut assets = Vec::new();
        for (name, payload, bytes) in [
            ("DINPUT.dll", "proxy.dll", b"subtitle proxy".as_slice()),
            (
                ".soul-reaver-ptbr/subtitles.tsv",
                "subtitles.tsv",
                b"154\tVoce renasceu.\n".as_slice(),
            ),
        ] {
            fs::write(root.path().join(payload), bytes).unwrap();
            assets.push(Asset {
                file: name.into(),
                payload: payload.into(),
                source_sha256: None,
                result_sha256: sha(bytes),
            });
        }
        fs::write(
            &manifest,
            serde_json::to_vec(&AssetPackage { schema: 1, assets }).unwrap(),
        )
        .unwrap();
        let backups = root.path().join("backup");
        let game = game.canonicalize().unwrap();
        (root, game, manifest, backups)
    }

    const LEGACY_ORIGINAL: &[u8] = b"original legacy video fixture";
    const TEST_LEGACY_VIDEO: AssetsComponent = AssetsComponent {
        known: &[(
            "intro.bik",
            "29af73d4b745c56981d523509446ca83a2cd3d768c67050ff32db2da38d7bd3e",
        )],
        ..VIDEO
    };

    fn legacy_fixture() -> (tempfile::TempDir, PathBuf, Vec<u8>) {
        let (root, game, manifest, backups) = fixture();
        apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {}).unwrap();
        let mut state = load_state(&game, &LOCALIZATION).unwrap();
        let bytes = b"legacy translated video fixture";
        fs::write(game.join("intro.bik"), bytes).unwrap();
        fs::create_dir_all(&backups).unwrap();
        let backup = backups.join("intro.bik.original");
        fs::write(&backup, LEGACY_ORIGINAL).unwrap();
        state.assets.push(Entry {
            file: "intro.bik".into(),
            source_sha256: Some(sha(LEGACY_ORIGINAL)),
            result_sha256: sha(bytes),
            previous_sha256: Some(sha(bytes)),
            backup: Some(backup),
        });
        let path = game.join(MANAGER).join(LOCALIZATION.state_file);
        let original = serde_json::to_vec_pretty(&state).unwrap();
        fs::write(&path, &original).unwrap();
        (root, game, original)
    }

    #[test]
    fn legacy_mixed_video_inspection_is_read_only() {
        let (_root, game, original) = legacy_fixture();
        assert_eq!(
            inspect_component(&game, &TEST_LEGACY_VIDEO).unwrap().videos,
            1
        );
        assert_eq!(
            fs::read(game.join(MANAGER).join(LOCALIZATION.state_file)).unwrap(),
            original
        );
        assert!(!game.join(MANAGER).join(VIDEO.state_file).exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
    }

    #[test]
    fn legacy_mixed_video_restore_migrates_metadata_and_preserves_localization() {
        let (_root, game, original) = legacy_fixture();
        restore_checked(&game, &TEST_LEGACY_VIDEO, |_| {}).unwrap();
        assert_eq!(fs::read(game.join("intro.bik")).unwrap(), LEGACY_ORIGINAL);
        let localization = inspect_component(&game, &LOCALIZATION).unwrap();
        assert!(localization.subtitles);
        assert_eq!(localization.files, 2);
        assert_eq!(
            inspect_component(&game, &TEST_LEGACY_VIDEO).unwrap().videos,
            0
        );
        let snapshot = game
            .join(MANAGER)
            .join(format!("assets-state.legacy-{}.json", sha(&original)));
        assert_eq!(fs::read(snapshot).unwrap(), original);
        restore_checked(&game, &LOCALIZATION, |_| {}).unwrap();
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"other graphics mod"
        );
    }

    #[test]
    fn legacy_mixed_split_resumes_after_video_first_interruption() {
        let (_root, game, original) = legacy_fixture();
        let views = legacy_views(&game, &TEST_LEGACY_VIDEO).unwrap().unwrap();
        let video_path = game.join(MANAGER).join(VIDEO.state_file);
        fs::write(
            &video_path,
            serde_json::to_vec_pretty(&views.video).unwrap(),
        )
        .unwrap();
        assert_eq!(
            inspect_component(&game, &TEST_LEGACY_VIDEO).unwrap().videos,
            1
        );
        let lock_guard = lock(&game).unwrap();
        migrate_legacy_state(&game, &TEST_LEGACY_VIDEO).unwrap();
        let local_path = game.join(MANAGER).join(LOCALIZATION.state_file);
        let local_before = fs::read(&local_path).unwrap();
        let video_before = fs::read(&video_path).unwrap();
        migrate_legacy_state(&game, &TEST_LEGACY_VIDEO).unwrap();
        assert_eq!(fs::read(&local_path).unwrap(), local_before);
        assert_eq!(fs::read(&video_path).unwrap(), video_before);
        let snapshot = game
            .join(MANAGER)
            .join(format!("assets-state.legacy-{}.json", sha(&original)));
        assert_eq!(fs::read(snapshot).unwrap(), original);
        drop(lock_guard);
        restore_checked(&game, &LOCALIZATION, |_| {}).unwrap();
        assert_eq!(
            inspect_component(&game, &TEST_LEGACY_VIDEO).unwrap().videos,
            1
        );
        assert_eq!(inspect_component(&game, &LOCALIZATION).unwrap().files, 0);
        restore_checked(&game, &TEST_LEGACY_VIDEO, |_| {}).unwrap();
        assert_eq!(fs::read(game.join("intro.bik")).unwrap(), LEGACY_ORIGINAL);
    }

    #[test]
    fn legacy_mixed_conflicting_video_journal_is_preserved() {
        let (_root, game, original) = legacy_fixture();
        let mut video = legacy_views(&game, &TEST_LEGACY_VIDEO)
            .unwrap()
            .unwrap()
            .video;
        video.phase = "restored".into();
        let video_path = game.join(MANAGER).join(VIDEO.state_file);
        let bytes = serde_json::to_vec_pretty(&video).unwrap();
        fs::write(&video_path, &bytes).unwrap();
        assert!(
            migrate_legacy_state(&game, &TEST_LEGACY_VIDEO)
                .unwrap_err()
                .contains("divergentes")
        );
        assert_eq!(fs::read(video_path).unwrap(), bytes);
        assert_eq!(
            fs::read(game.join(MANAGER).join(LOCALIZATION.state_file)).unwrap(),
            original
        );
    }

    #[test]
    fn legacy_mixed_modified_video_and_invalid_backup_refuse_migration() {
        for damage_backup in [false, true] {
            let (root, game, original) = legacy_fixture();
            let target = if damage_backup {
                root.path().join("backup/intro.bik.original")
            } else {
                game.join("intro.bik")
            };
            fs::write(&target, b"changed by another mod").unwrap();
            let error = migrate_legacy_state(&game, &TEST_LEGACY_VIDEO).unwrap_err();
            assert!(error.contains(if damage_backup { "Backup" } else { "mudou" }));
            assert_eq!(fs::read(&target).unwrap(), b"changed by another mod");
            assert_eq!(
                fs::read(game.join(MANAGER).join(LOCALIZATION.state_file)).unwrap(),
                original
            );
            assert!(!game.join(MANAGER).join(VIDEO.state_file).exists());
        }
    }

    #[test]
    fn legacy_mixed_unknown_and_duplicate_entries_are_refused() {
        for duplicate in [false, true] {
            let (_root, game, original) = legacy_fixture();
            let mut state: State = serde_json::from_slice(&original).unwrap();
            let mut entry = state.assets.last().unwrap().clone();
            if !duplicate {
                entry.file = "../foreign.bik".into();
            }
            state.assets.push(entry);
            let bytes = serde_json::to_vec_pretty(&state).unwrap();
            let path = game.join(MANAGER).join(LOCALIZATION.state_file);
            fs::write(&path, &bytes).unwrap();
            assert!(migrate_legacy_state(&game, &TEST_LEGACY_VIDEO).is_err());
            assert_eq!(fs::read(&path).unwrap(), bytes);
            assert!(!game.join(MANAGER).join(VIDEO.state_file).exists());
        }
    }

    #[test]
    fn legacy_mixed_snapshot_collision_and_operation_lock_are_preserved() {
        let (_root, game, original) = legacy_fixture();
        let guard = lock(&game).unwrap();
        assert!(
            restore_checked(&game, &TEST_LEGACY_VIDEO, |_| {})
                .unwrap_err()
                .contains("Outra instalação")
        );
        drop(guard);
        let snapshot = game
            .join(MANAGER)
            .join(format!("assets-state.legacy-{}.json", sha(&original)));
        fs::write(&snapshot, b"foreign snapshot").unwrap();
        assert!(
            migrate_legacy_state(&game, &TEST_LEGACY_VIDEO)
                .unwrap_err()
                .contains("preexistente diferente")
        );
        assert_eq!(fs::read(snapshot).unwrap(), b"foreign snapshot");
        assert_eq!(
            fs::read(game.join(MANAGER).join(LOCALIZATION.state_file)).unwrap(),
            original
        );
        assert!(!game.join(MANAGER).join(VIDEO.state_file).exists());
    }

    #[test]
    fn localization_and_video_use_independent_journals_and_restore_independently() {
        let (root, game, localization_manifest, backups) = fixture();
        let video_payload = b"translated video fixture";
        fs::write(root.path().join("video.bik"), video_payload).unwrap();
        let video_manifest = root.path().join("video.json");
        fs::write(
            &video_manifest,
            serde_json::to_vec(&AssetPackage {
                schema: 1,
                assets: vec![Asset {
                    file: "intro.bik".into(),
                    source_sha256: None,
                    result_sha256: sha(video_payload),
                    payload: "video.bik".into(),
                }],
            })
            .unwrap(),
        )
        .unwrap();

        assert_ne!(LOCALIZATION.state_file, VIDEO.state_file);
        apply_checked(
            &game,
            &LOCALIZATION,
            &localization_manifest,
            &backups,
            |_| {},
        )
        .unwrap();
        apply_checked(&game, &TEST_VIDEO, &video_manifest, &backups, |_| {}).unwrap();

        let manager = game.join(MANAGER);
        assert!(manager.join(LOCALIZATION.state_file).is_file());
        assert!(manager.join(VIDEO.state_file).is_file());
        assert!(inspect_component(&game, &LOCALIZATION).unwrap().subtitles);
        assert_eq!(inspect_component(&game, &TEST_VIDEO).unwrap().videos, 1);

        restore_checked(&game, &TEST_VIDEO, |_| {}).unwrap();
        assert!(!game.join("intro.bik").exists());
        assert!(inspect_component(&game, &LOCALIZATION).unwrap().subtitles);
        assert!(manager.join(LOCALIZATION.state_file).is_file());

        apply_checked(&game, &TEST_VIDEO, &video_manifest, &backups, |_| {}).unwrap();
        restore_checked(&game, &LOCALIZATION, |_| {}).unwrap();
        assert_eq!(inspect_component(&game, &TEST_VIDEO).unwrap().videos, 1);
        assert!(manager.join(VIDEO.state_file).is_file());
        restore_checked(&game, &TEST_VIDEO, |_| {}).unwrap();
        assert_eq!(inspect_component(&game, &LOCALIZATION).unwrap().files, 0);
    }

    #[test]
    fn new_files_conflicts_and_restore_preserve_save_and_other_mods() {
        let (_root, game, manifest, backups) = fixture();
        fs::write(game.join("DINPUT.dll"), b"foreign input mod").unwrap();
        assert!(
            apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {})
                .unwrap_err()
                .contains("preexistente")
        );
        assert_eq!(
            fs::read(game.join("DINPUT.dll")).unwrap(),
            b"foreign input mod"
        );
        fs::remove_file(game.join("DINPUT.dll")).unwrap(); // Fixture only.
        let result = apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {}).unwrap();
        assert!(result.subtitles);
        assert_eq!(result.files, 2);
        apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {}).unwrap();
        let target = game.join(MANAGER).join("subtitles.tsv");
        fs::write(&target, b"subsequent mod").unwrap();
        assert!(
            restore_checked(&game, &LOCALIZATION, |_| {})
                .unwrap_err()
                .contains("Conflito")
        );
        assert_eq!(
            fs::read(game.join("DINPUT.dll")).unwrap(),
            b"subtitle proxy"
        );
        assert_eq!(fs::read(&target).unwrap(), b"subsequent mod");
        fs::write(&target, b"154\tVoce renasceu.\n").unwrap();
        assert_eq!(
            restore_checked(&game, &LOCALIZATION, |_| {}).unwrap().files,
            0
        );
        assert!(!target.exists());
        assert!(!game.join("DINPUT.dll").exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"other graphics mod"
        );
    }

    #[test]
    fn interrupted_upgrade_can_restore_previous_owned_proxy() {
        let (_root, game, manifest, backups) = fixture();
        apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {}).unwrap();
        let mut state = load_state(&game, &LOCALIZATION).unwrap();
        let old_hash = state.assets[0].result_sha256.clone();
        state.assets[0].previous_sha256 = Some(old_hash);
        state.assets[0].result_sha256 = sha(b"next proxy, not yet written");
        state.phase = "preparing".into();
        save(&game, &LOCALIZATION, &state).unwrap();
        // Simulate interruption before the proxy replacement, then during restore.
        state.phase = "restoring".into();
        save(&game, &LOCALIZATION, &state).unwrap();
        assert_eq!(
            restore_checked(&game, &LOCALIZATION, |_| {}).unwrap().files,
            0
        );
        assert!(!game.join("DINPUT.dll").exists());
    }

    #[test]
    fn payload_traversal_and_shared_lock_are_refused() {
        let (_root, game, manifest, backups) = fixture();
        let held = lock(&game).unwrap();
        assert!(
            apply_checked(&game, &LOCALIZATION, &manifest, &backups, |_| {})
                .unwrap_err()
                .contains("andamento")
        );
        drop(held);
        let mut data: AssetPackage = serde_json::from_slice(&fs::read(&manifest).unwrap()).unwrap();
        data.assets[0].payload = "../proxy.dll".into();
        fs::write(&manifest, serde_json::to_vec(&data).unwrap()).unwrap();
        assert!(
            package(&LOCALIZATION, &manifest)
                .err()
                .unwrap()
                .contains("caminho")
        );
        assert!(!game.join("DINPUT.dll").exists());
    }
}
