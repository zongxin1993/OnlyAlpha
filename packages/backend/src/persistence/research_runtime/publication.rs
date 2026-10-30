//! Physical publication in the existing artifact and Generation namespaces.
use super::{INVALID, Result, UNAVAILABLE};
use crate::security::{immutable_json::Directory, protected_files};
use rustix::fs;
use std::{fs::File, io::Write, path::Path};

pub(super) fn nonce(prefix: &str) -> Result<String> {
    let mut bytes = [0; 16];
    getrandom::fill(&mut bytes).map_err(|_| UNAVAILABLE)?;
    Ok(format!(
        "{prefix}{}",
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    ))
}
fn encoded(value: &serde_json::Value) -> Result<Vec<u8>> {
    let mut raw = onlyalpha_metadata_json::canonical_json(&value.to_string(), super::LIMIT)
        .map_err(|_| INVALID)?
        .into_bytes();
    raw.push(b'\n');
    if raw.len() > super::LIMIT {
        return Err(UNAVAILABLE);
    }
    Ok(raw)
}
fn document(directory: &Directory, name: &str) -> Result<serde_json::Value> {
    directory.verify()?;
    let raw = protected_files::read_file_at(
        &directory.fd,
        std::ffi::OsStr::new(name),
        protected_files::FilePolicy::HistoryDocument,
        super::LIMIT,
    )
    .map_err(|_| UNAVAILABLE)?;
    let value: serde_json::Value = serde_json::from_slice(&raw).map_err(|_| INVALID)?;
    // Original Generation/Artifact wire documents have exactly one terminal LF.
    if encoded(&value)? != *raw {
        return Err(INVALID);
    }
    Ok(value)
}
fn create(parent: &Directory, name: &str, bytes: &[u8], mode: u32) -> Result<()> {
    let fd = fs::openat(
        &parent.fd,
        name,
        fs::OFlags::WRONLY
            | fs::OFlags::CREATE
            | fs::OFlags::EXCL
            | fs::OFlags::NOFOLLOW
            | fs::OFlags::CLOEXEC,
        fs::Mode::from_raw_mode(0o600),
    )
    .map_err(|_| UNAVAILABLE)?;
    let mut file = File::from(fd);
    file.write_all(bytes).map_err(|_| UNAVAILABLE)?;
    fs::fchmod(&file, fs::Mode::from_raw_mode(mode)).map_err(|_| UNAVAILABLE)?;
    file.sync_all().map_err(|_| UNAVAILABLE)
}
pub(super) fn initialize_fresh(root: &Path) -> Result<()> {
    let parent = Directory::open(root.parent().ok_or(INVALID)?)?;
    let name = root.file_name().and_then(|n| n.to_str()).ok_or(INVALID)?;
    let stage = nonce(".generation-init-")?;
    fs::mkdirat(&parent.fd, stage.as_str(), fs::Mode::from_raw_mode(0o700))
        .map_err(|_| UNAVAILABLE)?;
    let staging = parent.child(&stage, false)?;
    // The journal and lifecycle lock appear together; an existing namespace is never repaired here.
    create(&staging, "generation-events.jsonl", b"", 0o600)?;
    let fd = fs::openat(
        &staging.fd,
        ".generation-authority.lock",
        fs::OFlags::RDWR
            | fs::OFlags::CREATE
            | fs::OFlags::EXCL
            | fs::OFlags::NOFOLLOW
            | fs::OFlags::CLOEXEC,
        fs::Mode::from_raw_mode(0o600),
    )
    .map_err(|_| UNAVAILABLE)?;
    fs::fchmod(&fd, fs::Mode::from_raw_mode(0o600)).map_err(|_| UNAVAILABLE)?;
    fs::fsync(&fd).map_err(|_| UNAVAILABLE)?;
    fs::fsync(&staging.fd).map_err(|_| UNAVAILABLE)?;
    parent.verify()?;
    fs::renameat_with(
        &parent.fd,
        stage.as_str(),
        &parent.fd,
        name,
        fs::RenameFlags::NOREPLACE,
    )
    .map_err(|_| "RUNTIME_GENERATION_INITIALIZATION_CONFLICT")?;
    fs::fsync(&parent.fd).map_err(|_| "RUNTIME_GENERATION_OUTCOME_UNKNOWN")?;
    let selected = parent.child(name, false)?;
    let actual = fs::fstat(&selected.fd).map_err(|_| UNAVAILABLE)?;
    let held = fs::fstat(&staging.fd).map_err(|_| UNAVAILABLE)?;
    if actual.st_dev != held.st_dev || actual.st_ino != held.st_ino {
        return Err(INVALID);
    }
    Ok(())
}
pub(super) fn put_file(
    root: &Directory,
    parts: &[&str],
    leaf: &str,
    value: &serde_json::Value,
) -> Result<()> {
    let parent = root.path(parts, true)?;
    match document(&parent, leaf) {
        Ok(existing) => {
            return if existing == *value {
                Ok(())
            } else {
                Err(INVALID)
            };
        }
        Err(_) => {
            // Distinguish positive absence from corrupt/unreadable existing history.
            match fs::statat(&parent.fd, leaf, fs::AtFlags::SYMLINK_NOFOLLOW) {
                Err(rustix::io::Errno::NOENT) => {}
                _ => return Err(INVALID),
            }
        }
    }
    let stage = nonce(".generation-file-")?;
    let canonical = encoded(value)?;
    create(&parent, &stage, &canonical, 0o400)?;
    parent.verify()?;
    fs::renameat_with(
        &parent.fd,
        stage.as_str(),
        &parent.fd,
        leaf,
        fs::RenameFlags::NOREPLACE,
    )
    .map_err(|_| UNAVAILABLE)?;
    fs::fsync(&parent.fd).map_err(|_| "RUNTIME_GENERATION_OUTCOME_UNKNOWN")?;
    if document(&parent, leaf)? != *value {
        return Err(INVALID);
    }
    Ok(())
}
pub(super) fn put_pair(
    root: &Directory,
    parts: &[&str],
    manifest: &serde_json::Value,
    name: &str,
    bytes: &[u8],
    executable: bool,
) -> Result<()> {
    let (last, parents) = parts.split_last().ok_or(INVALID)?;
    let parent = root.path(parents, true)?;
    match protected_files::open_directory_at(&parent.fd, std::ffi::OsStr::new(last)) {
        Ok(_) => return verify_pair(root, parts, manifest, name, bytes),
        Err(protected_files::ReadError::Missing) => {}
        Err(_) => return Err(INVALID),
    }
    let stage = nonce(".generation-artifact-")?;
    fs::mkdirat(&parent.fd, stage.as_str(), fs::Mode::from_raw_mode(0o700))
        .map_err(|_| UNAVAILABLE)?;
    let staging = parent.child(&stage, false)?;
    let canonical = encoded(manifest)?;
    create(&staging, "manifest.json", &canonical, 0o400)?;
    create(
        &staging,
        name,
        bytes,
        if executable { 0o500 } else { 0o400 },
    )?;
    fs::fsync(&staging.fd).map_err(|_| UNAVAILABLE)?;
    parent.verify()?;
    fs::renameat_with(
        &parent.fd,
        stage.as_str(),
        &parent.fd,
        *last,
        fs::RenameFlags::NOREPLACE,
    )
    .map_err(|_| UNAVAILABLE)?;
    fs::fsync(&parent.fd).map_err(|_| "RUNTIME_GENERATION_OUTCOME_UNKNOWN")?;
    verify_pair(root, parts, manifest, name, bytes)
}
fn verify_pair(
    root: &Directory,
    parts: &[&str],
    manifest: &serde_json::Value,
    name: &str,
    bytes: &[u8],
) -> Result<()> {
    use sha2::{Digest, Sha256};
    let selected = root.path(parts, false)?;
    let mut names = selected.names()?;
    names.sort();
    let mut expected = vec!["manifest.json".to_owned(), name.to_owned()];
    expected.sort();
    if names != expected || document(&selected, "manifest.json")? != *manifest {
        return Err(INVALID);
    }
    let sha = Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let path = parts
        .iter()
        .copied()
        .chain([name])
        .collect::<Vec<_>>()
        .join("/");
    super::verify_bytes(&root.fd, &path, &sha, bytes.len() as u64)
}
