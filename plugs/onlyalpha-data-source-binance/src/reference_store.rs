//! 在调用方提供的私有根目录中发布与验证不可变 Spot 原始证据及语义资源。
use crate::reference_capture::{ReferenceCapture, rows, text};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_market_crypto::reference::{Kind, Reference, Result, raw_sha256, read_json};
use serde_json::{Value, json};
use std::{
    fs,
    io::{ErrorKind, Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

const RAW: [&str; 2] = ["exchangeInfo.json", "executionRules.json"];
const MAX: u64 = 16 * 1024 * 1024;
static STAGE: AtomicU64 = AtomicU64::new(0);
fn digest(id: &str) -> Result<()> {
    if id.len() == 64
        && id
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        Ok(())
    } else {
        Err("BINANCE_REFERENCE_DIGEST")
    }
}
fn directory(p: &Path) -> Result<()> {
    let m = fs::symlink_metadata(p).map_err(|_| "BINANCE_REFERENCE_DIRECTORY_UNAVAILABLE")?;
    if !m.file_type().is_dir() {
        return Err("BINANCE_REFERENCE_DIRECTORY_INVALID");
    }
    Ok(())
}
fn make_dir(p: &Path) -> Result<()> {
    match fs::create_dir(p) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == ErrorKind::AlreadyExists => directory(p),
        Err(_) => Err("BINANCE_REFERENCE_DIRECTORY_UNAVAILABLE"),
    }
}
fn path(root: &Path, kind: &str, id: &str) -> Result<PathBuf> {
    digest(id)?;
    directory(root)?;
    let parent = root.join(kind);
    directory(&parent)?;
    let target = parent.join(id);
    directory(&target)?;
    Ok(target)
}
fn read(p: &Path) -> Result<Vec<u8>> {
    let m = fs::symlink_metadata(p).map_err(|_| "BINANCE_REFERENCE_FILE_UNAVAILABLE")?;
    if !m.file_type().is_file() || m.len() > MAX {
        return Err("BINANCE_REFERENCE_FILE_INVALID");
    }
    let mut bytes = Vec::new();
    fs::File::open(p)
        .map_err(|_| "BINANCE_REFERENCE_FILE_UNAVAILABLE")?
        .take(MAX + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "BINANCE_REFERENCE_FILE_UNAVAILABLE")?;
    if bytes.len() as u64 > MAX {
        return Err("BINANCE_REFERENCE_FILE_INVALID");
    }
    Ok(bytes)
}
fn historical_bytes(v: &Value) -> Result<Vec<u8>> {
    let mut s = crate::reference_capture::ascii_json(v)?;
    s.push('\n');
    Ok(s.into_bytes())
}
fn sync_dir(path: &Path) -> Result<()> {
    fs::File::open(path)
        .and_then(|f| f.sync_all())
        .map_err(|_| "BINANCE_REFERENCE_DIRECTORY_SYNC")
}
fn publish(root: &Path, kind: &str, id: &str, files: &[(&str, &[u8])]) -> Result<bool> {
    digest(id)?;
    directory(root)?;
    let parent = root.join(kind);
    make_dir(&parent)?;
    sync_dir(root)?;
    let target = parent.join(id);
    match fs::symlink_metadata(&target) {
        Ok(meta) if meta.is_dir() => return Ok(false),
        Ok(_) => return Err("BINANCE_REFERENCE_TARGET_CONFLICT"),
        Err(e) if e.kind() == ErrorKind::NotFound => {}
        Err(_) => return Err("BINANCE_REFERENCE_DIRECTORY_UNAVAILABLE"),
    }
    let stage = loop {
        let n = STAGE
            .try_update(Ordering::Relaxed, Ordering::Relaxed, |x| x.checked_add(1))
            .map_err(|_| "BINANCE_REFERENCE_STAGE_EXHAUSTED")?;
        let stage = parent.join(format!(".{id}.{n}"));
        match fs::create_dir(&stage) {
            Ok(()) => break stage,
            Err(e) if e.kind() == ErrorKind::AlreadyExists => continue,
            Err(_) => return Err("BINANCE_REFERENCE_STAGE_UNAVAILABLE"),
        }
    };
    let result = (|| {
        for (name, bytes) in files {
            let mut f =
                fs::File::create_new(stage.join(name)).map_err(|_| "BINANCE_REFERENCE_CREATE")?;
            f.write_all(bytes)
                .and_then(|_| f.sync_all())
                .map_err(|_| "BINANCE_REFERENCE_WRITE")?;
        }
        sync_dir(&stage)?;
        let created = match fs::rename(&stage, &target) {
            Ok(()) => true,
            Err(e)
                if matches!(
                    e.kind(),
                    ErrorKind::AlreadyExists | ErrorKind::DirectoryNotEmpty
                ) =>
            {
                false
            }
            Err(_) => return Err("BINANCE_REFERENCE_PUBLISH"),
        };
        sync_dir(&parent)?;
        Ok(created)
    })();
    if result != Ok(true) && stage.exists() {
        for (name, _) in files {
            match fs::remove_file(stage.join(name)) {
                Ok(()) => {}
                Err(e) if e.kind() == ErrorKind::NotFound => {}
                Err(_) => return Err("BINANCE_REFERENCE_STAGE_CLEANUP"),
            }
        }
        fs::remove_dir(&stage).map_err(|_| "BINANCE_REFERENCE_STAGE_CLEANUP")?;
    }
    result
}
pub fn load_spot_capture(root: &Path, expected: &str) -> Result<ReferenceCapture> {
    let target = path(root, "captures", expected)?;
    let manifest = read_json(&read(&target.join("manifest.json"))?)?;
    let p = &manifest["provenance"];
    let at: OnlyUtcDateTime = text(&p["captured_at_utc"])?
        .parse()
        .map_err(|_| "BINANCE_REFERENCE_TIME")?;
    let requested = rows(&p["requested_symbols"])?
        .iter()
        .map(text)
        .collect::<Result<Vec<_>>>()?;
    let a = read(&target.join(RAW[0]))?;
    let b = read(&target.join(RAW[1]))?;
    let capture = ReferenceCapture::spot(&a, &b, at, text(&p["environment"])?, &requested)?;
    if capture.fingerprint() != expected || capture.manifest() != &manifest {
        return Err("BINANCE_CAPTURE_MISMATCH");
    }
    Ok(capture)
}
fn semantic_resource(root: &Path, id: &str, expected_manifest: Option<&str>) -> Result<Reference> {
    let target = path(root, "references", id)?;
    let bytes = read(&target.join("manifest.json"))?;
    if expected_manifest.is_some_and(|sha| raw_sha256(&bytes) != sha) {
        return Err("BINANCE_REFERENCE_MANIFEST_MISMATCH");
    }
    let manifest = read_json(&bytes)?;
    let semantic = read(&target.join("reference.json"))?;
    if manifest
        != json!({"schema_version":1,"authority_fingerprint":id,"observed_at":manifest["observed_at"],"semantic_sha256":raw_sha256(&semantic)})
    {
        return Err("BINANCE_REFERENCE_MANIFEST_MISMATCH");
    }
    let r = Reference::load(
        &json!({"observed_at":manifest["observed_at"],"authority":read_json(&semantic)?}),
    )?;
    if r.fingerprint() != id {
        return Err("BINANCE_REFERENCE_IDENTITY");
    }
    Ok(r)
}
/// 原始语义身份不含观测时刻。调用方必须另外提供历史绑定的 manifest SHA。
pub fn load_spot_reference(root: &Path, id: &str, manifest_sha256: &str) -> Result<Reference> {
    digest(manifest_sha256)?;
    semantic_resource(root, id, Some(manifest_sha256))
}
pub fn publish_spot(root: &Path, c: &ReferenceCapture) -> Result<(bool, bool)> {
    let [r] = c.authorities() else {
        return Err("BINANCE_SPOT_CAPTURE_REQUIRED");
    };
    if r.kind() != Kind::Spot {
        return Err("BINANCE_SPOT_CAPTURE_REQUIRED");
    }
    let manifest = historical_bytes(c.manifest())?;
    let first = publish(
        root,
        "captures",
        c.fingerprint(),
        &[
            (RAW[0], &c.evidence[0]),
            (RAW[1], &c.evidence[1]),
            ("manifest.json", &manifest),
        ],
    )?;
    if load_spot_capture(root, c.fingerprint())?.raw_evidence() != c.raw_evidence() {
        return Err("BINANCE_CAPTURE_RAW_CONFLICT");
    }
    let semantic = historical_bytes(&r.payload()["authority"])?;
    let m = historical_bytes(
        &json!({"schema_version":1,"authority_fingerprint":r.fingerprint(),"observed_at":r.payload()["observed_at"],"semantic_sha256":raw_sha256(&semantic)}),
    )?;
    let second = publish(
        root,
        "references",
        r.fingerprint(),
        &[("reference.json", &semantic), ("manifest.json", &m)],
    )?;
    if semantic_resource(root, r.fingerprint(), None)?.payload()["authority"]
        != r.payload()["authority"]
    {
        return Err("BINANCE_REFERENCE_CONFLICT");
    }
    Ok((first, second))
}
