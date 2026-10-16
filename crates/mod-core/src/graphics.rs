//! dgVoodoo2 4K wrapper and Hor+ 16:9 patch under their own ownership journal.
//!
//! Nothing here overwrites a file that this journal does not own, so a graphics
//! wrapper installed by another mod is always preserved. The widescreen patch
//! only rewrites the fixed field-of-view constant of the two supported
//! executables and keeps a byte-exact backup for restoration.
use super::*;

const STATE: &str = "graphics-state.json";
const EXE_BACKUP: &str = "kain2.graphics-original.exe";
const WRAPPER: [&str; 5] = [
    "DDraw.dll",
    "D3DImm.dll",
    "dgVoodoo.conf",
    "D3D8.dll",
    "D3D9.dll",
];
const LIMIT: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GraphicsInfo {
    pub installed: bool,
    pub widescreen: bool,
    pub files: usize,
    pub message: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Item {
    file: String,
    result_sha256: String,
    previous_sha256: Option<String>,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExeRecord {
    original_sha256: String,
    patched_sha256: String,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    schema: u32,
    game: PathBuf,
    phase: String,
    widescreen: bool,
    files: Vec<Item>,
    exe: Option<ExeRecord>,
}

fn ok_hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
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

fn game_path(game: &Path) -> Result<PathBuf> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let exe = sha(&read(&game.join("kain2.exe"), LIMIT)?);
    if exe != EXE_SHA256 && exe != EXE_WIDESCREEN_SHA256 {
        return Err("Executável incompatível com o perfil gráfico.".into());
    }
    Ok(game)
}

fn load(game: &Path) -> Result<State> {
    let path = game.join(MANAGER).join(STATE);
    if !path.exists() {
        return Ok(State {
            schema: 1,
            game: game.into(),
            phase: "original".into(),
            widescreen: false,
            files: vec![],
            exe: None,
        });
    }
    let state: State = serde_json::from_slice(&read(&path, 128 * 1024)?)
        .map_err(|e| format!("Registro gráfico inválido: {e}"))?;
    if state.schema != 1
        || io(state.game.canonicalize())? != game
        || !["original", "preparing", "installed", "restored"].contains(&state.phase.as_str())
        || state.files.iter().any(|i| {
            !WRAPPER.contains(&i.file.as_str())
                || !ok_hash(&i.result_sha256)
                || i.previous_sha256.as_ref().is_some_and(|h| !ok_hash(h))
        })
        || state
            .exe
            .as_ref()
            .is_some_and(|e| !ok_hash(&e.original_sha256) || !ok_hash(&e.patched_sha256))
    {
        return Err("Registro gráfico incompatível. Nada foi alterado.".into());
    }
    Ok(state)
}

fn save(game: &Path, state: &State) -> Result<()> {
    atomic_write(
        &game.join(MANAGER).join(STATE),
        &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
    )
}

pub fn inspect(game: &Path) -> Result<GraphicsInfo> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let state = load(&game)?;
    let mut installed = 0usize;
    for item in &state.files {
        let path = game.join(&item.file);
        if path.exists() && sha(&read(&path, LIMIT)?) == item.result_sha256 {
            installed += 1;
        }
    }
    let widescreen = match &state.exe {
        Some(record) => sha(&read(&game.join("kain2.exe"), LIMIT)?) == record.patched_sha256,
        None => false,
    };
    let active = installed > 0 || widescreen;
    let message = if active {
        format!(
            "Wrapper 4K aplicado ({installed} arquivo(s)){}.",
            if widescreen { " com Hor+ 16:9" } else { "" }
        )
    } else {
        "Perfil gráfico 4K não instalado.".into()
    };
    Ok(GraphicsInfo {
        installed: active,
        widescreen,
        files: installed,
        message,
    })
}

/// Install the wrapper files present in `source` and, when requested, patch the
/// executable to Hor+ 16:9. Refuses any unowned preexisting wrapper file.
pub fn apply(
    game: &Path,
    source: &Path,
    widescreen: bool,
    progress: impl FnMut(&str),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    apply_checked(&game, source, widescreen, progress)
}

pub fn apply_with_control(
    game: &Path,
    source: &Path,
    widescreen: bool,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    apply_checked_control(&game, source, widescreen, control, progress)
}

fn apply_checked(
    game: &Path,
    source: &Path,
    widescreen: bool,
    mut progress: impl FnMut(&str),
) -> Result<GraphicsInfo> {
    apply_checked_control(
        game,
        source,
        widescreen,
        &OperationControl::default(),
        |p| progress(&p.message),
    )
}

fn apply_checked_control(
    game: &Path,
    source: &Path,
    widescreen: bool,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let _lock = lock(game)?;
    ensure_closed(game)?;
    let source = io(source.canonicalize())?;
    chain(&source)?;
    let mut state = load(game)?;

    // Collect the wrapper files the package actually provides.
    let mut plan: Vec<(String, Vec<u8>)> = Vec::new();
    for name in WRAPPER {
        let path = source.join(name);
        if path.is_file() {
            plan.push((name.to_string(), read(&path, LIMIT)?));
        }
    }
    if plan.is_empty() {
        return Err("Pacote gráfico sem arquivos DDraw/D3DImm/dgVoodoo.".into());
    }

    // Conflict check before any mutation: the target must be absent or already
    // owned by this journal with the same result.
    for (name, bytes) in &plan {
        let target = game.join(name);
        let owned = state
            .files
            .iter()
            .any(|i| i.file == *name && i.result_sha256 == sha(bytes));
        if target.exists() {
            plain(&target)?;
            let current = sha(&read(&target, LIMIT)?);
            if !owned || current != sha(bytes) {
                return Err(format!(
                    "Arquivo gráfico preexistente sem propriedade comprovada: {name}. Preservado."
                ));
            }
        }
    }

    state.files = plan
        .iter()
        .map(|(name, bytes)| Item {
            file: name.clone(),
            result_sha256: sha(bytes),
            previous_sha256: None,
        })
        .collect();
    state.phase = "preparing".into();
    save(game, &state)?;
    let total = plan.len() + usize::from(widescreen || state.exe.is_some());
    for (index, (name, bytes)) in plan.iter().enumerate() {
        control.checkpoint()?;
        progress(Progress {
            stage: "graficos".into(),
            current: index,
            total,
            message: format!("Instalando {name}"),
        });
        ensure_closed(game)?;
        atomic_write(&game.join(name), bytes)?;
        progress(Progress {
            stage: "graficos".into(),
            current: index + 1,
            total,
            message: format!("Arquivo instalado: {name}"),
        });
    }

    // Widescreen patch: only touch the executable when the profile asks for it
    // or a previous record has to be undone.
    let exe_path = game.join("kain2.exe");
    let backup_path = game.join(MANAGER).join(EXE_BACKUP);
    let mut record = state.exe.clone().unwrap_or(ExeRecord {
        original_sha256: String::new(),
        patched_sha256: String::new(),
    });
    if widescreen {
        control.checkpoint()?;
        let current_exe = read(&exe_path, LIMIT)?;
        if record.original_sha256.is_empty() {
            if sha(&current_exe) == EXE_SHA256 {
                record.original_sha256 = EXE_SHA256.into();
                atomic_write(&backup_path, &current_exe)?;
            } else {
                return Err("Executável incompatível para o patch widescreen.".into());
            }
        }
        let mut patched = read(&exe_path, LIMIT)?;
        if patched.len() > FOV_OFFSET + 4 && patched[FOV_OFFSET..FOV_OFFSET + 4] == FOV_ORIGINAL {
            patched[FOV_OFFSET..FOV_OFFSET + 4].copy_from_slice(&FOV_16_9);
            record.patched_sha256 = sha(&patched);
            state.exe = Some(record.clone());
            state.widescreen = true;
            save(game, &state)?;
            control.checkpoint()?;
            progress(Progress {
                stage: "graficos".into(),
                current: plan.len(),
                total,
                message: "Aplicando patch de aspect ratio Hor+ 16:9...".into(),
            });
            atomic_write(&exe_path, &patched)?;
        } else if patched[FOV_OFFSET..FOV_OFFSET + 4] != FOV_16_9 {
            return Err("Offset de FOV inesperado; patch widescreen não aplicado.".into());
        }
        record.patched_sha256 = sha(&read(&exe_path, LIMIT)?);
    } else {
        if backup_path.exists() {
            let original = read(&backup_path, LIMIT)?;
            if sha(&original) != EXE_SHA256 {
                return Err("Backup do executável alterado.".into());
            }
            control.checkpoint()?;
            atomic_write(&exe_path, &original)?;
            io(fs::remove_file(&backup_path))?;
        }
        record = ExeRecord {
            original_sha256: String::new(),
            patched_sha256: String::new(),
        };
    }

    state.files = plan
        .iter()
        .map(|(name, bytes)| Item {
            file: name.clone(),
            result_sha256: sha(bytes),
            previous_sha256: None,
        })
        .collect();
    state.widescreen = widescreen;
    state.exe = if record.patched_sha256.is_empty() && record.original_sha256.is_empty() {
        None
    } else {
        Some(record)
    };
    state.phase = "installed".into();
    save(game, &state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: total,
        total,
        message: "Configuração 4K concluída.".into(),
    });
    inspect(game)
}

pub fn restore(game: &Path, progress: impl FnMut(&str)) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    restore_checked(&game, progress)
}

pub fn restore_with_control(
    game: &Path,
    control: &OperationControl,
    progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let game = game_path(game)?;
    restore_checked_control(&game, control, progress)
}

fn restore_checked(game: &Path, mut progress: impl FnMut(&str)) -> Result<GraphicsInfo> {
    restore_checked_control(game, &OperationControl::default(), |p| progress(&p.message))
}

fn restore_checked_control(
    game: &Path,
    control: &OperationControl,
    mut progress: impl FnMut(Progress),
) -> Result<GraphicsInfo> {
    let _lock = lock(game)?;
    ensure_closed(game)?;
    let mut state = load(game)?;

    // Conflict check before any mutation: the journal only removes files it still
    // owns. A file or executable changed after installation blocks the restore
    // instead of being silently orphaned.
    for item in &state.files {
        let target = game.join(&item.file);
        if target.exists() && sha(&read(&target, LIMIT)?) != item.result_sha256 {
            return Err(format!(
                "Conflito: {} mudou após a instalação; preservado.",
                item.file
            ));
        }
    }
    if let Some(record) = &state.exe {
        let current = sha(&read(&game.join("kain2.exe"), LIMIT)?);
        if current != record.patched_sha256
            && current != EXE_SHA256
            && current != EXE_WIDESCREEN_SHA256
        {
            return Err("Conflito: kain2.exe mudou após a instalação; preservado.".into());
        }
    }

    // Restore the executable before removing wrapper files.
    let total = state.files.len() + usize::from(state.exe.is_some());
    let mut progress_current = 0;
    if let Some(record) = state.exe.clone() {
        let backup_path = game.join(MANAGER).join(EXE_BACKUP);
        let current = sha(&read(&game.join("kain2.exe"), LIMIT)?);
        if backup_path.exists()
            && (current == record.patched_sha256
                || current == EXE_SHA256
                || current == EXE_WIDESCREEN_SHA256)
        {
            let original = read(&backup_path, LIMIT)?;
            if sha(&original) != EXE_SHA256 {
                return Err("Backup do executável alterado; restauração bloqueada.".into());
            }
            if current != EXE_SHA256 {
                control.checkpoint()?;
                progress(Progress {
                    stage: "restauracao-graficos".into(),
                    current: progress_current,
                    total,
                    message: "Restaurando executável original...".into(),
                });
                atomic_write(&game.join("kain2.exe"), &original)?;
            }
            io(fs::remove_file(&backup_path))?;
        }
        progress_current += 1;
    }

    // Every remaining owned file matched its installed hash above.
    for item in &state.files {
        let target = game.join(&item.file);
        if !target.exists() {
            continue;
        }
        control.checkpoint()?;
        progress(Progress {
            stage: "restauracao-graficos".into(),
            current: progress_current,
            total,
            message: format!("Removendo {}", item.file),
        });
        io(fs::remove_file(&target))?;
        progress_current += 1;
        progress(Progress {
            stage: "restauracao-graficos".into(),
            current: progress_current,
            total,
            message: format!("Removido {}", item.file),
        });
    }
    state.files.clear();
    state.exe = None;
    state.widescreen = false;
    state.phase = "restored".into();
    save(game, &state)?;
    progress(Progress {
        stage: "concluido".into(),
        current: total,
        total,
        message: "Gráficos restaurados ao original.".into(),
    });
    inspect(game)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (tempfile::TempDir, PathBuf, PathBuf) {
        let root = tempfile::tempdir().unwrap();
        let game = root.path().join("game");
        let source = root.path().join("graphics");
        fs::create_dir(&game).unwrap();
        fs::create_dir(&source).unwrap();
        fs::write(game.join("kain2.exe"), b"fixture executable, never started").unwrap();
        fs::write(game.join("savegame.her"), b"user save").unwrap();
        fs::write(source.join("DDraw.dll"), b"dgvoodoo ddraw wrapper").unwrap();
        fs::write(source.join("D3DImm.dll"), b"dgvoodoo d3dimm wrapper").unwrap();
        fs::write(source.join("dgVoodoo.conf"), b"resolution = 3840x2160").unwrap();
        let game = game.canonicalize().unwrap();
        (root, game, source)
    }

    #[test]
    fn wrapper_apply_and_restore_preserve_save() {
        let (_root, game, source) = fixture();
        let info = apply_checked(&game, &source, false, |_| {}).unwrap();
        assert_eq!(info.files, 3);
        assert!(info.installed);
        assert!(!info.widescreen);
        assert!(game.join("DDraw.dll").exists());
        let restored = restore_checked(&game, |_| {}).unwrap();
        assert_eq!(restored.files, 0);
        assert!(!game.join("DDraw.dll").exists());
        assert!(!game.join("dgVoodoo.conf").exists());
        assert_eq!(fs::read(game.join("savegame.her")).unwrap(), b"user save");
    }

    #[test]
    fn applying_the_same_wrapper_package_twice_is_idempotent() {
        let (_root, game, source) = fixture();
        let first = apply_checked(&game, &source, false, |_| {}).unwrap();
        let first_state = fs::read(game.join(MANAGER).join(STATE)).unwrap();
        let second = apply_checked(&game, &source, false, |_| {}).unwrap();

        assert_eq!(first.files, second.files);
        assert!(second.installed);
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"dgvoodoo ddraw wrapper"
        );
        assert_eq!(
            fs::read(game.join(MANAGER).join(STATE)).unwrap(),
            first_state
        );
    }

    #[test]
    fn foreign_wrapper_is_preserved() {
        let (_root, game, source) = fixture();
        fs::write(game.join("DDraw.dll"), b"another graphics mod").unwrap();
        assert!(
            apply_checked(&game, &source, false, |_| {})
                .unwrap_err()
                .contains("preexistente")
        );
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"another graphics mod"
        );
    }

    #[test]
    fn modified_owned_wrapper_blocks_restore_and_is_preserved() {
        let (_root, game, source) = fixture();
        apply_checked(&game, &source, false, |_| {}).unwrap();
        fs::write(game.join("DDraw.dll"), b"changed after install").unwrap();
        let error = restore_checked(&game, |_| {}).unwrap_err();
        assert!(error.contains("Conflito"), "erro inesperado: {error}");
        // The modified file is preserved and the journal keeps ownership.
        assert_eq!(
            fs::read(game.join("DDraw.dll")).unwrap(),
            b"changed after install"
        );
        assert_eq!(load(&game).unwrap().files.len(), 3);
        // Putting the file back to the installed bytes allows the restore.
        fs::write(game.join("DDraw.dll"), b"dgvoodoo ddraw wrapper").unwrap();
        assert_eq!(restore_checked(&game, |_| {}).unwrap().files, 0);
        assert!(!game.join("DDraw.dll").exists());
    }
}
