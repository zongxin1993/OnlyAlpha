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
    components(parts, leaf)?;
    let (name, parents) = parts.split_last().ok_or(INVALID)?;
    let parent = directory.path(parents, true)?;
    publish_at(&parent.fd, &parent.fd, name, leaf, value, || parent.verify())
}
/// Same physical put-once operation for an already selected descriptor owner.
/// This preserves the selected namespace if its original absolute path is renamed.
pub(crate) fn put_at(
    selected: std::os::fd::BorrowedFd<'_>,
    parts: &[&str],
    leaf: &str,
    value: &Value,
) -> Result<()> {
    components(parts, leaf)?;
    let (name, parents) = parts.split_last().ok_or(INVALID)?;
    let selected = files::duplicate_directory(selected).map_err(io)?;
    // Interrupted writes never enter a semantic SHA namespace. Retain unknown
    // old staging inodes; only the current invocation may remove its own stage.
    let staging_name = ".immutable-json-staging";
    let created = match fs::mkdirat(&selected, staging_name, fs::Mode::from_raw_mode(0o700)) {
        Ok(()) => true,
        Err(rustix::io::Errno::EXIST) => false,
        Err(error) => return Err(io(error)),
    };
    let staging = files::open_directory_at(&selected, OsStr::new(staging_name)).map_err(io)?;
    if created {
        fs::fsync(&staging).map_err(io)?;
        fs::fsync(&selected).map_err(io)?;
    }
    let mut parent = selected;
    for part in parents {
        let created = match fs::mkdirat(&parent, *part, fs::Mode::from_raw_mode(0o700)) {
            Ok(()) => true,
            Err(rustix::io::Errno::EXIST) => false,
            Err(e) => return Err(io(e)),
        };
        let next = files::open_directory_at(&parent, OsStr::new(part)).map_err(io)?;
        if created {
            fs::fsync(&next).map_err(io)?;
            fs::fsync(&parent).map_err(io)?;
        }
        parent = next;
    }
    publish_at(&parent, &staging, name, leaf, value, || {
        use std::os::fd::AsFd;
        files::duplicate_directory(parent.as_fd())
            .map(drop)
            .map_err(io)
    })
}
fn components(parts: &[&str], leaf: &str) -> Result<()> {
    if parts.is_empty()
        || parts
            .iter()
            .copied()
            .chain([leaf])
            .any(|s| s.is_empty() || matches!(s, "." | "..") || s.contains('/') || s.contains('\0'))
    {
        return Err(INVALID);
    }
    Ok(())
}
fn names_at(fd: &OwnedFd) -> Result<Vec<String>> {
    let mut work = MAX_ENTRIES;
    files::directory_entries(fd, &mut work)
        .map_err(io)?
        .into_iter()
        .map(|name| name.into_string().map_err(|_| INVALID))
        .collect()
}
fn value_at(fd: &OwnedFd, leaf: &str) -> Result<Value> {
    parsed(
        &files::read_file_at(fd, OsStr::new(leaf), FilePolicy::HistoryDocument, LIMIT)
            .map_err(io)?,
    )
}
fn publish_at(
    parent: &OwnedFd,
    staging_parent: &OwnedFd,
    name: &str,
    leaf: &str,
    value: &Value,
    verify: impl Fn() -> Result<()>,
) -> Result<()> {
    verify()?;
    // renameat must stay on one filesystem. Both endpoints are selected
    // directory descriptors, never reconstructed absolute or /proc paths.
    if fs::fstat(parent).map_err(io)?.st_dev != fs::fstat(staging_parent).map_err(io)?.st_dev {
        return Err(INVALID);
    }
    let bytes = canonical(value)?;
    if bytes.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    match files::open_directory_at(parent, OsStr::new(name)) {
        Ok(existing) => {
            return if names_at(&existing)? == vec![leaf.to_string()]
                && value_at(&existing, leaf)? == *value
            {
                // Replay also closes a prior crash after rename but before
                // either directory fsync, without rewriting the semantic fact.
                fs::fsync(parent).map_err(io)?;
                fs::fsync(staging_parent).map_err(io)?;
                verify()
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
    fs::mkdirat(staging_parent, stage.as_str(), fs::Mode::from_raw_mode(0o700)).map_err(io)?;
    let staging = files::open_directory_at(staging_parent, OsStr::new(&stage)).map_err(io)?;
    fs::fsync(staging_parent).map_err(io)?;
    #[cfg(test)]
    publication_crash(PublicationCrashPoint::StageCreated);
    let result = (|| {
        let fd = fs::openat(
            &staging,
            leaf,
            fs::OFlags::WRONLY
                | fs::OFlags::CREATE
                | fs::OFlags::EXCL
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::CLOEXEC
                | fs::OFlags::NONBLOCK,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(io)?;
        let mut file = File::from(fd);
        #[cfg(test)]
        partial_publication_crash(&mut file, bytes.as_bytes())?;
        file.write_all(bytes.as_bytes()).map_err(io)?;
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::LeafWritten);
        file.sync_all().map_err(io)?;
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::FileSynced);
        fs::fsync(&staging).map_err(io)?;
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::StageSynced);
        verify()?;
        match fs::renameat_with(
            staging_parent,
            stage.as_str(),
            parent,
            name,
            fs::RenameFlags::NOREPLACE,
        ) {
            Ok(()) => {}
            Err(rustix::io::Errno::EXIST) => {}
            Err(e) => return Err(io(e)),
        }
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::Renamed);
        fs::fsync(parent).map_err(io)?;
        fs::fsync(staging_parent).map_err(io)?;
        let selected = files::open_directory_at(parent, OsStr::new(name)).map_err(io)?;
        if names_at(&selected)? != vec![leaf.to_string()] || value_at(&selected, leaf)? != *value {
            return Err(INVALID);
        }
        verify()
    })();
    // Remove only this invocation's exclusive random staging inode.
    if let Ok(still) = files::open_directory_at(staging_parent, OsStr::new(&stage)) {
        let held = fs::fstat(&staging).map_err(io)?;
        let actual = fs::fstat(&still).map_err(io)?;
        if held.st_ino == actual.st_ino && held.st_dev == actual.st_dev {
            let names = names_at(&still)?;
            if names == vec![leaf.to_string()] {
                fs::unlinkat(&still, leaf, fs::AtFlags::empty()).map_err(io)?;
            } else if !names.is_empty() {
                return Err(INVALID);
            }
            fs::unlinkat(staging_parent, stage.as_str(), fs::AtFlags::REMOVEDIR).map_err(io)?;
            fs::fsync(staging_parent).map_err(io)?;
        }
    }
    result
}
/// Publish a bounded complete physical bundle in the selected owner's namespace.
/// Callers own semantic validation and authorization; this helper grants neither.
pub(crate) fn put_bundle_at(
    selected: std::os::fd::BorrowedFd<'_>,
    parts: &[&str],
    files: &std::collections::BTreeMap<String, Vec<u8>>,
    max_bytes: usize,
) -> Result<()> {
    use std::{collections::BTreeMap, os::fd::AsFd};
    components(parts, "manifest.json")?;
    if parts.len() > 32 || parts.iter().any(|p| p.len() > 255 || p.contains('\\')) {
        return Err(INVALID);
    }
    // Validate the complete input before creating any directory.
    let layout = bundle_layout(files, max_bytes)?;
    let (name, parents) = parts.split_last().ok_or(INVALID)?;
    let selected = files::duplicate_directory(selected).map_err(io)?;
    let staging_name = ".immutable-json-staging";
    let created = match fs::mkdirat(&selected, staging_name, fs::Mode::from_raw_mode(0o700)) {
        Ok(()) => true,
        Err(rustix::io::Errno::EXIST) => false,
        Err(error) => return Err(io(error)),
    };
    let staging_parent = files::open_directory_at(&selected, OsStr::new(staging_name)).map_err(io)?;
    if created {
        fs::fsync(&staging_parent).map_err(io)?;
        fs::fsync(&selected).map_err(io)?;
    }
    let mut parent = selected;
    for part in parents {
        let created = match fs::mkdirat(&parent, *part, fs::Mode::from_raw_mode(0o700)) {
            Ok(()) => true,
            Err(rustix::io::Errno::EXIST) => false,
            Err(error) => return Err(io(error)),
        };
        let next = files::open_directory_at(&parent, OsStr::new(part)).map_err(io)?;
        if created {
            fs::fsync(&next).map_err(io)?;
            fs::fsync(&parent).map_err(io)?;
        }
        parent = next;
    }
    if fs::fstat(&parent).map_err(io)?.st_dev != fs::fstat(&staging_parent).map_err(io)?.st_dev {
        return Err(INVALID);
    }
    match files::open_directory_at(&parent, OsStr::new(name)) {
        Ok(existing) => {
            verify_bundle(&existing, files, &layout)?;
            fs::fsync(&parent).map_err(io)?;
            return fs::fsync(&staging_parent).map_err(io);
        }
        Err(files::ReadError::Missing) => {}
        Err(error) => return Err(io(error)),
    }
    let mut random = [0_u8; 16];
    getrandom::fill(&mut random).map_err(io)?;
    let stage = format!(".stage-{}", random.iter().map(|b| format!("{b:02x}")).collect::<String>());
    fs::mkdirat(&staging_parent, stage.as_str(), fs::Mode::from_raw_mode(0o700)).map_err(io)?;
    let staging = files::open_directory_at(&staging_parent, OsStr::new(&stage)).map_err(io)?;
    fs::fsync(&staging_parent).map_err(io)?;
    #[cfg(test)]
    publication_crash(PublicationCrashPoint::StageCreated);
    // Only these exact, invocation-created inodes are eligible for cleanup.
    let mut owned: BTreeMap<String, (bool, fs::Stat)> = BTreeMap::new();
    let result = (|| {
        for directory in layout.keys().filter(|p| !p.is_empty()) {
            let (prefix, leaf) = directory.rsplit_once('/').unwrap_or(("", directory));
            let at = bundle_directory(&staging, prefix, Some(&owned))?;
            fs::mkdirat(&at, leaf, fs::Mode::from_raw_mode(0o700)).map_err(io)?;
            let child = files::open_directory_at(&at, OsStr::new(leaf)).map_err(io)?;
            owned.insert(directory.clone(), (true, fs::fstat(&child).map_err(io)?));
        }
        for (relative, bytes) in files {
            let (prefix, leaf) = relative.rsplit_once('/').unwrap_or(("", relative));
            let at = bundle_directory(&staging, prefix, Some(&owned))?;
            let descriptor = fs::openat(&at, leaf,
                fs::OFlags::WRONLY | fs::OFlags::CREATE | fs::OFlags::EXCL | fs::OFlags::NOFOLLOW
                    | fs::OFlags::CLOEXEC | fs::OFlags::NONBLOCK,
                fs::Mode::from_raw_mode(0o600)).map_err(io)?;
            owned.insert(relative.clone(), (false, fs::fstat(&descriptor).map_err(io)?));
            let mut file = File::from(descriptor);
            #[cfg(test)]
            partial_publication_crash(&mut file, bytes)?;
            file.write_all(bytes).map_err(io)?;
            #[cfg(test)]
            publication_crash(PublicationCrashPoint::LeafWritten);
            file.sync_all().map_err(io)?;
            #[cfg(test)]
            publication_crash(PublicationCrashPoint::FileSynced);
        }
        for directory in layout.keys().rev() {
            fs::fsync(&bundle_directory(&staging, directory, Some(&owned))?).map_err(io)?;
        }
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::StageSynced);
        files::duplicate_directory(parent.as_fd()).map_err(io)?;
        match fs::renameat_with(&staging_parent, stage.as_str(), &parent, *name, fs::RenameFlags::NOREPLACE) {
            Ok(()) | Err(rustix::io::Errno::EXIST) => {}
            Err(error) => return Err(io(error)),
        }
        #[cfg(test)]
        publication_crash(PublicationCrashPoint::Renamed);
        fs::fsync(&parent).map_err(io)?;
        fs::fsync(&staging_parent).map_err(io)?;
        let final_directory = files::open_directory_at(&parent, OsStr::new(name)).map_err(io)?;
        verify_bundle(&final_directory, files, &layout)
    })();
    cleanup_bundle(&staging_parent, &stage, &staging, &owned)?;
    result
}

type BundleLayout = std::collections::BTreeMap<String, Vec<String>>;
fn bundle_layout(files: &std::collections::BTreeMap<String, Vec<u8>>, max_bytes: usize) -> Result<BundleLayout> {
    use std::collections::BTreeSet;
    if files.is_empty() || files.len() > MAX_ENTRIES || max_bytes == 0 || max_bytes > 512 * 1024 * 1024 {
        return Err(INVALID);
    }
    let mut remaining = max_bytes;
    let mut layout: std::collections::BTreeMap<String, BTreeSet<String>> = Default::default();
    layout.insert(String::new(), BTreeSet::new());
    for (path, bytes) in files {
        remaining = remaining.checked_sub(bytes.len()).ok_or(INVALID)?;
        let parts = path.split('/').collect::<Vec<_>>();
        if parts.len() > 32 || parts.iter().any(|p| p.is_empty() || p.len() > 255
            || matches!(*p, "." | "..") || p.contains('\\') || p.contains('\0')) {
            return Err(INVALID);
        }
        let mut prefix = String::new();
        for (index, part) in parts.iter().enumerate() {
            layout.entry(prefix.clone()).or_default().insert((*part).into());
            if !prefix.is_empty() { prefix.push('/'); }
            prefix.push_str(part);
            if index + 1 < parts.len() {
                if files.contains_key(&prefix) { return Err(INVALID); }
                layout.entry(prefix.clone()).or_default();
            }
        }
    }
    if layout.len().saturating_add(files.len()) > MAX_ENTRIES { return Err(INVALID); }
    let work = layout.values().flat_map(|names| names.iter()).try_fold(0_usize, |n,name| n.checked_add(1 + name.len())).ok_or(INVALID)?;
    if work > MAX_ENTRIES { return Err(INVALID); }
    Ok(layout.into_iter().map(|(k,v)|(k,v.into_iter().collect())).collect())
}
fn bundle_directory(
    root: &OwnedFd,
    relative: &str,
    owned: Option<&std::collections::BTreeMap<String, (bool, fs::Stat)>>,
) -> Result<OwnedFd> {
    use std::os::fd::AsFd;
    let mut at = files::duplicate_directory(root.as_fd()).map_err(io)?;
    let mut prefix = String::new();
    for part in relative.split('/').filter(|p| !p.is_empty()) {
        at = files::open_directory_at(&at, OsStr::new(part)).map_err(io)?;
        if !prefix.is_empty() { prefix.push('/'); }
        prefix.push_str(part);
        if let Some(owned) = owned {
            let (directory, expected) = owned.get(&prefix).ok_or(INVALID)?;
            let actual = fs::fstat(&at).map_err(io)?;
            if !directory || !bundle_inode(&actual, expected) { return Err(INVALID); }
        }
    }
    Ok(at)
}
fn bundle_inode(actual: &fs::Stat, expected: &fs::Stat) -> bool {
    actual.st_ino == expected.st_ino && actual.st_dev == expected.st_dev
}
fn verify_bundle(root: &OwnedFd, files: &std::collections::BTreeMap<String, Vec<u8>>, layout: &BundleLayout) -> Result<()> {
    use std::io::Read;
    let mut remaining = MAX_ENTRIES;
    for (relative, expected) in layout {
        if bundle_names(&bundle_directory(root, relative, None)?, &mut remaining)? != *expected { return Err(INVALID); }
    }
    for (relative, expected) in files {
        let (prefix, leaf) = relative.rsplit_once('/').unwrap_or(("", relative));
        let directory = bundle_directory(root, prefix, None)?;
        let descriptor = fs::openat(&directory, leaf,
            fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC | fs::OFlags::NONBLOCK,
            fs::Mode::empty()).map_err(io)?;
        let metadata = fs::fstat(&descriptor).map_err(io)?;
        if fs::FileType::from_raw_mode(metadata.st_mode) != fs::FileType::RegularFile
            || metadata.st_nlink != 1 || metadata.st_mode & 0o022 != 0
            || (metadata.st_uid != 0 && metadata.st_uid != rustix::process::geteuid().as_raw())
            || metadata.st_size < 0 || metadata.st_size as u64 != expected.len() as u64 { return Err(INVALID); }
        let mut file = File::from(descriptor);
        let mut offset = 0_usize;
        let mut buffer = [0_u8; 65536];
        loop {
            let length = file.read(&mut buffer).map_err(io)?;
            if length == 0 { break; }
            let end = offset.checked_add(length).filter(|end| *end <= expected.len()).ok_or(INVALID)?;
            if buffer[..length] != expected[offset..end] { return Err(INVALID); }
            offset = end;
        }
        if offset != expected.len() { return Err(INVALID); }
    }
    Ok(())
}
fn cleanup_bundle(parent: &OwnedFd, name: &str, root: &OwnedFd, owned: &std::collections::BTreeMap<String,(bool,fs::Stat)>) -> Result<()> {
    let current = match files::open_directory_at(parent, OsStr::new(name)) {
        Ok(fd) => fd,
        Err(files::ReadError::Missing) => return Ok(()),
        Err(error) => return Err(io(error)),
    };
    if !bundle_inode(&fs::fstat(root).map_err(io)?, &fs::fstat(&current).map_err(io)?) { return Err(INVALID); }
    let mut names: BundleLayout = Default::default();
    names.insert(String::new(), Vec::new());
    for (relative,(directory,_)) in owned {
        let (prefix,leaf)=relative.rsplit_once('/').unwrap_or(("",relative));
        names.entry(prefix.into()).or_default().push(leaf.into());
        if *directory { names.entry(relative.clone()).or_default(); }
    }
    // Never remove unrecognized files or a replacement inode, even under our stage.
    let mut remaining = MAX_ENTRIES;
    for (relative, children) in &mut names {
        children.sort();
        if bundle_names(&bundle_directory(root,relative,Some(owned))?, &mut remaining)? != *children { return Err(INVALID); }
    }
    for (relative,(directory,expected)) in owned.iter().rev() {
        let (prefix,leaf)=relative.rsplit_once('/').unwrap_or(("",relative));
        let at=bundle_directory(root,prefix,Some(owned))?;
        let actual=fs::statat(&at,leaf,fs::AtFlags::SYMLINK_NOFOLLOW).map_err(io)?;
        if !bundle_inode(&actual,expected) { return Err(INVALID); }
        fs::unlinkat(&at,leaf,if *directory {fs::AtFlags::REMOVEDIR}else{fs::AtFlags::empty()}).map_err(io)?;
        fs::fsync(&at).map_err(io)?;
    }
    let actual=fs::statat(parent,name,fs::AtFlags::SYMLINK_NOFOLLOW).map_err(io)?;
    if !bundle_inode(&actual,&fs::fstat(root).map_err(io)?) { return Err(INVALID); }
    fs::unlinkat(parent,name,fs::AtFlags::REMOVEDIR).map_err(io)?;
    fs::fsync(parent).map_err(io)
}

fn bundle_names(directory: &OwnedFd, remaining: &mut usize) -> Result<Vec<String>> {
    files::directory_entries(directory, remaining).map_err(io)?.into_iter()
        .map(|name| name.into_string().map_err(|_|INVALID)).collect()
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

#[cfg(test)]
mod selected_publication_tests {
    use super::*;
    use std::{os::fd::AsFd, os::unix::fs::PermissionsExt};

    #[test]
    fn selected_descriptor_put_is_exact_durable_and_keeps_the_original_namespace() {
        let mut nonce = [0_u8; 16];
        getrandom::fill(&mut nonce).unwrap();
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "use-test-selected-put-{}",
            nonce.iter().map(|b| format!("{b:02x}")).collect::<String>()
        ));
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let selected = files::open_directory(&path).unwrap();
        let value = serde_json::json!({"schema_version":1,"exact":"unchanged"});
        put_at(
            selected.as_fd(),
            &["history", "first"],
            "manifest.json",
            &value,
        )
        .unwrap();
        let first = path.join("history/first/manifest.json");
        let original = std::fs::read(&first).unwrap();
        put_at(
            selected.as_fd(),
            &["history", "first"],
            "manifest.json",
            &value,
        )
        .unwrap();
        assert_eq!(std::fs::read(&first).unwrap(), original);
        assert!(
            put_at(
                selected.as_fd(),
                &["history", "first"],
                "manifest.json",
                &serde_json::json!({"other":true})
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&first).unwrap(), original);
        let moved = path.with_extension("selected");
        std::fs::rename(&path, &moved).unwrap();
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        put_at(
            selected.as_fd(),
            &["history", "second"],
            "manifest.json",
            &value,
        )
        .unwrap();
        assert!(moved.join("history/second/manifest.json").is_file());
        assert!(!path.join("history").exists());
        let first = moved.join("history/first/manifest.json");
        std::fs::write(&first, b"{}\n").unwrap();
        assert!(
            put_at(
                selected.as_fd(),
                &["history", "first"],
                "manifest.json",
                &value
            )
            .is_err()
        );
        assert_eq!(std::fs::read(&first).unwrap(), b"{}\n");
        drop(selected);
        std::fs::remove_dir_all(&moved).unwrap();
        std::fs::remove_dir(&path).unwrap();
    }

    #[test]
    fn selected_descriptor_put_rejects_components_before_any_side_effect() {
        let mut nonce = [0_u8; 16];
        getrandom::fill(&mut nonce).unwrap();
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "use-test-invalid-put-{}",
            nonce.iter().map(|b| format!("{b:02x}")).collect::<String>()
        ));
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let selected = files::open_directory(&path).unwrap();
        for bad in [
            "",
            ".",
            "..",
            "../escape",
            "nested/path",
            "/absolute",
            "nul\0name",
        ] {
            assert!(
                put_at(
                    selected.as_fd(),
                    &["must-not-exist", bad],
                    "manifest.json",
                    &serde_json::json!({})
                )
                .is_err()
            );
            assert!(!path.join("must-not-exist").exists());
            assert!(
                put_at(
                    selected.as_fd(),
                    &["must-not-exist", "leaf"],
                    bad,
                    &serde_json::json!({})
                )
                .is_err()
            );
            assert!(!path.join("must-not-exist").exists());
        }
        assert!(
            put_at(
                selected.as_fd(),
                &[],
                "manifest.json",
                &serde_json::json!({})
            )
            .is_err()
        );
        drop(selected);
        std::fs::remove_dir(&path).unwrap();
    }
}

#[cfg(test)]
mod failed_stage_cleanup_tests {
    use super::*;
    use std::{os::fd::AsFd, os::unix::fs::PermissionsExt};
    #[test]
    fn leaf_open_failure_removes_only_its_empty_stage_and_keeps_parent_usable() {
        let mut nonce = [0u8; 16];
        getrandom::fill(&mut nonce).unwrap();
        let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "use-test-failed-stage-{}",
            nonce.iter().map(|b| format!("{b:02x}")).collect::<String>()
        ));
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let selected = files::open_directory(&path).unwrap();
        // A valid single component exceeds the filesystem name bound only when
        // opening the stage's leaf. No sleeps, retries or global fault state.
        assert!(
            put_at(
                selected.as_fd(),
                &["history", "first"],
                &"x".repeat(512),
                &serde_json::json!({"value":1})
            )
            .is_err()
        );
        assert!(
            std::fs::read_dir(path.join("history"))
                .unwrap()
                .next()
                .is_none()
        );
        assert!(
            std::fs::read_dir(path.join(".immutable-json-staging"))
                .unwrap()
                .next()
                .is_none()
        );
        put_at(
            selected.as_fd(),
            &["history", "first"],
            "manifest.json",
            &serde_json::json!({"value":1}),
        )
        .unwrap();
        assert!(path.join("history/first/manifest.json").is_file());
        drop(selected);
        std::fs::remove_dir_all(path).unwrap();
    }
}

#[cfg(test)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub(crate) enum PublicationCrashPoint {
    StageCreated,
    PartialWrite,
    LeafWritten,
    FileSynced,
    StageSynced,
    Renamed,
}
#[cfg(test)]
thread_local! { static PUBLICATION_CRASH: std::cell::Cell<Option<PublicationCrashPoint>> = const { std::cell::Cell::new(None) }; }
#[cfg(test)]
pub(crate) fn crash_publication_at_for_test(point: &str) -> Result<()> {
    let point = match point {
        "stage_created" => PublicationCrashPoint::StageCreated,
        "partial_write" => PublicationCrashPoint::PartialWrite,
        "leaf_written" => PublicationCrashPoint::LeafWritten,
        "file_synced" => PublicationCrashPoint::FileSynced,
        "stage_synced" => PublicationCrashPoint::StageSynced,
        "renamed" => PublicationCrashPoint::Renamed,
        _ => return Err(INVALID),
    };
    PUBLICATION_CRASH.with(|value| value.set(Some(point)));
    Ok(())
}
#[cfg(test)]
fn publication_crash(point: PublicationCrashPoint) {
    if PUBLICATION_CRASH.with(|value| value.get() == Some(point)) {
        std::process::exit(86);
    }
}
#[cfg(test)]
fn partial_publication_crash(file: &mut File, bytes: &[u8]) -> Result<()> {
    if PUBLICATION_CRASH.with(|value| value.get() == Some(PublicationCrashPoint::PartialWrite)) {
        file.write_all(&bytes[..bytes.len() / 2]).map_err(io)?;
        std::process::exit(86);
    }
    Ok(())
}

#[cfg(test)]
mod bundle_publication_tests {
    use super::*;
    use std::{collections::BTreeMap,os::fd::AsFd,os::unix::fs::{MetadataExt,PermissionsExt}};
    fn root()->PathBuf {
        let mut random=[0u8;16];getrandom::fill(&mut random).unwrap();
        let path=std::env::temp_dir().canonicalize().unwrap().join(format!("use-test-bundle-{}",random.iter().map(|b|format!("{b:02x}")).collect::<String>()));
        std::fs::create_dir(&path).unwrap();std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o700)).unwrap();path
    }
    fn bytes()->BTreeMap<String,Vec<u8>> {
        // Transport bytes only. This fixture makes no Arrow/Parquet or Evidence claim.
        BTreeMap::from([("manifest.json".into(),canonical(&serde_json::json!({"schema_version":1,"transport":"exact"})).unwrap().into_bytes()),
            ("data/p-000000.part".into(),b"first physical partition".to_vec()),("data/p-000001.part".into(),b"second physical partition".to_vec())])
    }
    fn check(path:&Path,expected:&BTreeMap<String,Vec<u8>>) {
        for (name,raw) in expected {assert_eq!(std::fs::read(path.join(name)).unwrap(),*raw);}
        assert_eq!(std::fs::read_dir(path).unwrap().count(),2);
        assert_eq!(std::fs::read_dir(path.join("data")).unwrap().count(),2);
    }
    #[test]
    fn descriptor_bundle_is_exact_replays_without_rewrite_and_keeps_selected_root() {
        let path=root();let selected=files::open_directory(&path).unwrap();let payload=bytes();
        put_bundle_at(selected.as_fd(),&["owner","sha256","aa","first"],&payload,8192).unwrap();
        let target=path.join("owner/sha256/aa/first");check(&target,&payload);
        let inode=std::fs::metadata(target.join("data/p-000000.part")).unwrap().ino();
        put_bundle_at(selected.as_fd(),&["owner","sha256","aa","first"],&payload,8192).unwrap();
        assert_eq!(std::fs::metadata(target.join("data/p-000000.part")).unwrap().ino(),inode);
        let moved=path.with_extension("retained");std::fs::rename(&path,&moved).unwrap();std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o700)).unwrap();
        put_bundle_at(selected.as_fd(),&["owner","sha256","aa","second"],&payload,8192).unwrap();
        check(&moved.join("owner/sha256/aa/second"),&payload);assert!(std::fs::read_dir(&path).unwrap().next().is_none());
        std::fs::write(moved.join("owner/sha256/aa/first/data/p-000000.part"),b"corrupt").unwrap();
        assert!(put_bundle_at(selected.as_fd(),&["owner","sha256","aa","first"],&payload,8192).is_err());
        assert_eq!(std::fs::read(moved.join("owner/sha256/aa/first/data/p-000000.part")).unwrap(),b"corrupt");
        drop(selected);std::fs::remove_dir_all(moved).unwrap();std::fs::remove_dir(path).unwrap();
    }
    #[test]
    fn bundle_invalid_paths_prefix_collisions_and_total_budget_have_no_side_effects() {
        let path=root();let selected=files::open_directory(&path).unwrap();
        for name in ["","../escape","/absolute","data//part","data/./part","data/../part","data\\part","nul\0part"] {
            let mut payload=bytes();payload.insert(name.into(),b"rejected".to_vec());
            assert!(put_bundle_at(selected.as_fd(),&["must-not-exist","first"],&payload,8192).is_err(),"{name:?}");
            assert!(std::fs::read_dir(&path).unwrap().next().is_none());
        }
        let mut collision=bytes();collision.insert("data".into(),b"not a directory".to_vec());
        assert!(put_bundle_at(selected.as_fd(),&["must-not-exist","first"],&collision,8192).is_err());
        assert!(put_bundle_at(selected.as_fd(),&["must-not-exist","first"],&bytes(),1).is_err());
        assert!(put_bundle_at(selected.as_fd(),&["must-not-exist","first"],&BTreeMap::new(),8192).is_err());
        assert!(std::fs::read_dir(&path).unwrap().next().is_none());
        drop(selected);std::fs::remove_dir(path).unwrap();
    }
    #[test]
    fn bundle_publication_preserves_unknown_auxiliary_stage_and_rejects_unexpected_final_files() {
        let path=root();let selected=files::open_directory(&path).unwrap();let payload=bytes();
        let unknown=path.join(".immutable-json-staging/.stage-ffffffffffffffffffffffffffffffff");std::fs::create_dir_all(&unknown).unwrap();
        std::fs::set_permissions(unknown.parent().unwrap(),std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::set_permissions(&unknown,std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::write(unknown.join("unrecognized"),b"retain unknown owner").unwrap();
        put_bundle_at(selected.as_fd(),&["owner","sha256","aa","first"],&payload,8192).unwrap();
        assert_eq!(std::fs::read(unknown.join("unrecognized")).unwrap(),b"retain unknown owner");
        let target=path.join("owner/sha256/aa/first");std::fs::write(target.join("unexpected"),b"not a declared file").unwrap();
        assert!(put_bundle_at(selected.as_fd(),&["owner","sha256","aa","first"],&payload,8192).is_err());
        assert_eq!(std::fs::read(target.join("unexpected")).unwrap(),b"not a declared file");
        drop(selected);std::fs::remove_dir_all(path).unwrap();
    }
    #[test]
    fn bundle_actual_process_exit_probe() {
        let Ok(path)=std::env::var("ONLYALPHA_USE_TEST_BUNDLE_ROOT") else {return;};
        let selected=files::open_directory(Path::new(&path)).unwrap();
        crash_publication_at_for_test(&std::env::var("ONLYALPHA_USE_TEST_BUNDLE_POINT").unwrap()).unwrap();
        let _=put_bundle_at(selected.as_fd(),&["owner","sha256","aa","original"],&bytes(),8192);
        panic!("actual publication crash point was not reached");
    }
    #[test]
    fn bundle_mid_publication_process_exit_preserves_original_identity_and_unknown_stage() {
        for point in ["stage_created","partial_write","leaf_written","file_synced","stage_synced","renamed"] {
            let path=root();let payload=bytes();
            let status=std::process::Command::new(std::env::current_exe().unwrap())
                .args(["--exact","security::immutable_json::bundle_publication_tests::bundle_actual_process_exit_probe","--nocapture"])
                .env("ONLYALPHA_USE_TEST_BUNDLE_ROOT",&path).env("ONLYALPHA_USE_TEST_BUNDLE_POINT",point).status().unwrap();
            assert_eq!(status.code(),Some(86),"{point}");
            let auxiliary=path.join(".immutable-json-staging");
            let stages=std::fs::read_dir(&auxiliary).unwrap().map(|e|e.unwrap().path()).collect::<Vec<_>>();
            assert_eq!(stages.len(),usize::from(point!="renamed"));
            let selected=files::open_directory(&path).unwrap();
            put_bundle_at(selected.as_fd(),&["owner","sha256","aa","original"],&payload,8192).unwrap();
            check(&path.join("owner/sha256/aa/original"),&payload);
            for stage in stages {assert!(stage.is_dir(),"unknown prior process stage must remain retained");}
            assert_eq!(std::fs::read_dir(path.join("owner/sha256/aa")).unwrap().count(),1);
            drop(selected);std::fs::remove_dir_all(path).unwrap();
        }
    }
}
