//! Descriptor-relative immutable canonical JSON publication for actual backend owners.
//! This module supplies physical persistence, never semantic or admission Authority.
use crate::security::protected_files::{self as files, FilePolicy};
use rustix::{fd::OwnedFd, fs};
use serde_json::Value;
use std::{
    ffi::OsStr,
    fs::File,
    io::Write,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "IMMUTABLE_JSON_INVALID";
const UNAVAILABLE: &str = "IMMUTABLE_JSON_UNAVAILABLE";
const LIMIT: usize = 8 * 1024 * 1024;
const MAX_ENTRIES: usize = 32768;
fn io(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), LIMIT).map_err(|_| INVALID)
}
pub(crate) fn parsed(raw: &[u8]) -> Result<Value> {
    if raw.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    let value: Value = serde_json::from_slice(raw).map_err(|_| INVALID)?;
    if canonical(&value)?.as_bytes() != raw {
        return Err(INVALID);
    }
    Ok(value)
}
pub(crate) struct Directory {
    pub(crate) path: PathBuf,
    pub(crate) fd: OwnedFd,
}
impl Directory {
    pub(crate) fn open(path: &Path) -> Result<Self> {
        Ok(Self {
            path: path.into(),
            fd: files::open_directory(path).map_err(io)?,
        })
    }
    pub(crate) fn verify(&self) -> Result<()> {
        let current = files::open_directory(&self.path).map_err(io)?;
        let a = fs::fstat(&self.fd).map_err(io)?;
        let b = fs::fstat(&current).map_err(io)?;
        if a.st_ino != b.st_ino || a.st_dev != b.st_dev {
            return Err(INVALID);
        }
        Ok(())
    }
    pub(crate) fn child(&self, name: &str, create: bool) -> Result<Self> {
        self.verify()?;
        if create {
            match fs::mkdirat(&self.fd, name, fs::Mode::from_raw_mode(0o700)) {
                Ok(()) => fs::fsync(&self.fd).map_err(io)?,
                Err(rustix::io::Errno::EXIST) => {}
                Err(e) => return Err(io(e)),
            }
        }
        let fd = files::open_directory_at(&self.fd, OsStr::new(name)).map_err(io)?;
        Ok(Self {
            path: self.path.join(name),
            fd,
        })
    }
    pub(crate) fn path(&self, parts: &[&str], create: bool) -> Result<Self> {
        let mut current = Self::open(&self.path)?;
        for part in parts {
            current = current.child(part, create)?;
        }
        Ok(current)
    }
    pub(crate) fn read(&self, name: &str) -> Result<Value> {
        self.verify()?;
        parsed(
            &files::read_file_at(
                &self.fd,
                OsStr::new(name),
                FilePolicy::HistoryDocument,
                LIMIT,
            )
            .map_err(io)?,
        )
    }
    pub(crate) fn names(&self) -> Result<Vec<String>> {
        self.verify()?;
        let mut remaining = MAX_ENTRIES;
        files::directory_entries(&self.fd, &mut remaining)
            .map_err(io)?
            .into_iter()
            .map(|name| name.into_string().map_err(|_| INVALID))
            .collect()
    }
}
pub(crate) struct SourceLock {
    pub(crate) directory: Directory,
    lock: OwnedFd,
}
fn source_binding(path: &Path, access: fs::OFlags) -> Result<(Directory, OwnedFd)> {
    let directory = Directory::open(path)?;
    let lock = fs::openat(
        &directory.fd,
        ".source-cut.lock",
        access | fs::OFlags::NOFOLLOW | fs::OFlags::NONBLOCK | fs::OFlags::CLOEXEC,
        fs::Mode::empty(),
    )
    .map_err(io)?;
    source_metadata(&fs::fstat(&lock).map_err(io)?)?;
    Ok((directory, lock))
}
fn source_metadata(metadata: &fs::Stat) -> Result<()> {
    if fs::FileType::from_raw_mode(metadata.st_mode) != fs::FileType::RegularFile
        || metadata.st_nlink != 1
        || metadata.st_mode & 0o022 != 0
        || (metadata.st_uid != 0 && metadata.st_uid != rustix::process::geteuid().as_raw())
    {
        return Err(INVALID);
    }
    Ok(())
}
fn verify_source_binding(directory: &Directory, lock: &OwnedFd) -> Result<()> {
    directory.verify()?;
    let actual = fs::statat(
        &directory.fd,
        ".source-cut.lock",
        fs::AtFlags::SYMLINK_NOFOLLOW,
    )
    .map_err(io)?;
    let held = fs::fstat(lock).map_err(io)?;
    source_metadata(&actual)?;
    source_metadata(&held)?;
    if actual.st_ino != held.st_ino || actual.st_dev != held.st_dev {
        return Err(INVALID);
    }
    Ok(())
}
/// Topology verification only: no lock acquisition, enumeration, absence or cut capability.
pub(crate) fn inspect_source_layout(path: &Path) -> Result<()> {
    let (directory, lock) = source_binding(path, fs::OFlags::RDONLY)?;
    verify_source_binding(&directory, &lock)
}
impl SourceLock {
    pub(crate) fn acquire(path: &Path) -> Result<Self> {
        Self::acquire_with(path, fs::FlockOperation::NonBlockingLockExclusive)
    }
    pub(crate) fn publication(path: &Path) -> Result<Self> {
        Self::acquire_with(path, fs::FlockOperation::NonBlockingLockShared)
    }
    fn acquire_with(path: &Path, operation: fs::FlockOperation) -> Result<Self> {
        let (directory, lock) = source_binding(path, fs::OFlags::RDWR)?;
        fs::flock(&lock, operation).map_err(io)?;
        let held = Self { directory, lock };
        held.verify()?;
        Ok(held)
    }
    pub(crate) fn verify(&self) -> Result<()> {
        verify_source_binding(&self.directory, &self.lock)
    }
}
/// Atomic put-once directory publication, in the original authority namespace.
pub(crate) fn put(directory: &Directory, parts: &[&str], leaf: &str, value: &Value) -> Result<()> {
    let (name, parents) = parts.split_last().ok_or(INVALID)?;
    let parent = directory.path(parents, true)?;
    let bytes = canonical(value)?;
    if bytes.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    match files::open_directory_at(&parent.fd, OsStr::new(name)) {
        Ok(fd) => {
            let existing = Directory {
                path: parent.path.join(name),
                fd,
            };
            return if existing.names()? == vec![leaf.to_string()] && existing.read(leaf)? == *value
            {
                Ok(())
            } else {
                Err(INVALID)
            };
        }
        Err(files::ReadError::Missing) => {}
        Err(error) => return Err(io(error)),
    }
    let mut random = [0u8; 16];
    getrandom::fill(&mut random).map_err(io)?;
    let stage = format!(
        ".stage-{}",
        random
            .iter()
            .map(|v| format!("{v:02x}"))
            .collect::<String>()
    );
    fs::mkdirat(&parent.fd, stage.as_str(), fs::Mode::from_raw_mode(0o700)).map_err(io)?;
    let staging = parent.child(&stage, false)?;
    let result = (|| {
        let fd = fs::openat(
            &staging.fd,
            leaf,
            fs::OFlags::WRONLY
                | fs::OFlags::CREATE
                | fs::OFlags::EXCL
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(io)?;
        let mut file = File::from(fd);
        file.write_all(bytes.as_bytes()).map_err(io)?;
        file.sync_all().map_err(io)?;
        fs::fsync(&staging.fd).map_err(io)?;
        parent.verify()?;
        match fs::renameat_with(
            &parent.fd,
            &stage,
            &parent.fd,
            *name,
            fs::RenameFlags::NOREPLACE,
        ) {
            Ok(()) => {}
            Err(rustix::io::Errno::EXIST) => {}
            Err(e) => return Err(io(e)),
        }
        fs::fsync(&parent.fd).map_err(io)?;
        let selected = parent.child(name, false)?;
        if selected.names()? != vec![leaf.to_string()] || selected.read(leaf)? != *value {
            return Err(INVALID);
        }
        Ok(())
    })();
    // If another exact writer won, remove only this exclusive random stage.
    if let Ok(still) = parent.child(&stage, false) {
        let held = fs::fstat(&staging.fd).map_err(io)?;
        let actual = fs::fstat(&still.fd).map_err(io)?;
        if held.st_ino == actual.st_ino && held.st_dev == actual.st_dev {
            let _ = fs::unlinkat(&still.fd, leaf, fs::AtFlags::empty());
            let _ = fs::unlinkat(&parent.fd, &stage, fs::AtFlags::REMOVEDIR);
        }
    }
    result
}
pub(crate) fn read_path(root: &Directory, parts: &[&str], leaf: &str) -> Result<Value> {
    root.path(parts, false)?.read(leaf)
}

#[cfg(test)]
mod source_binding_tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn owner() -> PathBuf {
        let mut nonce = [0_u8; 16];
        getrandom::fill(&mut nonce).unwrap();
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "source-binding-{}",
            nonce.iter().map(|b| format!("{b:02x}")).collect::<String>()
        ));
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let lock = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path.join(".source-cut.lock"))
            .unwrap();
        std::fs::set_permissions(
            path.join(".source-cut.lock"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        drop(lock);
        path
    }
    #[test]
    fn layout_inspection_does_not_release_or_downgrade_a_real_cut_or_publication() {
        let path = owner();
        let cut = SourceLock::acquire(&path).unwrap();
        inspect_source_layout(&path).unwrap();
        assert!(SourceLock::acquire(&path).is_err());
        assert!(SourceLock::publication(&path).is_err());
        drop(cut);
        let publication = SourceLock::publication(&path).unwrap();
        inspect_source_layout(&path).unwrap();
        assert!(SourceLock::acquire(&path).is_err());
        let second = SourceLock::publication(&path).unwrap();
        drop(second);
        drop(publication);
        std::fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn substituted_open_coordination_inode_cannot_satisfy_layout_or_cut_binding() {
        let path = owner();
        let (directory, lock) = source_binding(&path, fs::OFlags::RDONLY).unwrap();
        let cut = SourceLock::acquire(&path).unwrap();
        std::fs::rename(path.join(".source-cut.lock"), path.join("retained-lock")).unwrap();
        let replacement = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path.join(".source-cut.lock"))
            .unwrap();
        std::fs::set_permissions(
            path.join(".source-cut.lock"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        assert_eq!(
            verify_source_binding(&directory, &lock).unwrap_err(),
            INVALID
        );
        assert_eq!(cut.verify().unwrap_err(), INVALID);
        drop(replacement);
        drop(cut);
        drop(lock);
        drop(directory);
        std::fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn layout_and_cut_use_the_same_regular_owned_single_link_metadata_guard() {
        let path = owner();
        let file = std::fs::File::open(path.join(".source-cut.lock")).unwrap();
        let metadata = fs::fstat(&file).unwrap();
        source_metadata(&metadata).unwrap();
        for mutation in ["owner", "links", "mode", "kind"] {
            let mut changed = fs::fstat(&file).unwrap();
            match mutation {
                "owner" => changed.st_uid = u32::MAX,
                "links" => changed.st_nlink = 2,
                "mode" => changed.st_mode |= 0o002,
                "kind" => changed.st_mode = fs::FileType::Directory.as_raw_mode(),
                _ => unreachable!(),
            }
            assert_eq!(source_metadata(&changed).unwrap_err(), INVALID);
        }
        drop(file);
        std::fs::remove_dir_all(path).unwrap();
    }
}
