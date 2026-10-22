//! Descriptor-relative protected reads shared by actual startup and history consumers.
use rustix::fs::{FileType, Mode, OFlags, Stat, fstat, open, openat};
use std::{
    ffi::{OsStr, OsString},
    fs::File,
    io::Read,
    os::fd::{AsFd, BorrowedFd, OwnedFd},
    path::{Component, Path},
};
use zeroize::Zeroizing;
fn trusted_directory(metadata: &Stat, uid: u32) -> bool {
    let shared_root = metadata.st_uid == 0 && metadata.st_mode & 0o1000 != 0;
    FileType::from_raw_mode(metadata.st_mode) == FileType::Directory
        && (metadata.st_uid == 0 || metadata.st_uid == uid)
        && (metadata.st_mode & 0o022 == 0 || shared_root)
}
#[derive(Clone, Copy)]
pub enum FilePolicy {
    Secret,
    Metadata,
    Asset,
    HistoryDocument,
    /// Actual native program image only; assets and history retain their 8 MiB bound.
    Executable,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadError {
    Missing,
    Invalid,
    Unavailable,
}
impl From<rustix::io::Errno> for ReadError {
    fn from(error: rustix::io::Errno) -> Self {
        match error {
            rustix::io::Errno::NOENT => Self::Missing,
            rustix::io::Errno::LOOP | rustix::io::Errno::NOTDIR => Self::Invalid,
            _ => Self::Unavailable,
        }
    }
}
impl From<std::io::Error> for ReadError {
    fn from(_: std::io::Error) -> Self {
        Self::Unavailable
    }
}
fn trusted_file(metadata: &Stat, uid: u32, policy: FilePolicy) -> bool {
    FileType::from_raw_mode(metadata.st_mode) == FileType::RegularFile
        && (metadata.st_uid == 0 || metadata.st_uid == uid)
        && match policy {
            FilePolicy::Secret => metadata.st_mode & 0o077 == 0 && metadata.st_nlink == 1,
            // The existing atomic namespace publisher uses hard links; read sharing is safe.
            FilePolicy::Metadata | FilePolicy::HistoryDocument => metadata.st_mode & 0o022 == 0,
            FilePolicy::Asset => metadata.st_mode & 0o022 == 0 && metadata.st_nlink == 1,
            FilePolicy::Executable => {
                metadata.st_mode & 0o022 == 0
                    && metadata.st_mode & 0o111 != 0
                    && metadata.st_nlink == 1
            }
        }
}
pub fn read_protected(path: &Path) -> Result<Zeroizing<Vec<u8>>, ReadError> {
    read_file(path, FilePolicy::Secret)
}
fn path_names(path: &Path) -> Result<Vec<&OsStr>, ReadError> {
    // Reject raw parent/current segments before Path normalizes '.' away.
    use std::os::unix::ffi::OsStrExt;
    if !path.is_absolute()
        || path
            .as_os_str()
            .as_bytes()
            .split(|byte| *byte == b'/')
            .any(|part| part == b"." || part == b"..")
    {
        return Err(ReadError::Invalid);
    }
    let mut parts = path.components();
    if parts.next() != Some(Component::RootDir) {
        return Err(ReadError::Invalid);
    }
    parts
        .map(|component| match component {
            Component::Normal(name) => Ok(name),
            _ => Err(ReadError::Invalid),
        })
        .collect()
}
pub fn open_directory(path: &Path) -> Result<OwnedFd, ReadError> {
    open_directory_components(&path_names(path)?)
}
pub fn open_directory_at(parent: &impl AsFd, name: &OsStr) -> Result<OwnedFd, ReadError> {
    component(name)?;
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let directory = openat(parent, name, flags, Mode::empty())?;
    if !trusted_directory(&fstat(&directory)?, rustix::process::geteuid().as_raw()) {
        return Err(ReadError::Invalid);
    }
    Ok(directory)
}
fn open_directory_components(names: &[&OsStr]) -> Result<OwnedFd, ReadError> {
    let uid = rustix::process::geteuid().as_raw();
    let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let mut directory = open("/", flags, Mode::empty())?;
    if !trusted_directory(&fstat(&directory)?, uid) {
        return Err(ReadError::Invalid);
    }
    for name in names {
        directory = open_directory_at(&directory, name)?;
    }
    Ok(directory)
}
pub fn read_file(path: &Path, policy: FilePolicy) -> Result<Zeroizing<Vec<u8>>, ReadError> {
    let names = path_names(path)?;
    let (leaf, parents) = names.split_last().ok_or(ReadError::Invalid)?;
    let directory = open_directory_components(parents)?;
    read_file_at(&directory, leaf, policy, 32768)
}
pub fn read_file_at(
    directory: &impl AsFd,
    leaf: &OsStr,
    policy: FilePolicy,
    limit: usize,
) -> Result<Zeroizing<Vec<u8>>, ReadError> {
    component(leaf)?;
    let descriptor = openat(
        directory,
        leaf,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
        Mode::empty(),
    )?;
    let metadata = fstat(&descriptor)?;
    if !trusted_file(&metadata, rustix::process::geteuid().as_raw(), policy) {
        return Err(ReadError::Invalid);
    }
    let size_error = match policy {
        FilePolicy::Secret => ReadError::Invalid,
        FilePolicy::Metadata
        | FilePolicy::Asset
        | FilePolicy::HistoryDocument
        | FilePolicy::Executable => ReadError::Unavailable,
    };
    let limit = limit.min(match policy {
        FilePolicy::Asset | FilePolicy::HistoryDocument => 8 * 1024 * 1024,
        FilePolicy::Secret | FilePolicy::Metadata => 32768,
        FilePolicy::Executable => 128 * 1024 * 1024,
    });
    if matches!(policy, FilePolicy::Secret) && metadata.st_size == 0 {
        return Err(ReadError::Invalid);
    }
    if metadata.st_size < 0 || metadata.st_size as u64 > limit as u64 {
        return Err(size_error);
    }
    let mut data = Zeroizing::new(Vec::new());
    File::from(descriptor)
        .take(limit as u64 + 1)
        .read_to_end(&mut data)?;
    if matches!(policy, FilePolicy::Secret) && data.is_empty() {
        return Err(ReadError::Invalid);
    }
    if data.len() > limit {
        return Err(size_error);
    }
    Ok(data)
}

fn component(name: &OsStr) -> Result<(), ReadError> {
    use std::os::unix::ffi::OsStrExt;
    let raw = name.as_bytes();
    if raw.is_empty() || raw == b"." || raw == b".." || raw.contains(&b'/') {
        return Err(ReadError::Invalid);
    }
    Ok(())
}

/// Validate and duplicate a selected directory with atomic close-on-exec.
pub fn duplicate_directory(directory: BorrowedFd<'_>) -> Result<OwnedFd, ReadError> {
    if !trusted_directory(&fstat(directory)?, rustix::process::geteuid().as_raw()) {
        return Err(ReadError::Invalid);
    }
    rustix::fs::accessat(
        directory,
        ".",
        rustix::fs::Access::READ_OK | rustix::fs::Access::EXEC_OK,
        rustix::fs::AtFlags::EACCESS,
    )?;
    directory.try_clone_to_owned().map_err(ReadError::from)
}

/// Enumerate a held history directory within the caller's cumulative work budget.
pub(crate) fn directory_entries(
    directory: &impl AsFd,
    remaining: &mut usize,
) -> Result<Vec<OsString>, ReadError> {
    use std::os::unix::ffi::OsStrExt;
    let mut result = Vec::new();
    for entry in rustix::fs::Dir::read_from(directory)? {
        let entry = entry?;
        let raw = entry.file_name().to_bytes();
        if raw == b"." || raw == b".." {
            continue;
        }
        *remaining = remaining
            .checked_sub(1 + raw.len())
            .ok_or(ReadError::Unavailable)?;
        if result.len() >= 4096 {
            return Err(ReadError::Unavailable);
        }
        result.push(OsStr::from_bytes(raw).to_owned());
    }
    result.sort();
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metadata_owner_policy_is_not_just_file_permissions() {
        // Actual metadata structure comes from a held descriptor; only scalar
        // policy fields are varied here, without privileged filesystem changes.
        let descriptor = open("/", OFlags::RDONLY | OFlags::DIRECTORY, Mode::empty()).unwrap();
        let mut metadata = fstat(&descriptor).unwrap();
        metadata.st_uid = 1234;
        metadata.st_mode = 0o040700;
        assert!(trusted_directory(&metadata, 1234));
        assert!(!trusted_directory(&metadata, 5678));
        metadata.st_mode = 0o041777;
        assert!(!trusted_directory(&metadata, 1234));
        metadata.st_uid = 0;
        assert!(trusted_directory(&metadata, 5678));
        metadata.st_mode = 0o100600;
        metadata.st_nlink = 1;
        metadata.st_size = 100;
        metadata.st_uid = 1234;
        assert!(trusted_file(&metadata, 1234, FilePolicy::Secret));
        assert!(!trusted_file(&metadata, 5678, FilePolicy::Secret));
    }
}

#[cfg(test)]
mod executable_tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    #[test]
    fn executable_bound_does_not_expand_asset_or_history_reads() {
        let root =
            std::env::temp_dir().join(format!("onlyalpha-executable-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let path = root.join("native");
        let file = std::fs::File::create(&path).unwrap();
        // Actual release is 22,293,888 bytes; the regression crosses the old 8 MiB cap.
        file.set_len(22_293_888).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let directory = open_directory(&root).unwrap();
        for policy in [FilePolicy::Asset, FilePolicy::HistoryDocument] {
            assert_eq!(
                read_file_at(&directory, OsStr::new("native"), policy, 128 * 1024 * 1024)
                    .unwrap_err(),
                ReadError::Unavailable
            );
        }
        assert_eq!(
            read_file_at(
                &directory,
                OsStr::new("native"),
                FilePolicy::Executable,
                128 * 1024 * 1024
            )
            .unwrap()
            .len(),
            22_293_888
        );
        assert_eq!(
            read_file_at(
                &directory,
                OsStr::new("native"),
                FilePolicy::Executable,
                1024
            )
            .unwrap_err(),
            ReadError::Unavailable
        );
        file.set_len(128 * 1024 * 1024 + 1).unwrap();
        assert_eq!(
            read_file_at(
                &directory,
                OsStr::new("native"),
                FilePolicy::Executable,
                usize::MAX
            )
            .unwrap_err(),
            ReadError::Unavailable
        );
        file.set_len(1).unwrap();
        for mode in [0o600, 0o722] {
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
            assert_eq!(
                read_file_at(
                    &directory,
                    OsStr::new("native"),
                    FilePolicy::Executable,
                    128 * 1024 * 1024
                )
                .unwrap_err(),
                ReadError::Invalid
            );
        }
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::hard_link(&path, root.join("alias")).unwrap();
        assert_eq!(
            read_file_at(
                &directory,
                OsStr::new("native"),
                FilePolicy::Executable,
                128 * 1024 * 1024
            )
            .unwrap_err(),
            ReadError::Invalid
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
