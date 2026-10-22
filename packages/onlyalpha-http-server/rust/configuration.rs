//! Protected startup configuration. Errors never contain file paths or credentials.
use http::Uri;
use onlyalpha_product_runtime::credentials::Key;
use onlyalpha_product_runtime::protected_files::{
    FilePolicy, ReadError, open_directory, read_file_at, read_protected,
};
use onlyalpha_product_runtime::source_access::{
    Authority, Grant, Permission, Reference, Selection,
};
use serde::de::{MapAccess, Visitor, value::MapAccessDeserializer};
use serde::{Deserialize, Deserializer};
use sha2::{Digest, Sha256};
use std::ffi::OsStr;
use std::fmt;
use std::marker::PhantomData;
use std::os::fd::OwnedFd;
use std::path::Path;
use subtle::ConstantTimeEq;
use zeroize::Zeroizing;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidConfiguration,
}
impl Error {
    pub fn code(self) -> &'static str {
        "LOCAL_READ_CONFIG_INVALID"
    }
}
impl fmt::Display for Error {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(self.code())
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MasterKeyFileError {
    Missing,
    Invalid,
}
impl MasterKeyFileError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "CREDENTIAL_MASTER_KEY_MISSING",
            Self::Invalid => "CREDENTIAL_MASTER_KEY_INVALID",
        }
    }
}
impl fmt::Display for MasterKeyFileError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(self.code())
    }
}
impl std::error::Error for MasterKeyFileError {}

/// Load the existing runtime key, never initialize or repair deployment state.
/// The same descriptor-relative protection applies to every path component.
pub fn load_master_key(path: &Path) -> Result<Key, MasterKeyFileError> {
    decode_master_key(read_protected(path))
}
pub(crate) fn load_master_key_at(directory: &OwnedFd) -> Result<Key, MasterKeyFileError> {
    decode_master_key(read_file_at(
        directory,
        OsStr::new("dev-master-key"),
        FilePolicy::Secret,
        32768,
    ))
}
fn decode_master_key(
    data: Result<Zeroizing<Vec<u8>>, ReadError>,
) -> Result<Key, MasterKeyFileError> {
    let data = data.map_err(|error| {
        if error == ReadError::Missing {
            MasterKeyFileError::Missing
        } else {
            MasterKeyFileError::Invalid
        }
    })?;
    Key::new(&data).map_err(|_| MasterKeyFileError::Invalid)
}

/// Snapshot the explicitly selected, protected SQL directory. This does not
/// initialize a database or establish node readiness.
pub fn load_schema_history(
    root: &Path,
    max_work: usize,
) -> Result<
    onlyalpha_product_runtime::schema::SchemaHistory,
    onlyalpha_product_runtime::schema::Error,
> {
    use onlyalpha_product_runtime::schema::{Error, SchemaHistory};
    use std::os::unix::ffi::OsStrExt;
    let invalid_root = |error| match error {
        ReadError::Missing | ReadError::Invalid => Error::Integrity,
        ReadError::Unavailable => Error::Unavailable,
    };
    let directory = open_directory(root).map_err(invalid_root)?;
    let entries = rustix::fs::Dir::read_from(&directory).map_err(|_| Error::Unavailable)?;
    let mut remaining = max_work;
    let mut sources = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|_| Error::Unavailable)?;
        let name = entry.file_name().to_bytes();
        if name == b"." || name == b".." {
            continue;
        }
        remaining = remaining
            .checked_sub(name.len())
            .ok_or(Error::Unavailable)?;
        if name.len() < 9
            || !name[..4].iter().all(u8::is_ascii_digit)
            || name[4] != b'_'
            || !name.ends_with(b".sql")
        {
            continue;
        }
        let text = std::str::from_utf8(name).map_err(|_| Error::Integrity)?;
        remaining = remaining.checked_sub(64).ok_or(Error::Unavailable)?;
        let data = read_file_at(
            &directory,
            OsStr::from_bytes(name),
            FilePolicy::Metadata,
            remaining.min(32768),
        )
        .map_err(|error| match error {
            ReadError::Invalid => Error::Integrity,
            ReadError::Missing | ReadError::Unavailable => Error::Unavailable,
        })?;
        remaining = remaining
            .checked_sub(data.len())
            .ok_or(Error::Unavailable)?;
        sources.push((text[..text.len() - 4].to_owned(), data.to_vec()));
    }
    SchemaHistory::from_sql(sources, max_work)
}

pub struct Configuration {
    authority: Authority,
    origin: String,
    host_header: String,
}
impl Configuration {
    pub fn authority(&self) -> &Authority {
        &self.authority
    }
    pub fn origin(&self) -> &str {
        &self.origin
    }
    pub fn host_header(&self) -> &str {
        &self.host_header
    }

    /// Snapshot the protected file once. No fallback, watcher, or credential generation.
    pub fn load(path: &Path, excluded_credentials: &[&str]) -> Result<Self, Error> {
        let data = read_protected(path).map_err(|_| Error::InvalidConfiguration)?;
        let Object(dto): Object<ConfigurationDto> =
            serde_json::from_slice(&data).map_err(|_| Error::InvalidConfiguration)?;
        if dto.schema_version != 1 || !(1..=32).contains(&dto.grants.len()) {
            return Err(Error::InvalidConfiguration);
        }
        let host_header = origin_host(&dto.origin).ok_or(Error::InvalidConfiguration)?;
        for credential in excluded_credentials
            .iter()
            .filter(|value| !value.is_empty())
        {
            let digest: String = Sha256::digest(credential.as_bytes())
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            if bool::from(digest.as_bytes().ct_eq(dto.bearer_sha256.as_bytes())) {
                return Err(Error::InvalidConfiguration);
            }
        }
        let grants = dto
            .grants
            .into_iter()
            .map(|Object(grant)| {
                let reference = Reference::new(
                    &grant.integration_id,
                    &grant.integration_revision_fingerprint,
                    Some(&grant.expected_type_id),
                )?;
                let selection = Selection::new(reference, &grant.source_id, &grant.environment)?;
                Grant::new(
                    selection,
                    grant
                        .permissions
                        .into_iter()
                        .map(|permission| match permission {
                            PermissionDto::ClosedHistory => Permission::ClosedHistory,
                            PermissionDto::RealtimePreview => Permission::RealtimePreview,
                        })
                        .collect(),
                )
            })
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| Error::InvalidConfiguration)?;
        let authority = Authority::new(&dto.subject_id, &dto.bearer_sha256, grants)
            .map_err(|_| Error::InvalidConfiguration)?;
        Ok(Self {
            authority,
            origin: dto.origin,
            host_header,
        })
    }
}

// Derived struct visitors also accept positional arrays. This map-only wrapper
// delegates field handling directly, preserving duplicate detection at every level.
struct Object<T>(T);
impl<'de, T: Deserialize<'de>> Deserialize<'de> for Object<T> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ObjectVisitor<T>(PhantomData<T>);
        impl<'de, T: Deserialize<'de>> Visitor<'de> for ObjectVisitor<T> {
            type Value = Object<T>;
            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("an object")
            }
            fn visit_map<M: MapAccess<'de>>(self, map: M) -> Result<Self::Value, M::Error> {
                T::deserialize(MapAccessDeserializer::new(map)).map(Object)
            }
        }
        deserializer.deserialize_map(ObjectVisitor(PhantomData))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigurationDto {
    schema_version: u8,
    subject_id: String,
    bearer_sha256: String,
    origin: String,
    grants: Vec<Object<GrantDto>>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GrantDto {
    integration_id: String,
    integration_revision_fingerprint: String,
    expected_type_id: String,
    source_id: String,
    environment: String,
    permissions: Vec<PermissionDto>,
}
#[derive(Deserialize)]
#[serde(try_from = "String")]
enum PermissionDto {
    ClosedHistory,
    RealtimePreview,
}
impl TryFrom<String> for PermissionDto {
    type Error = &'static str;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        match value.as_str() {
            "CLOSED_HISTORY" => Ok(Self::ClosedHistory),
            "REALTIME_PREVIEW" => Ok(Self::RealtimePreview),
            _ => Err("invalid permission"),
        }
    }
}

fn origin_host(origin: &str) -> Option<String> {
    if origin.len() > 256 || !origin.is_ascii() {
        return None;
    }
    let (scheme, authority) = origin.split_once("://")?;
    if !(scheme.eq_ignore_ascii_case("http") || scheme.eq_ignore_ascii_case("https"))
        || authority.is_empty()
        || authority.bytes().any(|byte| {
            byte <= b' ' || byte == 127 || matches!(byte, b'@' | b'/' | b'?' | b'#' | b'\\')
        })
    {
        return None;
    }
    let uri: Uri = origin.parse().ok()?;
    let parsed = uri.authority()?;
    let host = parsed.host();
    if !["localhost", "127.0.0.1", "[::1]"]
        .iter()
        .any(|allowed| host.eq_ignore_ascii_case(allowed))
    {
        return None;
    }
    // The maintained parser returns None for both absent and invalid ports.
    // Require any suffix after the parsed host to be an explicit valid port.
    let suffix = authority.get(host.len()..)?;
    if !suffix.is_empty() {
        let port = suffix.strip_prefix(':')?;
        if port.is_empty()
            || !port.bytes().all(|byte| byte.is_ascii_digit())
            || parsed.port_u16().is_none()
        {
            return None;
        }
    }
    Some(authority.to_owned())
}

/// Exact release artifact digest. No trimming or alternate metadata authority.
pub fn parse_algorithm_artifact(bytes: &[u8]) -> Result<String, Error> {
    let bytes = bytes.strip_suffix(b"\n").unwrap_or(bytes);
    if bytes.len() != 64
        || !bytes
            .iter()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(b))
    {
        return Err(Error::InvalidConfiguration);
    }
    String::from_utf8(bytes.to_vec()).map_err(|_| Error::InvalidConfiguration)
}
pub fn load_algorithm_artifact(path: &Path) -> Result<String, Error> {
    let parent = path.parent().ok_or(Error::InvalidConfiguration)?;
    let name = path.file_name().ok_or(Error::InvalidConfiguration)?;
    let directory = open_directory(parent).map_err(|_| Error::InvalidConfiguration)?;
    let bytes = read_file_at(&directory, name, FilePolicy::Asset, 65)
        .map_err(|_| Error::InvalidConfiguration)?;
    parse_algorithm_artifact(&bytes)
}

#[cfg(test)]
mod artifact_digest_tests {
    #[test]
    fn artifact_file_has_one_exact_lowercase_digest() {
        let digest = "a".repeat(64);
        assert_eq!(
            super::parse_algorithm_artifact(digest.as_bytes()).unwrap(),
            digest
        );
        assert_eq!(
            super::parse_algorithm_artifact(format!("{digest}\n").as_bytes()).unwrap(),
            digest
        );
        for bad in [
            "a".repeat(63),
            "A".repeat(64),
            format!("{digest}\n\n"),
            format!(" {digest}"),
            format!("{digest}\0"),
            format!("{digest}\r\n"),
        ] {
            assert!(super::parse_algorithm_artifact(bad.as_bytes()).is_err());
        }
    }
}
