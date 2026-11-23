use crate::security::{
    immutable_json::Directory,
    protected_files::{self as files, FilePolicy, ReadError},
};
use rustix::fs;
use serde_json::Value;
use std::{
    ffi::OsStr,
    os::fd::AsFd,
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "BACKTEST_EVIDENCE_CORRUPT";
const UNAVAILABLE: &str = "BACKTEST_EVIDENCE_UNAVAILABLE";
const BUDGET: usize = 128 * 1024 * 1024;
fn sha(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn canonical(value: &Value) -> Result<Vec<u8>> {
    onlyalpha_metadata_json::canonical_json(&value.to_string(), BUDGET)
        .map(String::into_bytes)
        .map_err(|_| INVALID)
}
fn parsed(raw: &[u8]) -> Result<Value> {
    let value: Value = serde_json::from_slice(raw).map_err(|_| INVALID)?;
    if canonical(&value)? != raw {
        return Err(INVALID);
    }
    Ok(value)
}
fn read(directory: &Directory, name: &str, limit: usize) -> Result<(Vec<u8>, (u64, u64))> {
    if name.is_empty()
        || matches!(name, "." | "..")
        || name.contains('/')
        || name.contains('\\')
        || name.contains('\0')
    {
        return Err(INVALID);
    }
    directory.verify().map_err(|_| INVALID)?;
    let before =
        fs::statat(&directory.fd, name, fs::AtFlags::SYMLINK_NOFOLLOW).map_err(|_| INVALID)?;
    let raw = files::read_file_at(
        &directory.fd,
        OsStr::new(name),
        FilePolicy::EvidenceArtifact,
        limit,
    )
    .map_err(|e| match e {
        ReadError::Unavailable => UNAVAILABLE,
        _ => INVALID,
    })?
    .to_vec();
    let after =
        fs::statat(&directory.fd, name, fs::AtFlags::SYMLINK_NOFOLLOW).map_err(|_| INVALID)?;
    if before.st_ino != after.st_ino
        || before.st_dev != after.st_dev
        || before.st_size < 0
        || before.st_size != after.st_size
        || raw.len() as u64 != before.st_size as u64
    {
        return Err(INVALID);
    }
    directory.verify().map_err(|_| INVALID)?;
    Ok((raw, (before.st_dev, before.st_ino)))
}
fn optional(root: &Directory, parts: &[&str]) -> Result<Option<Directory>> {
    root.verify().map_err(|_| INVALID)?;
    let mut path = root.path.clone();
    let mut fd = files::duplicate_directory(root.fd.as_fd()).map_err(|_| UNAVAILABLE)?;
    for part in parts {
        if part.is_empty()
            || matches!(*part, "." | "..")
            || part.contains('/')
            || part.contains('\\')
            || part.contains('\0')
        {
            return Err(INVALID);
        }
        fd = match files::open_directory_at(&fd, OsStr::new(part)) {
            Ok(fd) => fd,
            Err(ReadError::Missing) => return Ok(None),
            Err(ReadError::Invalid) => return Err(INVALID),
            Err(_) => return Err(UNAVAILABLE),
        };
        path.push(part);
    }
    Ok(Some(Directory { path, fd }))
}
fn names(directory: &Directory, remaining: &mut usize) -> Result<Vec<String>> {
    directory.verify().map_err(|_| INVALID)?;
    files::directory_entries(&directory.fd, remaining)
        .map_err(|_| UNAVAILABLE)?
        .into_iter()
        .map(|v| v.into_string().map_err(|_| INVALID))
        .collect()
}
struct File {
    raw: Vec<u8>,
    device: u64,
    inode: u64,
}

/// The already selected immutable Dataset bytes, retained independently of a
/// later Store load. This carries no materialization or execution capability.
pub(super) struct DatasetCut {
    files: Vec<(Directory, String, File)>,
}
impl DatasetCut {
    pub(super) fn capture(
        root: &std::path::Path,
        manifest: &Value,
        lineage: &Value,
    ) -> Result<Self> {
        let root = Directory::open(root).map_err(|_| UNAVAILABLE)?;
        let snapshot = manifest["snapshot_fingerprint"]
            .as_str()
            .filter(|p| crate::is_sha256_hex(p))
            .ok_or(INVALID)?;
        let directory = optional(&root, &["sha256", &snapshot[..2], snapshot])?.ok_or(INVALID)?;
        let mut files = Vec::new();
        let mut total = 0_usize;
        let mut capture = |directory: Directory, name: &str| -> Result<Vec<u8>> {
            let (raw, (device, inode)) = read(
                &directory,
                name,
                BUDGET.checked_sub(total).ok_or(UNAVAILABLE)?,
            )?;
            total = total.checked_add(raw.len()).ok_or(UNAVAILABLE)?;
            files.push((
                directory,
                name.into(),
                File {
                    raw: raw.clone(),
                    device,
                    inode,
                },
            ));
            Ok(raw)
        };
        let copy = |directory: &Directory| -> Result<Directory> {
            Ok(Directory {
                path: directory.path.clone(),
                fd: files::duplicate_directory(directory.fd.as_fd()).map_err(|_| UNAVAILABLE)?,
            })
        };
        if parsed(&capture(copy(&directory)?, "manifest.json")?)? != *manifest {
            return Err(INVALID);
        }
        let mut budget = 64 * 1024 * 1024;
        if names(&directory, &mut budget)? != vec!["data".to_owned(), "manifest.json".to_owned()] {
            return Err(INVALID);
        }
        let data = optional(&directory, &["data"])?.ok_or(INVALID)?;
        let mut expected = Vec::new();
        for (index, part) in manifest["partitions"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .enumerate()
        {
            let name = format!("p-{index:06}.parquet");
            if part["relative_path"] != format!("data/{name}")
                || part["byte_sha256"] != sha(&capture(copy(&data)?, &name)?)
            {
                return Err(INVALID);
            }
            expected.push(name);
        }
        if names(&data, &mut budget)? != expected {
            return Err(INVALID);
        }
        let identity = lineage["materialization_id"]
            .as_str()
            .and_then(|s| s.strip_prefix("dataset-materialization:"))
            .filter(|s| crate::is_sha256_hex(s))
            .ok_or(INVALID)?;
        let materialization =
            optional(&root, &["materializations", "sha256", &identity[..2]])?.ok_or(INVALID)?;
        if parsed(&capture(materialization, &format!("{identity}.json"))?)? != *lineage {
            return Err(INVALID);
        }
        let value = Self { files };
        value.verify()?;
        Ok(value)
    }
    pub(super) fn verify(&self) -> Result<()> {
        if self.files.is_empty() {
            return Err(INVALID);
        }
        for (directory, name, expected) in &self.files {
            let (raw, (device, inode)) = read(directory, name, expected.raw.len())?;
            if raw != expected.raw || device != expected.device || inode != expected.inode {
                return Err(INVALID);
            }
        }
        Ok(())
    }
}
