use super::*;
use crate::{fsx::plain, is_game_running};
use std::io::Read;
use tempfile::tempdir;

fn make_exe(table_entries: &[(u32, u32)]) -> Vec<u8> {
    let mut exe = vec![0u8; TABLE + COUNT * 8 + 64];
    for (i, &(offset, length)) in table_entries.iter().enumerate() {
        let pos = TABLE + i * 8;
        exe[pos..pos + 4].copy_from_slice(&offset.to_le_bytes());
        exe[pos + 4..pos + 8].copy_from_slice(&length.to_le_bytes());
    }
    exe
}

#[test]
fn test_slots_valid() {
    let entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    let exe = make_exe(&entries);
    let total_bytes = COUNT * 2;
    let res = slots(&exe, total_bytes).expect("valid slots");
    assert_eq!(res.len(), COUNT);
    assert_eq!(res[0], (0, 2));
    assert_eq!(res[COUNT - 1], ((COUNT - 1) * 2, 2));
}

#[test]
fn test_slots_invalid_cursor_gap() {
    let mut entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    entries[5].0 = 12; // gap
    let exe = make_exe(&entries);
    let err = slots(&exe, COUNT * 2).unwrap_err();
    assert_eq!(err, "Tabela de vozes inválida.");
}

#[test]
fn test_slots_zero_length() {
    let mut entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    entries[3].1 = 0;
    let exe = make_exe(&entries);
    let err = slots(&exe, COUNT * 2).unwrap_err();
    assert_eq!(err, "Tabela de vozes inválida.");
}

#[test]
fn test_slots_odd_length() {
    let mut entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    entries[2].1 = 3; // odd
    let exe = make_exe(&entries);
    let err = slots(&exe, COUNT * 2).unwrap_err();
    assert_eq!(err, "Tabela de vozes inválida.");
}

#[test]
fn test_slots_incomplete_coverage() {
    let entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    let exe = make_exe(&entries);
    let err = slots(&exe, COUNT * 2 + 10).unwrap_err();
    assert_eq!(err, "Tabela não cobre todo o arquivo de vozes.");
}

#[test]
fn test_slots_truncated_exe() {
    let exe = vec![0u8; 100];
    let err = slots(&exe, 100).unwrap_err();
    assert_eq!(err, "Executável sem tabela de vozes.");
}

#[test]
fn test_plain_and_read_and_atomic_write() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("test.bin");
    assert!(plain(dir.path()).is_ok());

    atomic_write(&path, b"hello atomic").unwrap();
    assert!(plain(&path).is_ok());

    let content = read(&path, 1024).unwrap();
    assert_eq!(content, b"hello atomic");

    let err = read(&path, 5).unwrap_err();
    assert_eq!(err, "Arquivo excede o limite permitido.");
}

#[test]
fn test_inspect_apply_and_restore_cycle() {
    let dir = tempdir().unwrap();
    let game_dir = dir.path().join("game");
    fs::create_dir(&game_dir).unwrap();

    let entry_len = 4usize;
    let total_bytes = COUNT * entry_len;
    let entries: Vec<(u32, u32)> = (0..COUNT)
        .map(|i| ((i * entry_len) as u32, entry_len as u32))
        .collect();
    let exe_data = make_exe(&entries);
    let original_voices = vec![0x11u8; total_bytes];

    let exe_hash = sha(&exe_data);
    let voices_hash = sha(&original_voices);

    fs::write(game_dir.join("kain2.exe"), &exe_data).unwrap();
    fs::write(game_dir.join("voices.dat"), &original_voices).unwrap();
    let shared = game_dir.join(MANAGER);
    fs::create_dir(&shared).unwrap();
    let asset_journal = serde_json::to_vec(&serde_json::json!({
        "schema": 1, "game": game_dir, "phase": "original", "assets": []
    }))
    .unwrap();
    fs::write(shared.join("assets-state.json"), &asset_journal).unwrap();

    let policy = Policy {
        exe: &exe_hash,
        voices: &voices_hash,
    };

    // 1. Inspect clean game
    let info = inspect_with(&game_dir, &policy).unwrap();
    assert_eq!(info.status, "original");
    assert_eq!(info.replaced, 0);
    assert_eq!(info.total, COUNT);

    // 2. Prepare patch package
    let patch_dir = dir.path().join("package");
    fs::create_dir(&patch_dir).unwrap();
    let patch_payload = vec![0x99u8; entry_len];
    let patch_payload_hash = sha(&patch_payload);
    fs::write(patch_dir.join("voice-0005.pcm"), &patch_payload).unwrap();

    let mut patched_voices = original_voices.clone();
    let offset_5 = 5 * entry_len;
    patched_voices[offset_5..offset_5 + entry_len].copy_from_slice(&patch_payload);
    let patched_hash = sha(&patched_voices);

    let manifest = Manifest {
        schema: 1,
        id: "sr1-ptbr-review".into(),
        name: "Test Package".into(),
        version: "0.1.0".into(),
        exe_sha256: exe_hash.clone(),
        source_sha256: voices_hash.clone(),
        result_sha256: patched_hash.clone(),
        patches: vec![Patch {
            id: 5,
            file: "voice-0005.pcm".into(),
            sha256: patch_payload_hash,
            length: entry_len,
        }],
        coverage: Coverage {
            replaced: 1,
            total: COUNT,
            complete: false,
        },
    };
    let manifest_path = patch_dir.join("manifest.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    // 3. Inspect package
    let (parsed_manifest, payloads, _) = package(&manifest_path, &policy).unwrap();
    assert_eq!(parsed_manifest.patches.len(), 1);
    assert_eq!(payloads.len(), 1);

    // 4. Apply package
    let mut progress_steps = Vec::new();
    let apply_info = apply_with(&game_dir, &manifest_path, &policy, |msg| {
        progress_steps.push(msg.to_string())
    })
    .unwrap();
    assert_eq!(apply_info.status, "installed");
    assert_eq!(apply_info.replaced, 1);
    assert_eq!(
        sha(&fs::read(game_dir.join("voices.dat")).unwrap()),
        patched_hash
    );
    assert!(!progress_steps.is_empty());

    // 5. Inspect installed game
    let inspected = inspect_with(&game_dir, &policy).unwrap();
    assert_eq!(inspected.status, "installed");
    assert_eq!(inspected.replaced, 1);

    // 6. Re-apply (idempotent)
    let reapply = apply_with(&game_dir, &manifest_path, &policy, |_| {}).unwrap();
    assert_eq!(reapply.status, "installed");

    // 7. Restore original
    let mut restore_steps = Vec::new();
    let restore_info = restore_with(&game_dir, &policy, |msg| {
        restore_steps.push(msg.to_string())
    })
    .unwrap();
    assert_eq!(restore_info.status, "original");
    assert_eq!(restore_info.replaced, 0);
    assert_eq!(
        sha(&fs::read(game_dir.join("voices.dat")).unwrap()),
        voices_hash
    );
    assert!(!restore_steps.is_empty());
    assert_eq!(
        fs::read(shared.join("assets-state.json")).unwrap(),
        asset_journal
    );
}

#[test]
fn test_inspect_rejects_foreign_mod() {
    let dir = tempdir().unwrap();
    let game_dir = dir.path().join("game");
    fs::create_dir(&game_dir).unwrap();

    let entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    let exe_data = make_exe(&entries);
    let voices_data = vec![0x11u8; COUNT * 2];

    let exe_hash = sha(&exe_data);
    let voices_hash = sha(&voices_data);

    fs::write(game_dir.join("kain2.exe"), &exe_data).unwrap();
    // Tampered voices
    let mut tampered = voices_data.clone();
    tampered[0] = 0x99;
    fs::write(game_dir.join("voices.dat"), &tampered).unwrap();

    let policy = Policy {
        exe: &exe_hash,
        voices: &voices_hash,
    };
    let err = inspect_with(&game_dir, &policy).unwrap_err();
    assert!(err.contains("modificado por outro processo"));
}

#[test]
fn test_inspect_rejects_wrong_exe() {
    let dir = tempdir().unwrap();
    let game_dir = dir.path().join("game");
    fs::create_dir(&game_dir).unwrap();

    let entries: Vec<(u32, u32)> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    let exe_data = make_exe(&entries);
    let voices_data = vec![0x11u8; COUNT * 2];

    fs::write(game_dir.join("kain2.exe"), &exe_data).unwrap();
    fs::write(game_dir.join("voices.dat"), &voices_data).unwrap();

    let policy = Policy {
        exe: "wronghash",
        voices: "wronghash",
    };
    let err = inspect_with(&game_dir, &policy).unwrap_err();
    assert!(err.contains("Edição não suportada"));
}

#[test]
fn test_real_pilot_package_on_isolated_fixture() {
    // Read-only use of the original installation for hash validation. Never writes
    // to Steam and never launches the game. Override with SRMOD_STEAM_GAME.
    let steam_dir = std::env::var_os("SRMOD_STEAM_GAME")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(r"D:\SteamLibrary\steamapps\common\Legacy of Kain Soul Reaver")
        });
    let steam_dir = steam_dir.as_path();
    if !steam_dir.join("kain2.exe").exists() || !steam_dir.join("voices.dat").exists() {
        return;
    }
    let manifest_path = Path::new(
        r"D:\Solutions\pessoal\soul-reaver-ptbr-mod\staging\packages\raziel-pilot-v1\manifest.json",
    );
    if !manifest_path.exists() {
        return;
    }

    let dir = tempdir().unwrap();
    let game_dir = dir.path().join("game");
    fs::create_dir(&game_dir).unwrap();

    fs::copy(steam_dir.join("kain2.exe"), game_dir.join("kain2.exe")).unwrap();
    let original = steam_dir.join(".soul-reaver-ptbr/voices.original.dat");
    let source = if original.exists() {
        original
    } else {
        steam_dir.join("voices.dat")
    };
    fs::copy(source, game_dir.join("voices.dat")).unwrap();

    // 1. Inspect clean game
    let clean_info = inspect_game(&game_dir).expect("inspect clean game");
    assert_eq!(clean_info.status, "original");
    assert_eq!(clean_info.replaced, 0);
    assert_eq!(clean_info.total, COUNT);

    // 2. Inspect package
    let pkg_info = inspect_package(manifest_path).expect("inspect pilot package");
    assert_eq!(pkg_info.name, "Dublagem PT-BR — piloto");
    assert_eq!(pkg_info.replaced, 1);
    assert_eq!(pkg_info.total, COUNT);
    assert_eq!(pkg_info.bytes, 279842);

    // 3. Apply pilot
    let mut apply_log = Vec::new();
    let applied_info = apply_package(&game_dir, manifest_path, |msg| {
        apply_log.push(msg.to_string())
    })
    .expect("apply pilot");
    assert_eq!(applied_info.status, "installed");
    assert_eq!(applied_info.replaced, 1);

    // Verify hash of voices.dat in game_dir
    let applied_bytes = fs::read(game_dir.join("voices.dat")).unwrap();
    assert_eq!(
        sha(&applied_bytes),
        "135a2342e7b4fc50ba07158c22bf5856599848c120f0ca0663b6423c36d77439"
    );

    // 4. Inspect installed game
    let installed_info = inspect_game(&game_dir).expect("inspect installed game");
    assert_eq!(installed_info.status, "installed");
    assert_eq!(installed_info.replaced, 1);

    // 5. Restore original
    let mut restore_log = Vec::new();
    let restored_info =
        restore_game(&game_dir, |msg| restore_log.push(msg.to_string())).expect("restore game");
    assert_eq!(restored_info.status, "original");
    assert_eq!(restored_info.replaced, 0);

    // Verify voices.dat hash is back to original
    let restored_bytes = fs::read(game_dir.join("voices.dat")).unwrap();
    assert_eq!(sha(&restored_bytes), VOICES_SHA256);
}

// A complete-looking manifest must never count unchanged English PCM as dubbing.
#[test]
fn test_rejects_original_audio_disguised_as_full_package() {
    let dir = tempdir().unwrap();
    let game = dir.path().join("game");
    let pack = dir.path().join("package");
    fs::create_dir(&game).unwrap();
    fs::create_dir(&pack).unwrap();
    let entries: Vec<_> = (0..COUNT).map(|i| ((i * 4) as u32, 4)).collect();
    let exe = make_exe(&entries);
    let original = vec![0x11; COUNT * 4];
    let exe_hash = sha(&exe);
    let source_hash = sha(&original);
    let policy = Policy {
        exe: &exe_hash,
        voices: &source_hash,
    };
    fs::write(game.join("kain2.exe"), exe).unwrap();
    fs::write(game.join("voices.dat"), &original).unwrap();
    let mut candidate = original.clone();
    candidate[0..4].fill(0x22);
    let patches = (0..COUNT)
        .map(|id| {
            let payload = &candidate[id * 4..id * 4 + 4];
            let file = format!("voice-{id:04}.pcm");
            fs::write(pack.join(&file), payload).unwrap();
            Patch {
                id,
                file,
                sha256: sha(payload),
                length: 4,
            }
        })
        .collect();
    let manifest = Manifest {
        schema: 1,
        id: "sr1-ptbr-full".into(),
        name: "Misleading complete package".into(),
        version: "1".into(),
        exe_sha256: exe_hash.clone(),
        source_sha256: source_hash.clone(),
        result_sha256: sha(&candidate),
        patches,
        coverage: Coverage {
            replaced: COUNT,
            total: COUNT,
            complete: true,
        },
    };
    let path = pack.join("manifest.json");
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    let err = apply_with(&game, &path, &policy, |_| {}).unwrap_err();
    assert!(err.contains("idêntica ao áudio original"), "{err}");
    assert_eq!(fs::read(game.join("voices.dat")).unwrap(), original);
    assert!(!game.join(MANAGER).exists());

    // Legacy journals may claim 479. Inspection must derive the real count.
    fs::create_dir(game.join(MANAGER)).unwrap();
    fs::write(game.join(MANAGER).join("voices.original.dat"), &original).unwrap();
    fs::write(game.join("voices.dat"), &candidate).unwrap();
    let legacy = Journal {
        schema: 1,
        phase: "installed".into(),
        original_sha256: source_hash.clone(),
        installed_sha256: sha(&candidate),
        manifest_sha256: sha(b"legacy"),
        replaced: COUNT,
    };
    fs::write(
        game.join(MANAGER).join("state.json"),
        serde_json::to_vec(&legacy).unwrap(),
    )
    .unwrap();
    assert_eq!(inspect_with(&game, &policy).unwrap().replaced, 1);
}

#[test]
fn test_real_legacy_full_package_is_not_dubbing() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../staging/packages/sr1-ptbr-full/manifest.json");
    if !path.exists() {
        return;
    }
    let error = inspect_package(&path).unwrap_err();
    assert!(error.contains("áudio inglês original"), "{error}");
}

fn safety_fixture(root: &Path) -> (PathBuf, PathBuf, Policy<'static>) {
    let game = root.join("game-safety");
    let package = root.join("package-safety");
    fs::create_dir(&game).unwrap();
    fs::create_dir(&package).unwrap();

    let entries: Vec<_> = (0..COUNT).map(|i| ((i * 2) as u32, 2u32)).collect();
    let exe = make_exe(&entries);
    let original = vec![0x11; COUNT * 2];
    let exe_hash = Box::leak(sha(&exe).into_boxed_str());
    let original_hash = Box::leak(sha(&original).into_boxed_str());
    fs::write(game.join("kain2.exe"), exe).unwrap();
    fs::write(game.join("voices.dat"), &original).unwrap();

    let payload = vec![0x99; 2];
    let mut candidate = original;
    candidate[10..12].copy_from_slice(&payload);
    fs::write(package.join("voice-0005.pcm"), &payload).unwrap();
    let manifest = Manifest {
        schema: 1,
        id: "sr1-ptbr-review".into(),
        name: "Safety fixture".into(),
        version: "1".into(),
        exe_sha256: exe_hash.to_string(),
        source_sha256: original_hash.to_string(),
        result_sha256: sha(&candidate),
        patches: vec![Patch {
            id: 5,
            file: "voice-0005.pcm".into(),
            sha256: sha(&payload),
            length: 2,
        }],
        coverage: Coverage {
            replaced: 1,
            total: COUNT,
            complete: false,
        },
    };
    fs::write(
        package.join("manifest.json"),
        serde_json::to_vec(&manifest).unwrap(),
    )
    .unwrap();
    (
        game,
        package.join("manifest.json"),
        Policy {
            exe: exe_hash,
            voices: original_hash,
        },
    )
}

#[test]
fn interrupted_preparing_restore_preserves_voice_original() {
    let root = tempdir().unwrap();
    let (game, manifest, policy) = safety_fixture(root.path());
    let original = fs::read(game.join("voices.dat")).unwrap();
    apply_with(&game, &manifest, &policy, |_| {}).unwrap();

    // Simulate a crash after the journal was committed but before voices.dat
    // was replaced: the installed hash is journaled, while the original remains.
    let mut journal = journal(&game, &policy).unwrap().unwrap();
    journal.phase = "preparing".into();
    let manager = Manager::open(&game, &policy).unwrap();
    manager.save(&journal).unwrap();
    fs::write(game.join("voices.dat"), &original).unwrap();
    drop(manager);

    let restored = restore_with(&game, &policy, |_| {}).unwrap();
    assert_eq!(restored.status, "original");
    assert_eq!(fs::read(game.join("voices.dat")).unwrap(), original);
}

#[test]
fn modified_voices_block_restore() {
    let root = tempdir().unwrap();
    let (game, manifest, policy) = safety_fixture(root.path());
    apply_with(&game, &manifest, &policy, |_| {}).unwrap();
    let mut modified = fs::read(game.join("voices.dat")).unwrap();
    modified[0] ^= 0xff;
    fs::write(game.join("voices.dat"), &modified).unwrap();

    let error = restore_with(&game, &policy, |_| {}).unwrap_err();
    assert!(error.contains("alterado após a instalação"), "{error}");
    assert_eq!(fs::read(game.join("voices.dat")).unwrap(), modified);
}

#[test]
fn structured_progress_percentage_is_bounded_and_meaningful() {
    assert_eq!(
        Progress {
            stage: "teste".into(),
            current: 0,
            total: 4,
            message: String::new()
        }
        .percent(),
        0
    );
    assert_eq!(
        Progress {
            stage: "teste".into(),
            current: 2,
            total: 4,
            message: String::new()
        }
        .percent(),
        50
    );
    assert_eq!(
        Progress {
            stage: "teste".into(),
            current: 9,
            total: 4,
            message: String::new()
        }
        .percent(),
        100
    );
    assert_eq!(
        Progress {
            stage: "teste".into(),
            current: 1,
            total: 0,
            message: String::new()
        }
        .percent(),
        0
    );
}

#[test]
fn cancellation_at_atomic_voice_boundary_keeps_file_intact_and_journal_repairable() {
    let root = tempdir().unwrap();
    let (game, manifest, policy) = safety_fixture(root.path());
    let original = fs::read(game.join("voices.dat")).unwrap();
    let control = OperationControl::default();
    let result = apply_with_control(&game, &manifest, &policy, &control, |progress| {
        if progress.stage == "instalacao" {
            control.cancel();
        }
    });

    let error = result.unwrap_err();
    assert!(error.contains("cancelada"), "{error}");
    assert_eq!(fs::read(game.join("voices.dat")).unwrap(), original);
    assert_eq!(journal(&game, &policy).unwrap().unwrap().phase, "preparing");

    let restored = restore_with(&game, &policy, |_| {}).unwrap();
    assert_eq!(restored.status, "original");
    assert_eq!(fs::read(game.join("voices.dat")).unwrap(), original);
}

#[test]
fn package_payload_hash_mismatch_is_refused_without_mutation() {
    let root = tempdir().unwrap();
    let (game, manifest, policy) = safety_fixture(root.path());
    fs::write(
        manifest.parent().unwrap().join("voice-0005.pcm"),
        b"tampered",
    )
    .unwrap();

    let error = apply_with(&game, &manifest, &policy, |_| {}).unwrap_err();
    assert!(error.contains("integridade"), "{error}");
    assert_eq!(
        fs::read(game.join("voices.dat")).unwrap(),
        vec![0x11; COUNT * 2]
    );
    assert!(!game.join(MANAGER).exists());
}

#[test]
fn test_synthetic_wait_child_target() {
    if std::env::var("SRMOD_SYNTHETIC_CHILD").is_err() {
        return;
    }
    let mut buf = [0u8; 1];
    let _ = std::io::stdin().read(&mut buf);
}

#[test]
fn test_is_game_running_synthetic_child() {
    let dir = tempdir().unwrap();
    let game = dir.path().join("game");
    fs::create_dir(&game).unwrap();
    let current_exe = std::env::current_exe().unwrap();
    let kain2_path = game.join("kain2.exe");
    fs::copy(&current_exe, &kain2_path).unwrap();

    assert!(!is_game_running(&game).unwrap());

    let mut child = std::process::Command::new(&kain2_path)
        .arg("test_synthetic_wait_child_target")
        .env("SRMOD_SYNTHETIC_CHILD", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap();

    let mut running = false;
    for _ in 0..20 {
        std::thread::sleep(std::time::Duration::from_millis(50));
        if is_game_running(&game).unwrap() {
            running = true;
            break;
        }
    }

    let _ = child.kill();
    let _ = child.wait();

    assert!(
        running,
        "is_game_running should return true when kain2.exe process is active"
    );

    let mut stopped = false;
    for _ in 0..20 {
        if !is_game_running(&game).unwrap() {
            stopped = true;
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    assert!(
        stopped,
        "is_game_running should return false after process termination"
    );
}

#[test]
#[ignore]
fn bench_is_game_running() {
    let dir = tempdir().unwrap();
    let game = dir.path().join("game");
    fs::create_dir(&game).unwrap();
    fs::write(game.join("kain2.exe"), b"fake kain2").unwrap();

    let iterations = 20;
    let start = std::time::Instant::now();
    for _ in 0..iterations {
        let _ = is_game_running(&game);
    }
    let elapsed = start.elapsed();
    let avg = elapsed / iterations;
    println!(
        "bench_is_game_running: total = {:?}, avg = {:?}",
        elapsed, avg
    );
}

#[cfg(windows)]
#[test]
fn managed_file_links_and_directory_junctions_are_refused_when_available() {
    use std::os::windows::fs::{symlink_dir, symlink_file};
    let root = tempdir().unwrap();
    let target = root.path().join("target");
    let target_dir = root.path().join("target-dir");
    fs::write(&target, b"target").unwrap();
    fs::create_dir(&target_dir).unwrap();

    let file_link = root.path().join("file-link");
    if symlink_file(&target, &file_link).is_ok() {
        assert!(plain(&file_link).unwrap_err().contains("Links"));
    }
    // A Windows directory symlink is a reparse point; on systems where the
    // test process lacks the required privilege, creation is not testable.
    let dir_link = root.path().join("directory-link");
    if symlink_dir(&target_dir, &dir_link).is_ok() {
        assert!(plain(&dir_link).unwrap_err().contains("Links"));
    }
}

/// A package with `count` single-slot patches over the safety fixture layout.
fn write_package(dir: &Path, policy: &Policy, count: usize) -> PathBuf {
    let mut candidate = vec![0x11u8; COUNT * 2];
    let patches = (0..count)
        .map(|id| {
            let payload = [0x80 + (id % 100) as u8, 0x22];
            let file = format!("voice-{id:04}.pcm");
            fs::write(dir.join(&file), payload).unwrap();
            candidate[id * 2..id * 2 + 2].copy_from_slice(&payload);
            Patch {
                id,
                file,
                sha256: sha(&payload),
                length: 2,
            }
        })
        .collect();
    let manifest = Manifest {
        schema: 1,
        id: "sr1-ptbr-review".into(),
        name: "Parallel fixture".into(),
        version: "1".into(),
        exe_sha256: policy.exe.into(),
        source_sha256: policy.voices.into(),
        result_sha256: sha(&candidate),
        patches,
        coverage: Coverage {
            replaced: count,
            total: COUNT,
            complete: count == COUNT,
        },
    };
    let path = dir.join("manifest.json");
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    path
}

#[test]
fn parallel_package_verification_reports_the_first_failure_in_manifest_order() {
    let root = tempdir().unwrap();
    let (game, _, policy) = safety_fixture(root.path());
    let dir = root.path().join("package-parallel");
    fs::create_dir(&dir).unwrap();
    let path = write_package(&dir, &policy, 64);
    let (_, payloads, _) = package(&path, &policy).unwrap();
    assert_eq!(payloads.len(), 64);
    assert_eq!(payloads[63], [0x80 + 63, 0x22]);

    // Two defects: the earlier entry decides the message, whichever worker saw it.
    let mut manifest: Manifest = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manifest.patches[60].file = "../voice-0060.pcm".into();
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    fs::write(dir.join("voice-0003.pcm"), b"xx").unwrap();
    let error = package(&path, &policy).err().unwrap();
    assert!(error.contains("integridade"), "{error}");

    fs::write(dir.join("voice-0003.pcm"), [0x83, 0x22]).unwrap();
    let error = package(&path, &policy).err().unwrap();
    assert!(error.contains("caminho de pacote não permitido"), "{error}");
    assert_eq!(
        fs::read(game.join("voices.dat")).unwrap(),
        vec![0x11; COUNT * 2]
    );
}

#[test]
fn apply_never_marks_installed_when_the_backup_does_not_verify() {
    let root = tempdir().unwrap();
    let (game, manifest, policy) = safety_fixture(root.path());
    let control = OperationControl::default();
    let backup = game.join(MANAGER).join("voices.original.dat");
    // The backup is damaged after it was written and before the final proof.
    let error = apply_with_control(&game, &manifest, &policy, &control, |progress| {
        if progress.stage == "instalacao" {
            fs::write(&backup, b"damaged backup").unwrap();
        }
    })
    .unwrap_err();
    assert!(error.contains("Conflito"), "{error}");
    assert_eq!(journal(&game, &policy).unwrap().unwrap().phase, "preparing");
}

#[test]
fn streamed_hash_matches_the_in_memory_hash_and_enforces_the_limit() {
    use crate::fsx::sha_file;
    let dir = tempdir().unwrap();
    let path = dir.path().join("archive.bin");
    let bytes = crate::test_support::noise(7, 3 * 1024 * 1024 + 17);
    fs::write(&path, &bytes).unwrap();
    assert_eq!(
        sha_file(&path, bytes.len() as u64).unwrap(),
        (sha(&bytes), bytes.len() as u64)
    );
    assert_eq!(
        sha_file(&path, bytes.len() as u64 - 1).unwrap_err(),
        "Arquivo excede o limite permitido."
    );
    fs::write(&path, b"").unwrap();
    assert_eq!(sha_file(&path, 16).unwrap(), (sha(b""), 0));
}

/// Full-size synthetic fixture: 479 slots covering exactly `VOICES_BYTES`.
/// Run with `cargo test --release -p soul-reaver-mod-core -- --ignored bench_ --nocapture --test-threads 1`.
#[test]
#[ignore = "benchmark: writes ~600 MB of temporary data"]
fn bench_voice_pipeline() {
    use crate::test_support::{best_ms, elapsed_ms, noise, peak_rss_mb};
    use std::time::Instant;

    let total = VOICES_BYTES as usize;
    let slot = (total / COUNT) & !1;
    let entries: Vec<(u32, u32)> = (0..COUNT)
        .map(|i| {
            let length = if i == COUNT - 1 {
                total - slot * (COUNT - 1)
            } else {
                slot
            };
            ((i * slot) as u32, length as u32)
        })
        .collect();
    let exe = make_exe(&entries);
    let original = noise(0x5eed, total);
    let exe_hash = sha(&exe);
    let voices_hash = sha(&original);
    let policy = Policy {
        exe: &exe_hash,
        voices: &voices_hash,
    };

    let dir = tempdir().unwrap();
    let game = dir.path().join("game");
    let pack = dir.path().join("package");
    fs::create_dir(&game).unwrap();
    fs::create_dir(&pack).unwrap();
    fs::write(game.join("kain2.exe"), &exe).unwrap();
    fs::write(game.join("voices.dat"), &original).unwrap();

    let mut patched = original.clone();
    let mut patches = Vec::new();
    for (id, &(offset, length)) in entries.iter().enumerate() {
        let payload = noise(0xd0b + id as u64, length as usize);
        let file = format!("voice-{id:04}.pcm");
        fs::write(pack.join(&file), &payload).unwrap();
        patched[offset as usize..(offset + length) as usize].copy_from_slice(&payload);
        patches.push(Patch {
            id,
            file,
            sha256: sha(&payload),
            length: length as usize,
        });
    }
    let manifest = Manifest {
        schema: 1,
        id: "sr1-ptbr-full".into(),
        name: "Benchmark".into(),
        version: "0.0.0".into(),
        exe_sha256: exe_hash.clone(),
        source_sha256: voices_hash.clone(),
        result_sha256: sha(&patched),
        patches,
        coverage: Coverage {
            replaced: COUNT,
            total: COUNT,
            complete: true,
        },
    };
    drop(patched);
    let manifest_path = pack.join("manifest.json");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let megabytes = total as f64 / 1_048_576.0;
    let hash_ms = best_ms(3, || {
        std::hint::black_box(sha(&original));
    });
    drop(original);
    println!(
        "BENCH sha256_throughput_mb_s {:.0}",
        megabytes / (hash_ms / 1000.0)
    );

    let inspect_original = best_ms(5, || {
        assert_eq!(inspect_with(&game, &policy).unwrap().status, "original");
    });
    println!("BENCH voices_inspect_original_ms {inspect_original:.0}");
    let package_ms = best_ms(5, || {
        package(&manifest_path, &policy).unwrap();
    });
    println!("BENCH voices_verify_package_ms {package_ms:.0}");

    let (mut apply_ms, mut restore_ms, mut inspect_installed) =
        (f64::INFINITY, f64::INFINITY, f64::INFINITY);
    let (mut apply_peak, mut inspect_peak, mut restore_peak) = (None, None, None);
    for _ in 0..3 {
        let start = Instant::now();
        let (info, peak) =
            peak_rss_mb(|| apply_with(&game, &manifest_path, &policy, |_| {}).unwrap());
        apply_ms = apply_ms.min(elapsed_ms(start));
        apply_peak = peak;
        assert_eq!((info.status.as_str(), info.replaced), ("installed", COUNT));
        let ((), peak) = peak_rss_mb(|| {
            inspect_installed = inspect_installed.min(best_ms(3, || {
                assert_eq!(inspect_with(&game, &policy).unwrap().replaced, COUNT);
            }));
        });
        inspect_peak = peak;
        let start = Instant::now();
        let (info, peak) = peak_rss_mb(|| restore_with(&game, &policy, |_| {}).unwrap());
        restore_ms = restore_ms.min(elapsed_ms(start));
        restore_peak = peak;
        assert_eq!(info.status, "original");
    }
    println!("BENCH voices_apply_full_package_ms {apply_ms:.0}");
    println!("BENCH voices_inspect_installed_ms {inspect_installed:.0}");
    println!("BENCH voices_restore_ms {restore_ms:.0}");
    for (name, peak) in [
        ("apply", apply_peak),
        ("inspect_installed", inspect_peak),
        ("restore", restore_peak),
    ] {
        if let Some(peak) = peak {
            println!("BENCH voices_{name}_peak_rss_mb {peak:.0}");
        }
    }
}
