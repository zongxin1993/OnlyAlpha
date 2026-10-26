//! Immutable presentation bytes from an explicitly selected Shipping build.
//! This owns no Product/Trading facts, startup readiness or authentication.
use crate::security::protected_files::{
    FilePolicy, ReadError, open_directory, open_directory_at, read_file_at,
};
use axum::{
    Router,
    body::{Body, Bytes},
    extract::State,
    response::{IntoResponse, Response},
    routing::get,
};
use http::{StatusCode, Uri, header};
use rustix::fs::{AtFlags, Dir, FileType, statat};
use std::{collections::BTreeMap, ffi::OsStr, fmt, os::fd::OwnedFd, path::Path, sync::Arc};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Missing,
    Invalid,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "DEV_WEB_BUILD_MISSING",
            Self::Invalid => "DEV_WEB_BUILD_INVALID",
            Self::Unavailable => "DEV_WEB_BUILD_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<ReadError> for Error {
    fn from(error: ReadError) -> Self {
        match error {
            ReadError::Missing => Self::Missing,
            ReadError::Invalid => Self::Invalid,
            ReadError::Unavailable => Self::Unavailable,
        }
    }
}
struct Asset {
    bytes: Bytes,
    mime: &'static str,
}
pub struct Assets {
    files: BTreeMap<String, Asset>,
}
impl Assets {
    /// Open protected descriptors once, load a bounded complete build, then serve
    /// these exact bytes. Later path replacement cannot select a new build.
    pub fn load(root: &Path, max_work: usize) -> Result<Self, Error> {
        if max_work == 0 {
            return Err(Error::Unavailable);
        }
        let root = open_directory(root)?;
        let mut remaining = max_work;
        let index = read_file_at(
            &root,
            OsStr::new("index.html"),
            FilePolicy::Asset,
            remaining,
        )?;
        if index.is_empty() || std::str::from_utf8(&index).is_err() {
            return Err(Error::Invalid);
        }
        charge(&mut remaining, 1, index.len())?;
        let mut files = BTreeMap::from([(
            "/".into(),
            Asset {
                bytes: Bytes::from(index.to_vec()),
                mime: "text/html; charset=utf-8",
            },
        )]);
        let assets = open_directory_at(&root, OsStr::new("assets"))?;
        let mut entries = 1024;
        collect(
            &assets,
            "/assets",
            0,
            &mut remaining,
            &mut entries,
            &mut files,
        )?;
        Ok(Self { files })
    }
    /// Mount only behind the common owning ingress. It supplies normal guarded
    /// navigation/bootstrap and Human identity, then fences physical release.
    pub fn router(self) -> Router {
        Router::new()
            .route("/", get(serve))
            .route("/assets/{*path}", get(serve))
            .with_state(Arc::new(self))
    }
}
fn charge(remaining: &mut usize, name: usize, bytes: usize) -> Result<(), Error> {
    let cost = name
        .checked_add(bytes)
        .and_then(|n| n.checked_add(64))
        .ok_or(Error::Unavailable)?;
    *remaining = remaining.checked_sub(cost).ok_or(Error::Unavailable)?;
    Ok(())
}
fn collect(
    directory: &OwnedFd,
    prefix: &str,
    depth: usize,
    remaining: &mut usize,
    entries: &mut usize,
    files: &mut BTreeMap<String, Asset>,
) -> Result<(), Error> {
    if depth >= 8 {
        return Err(Error::Unavailable);
    }
    let mut names = Vec::new();
    for entry in Dir::read_from(directory).map_err(|_| Error::Unavailable)? {
        let entry = entry.map_err(|_| Error::Unavailable)?;
        let name = entry.file_name().to_str().map_err(|_| Error::Invalid)?;
        if matches!(name, "." | "..") {
            continue;
        }
        *entries = entries.checked_sub(1).ok_or(Error::Unavailable)?;
        charge(remaining, name.len(), 0)?;
        if name.starts_with('.')
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'-' | b'_'))
        {
            return Err(Error::Invalid);
        }
        names.push(name.to_owned());
    }
    names.sort();
    for name in names {
        let metadata = statat(directory, name.as_str(), AtFlags::SYMLINK_NOFOLLOW)
            .map_err(|_| Error::Unavailable)?;
        let path = format!("{prefix}/{name}");
        match FileType::from_raw_mode(metadata.st_mode) {
            FileType::Directory => {
                let child = open_directory_at(directory, OsStr::new(&name))?;
                collect(&child, &path, depth + 1, remaining, entries, files)?;
            }
            FileType::RegularFile => {
                let mime = mime(&name).ok_or(Error::Invalid)?;
                let bytes =
                    read_file_at(directory, OsStr::new(&name), FilePolicy::Asset, *remaining)?;
                charge(remaining, path.len(), bytes.len())?;
                files.insert(
                    path,
                    Asset {
                        bytes: Bytes::from(bytes.to_vec()),
                        mime,
                    },
                );
            }
            _ => return Err(Error::Invalid),
        }
    }
    Ok(())
}
fn mime(name: &str) -> Option<&'static str> {
    Some(match name.rsplit_once('.')?.1 {
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "avif" => "image/avif",
        "ico" => "image/x-icon",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        _ => return None,
    })
}
async fn serve(State(assets): State<Arc<Assets>>, uri: Uri) -> Response {
    let Some(path) = crate::security::ingress::decoded_path(&uri) else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Some(asset) = assets.files.get(&path) else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let mut response = Body::from(asset.bytes.clone()).into_response();
    let headers = response.headers_mut();
    headers.insert(
        header::CONTENT_TYPE,
        http::HeaderValue::from_static(asset.mime),
    );
    headers.insert(header::CONTENT_LENGTH, asset.bytes.len().into());
    headers.insert(
        header::CACHE_CONTROL,
        http::HeaderValue::from_static("no-store"),
    );
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        http::HeaderValue::from_static("nosniff"),
    );
    response
}
