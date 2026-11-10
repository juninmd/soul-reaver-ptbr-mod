//! Guarded filesystem and integrity primitives shared by every component.
//!
//! Nothing here knows about voices, assets or graphics: the module only reads,
//! hashes, locks and atomically replaces files, refusing links and junctions on
//! the way so a managed path can never be redirected outside the installation.

use crate::{MANAGER, Result, is_supported_exe};
use fs2::FileExt;
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

/// Largest `kain2.exe` accepted before hashing.
pub(crate) const EXE_LIMIT: u64 = 4 * 1024 * 1024;
/// Journals are small JSON documents; anything larger is not ours.
pub(crate) const JOURNAL_LIMIT: u64 = 128 * 1024;
/// Streaming buffer: large enough to amortize syscalls, small enough to stay in cache.
const CHUNK: usize = 1024 * 1024;

pub(crate) fn io<T>(value: std::io::Result<T>) -> Result<T> {
    value.map_err(|e| e.to_string())
}

fn hex(digest: impl AsRef<[u8]>) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let digest = digest.as_ref();
    let mut out = String::with_capacity(digest.len() * 2);
    for &byte in digest {
        out.push(DIGITS[usize::from(byte >> 4)] as char);
        out.push(DIGITS[usize::from(byte & 0x0f)] as char);
    }
    out
}

/// Lowercase hexadecimal SHA-256 of an in-memory buffer.
pub(crate) fn sha(data: &[u8]) -> String {
    hex(Sha256::digest(data))
}

/// True for a lowercase, 64-digit hexadecimal SHA-256.
pub(crate) fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// Refuses symbolic links and, on Windows, any reparse point (junctions included).
pub(crate) fn plain(path: &Path) -> Result<()> {
    let metadata = io(fs::symlink_metadata(path))?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err("Links e junctions não são aceitos nos arquivos gerenciados.".into());
        }
    }
    if metadata.file_type().is_symlink() {
        return Err("Links não são aceitos nos arquivos gerenciados.".into());
    }
    Ok(())
}

/// Applies [`plain`] to every existing ancestor of `path`.
pub(crate) fn chain(path: &Path) -> Result<()> {
    for part in path.ancestors() {
        match fs::symlink_metadata(part) {
            Ok(_) => plain(part)?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.to_string()),
        }
    }
    Ok(())
}

/// Canonical form of a path whose trailing components may not exist yet.
pub(crate) fn prospective(path: &Path) -> Result<PathBuf> {
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

fn open_bounded(path: &Path, maximum: u64) -> Result<File> {
    plain(path)?;
    let file = io(File::open(path))?;
    if io(file.metadata())?.len() > maximum {
        return Err("Arquivo excede o limite permitido.".into());
    }
    Ok(file)
}

/// Reads a regular file of at most `maximum` bytes into memory.
pub(crate) fn read(path: &Path, maximum: u64) -> Result<Vec<u8>> {
    let file = open_bounded(path, maximum)?;
    let expected = io(file.metadata())?.len();
    // Sized up front: growing a multi-megabyte vector doubles the copies.
    let mut data = Vec::with_capacity(usize::try_from(expected).unwrap_or(0).saturating_add(1));
    io(file.take(maximum + 1).read_to_end(&mut data))?;
    if data.len() as u64 > maximum {
        return Err("Arquivo cresceu durante a leitura.".into());
    }
    Ok(data)
}

/// SHA-256 and length of a regular file, streamed in constant memory.
///
/// Verification-only paths use this instead of [`read`] + [`sha`]: a 150 MB
/// archive is checked without allocating 150 MB.
pub(crate) fn sha_file(path: &Path, maximum: u64) -> Result<(String, u64)> {
    let mut file = open_bounded(path, maximum)?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; CHUNK];
    let mut total = 0u64;
    loop {
        let count = match file.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => count,
            Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e.to_string()),
        };
        total += count as u64;
        if total > maximum {
            return Err("Arquivo cresceu durante a leitura.".into());
        }
        hasher.update(&buffer[..count]);
    }
    Ok((hex(hasher.finalize()), total))
}

/// Hash of a managed file, or `None` when it does not exist.
pub(crate) fn current_hash(path: &Path, maximum: u64) -> Result<Option<String>> {
    chain(path)?;
    if !path.exists() {
        return Ok(None);
    }
    Ok(Some(sha_file(path, maximum)?.0))
}

/// Writes through a synced temporary file in the destination directory, then renames.
pub(crate) fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        plain(path)?;
    }
    let parent = path.parent().ok_or("Destino sem diretório pai.")?;
    plain(parent)?;
    let mut temporary = io(tempfile::NamedTempFile::new_in(parent))?;
    io(temporary.write_all(bytes))?;
    io(temporary.as_file().sync_all())?;
    temporary.persist(path).map_err(|e| e.to_string())?;
    Ok(())
}

/// Creates a new synced file, failing if the destination already exists.
pub(crate) fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = io(OpenOptions::new().write(true).create_new(true).open(path))?;
    io(file.write_all(bytes))?;
    io(file.sync_all())
}

/// Canonical game directory whose `kain2.exe` is one of the supported builds.
pub(crate) fn supported_game_dir(
    game: &Path,
    mismatch: impl FnOnce() -> String,
) -> Result<PathBuf> {
    chain(game)?;
    let game = io(game.canonicalize())?;
    let (exe, _) = sha_file(&game.join("kain2.exe"), EXE_LIMIT)?;
    if !is_supported_exe(&exe) {
        return Err(mismatch());
    }
    Ok(game)
}

/// Exclusive cross-process lock shared by every component of one installation.
/// The lock is released when the returned handle is dropped.
pub(crate) fn lock_operation(game: &Path) -> Result<File> {
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
