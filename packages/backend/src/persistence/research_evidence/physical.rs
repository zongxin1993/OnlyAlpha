//! Retained physical witnesses, never a caller-provided semantic capability.
use super::super::{Directory, INVALID, LIMIT, Result, SourceLock, UNAVAILABLE};
use crate::persistence::research_runtime::RuntimeEvidenceHold;
use crate::security::protected_files::{self as protected, ReadError};
use rustix::fs;
use serde_json::Value;
use std::{
    ffi::OsStr,
    fs::File,
    io::{Read, Seek},
    os::fd::AsFd,
    path::Path,
    sync::Arc,
};

pub(crate) struct ReadCut {
    pub(crate) runtime: Arc<RuntimeEvidenceHold>,
    pub(crate) files: Vec<Witness>,
    pub(crate) locks: Vec<Arc<SourceLock>>,
}
impl ReadCut {
    pub(crate) fn verify(&self) -> Result<()> {
        if self.locks.is_empty() || self.files.is_empty() {
            return Err(INVALID);
        }
        for source in &self.locks {
            source.verify()?;
        }
        self.runtime.verify()?;
        for file in &self.files {
            file.verify()?;
        }
        Ok(())
    }
}
pub(crate) struct Witness {
    directory: Directory,
    name: String,
    digest: String,
    size: u64,
    inode: u64,
    device: u64,
}
fn failure(
    directory: &Directory,
    name: &str,
    predicate: &'static str,
    expected: &str,
    actual: &str,
    errno: Option<i32>,
) {
    if !tracing::enabled!(target:"onlyalpha.observability",tracing::Level::ERROR) {
        return;
    }
    let path = directory.path.join(name);
    let path = path.to_string_lossy();
    macro_rules! emit {
        ($errno:expr) => { tracing::error!(target:"onlyalpha.observability",event_kind="summary",module="backend",operation="evidence.witness.failure",outcome="failed",error_code=predicate,file_path=path.as_ref(),expected_value=expected,actual_value=actual,errno=$errno) };
    }
    match errno {
        Some(code) => emit!(i64::from(code)),
        None => emit!(tracing::field::Empty),
    }
}
fn io_failure(
    directory: &Directory,
    name: &str,
    predicate: &'static str,
    errno: Option<i32>,
) -> &'static str {
    let actual = errno.map_or_else(
        || "io_error_without_errno".to_owned(),
        |code| format!("errno:{code}"),
    );
    failure(directory, name, predicate, "successful_io", &actual, errno);
    UNAVAILABLE
}
impl Witness {
    pub(crate) fn verify(&self) -> Result<()> {
        self.directory.verify().inspect_err(|code| {
            failure(
                &self.directory,
                &self.name,
                "WITNESS_DIRECTORY_BEFORE",
                "verified_directory",
                code,
                None,
            )
        })?;
        let (raw, file) = read_file(&self.directory, &self.name)?;
        let stat = fs::fstat(file.as_fd()).map_err(|error| {
            io_failure(
                &self.directory,
                &self.name,
                "WITNESS_RESTAT_UNAVAILABLE",
                Some(error.raw_os_error()),
            )
        })?;
        let mismatch = if stat.st_ino != self.inode {
            Some((
                "WITNESS_INODE_MISMATCH",
                self.inode.to_string(),
                stat.st_ino.to_string(),
            ))
        } else if stat.st_dev != self.device {
            Some((
                "WITNESS_DEVICE_MISMATCH",
                self.device.to_string(),
                stat.st_dev.to_string(),
            ))
        } else if stat.st_size as u64 != self.size {
            Some((
                "WITNESS_SIZE_MISMATCH",
                self.size.to_string(),
                stat.st_size.to_string(),
            ))
        } else {
            let actual = byte_sha(&raw);
            (actual != self.digest)
                .then(|| ("WITNESS_DIGEST_MISMATCH", self.digest.clone(), actual))
        };
        if let Some((predicate, expected, actual)) = mismatch {
            failure(
                &self.directory,
                &self.name,
                predicate,
                &expected,
                &actual,
                None,
            );
            return Err(INVALID);
        }
        self.directory.verify().inspect_err(|code| {
            failure(
                &self.directory,
                &self.name,
                "WITNESS_DIRECTORY_AFTER",
                "verified_directory",
                code,
                None,
            )
        })
    }
}
pub(crate) fn byte_sha(raw: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(raw)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub(crate) fn read_file(directory: &Directory, name: &str) -> Result<(Vec<u8>, File)> {
    read_file_with_size_error(directory, name, INVALID)
}
pub(super) fn read_report_file(directory: &Directory, name: &str) -> Result<(Vec<u8>, File)> {
    read_file_with_size_error(directory, name, UNAVAILABLE)
}
fn open_failure(directory: &Directory, name: &str, error: rustix::io::Errno) -> &'static str {
    let (predicate, code) = match error {
        rustix::io::Errno::NOENT => ("WITNESS_FILE_MISSING", INVALID),
        rustix::io::Errno::LOOP => ("WITNESS_SYMLINK_REJECTED", INVALID),
        rustix::io::Errno::NOTDIR => ("WITNESS_NOT_DIRECTORY", INVALID),
        _ => ("WITNESS_OPEN_UNAVAILABLE", UNAVAILABLE),
    };
    failure(
        directory,
        name,
        predicate,
        "successful_open",
        &format!("errno:{}", error.raw_os_error()),
        Some(error.raw_os_error()),
    );
    code
}
fn validate_file_metadata(
    directory: &Directory,
    name: &str,
    stat: &fs::Stat,
    euid: impl FnOnce() -> u32,
    oversize: &'static str,
) -> Result<()> {
    let mismatch = if fs::FileType::from_raw_mode(stat.st_mode) != fs::FileType::RegularFile {
        Some((
            "WITNESS_FILE_TYPE_INVALID",
            "regular_file".to_owned(),
            format!("mode:{:#o}", stat.st_mode),
        ))
    } else if stat.st_nlink != 1 {
        Some((
            "WITNESS_LINK_COUNT_INVALID",
            "1".to_owned(),
            stat.st_nlink.to_string(),
        ))
    } else if stat.st_mode & 0o022 != 0 {
        Some((
            "WITNESS_WRITE_BITS_INVALID",
            "0o0".to_owned(),
            format!("{:#o}", stat.st_mode & 0o022),
        ))
    } else {
        None
    };
    if let Some((predicate, expected, actual)) = mismatch {
        failure(directory, name, predicate, &expected, &actual, None);
        return Err(INVALID);
    }
    if stat.st_uid != 0 {
        let euid = euid();
        if stat.st_uid != euid {
            failure(
                directory,
                name,
                "WITNESS_OWNER_INVALID",
                &format!("0_or_{euid}"),
                &stat.st_uid.to_string(),
                None,
            );
            return Err(INVALID);
        }
    }
    if stat.st_size < 0 {
        failure(
            directory,
            name,
            "WITNESS_NEGATIVE_SIZE",
            ">=0",
            &stat.st_size.to_string(),
            None,
        );
        return Err(INVALID);
    }
    if stat.st_size as u64 > LIMIT as u64 {
        failure(
            directory,
            name,
            "WITNESS_STAT_SIZE_LIMIT",
            &format!("<={LIMIT}"),
            &stat.st_size.to_string(),
            None,
        );
        return Err(oversize);
    }
    Ok(())
}
fn read_content(
    directory: &Directory,
    name: &str,
    file: &mut impl Read,
    size: usize,
    oversize: &'static str,
) -> Result<Vec<u8>> {
    let mut raw = Vec::new();
    file.take(LIMIT as u64 + 1)
        .read_to_end(&mut raw)
        .map_err(|error| {
            io_failure(
                directory,
                name,
                "WITNESS_READ_UNAVAILABLE",
                error.raw_os_error(),
            )
        })?;
    if raw.len() > LIMIT {
        failure(
            directory,
            name,
            "WITNESS_READ_SIZE_LIMIT",
            &format!("<={LIMIT}"),
            &raw.len().to_string(),
            None,
        );
        return Err(oversize);
    }
    if raw.len() != size {
        failure(
            directory,
            name,
            "WITNESS_READ_LENGTH_MISMATCH",
            &size.to_string(),
            &raw.len().to_string(),
            None,
        );
        return Err(INVALID);
    }
    Ok(raw)
}
fn read_file_with_size_error(
    directory: &Directory,
    name: &str,
    oversize: &'static str,
) -> Result<(Vec<u8>, File)> {
    if name.is_empty()
        || matches!(name, "." | "..")
        || name.contains('/')
        || name.contains('\\')
        || name.contains('\0')
    {
        failure(
            directory,
            name,
            "WITNESS_BASENAME_INVALID",
            "valid_basename",
            "invalid_basename",
            None,
        );
        return Err(INVALID);
    }
    directory.verify().inspect_err(|code| {
        failure(
            directory,
            name,
            "WITNESS_DIRECTORY_READ",
            "verified_directory",
            code,
            None,
        )
    })?;
    let fd = fs::openat(
        &directory.fd,
        name,
        fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::NONBLOCK | fs::OFlags::CLOEXEC,
        fs::Mode::empty(),
    )
    .map_err(|error| open_failure(directory, name, error))?;
    let stat = fs::fstat(&fd).map_err(|error| {
        io_failure(
            directory,
            name,
            "WITNESS_STAT_UNAVAILABLE",
            Some(error.raw_os_error()),
        )
    })?;
    validate_file_metadata(
        directory,
        name,
        &stat,
        || rustix::process::geteuid().as_raw(),
        oversize,
    )?;
    let mut file = File::from(fd);
    let raw = read_content(directory, name, &mut file, stat.st_size as usize, oversize)?;
    file.rewind().map_err(|error| {
        io_failure(
            directory,
            name,
            "WITNESS_REWIND_UNAVAILABLE",
            error.raw_os_error(),
        )
    })?;
    Ok((raw, file))
}
pub(crate) fn witness(
    directory: &Directory,
    name: &str,
    raw: &[u8],
    file: &File,
) -> Result<Witness> {
    let stat = fs::fstat(file.as_fd()).map_err(|error| {
        io_failure(
            directory,
            name,
            "WITNESS_CAPTURE_STAT_UNAVAILABLE",
            Some(error.raw_os_error()),
        )
    })?;
    let directory = Directory {
        path: directory.path.clone(),
        fd: protected::duplicate_directory(directory.fd.as_fd()).map_err(|error| {
            let actual = match error {
                ReadError::Missing => "missing",
                ReadError::Invalid => "invalid",
                ReadError::Unavailable => "unavailable",
            };
            failure(
                directory,
                name,
                "WITNESS_CAPTURE_DIRECTORY_UNAVAILABLE",
                "duplicable_directory",
                actual,
                None,
            );
            UNAVAILABLE
        })?,
    };
    Ok(Witness {
        directory,
        name: name.into(),
        digest: byte_sha(raw),
        size: raw.len() as u64,
        inode: stat.st_ino,
        device: stat.st_dev,
    })
}
pub(crate) fn document(
    directory: &Directory,
    name: &str,
    witnesses: &mut Vec<Witness>,
) -> Result<Value> {
    let (bytes, file) = read_file(directory, name)?;
    let value = crate::security::immutable_json::parsed(&bytes).map_err(|code| {
        failure(
            directory,
            name,
            "WITNESS_DOCUMENT_ENCODING_INVALID",
            "canonical_json",
            code,
            None,
        );
        INVALID
    })?;
    witnesses.push(witness(directory, name, &bytes, &file)?);
    Ok(value)
}
pub(crate) fn optional_directory(root: &Directory, parts: &[&str]) -> Result<Option<Directory>> {
    root.verify()?;
    let mut path = root.path.clone();
    let mut fd = protected::duplicate_directory(root.fd.as_fd()).map_err(|_| UNAVAILABLE)?;
    for part in parts {
        if part.is_empty()
            || matches!(*part, "." | "..")
            || part.contains('/')
            || part.contains('\\')
            || part.contains('\0')
        {
            return Err(INVALID);
        }
        fd = match protected::open_directory_at(&fd, OsStr::new(part)) {
            Ok(fd) => fd,
            Err(ReadError::Missing) => return Ok(None),
            Err(ReadError::Invalid) => return Err(INVALID),
            Err(_) => return Err(UNAVAILABLE),
        };
        path.push(part);
    }
    Ok(Some(Directory { path, fd }))
}
pub(crate) fn exact_files(directory: &Directory, names: &[&str]) -> Result<()> {
    let mut expected = names.iter().map(|n| (*n).to_owned()).collect::<Vec<_>>();
    expected.sort();
    if directory.names()? != expected {
        return Err(INVALID);
    }
    Ok(())
}
pub(crate) fn data_file(
    directory: &Directory,
    relative: &str,
    witnesses: &mut Vec<Witness>,
) -> Result<(Vec<u8>, File)> {
    let (parent, name) = relative.rsplit_once('/').unwrap_or(("", relative));
    let parts = parent
        .split('/')
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>();
    let leaf = optional_directory(directory, &parts)?.ok_or(INVALID)?;
    let (bytes, file) = read_file(&leaf, name)?;
    witnesses.push(witness(&leaf, name, &bytes, &file)?);
    Ok((bytes, file))
}
pub(crate) fn capture_dataset(
    root: &Path,
    manifest: &Value,
    lineage: &Value,
    witnesses: &mut Vec<Witness>,
) -> Result<()> {
    let root = Directory::open(root)?;
    let snapshot = manifest["snapshot_fingerprint"]
        .as_str()
        .filter(|p| crate::is_sha256_hex(p))
        .ok_or(INVALID)?;
    let leaf = optional_directory(&root, &["sha256", &snapshot[..2], snapshot])?.ok_or(INVALID)?;
    if document(&leaf, "manifest.json", witnesses)? != *manifest {
        return Err(INVALID);
    }
    let partitions = manifest["partitions"].as_array().ok_or(INVALID)?;
    exact_files(&leaf, &["manifest.json", "data"])?;
    let mut names = Vec::new();
    for (index, partition) in partitions.iter().enumerate() {
        let name = format!("data/p-{index:06}.parquet");
        if partition["relative_path"] != name {
            return Err(INVALID);
        }
        let (raw, _) = data_file(&leaf, &name, witnesses)?;
        if partition["byte_sha256"] != byte_sha(&raw) {
            return Err(INVALID);
        }
        names.push(format!("p-{index:06}.parquet"));
    }
    let data = optional_directory(&leaf, &["data"])?.ok_or(INVALID)?;
    exact_files(&data, &names.iter().map(String::as_str).collect::<Vec<_>>())?;
    let id = lineage["materialization_id"]
        .as_str()
        .and_then(|p| p.strip_prefix("dataset-materialization:"))
        .filter(|p| crate::is_sha256_hex(p))
        .ok_or(INVALID)?;
    let materialization =
        optional_directory(&root, &["materializations", "sha256", &id[..2]])?.ok_or(INVALID)?;
    let stored = document(&materialization, &format!("{id}.json"), witnesses)?;
    if stored != *lineage {
        return Err(INVALID);
    }
    Ok(())
}

#[cfg(test)]
#[path = "../../tests/research_evidence_witness.rs"]
mod witness_diagnostic_tests;
