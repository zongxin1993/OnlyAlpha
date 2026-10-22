//! Canonical OAMD v1 file ownership. A WAL seal proves local durable bytes;
//! it never grants a Market Data Revision/Manifest/Seal or COMPLETE coverage.
use crate::protected_files;
use base64::{Engine, engine::general_purpose::STANDARD};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_metadata_json as metadata;
use rustix::fs::{self as rfs, AtFlags, FileType, Mode, OFlags};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{Read, Write},
    os::fd::OwnedFd,
    path::Path,
};
const HEADER: usize = 53;
const MAX_READ: usize = 128 * 1024 * 1024;
const MAX_RECORD: usize = 16 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Corrupt,
    Unavailable,
    Capacity,
    Conflict,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "WAL_RECORD_INVALID",
            Self::Corrupt => "WAL_STATE_CORRUPT",
            Self::Unavailable => "WAL_UNAVAILABLE",
            Self::Capacity => "WAL_CAPACITY_FULL",
            Self::Conflict => "WAL_IDENTITY_CONFLICT",
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<std::io::Error> for Error {
    fn from(_: std::io::Error) -> Self {
        Self::Unavailable
    }
}
impl From<rustix::io::Errno> for Error {
    fn from(_: rustix::io::Errno) -> Self {
        Self::Unavailable
    }
}
impl From<protected_files::ReadError> for Error {
    fn from(e: protected_files::ReadError) -> Self {
        if matches!(e, protected_files::ReadError::Invalid) {
            Self::Corrupt
        } else {
            Self::Unavailable
        }
    }
}
type Result<T> = std::result::Result<T, Error>;
pub(crate) fn id(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    {
        Err(Error::Invalid)
    } else {
        Ok(())
    }
}
fn text(value: &Value) -> Result<&str> {
    value
        .as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or(Error::Invalid)
}
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn canonical(value: &Value) -> Result<String> {
    metadata::canonical_json(&value.to_string(), MAX_RECORD * 16).map_err(|e| {
        if e == metadata::Error::Unavailable {
            Error::Unavailable
        } else {
            Error::Invalid
        }
    })
}
fn fingerprint(value: &Value) -> Result<String> {
    Ok(hash(canonical(value)?.as_bytes()))
}
fn decode(bytes: &[u8]) -> Result<Value> {
    if bytes.len() > MAX_RECORD {
        return Err(Error::Unavailable);
    }
    let raw = std::str::from_utf8(bytes).map_err(|_| Error::Invalid)?;
    let original = metadata::canonical_json(raw, MAX_RECORD * 16).map_err(|e| {
        if e == metadata::Error::Unavailable {
            Error::Unavailable
        } else {
            Error::Invalid
        }
    })?;
    let value: Value = serde_json::from_str(raw).map_err(|_| Error::Invalid)?;
    if original != canonical(&value)? {
        return Err(Error::Invalid);
    }
    Ok(value)
}
fn incomplete_json(bytes: &[u8]) -> bool {
    std::str::from_utf8(bytes)
        .err()
        .is_none_or(|error| error.error_len().is_none())
        && serde_json::from_slice::<Value>(bytes).is_err_and(|error| error.is_eof())
}
fn utc(value: &str) -> Result<(OnlyUtcDateTime, String)> {
    let time: OnlyUtcDateTime = value.parse().map_err(|_| Error::Invalid)?;
    let s = time.to_string();
    Ok((
        time,
        format!("{}+00:00", s.strip_suffix('Z').ok_or(Error::Invalid)?),
    ))
}
fn ns(value: &Value) -> Result<i64> {
    let time = utc(text(value)?)?.0;
    OnlyTimestamp::from_datetime(time)
        .unix_nanos()
        .to_string()
        .parse()
        .map_err(|_| Error::Invalid)
}
fn bundle(raw: &[u8], segment: &str) -> Result<Value> {
    let value = decode(raw)?;
    if value["schema_version"] != 1 {
        return Err(Error::Invalid);
    }
    let evidence = &value["evidence"];
    if !evidence.is_object() {
        return Err(Error::Invalid);
    }
    for key in [
        "raw_event_id",
        "source_id",
        "capture_session_id",
        "provider",
        "venue",
        "market",
        "stream",
        "provider_event_type",
        "payload_codec",
        "provider_schema",
    ] {
        text(evidence.get(key).ok_or(Error::Invalid)?)?;
    }
    let provenance = text(&value["evidence"]["provenance"])?;
    if !matches!(
        provenance,
        "REALTIME_STREAM" | "REST_BACKFILL" | "REPAIR" | "REPLAY"
    ) {
        return Err(Error::Invalid);
    }
    if !evidence["ts_receive_ns"].is_i64() {
        return Err(Error::Invalid);
    }
    for key in ["ts_event_ns", "provider_sequence"] {
        if !evidence[key].is_null() && !evidence[key].is_i64() {
            return Err(Error::Invalid);
        }
    }
    let payload = STANDARD
        .decode(evidence["payload_base64"].as_str().ok_or(Error::Invalid)?)
        .map_err(|_| Error::Invalid)?;
    if hash(&payload) != text(&evidence["raw_sha256"])? {
        return Err(Error::Invalid);
    }
    if let Some(binding) = evidence
        .get("integration_binding_fingerprint")
        .filter(|v| !v.is_null())
        && !crate::is_sha256_hex(text(binding)?)
    {
        return Err(Error::Invalid);
    }
    let construction = evidence
        .get("bar_construction")
        .filter(|v| !v.is_null())
        .map(|v| {
            onlyalpha_market_data_construction::OnlyConstructionIdentity::from_record(v)
                .map_err(|_| Error::Invalid)
        })
        .transpose()?;
    if let Some(identity) = &construction
        && (!identity.plan().recipe().is_native()
            || identity.plan().context().source() != text(&evidence["source_id"])?)
    {
        return Err(Error::Invalid);
    }
    let facts = value["canonical_facts"].as_array().ok_or(Error::Invalid)?;
    for fact in facts {
        for key in [
            "canonical_fact_id",
            "raw_event_id",
            "source_id",
            "segment_id",
            "capture_session_id",
            "data_kind",
            "instrument_id",
            "canonical_payload_hash",
            "normalizer_id",
            "normalizer_version",
        ] {
            text(&fact[key])?;
        }
        for key in [
            "raw_event_id",
            "source_id",
            "capture_session_id",
            "provenance",
            "ts_receive_ns",
        ] {
            if fact[key] != value["evidence"][key] {
                return Err(Error::Invalid);
            }
        }
        if fact["segment_id"] != segment
            || fingerprint(&fact["canonical_payload"])? != text(&fact["canonical_payload_hash"])?
            || !fact["canonical_payload"].is_object()
        {
            return Err(Error::Invalid);
        }
        if !matches!(
            fact["quality_state"].as_str(),
            Some("VALID" | "CONFLICT" | "CORRUPT")
        ) {
            return Err(Error::Invalid);
        }
        for key in ["ts_event_ns", "ts_ingest_ns"] {
            if !fact[key].is_i64() {
                return Err(Error::Invalid);
            }
        }
        let payload = &fact["canonical_payload"];
        for (outer, inner) in [
            ("canonical_fact_id", "update_id"),
            ("source_id", "source_id"),
            ("instrument_id", "instrument_id"),
            ("data_kind", "data_type"),
            ("ts_event_ns", "ts_event"),
        ] {
            if fact[outer] != payload[inner] {
                return Err(Error::Invalid);
            }
        }
        if !matches!(payload["schema_version"].as_u64(), Some(1..=3))
            || !payload["ts_init"].is_i64()
            || payload["ts_init"].as_i64() < payload["ts_event"].as_i64()
            || payload["payload"]["kind"] != payload["data_type"]
                && !(payload["data_type"] == "SETTLEMENT"
                    && payload["payload"]["kind"] == "REFERENCE_PRICE")
        {
            return Err(Error::Invalid);
        }
        text(&payload["data_version"])?;
        if construction.is_some() && fact["data_kind"] != "BAR" {
            return Err(Error::Invalid);
        }
        if fact["data_kind"] == "BAR" {
            let bar = OnlyBar::from_record(&fact["canonical_payload"]["payload"]["value"])
                .map_err(|_| Error::Invalid)?;
            if bar.instrument_id().to_string() != text(&fact["instrument_id"])? {
                return Err(Error::Invalid);
            }
            if OnlyTimestamp::from_datetime(*bar.ts_event())
                .unix_nanos()
                .to_string()
                != fact["ts_event_ns"]
                    .as_number()
                    .ok_or(Error::Invalid)?
                    .as_str()
            {
                return Err(Error::Invalid);
            }
            if let Some(identity) = &construction
                && (identity.plan().context().instrument() != bar.instrument_id()
                    || identity.plan().target() != bar.bar_type().semantic()
                    || evidence["bar_construction"]["data_version"] != payload["data_version"])
            {
                return Err(Error::Invalid);
            }
        }
    }
    Ok(value)
}
struct Frames {
    bundles: Vec<Value>,
    valid_end: usize,
    corrupt: bool,
}
fn frames(bytes: &[u8], segment: &str) -> Result<Frames> {
    let mut result = Frames {
        bundles: Vec::new(),
        valid_end: 0,
        corrupt: false,
    };
    while result.valid_end < bytes.len() {
        let offset = result.valid_end;
        if bytes.len() - offset < HEADER {
            result.corrupt = true;
            break;
        }
        let header = &bytes[offset..offset + HEADER];
        let length = u64::from_be_bytes(header[5..13].try_into().map_err(|_| Error::Corrupt)?);
        if length > MAX_RECORD as u64 {
            return Err(Error::Unavailable);
        }
        let length = usize::try_from(length).map_err(|_| Error::Unavailable)?;
        let end = offset
            .checked_add(HEADER)
            .and_then(|v| v.checked_add(length))
            .ok_or(Error::Unavailable)?;
        let ordinal = u64::from_be_bytes(header[13..21].try_into().map_err(|_| Error::Corrupt)?);
        if &header[..5] != b"OAMD\x01"
            || ordinal != result.bundles.len() as u64
            || end > bytes.len()
        {
            result.corrupt = true;
            break;
        }
        let payload = &bytes[offset + HEADER..end];
        if Sha256::digest(payload).as_slice() != &header[21..53] {
            result.corrupt = true;
            break;
        }
        let value = bundle(payload, segment).map_err(|e| {
            if e == Error::Invalid {
                Error::Corrupt
            } else {
                e
            }
        })?;
        result.bundles.push(value);
        result.valid_end = end;
    }
    Ok(result)
}
fn segment_metadata(
    segment: &str,
    records: &[Value],
    bytes: &[u8],
    created: &str,
    sealed: &str,
) -> Result<Value> {
    let first = records.first().ok_or(Error::Invalid)?;
    let evidence = &first["evidence"];
    for record in records {
        for key in [
            "capture_session_id",
            "source_id",
            "provider",
            "venue",
            "market",
            "stream",
            "provenance",
            "provider_schema",
            "payload_codec",
            "integration_binding_fingerprint",
            "bar_construction",
        ] {
            if record["evidence"][key] != evidence[key] {
                return Err(Error::Corrupt);
            }
        }
    }
    let (created_time, created) = utc(created)?;
    let (sealed_time, sealed) = utc(sealed)?;
    if sealed_time < created_time {
        return Err(Error::Invalid);
    }
    let facts: Vec<_> = records
        .iter()
        .flat_map(|r| r["canonical_facts"].as_array().into_iter().flatten())
        .collect();
    let mut result = json!({"schema_version":1,"segment_id":segment,"capture_session_id":evidence["capture_session_id"],"source_id":evidence["source_id"],"market":evidence["market"],"stream":evidence["stream"],"provider":evidence["provider"],"venue":evidence["venue"],"capture_mode":evidence["provenance"],"provider_schema":evidence["provider_schema"],"codec":evidence["payload_codec"],"record_count":records.len(),"raw_count":records.len(),"canonical_count":facts.len(),"content_hash":hash(bytes),"created_at":created,"sealed_at":sealed,
        "instrument_id":null,"data_kind":null,"start_ns":null,"end_ns":null,"data_version":null,"bar_type":null,"first_sequence":null,"last_sequence":null});
    for key in ["integration_binding_fingerprint", "bar_construction"] {
        if !evidence[key].is_null() {
            result[key] = evidence[key].clone();
        }
    }
    if let Some(first) = facts.first() {
        for fact in &facts {
            for key in ["source_id", "instrument_id", "data_kind", "provenance"] {
                if fact[key] != first[key] {
                    return Err(Error::Corrupt);
                }
            }
            if fact["canonical_payload"]["data_version"]
                != first["canonical_payload"]["data_version"]
            {
                return Err(Error::Corrupt);
            }
        }
        text(&first["canonical_payload"]["data_version"])?;
        result["instrument_id"] = first["instrument_id"].clone();
        result["data_kind"] = first["data_kind"].clone();
        result["data_version"] = first["canonical_payload"]["data_version"].clone();
        let mut starts = Vec::new();
        let mut ends = Vec::new();
        let mut types = std::collections::BTreeSet::new();
        let mut sequences = Vec::new();
        for fact in &facts {
            if fact["data_kind"] == "BAR" {
                let bar = &fact["canonical_payload"]["payload"]["value"];
                starts.push(ns(&bar["bar_start"])?);
                ends.push(ns(&bar["bar_end"])?);
                types.insert(fingerprint(&bar["bar_type"])?);
            } else {
                let t = fact["ts_event_ns"].as_i64().ok_or(Error::Invalid)?;
                starts.push(t);
                ends.push(t.checked_add(1).ok_or(Error::Invalid)?);
            }
            if fact["canonical_payload"]["sequence_semantics"] == "CONTIGUOUS"
                && !fact["canonical_payload"]["source_sequence"].is_null()
            {
                sequences.push(
                    fact["canonical_payload"]["source_sequence"]
                        .as_i64()
                        .ok_or(Error::Invalid)?,
                );
            }
        }
        result["start_ns"] = (*starts.iter().min().ok_or(Error::Invalid)?).into();
        result["end_ns"] = (*ends.iter().max().ok_or(Error::Invalid)?).into();
        if first["data_kind"] == "BAR" {
            if types.len() != 1 {
                return Err(Error::Corrupt);
            }
            result["bar_type"] = types.into_iter().next().ok_or(Error::Invalid)?.into();
        }
        if first["data_kind"] == "TRADE" && !sequences.is_empty() {
            result["first_sequence"] = (*sequences.iter().min().ok_or(Error::Invalid)?).into();
            result["last_sequence"] = (*sequences.iter().max().ok_or(Error::Invalid)?).into();
        }
    }
    Ok(result)
}
/// The Host supplies an initialized, owned WAL directory under its lifecycle
/// guard. One mutable writer owns an open segment; no automatic clock/identity.
pub struct Wal {
    directory: OwnedFd,
    _writer_lock: File,
    capacity: usize,
    open: Option<String>,
    drain_lifecycle: std::sync::Arc<()>,
}
impl Wal {
    pub fn new(root: &Path, capacity: usize) -> Result<Self> {
        if capacity <= HEADER {
            return Err(Error::Invalid);
        }
        let directory = protected_files::open_directory(root)?;
        Self::from_directory(std::os::fd::AsFd::as_fd(&directory), capacity)
    }
    /// Retain the Host's selected directory capability without reopening a path.
    pub fn from_directory(directory: std::os::fd::BorrowedFd<'_>, capacity: usize) -> Result<Self> {
        if capacity <= HEADER {
            return Err(Error::Invalid);
        }
        let directory = protected_files::duplicate_directory(directory)?;
        let fd = rfs::openat(
            &directory,
            ".writer.lock",
            OFlags::RDWR | OFlags::CREATE | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            Mode::from_raw_mode(0o600),
        )?;
        let stat = rfs::fstat(&fd)?;
        if FileType::from_raw_mode(stat.st_mode) != FileType::RegularFile
            || stat.st_nlink != 1
            || stat.st_mode & 0o077 != 0
            || stat.st_uid != rustix::process::geteuid().as_raw()
        {
            return Err(Error::Corrupt);
        }
        rfs::flock(&fd, rfs::FlockOperation::NonBlockingLockExclusive)
            .map_err(|_| Error::Conflict)?;
        Ok(Self {
            directory,
            _writer_lock: File::from(fd),
            capacity,
            open: None,
            drain_lifecycle: std::sync::Arc::new(()),
        })
    }
    fn file(&self, name: &str, flags: OFlags, create: bool) -> Result<File> {
        let fd = rfs::openat(
            &self.directory,
            name,
            flags | OFlags::NOFOLLOW | OFlags::CLOEXEC | OFlags::NONBLOCK,
            if create {
                Mode::from_raw_mode(0o600)
            } else {
                Mode::empty()
            },
        )?;
        let stat = rfs::fstat(&fd)?;
        if FileType::from_raw_mode(stat.st_mode) != FileType::RegularFile
            || stat.st_nlink != 1
            || stat.st_mode & 0o022 != 0
            || (stat.st_uid != 0 && stat.st_uid != rustix::process::geteuid().as_raw())
        {
            return Err(Error::Corrupt);
        }
        Ok(File::from(fd))
    }
    fn exists(&self, name: &str) -> Result<bool> {
        match rfs::statat(&self.directory, name, AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => Ok(true),
            Err(rustix::io::Errno::NOENT) => Ok(false),
            Err(_) => Err(Error::Unavailable),
        }
    }
    fn read(&self, name: &str) -> Result<Vec<u8>> {
        let mut out = Vec::new();
        self.file(name, OFlags::RDONLY, false)?
            .take(MAX_READ as u64 + 1)
            .read_to_end(&mut out)?;
        if out.len() > MAX_READ {
            return Err(Error::Unavailable);
        }
        Ok(out)
    }
    fn write_new(&self, name: &str, bytes: &[u8]) -> Result<()> {
        let mut file = self.file(name, OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL, true)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        Ok(())
    }
    fn sync(&self) -> Result<()> {
        rfs::fsync(&self.directory)?;
        Ok(())
    }
    fn rename(&self, from: &str, to: &str) -> Result<()> {
        // Recovery may observe a write interrupted before its content fsync.
        // Persist those exact bytes before publishing the new durable name.
        self.file(from, OFlags::RDONLY, false)?.sync_all()?;
        rfs::renameat_with(
            &self.directory,
            from,
            &self.directory,
            to,
            rfs::RenameFlags::NOREPLACE,
        )
        .map_err(|e| {
            if e == rustix::io::Errno::EXIST {
                Error::Conflict
            } else {
                Error::Unavailable
            }
        })?;
        self.sync()
    }
    fn remove(&self, name: &str) -> Result<()> {
        match rfs::unlinkat(&self.directory, name, AtFlags::empty()) {
            Ok(()) | Err(rustix::io::Errno::NOENT) => Ok(()),
            Err(_) => Err(Error::Unavailable),
        }
    }
    fn json(&self, name: &str) -> Result<Value> {
        decode(&self.read(name)?).map_err(|e| {
            if e == Error::Invalid {
                Error::Corrupt
            } else {
                e
            }
        })
    }
    pub fn bytes_used(&self) -> Result<usize> {
        let mut budget = 1024 * 1024;
        let mut total = 0usize;
        for name in protected_files::directory_entries(&self.directory, &mut budget)? {
            let name = name.to_str().ok_or(Error::Corrupt)?;
            if name.ends_with(".open.wal") || name.ends_with(".sealed.wal") {
                let stat = rfs::fstat(self.file(name, OFlags::RDONLY, false)?)?;
                let size = usize::try_from(stat.st_size).map_err(|_| Error::Unavailable)?;
                total = total.checked_add(size).ok_or(Error::Unavailable)?;
            }
        }
        Ok(total)
    }
    pub fn create_segment(&mut self, segment: &str, created: &str) -> Result<()> {
        id(segment)?;
        let created = utc(created)?.1;
        if self.open.is_some() {
            return Err(Error::Conflict);
        }
        for suffix in [
            "open.wal",
            "sealed.wal",
            "gc.wal",
            "abandoned.wal",
            "open.json",
            "segment.json",
            "gc.json",
            "abandoned.json",
            "open.json.tmp",
            "open.json.incomplete",
            "segment.json.tmp",
            "segment.json.incomplete",
            "corrupt-tail",
        ] {
            if self.exists(&format!("{segment}.{suffix}"))? {
                return Err(Error::Conflict);
            }
        }
        self.write_new(
            &format!("{segment}.open.json.tmp"),
            canonical(&json!({"schema_version":1,"segment_id":segment,"created_at":created}))?
                .as_bytes(),
        )?;
        self.sync()?;
        self.write_new(&format!("{segment}.open.wal"), &[])?;
        self.sync()?;
        self.rename(
            &format!("{segment}.open.json.tmp"),
            &format!("{segment}.open.json"),
        )?;
        self.open = Some(segment.into());
        Ok(())
    }
    pub fn append(&mut self, raw: &str) -> Result<u64> {
        let segment = self.open.as_deref().ok_or(Error::Conflict)?;
        let value = bundle(raw.as_bytes(), segment)?;
        let payload = canonical(&value)?;
        let name = format!("{segment}.open.wal");
        let previous = self.read(&name)?;
        let parsed = frames(&previous, segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        let ordinal = parsed.bundles.len() as u64;
        let length = append_length(previous.len(), payload.len())?;
        if self
            .bytes_used()?
            .checked_add(length)
            .is_none_or(|n| n > self.capacity)
        {
            return Err(Error::Capacity);
        }
        let mut frame = Vec::with_capacity(length);
        frame.extend_from_slice(b"OAMD\x01");
        frame.extend_from_slice(&(payload.len() as u64).to_be_bytes());
        frame.extend_from_slice(&ordinal.to_be_bytes());
        frame.extend_from_slice(&Sha256::digest(payload.as_bytes()));
        frame.extend_from_slice(payload.as_bytes());
        let mut file = self.file(&name, OFlags::WRONLY | OFlags::APPEND, false)?;
        file.write_all(&frame)?;
        file.sync_all()?;
        Ok(ordinal)
    }
    pub fn seal(&mut self, sealed: &str) -> Result<Value> {
        let segment = self.open.clone().ok_or(Error::Conflict)?;
        if self.exists(&format!("{segment}.sealed.wal"))?
            || self.exists(&format!("{segment}.segment.json"))?
        {
            return Err(Error::Conflict);
        }
        let bytes = self.read(&format!("{segment}.open.wal"))?;
        let parsed = frames(&bytes, &segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        let created = self.open_metadata(&segment)?;
        let metadata = segment_metadata(&segment, &parsed.bundles, &bytes, &created, sealed)?;
        let prepared = format!("{segment}.segment.json.tmp");
        if self.exists(&prepared)? {
            return Err(Error::Conflict);
        }
        self.write_new(&prepared, canonical(&metadata)?.as_bytes())?;
        self.sync()?;
        self.rename(
            &format!("{segment}.open.wal"),
            &format!("{segment}.sealed.wal"),
        )?;
        self.rename(&prepared, &format!("{segment}.segment.json"))?;
        self.remove(&format!("{segment}.open.json"))?;
        self.sync()?;
        self.open = None;
        Ok(metadata)
    }
    fn open_metadata(&self, segment: &str) -> Result<String> {
        let metadata = self.json(&format!("{segment}.open.json"))?;
        if metadata["schema_version"] != 1 || metadata["segment_id"] != segment {
            return Err(Error::Corrupt);
        }
        Ok(utc(text(&metadata["created_at"])?)?.1)
    }
    pub fn read_sealed(&self, segment: &str) -> Result<Vec<Value>> {
        id(segment)?;
        let bytes = self.read(&format!("{segment}.sealed.wal"))?;
        let parsed = frames(&bytes, segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        Ok(parsed.bundles)
    }
    pub fn load_segment(&mut self, segment: &str) -> Result<Value> {
        id(segment)?;
        self.validate_state(segment)?;
        if !self.exists(&format!("{segment}.segment.json"))? {
            self.recover_sealed(segment)?;
        }
        let observed = self.json(&format!("{segment}.segment.json"))?;
        self.verify_creation_lineage(segment, &observed)?;
        let bytes = self.read(&format!("{segment}.sealed.wal"))?;
        let parsed = frames(&bytes, segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        let expected = segment_metadata(
            segment,
            &parsed.bundles,
            &bytes,
            text(&observed["created_at"])?,
            text(&observed["sealed_at"])?,
        )?;
        verify_historical_metadata(&observed, &expected)?;
        Ok(expected)
    }
    fn publish_prepared(&self, segment: &str, from: &str) -> Result<Option<Value>> {
        let prepared = format!("{segment}.segment.json.tmp");
        if !self.exists(&prepared)? {
            return Ok(None);
        }
        if self.exists(&format!("{segment}.segment.json"))? {
            return Err(Error::Conflict);
        }
        let prepared_bytes = self.read(&prepared)?;
        let observed = match decode(&prepared_bytes) {
            Ok(value) => value,
            Err(Error::Invalid)
                if from == format!("{segment}.open.wal") && incomplete_json(&prepared_bytes) =>
            {
                // Only an unpublished EOF prefix is a normal interrupted write.
                // A renamed WAL or complete malformed metadata is never repaired.
                let quarantine = format!("{segment}.segment.json.incomplete");
                if !self.exists(&quarantine)? {
                    self.rename(&prepared, &quarantine)?;
                    return Ok(None);
                }
                self.read(&quarantine)?;
                // A second interruption can only complete the exact deterministic
                // recovery preparation; the original failed bytes stay immutable.
                let bytes = self.read(from)?;
                let parsed = frames(&bytes, segment)?;
                if parsed.corrupt {
                    return Err(Error::Corrupt);
                }
                let created = self.open_metadata(segment)?;
                let expected =
                    segment_metadata(segment, &parsed.bundles, &bytes, &created, &created)?;
                self.complete_prefix(&prepared, canonical(&expected)?.as_bytes())?;
                expected
            }
            Err(Error::Invalid) => return Err(Error::Corrupt),
            Err(error) => return Err(error),
        };
        self.verify_creation_lineage(segment, &observed)?;
        let bytes = self.read(from)?;
        let parsed = frames(&bytes, segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        let expected = segment_metadata(
            segment,
            &parsed.bundles,
            &bytes,
            text(&observed["created_at"])?,
            text(&observed["sealed_at"])?,
        )?;
        if observed != expected {
            return Err(Error::Corrupt);
        }
        let sealed = format!("{segment}.sealed.wal");
        if from != sealed {
            if self.exists(&sealed)? {
                return Err(Error::Conflict);
            }
            self.rename(from, &sealed)?;
        }
        self.rename(&prepared, &format!("{segment}.segment.json"))?;
        self.remove(&format!("{segment}.open.json"))?;
        self.sync()?;
        Ok(Some(expected))
    }
    fn recover_sealed(&self, segment: &str) -> Result<Value> {
        let name = format!("{segment}.sealed.wal");
        if let Some(metadata) = self.publish_prepared(segment, &name)? {
            return Ok(metadata);
        }
        let created = self.open_metadata(segment)?;
        let bytes = self.read(&name)?;
        let parsed = frames(&bytes, segment)?;
        if parsed.corrupt {
            return Err(Error::Corrupt);
        }
        let metadata = segment_metadata(segment, &parsed.bundles, &bytes, &created, &created)?;
        self.write_new(
            &format!("{segment}.segment.json.tmp"),
            canonical(&metadata)?.as_bytes(),
        )?;
        self.rename(
            &format!("{segment}.segment.json.tmp"),
            &format!("{segment}.segment.json"),
        )?;
        self.remove(&format!("{segment}.open.json"))?;
        self.sync()?;
        Ok(metadata)
    }
    /// Recover explicit creation, append and seal states. Empty creation is an
    /// abandoned identity, never a successful data segment or coverage proof.
    pub fn recover_segment(&mut self, segment: &str) -> Result<Recovery> {
        id(segment)?;
        if self.open.is_some() || std::sync::Arc::strong_count(&self.drain_lifecycle) > 1 {
            return Err(Error::Conflict);
        }
        self.validate_state(segment)?;
        let name = format!("{segment}.open.wal");
        let has_open = self.exists(&name)?;
        let has_sealed = self.exists(&format!("{segment}.sealed.wal"))?;
        if !has_open {
            if has_sealed {
                let segment_value = self.load_segment(segment)?;
                return Ok(Recovery::Sealed {
                    segment: segment_value,
                    quarantined_tail: self.quarantined(segment)?,
                });
            }
            if self.exists(&format!("{segment}.segment.json"))?
                || self.exists(&format!("{segment}.segment.json.tmp"))?
            {
                return Err(Error::Corrupt);
            }
            return self.abandon_creation(segment);
        }
        let bytes = self.read(&name)?;
        if bytes.is_empty() {
            if self.exists(&format!("{segment}.segment.json.tmp"))? {
                return Err(Error::Corrupt);
            }
            return self.abandon_creation(segment);
        }
        let created = self.open_metadata(segment)?;
        let parsed = frames(&bytes, segment)?;
        if parsed.corrupt {
            if self.exists(&format!("{segment}.segment.json.tmp"))? {
                return Err(Error::Corrupt);
            }
            let tail = &bytes[parsed.valid_end..];
            let quarantine = format!("{segment}.corrupt-tail");
            if self.exists(&quarantine)? {
                self.complete_prefix(&quarantine, tail)?;
            } else {
                self.write_new(&quarantine, tail)?;
            }
            self.sync()?;
            let file = self.file(&name, OFlags::WRONLY, false)?;
            file.set_len(parsed.valid_end as u64)?;
            file.sync_all()?;
            self.sync()?;
        }
        if parsed.bundles.is_empty() {
            return self.abandon_creation(segment);
        }
        let segment_value = if let Some(value) = self.publish_prepared(segment, &name)? {
            value
        } else {
            self.open = Some(segment.into());
            self.seal(&created)?
        };
        Ok(Recovery::Sealed {
            segment: segment_value,
            quarantined_tail: self.quarantined(segment)?,
        })
    }
    fn verify_creation_lineage(&self, segment: &str, metadata: &Value) -> Result<()> {
        if self.exists(&format!("{segment}.open.json"))?
            && self.open_metadata(segment)? != utc(text(&metadata["created_at"])?)?.1
        {
            return Err(Error::Corrupt);
        }
        Ok(())
    }
    fn validate_state(&self, segment: &str) -> Result<()> {
        let has = |suffix: &str| self.exists(&format!("{segment}.{suffix}"));
        let open = has("open.wal")?;
        let sealed = has("sealed.wal")?;
        let creation = has("open.json")?;
        let creation_prepared = has("open.json.tmp")?;
        let creation_incomplete = has("open.json.incomplete")?;
        let seal = has("segment.json")?;
        let seal_prepared = has("segment.json.tmp")?;
        let abandoned = has("abandoned.wal")?;
        let abandon_marker = has("abandoned.json")?;
        // These files belong to one identity and one lifecycle branch. Check
        // before recovery or the verified reader can publish or truncate anything.
        if (open && (sealed || seal))
            || ((abandoned || abandon_marker) && (open || sealed || seal || seal_prepared))
            || (creation_prepared && (creation || sealed || seal || seal_prepared))
            || (creation_incomplete
                && (creation || creation_prepared || sealed || seal || seal_prepared))
            || (seal && seal_prepared)
            || (abandon_marker && (creation || creation_prepared))
            || has("gc.wal")?
            || has("gc.json")?
        {
            return Err(Error::Conflict);
        }
        if (seal && !sealed)
            || (abandon_marker && !abandoned)
            || (creation && !open && !sealed && !abandoned)
        {
            return Err(Error::Corrupt);
        }
        Ok(())
    }
    fn complete_prefix(&self, name: &str, bytes: &[u8]) -> Result<()> {
        let prefix = self.read(name)?;
        if !bytes.starts_with(&prefix) {
            return Err(Error::Conflict);
        }
        let mut file = self.file(name, OFlags::WRONLY | OFlags::APPEND, false)?;
        file.write_all(&bytes[prefix.len()..])?;
        file.sync_all()?;
        Ok(())
    }
    fn quarantined(&self, segment: &str) -> Result<bool> {
        let name = format!("{segment}.corrupt-tail");
        if !self.exists(&name)? {
            return Ok(false);
        }
        if self.read(&name)?.is_empty() {
            return Err(Error::Corrupt);
        }
        Ok(true)
    }
    fn abandon_creation(&self, segment: &str) -> Result<Recovery> {
        let open = format!("{segment}.open.wal");
        let abandoned = format!("{segment}.abandoned.wal");
        let published = format!("{segment}.abandoned.json");
        let metadata = format!("{segment}.open.json");
        let prepared = format!("{segment}.open.json.tmp");
        if self.exists(&metadata)? && self.exists(&prepared)? {
            return Err(Error::Conflict);
        }
        // Published metadata proves a WAL existed. Its absence cannot become a
        // fabricated empty segment, unlike the pre-creation preparation state.
        if !self.exists(&open)?
            && !self.exists(&abandoned)?
            && (self.exists(&metadata)? || self.exists(&published)?)
        {
            return Err(Error::Corrupt);
        }
        if self.exists(&abandoned)? && !self.read(&abandoned)?.is_empty() {
            return Err(Error::Corrupt);
        }
        let quarantined_tail = self.quarantined(segment)?;
        let quarantine = format!("{segment}.open.json.incomplete");
        let mut quarantined_creation = self.exists(&quarantine)?;
        if quarantined_creation && !incomplete_json(&self.read(&quarantine)?) {
            return Err(Error::Corrupt);
        }
        if self.exists(&prepared)? && incomplete_json(&self.read(&prepared)?) {
            if self.exists(&open)? && !self.read(&open)?.is_empty() {
                return Err(Error::Corrupt);
            }
            self.rename(&prepared, &quarantine)?;
            quarantined_creation = true;
        }
        let source = if self.exists(&metadata)? {
            Some(metadata)
        } else if self.exists(&prepared)? {
            Some(prepared)
        } else {
            None
        };
        if let Some(name) = &source {
            let value = self.json(name)?;
            if value["schema_version"] != 1 || value["segment_id"] != segment {
                return Err(Error::Corrupt);
            }
            utc(text(&value["created_at"])?)?;
        }
        if self.exists(&open)? {
            if !self.read(&open)?.is_empty()
                || self.exists(&abandoned)?
                || self.exists(&published)?
            {
                return Err(Error::Conflict);
            }
            self.rename(&open, &abandoned)?;
        } else if !self.exists(&abandoned)? {
            if source.is_none() && !quarantined_creation {
                return Err(Error::Unavailable);
            }
            self.write_new(&abandoned, &[])?;
            self.sync()?;
        }
        if !self.read(&abandoned)?.is_empty() {
            return Err(Error::Corrupt);
        }
        if let Some(name) = source {
            if self.exists(&published)? {
                return Err(Error::Conflict);
            }
            self.rename(&name, &published)?;
        } else if !self.exists(&published)? {
            self.write_new(
                &published,
                canonical(
                    &json!({"schema_version":1,"segment_id":segment,"reason":"CREATION_ORPHAN"}),
                )?
                .as_bytes(),
            )?;
            self.sync()?;
        }
        let raw = self.read(&published)?;
        if incomplete_json(&raw) {
            // This exact no-clock marker is the only document that can be
            // reconstructed when an empty orphan had no creation metadata.
            self.complete_prefix(
                &published,
                canonical(
                    &json!({"schema_version":1,"segment_id":segment,"reason":"CREATION_ORPHAN"}),
                )?
                .as_bytes(),
            )?;
        }
        let value = self.json(&published)?;
        if value["schema_version"] != 1
            || value["segment_id"] != segment
            || (value["created_at"].is_null() && value["reason"] != "CREATION_ORPHAN")
        {
            return Err(Error::Corrupt);
        }
        if !value["created_at"].is_null() {
            utc(text(&value["created_at"])?)?;
        }
        Ok(Recovery::Abandoned {
            quarantined_tail,
            quarantined_creation,
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Recovery {
    Sealed {
        segment: Value,
        quarantined_tail: bool,
    },
    Abandoned {
        quarantined_tail: bool,
        quarantined_creation: bool,
    },
}
fn append_length(previous: usize, payload: usize) -> Result<usize> {
    if payload > MAX_RECORD {
        return Err(Error::Capacity);
    }
    let length = HEADER.checked_add(payload).ok_or(Error::Capacity)?;
    if previous.checked_add(length).is_none_or(|n| n > MAX_READ) {
        return Err(Error::Capacity);
    }
    Ok(length)
}
fn verify_historical_metadata(observed: &Value, expected: &Value) -> Result<()> {
    let mut projection = observed.as_object().ok_or(Error::Corrupt)?.clone();
    // Schema-1 readers explicitly reconstruct missing recovery fields only when
    // the original instrument field is absent. Preserve every stored byte.
    let reconstruct = expected["canonical_count"].as_u64().is_some_and(|n| n > 0)
        && !projection.contains_key("instrument_id");
    for key in [
        "instrument_id",
        "data_kind",
        "start_ns",
        "end_ns",
        "data_version",
        "bar_type",
        "first_sequence",
        "last_sequence",
    ] {
        if !projection.contains_key(key) && (reconstruct || expected[key].is_null()) {
            projection.insert(key.into(), expected[key].clone());
        }
    }
    for key in ["integration_binding_fingerprint", "bar_construction"] {
        if expected.get(key).is_none() {
            if projection.get(key).is_some_and(|value| !value.is_null()) {
                return Err(Error::Corrupt);
            }
            projection.remove(key);
        }
    }
    for key in ["created_at", "sealed_at"] {
        let time = utc(text(projection.get(key).ok_or(Error::Corrupt)?)?)?.1;
        projection.insert(key.into(), time.into());
    }
    // Unknown annotations never become formal segment fields or publication proof.
    projection.retain(|key, _| expected.get(key).is_some());
    if Value::Object(projection) != *expected {
        return Err(Error::Corrupt);
    }
    Ok(())
}
/// Validate an existing bundle using the one OAMD record codec. Consumers do not
/// obtain a durable receipt from this validation-only entry.
pub(crate) fn validate_bundle(raw: &str, segment: &str) -> Result<Value> {
    bundle(raw.as_bytes(), segment)
}
impl Wal {
    fn pending_suffixes(&self, suffixes: &[&str]) -> Result<Vec<String>> {
        let mut budget = 1024 * 1024;
        let mut result = std::collections::BTreeSet::new();
        for name in protected_files::directory_entries(&self.directory, &mut budget)? {
            let name = name.to_str().ok_or(Error::Corrupt)?;
            for suffix in suffixes {
                if let Some(segment) = name.strip_suffix(suffix) {
                    id(segment)?;
                    result.insert(segment.to_owned());
                }
            }
        }
        Ok(result.into_iter().collect())
    }
    /// Exclusive startup enumerates published and interrupted creation/seal states.
    pub fn recovery_pending(&self) -> Result<Vec<String>> {
        if self.open.is_some() || std::sync::Arc::strong_count(&self.drain_lifecycle) > 1 {
            return Err(Error::Conflict);
        }
        self.pending_suffixes(&[
            ".open.wal",
            ".open.json",
            ".open.json.tmp",
            ".sealed.wal",
            ".segment.json",
            ".segment.json.tmp",
        ])
    }
    /// Normal drain never resolves an unpublished seal or the live open segment.
    pub fn published_sealed(&self) -> Result<Vec<String>> {
        let mut result = Vec::new();
        for segment in self.pending_suffixes(&[".sealed.wal"])? {
            if self.exists(&format!("{segment}.segment.json"))?
                && !self.exists(&format!("{segment}.gc.json"))?
            {
                result.push(segment);
            }
        }
        Ok(result)
    }
    pub(crate) fn gc_pending(&self) -> Result<Vec<String>> {
        self.pending_suffixes(&[".gc.json", ".gc.json.tmp", ".gc.wal"])
    }
    /// Caller has just re-proved exact CH and durable PG ownership. This private
    /// capability cannot be reached through a public arbitrary GC command.
    pub(crate) fn collect_verified(&mut self, segment: &Value) -> Result<()> {
        let name = text(&segment["segment_id"])?;
        id(name)?;
        let expected =
            json!({"schema_version":1,"segment_id":name,"content_hash":segment["content_hash"]});
        let marker = format!("{name}.gc.json");
        let stage = format!("{name}.gc.json.tmp");
        let sealed = format!("{name}.sealed.wal");
        let gc = format!("{name}.gc.wal");
        let metadata = format!("{name}.segment.json");
        if self.exists(&marker)? {
            if self.json(&marker)? != expected || self.exists(&stage)? {
                return Err(Error::Conflict);
            }
        } else {
            if self.exists(&gc)? {
                return Err(Error::Corrupt);
            }
            let mut observed = self.load_segment(name)?;
            for key in ["integration_binding_fingerprint", "bar_construction"] {
                if observed.get(key).is_none() {
                    observed[key] = Value::Null;
                }
            }
            if observed != *segment {
                return Err(Error::Conflict);
            }
            let bytes = canonical(&expected)?;
            if self.exists(&stage)? {
                self.complete_prefix(&stage, bytes.as_bytes())?;
            } else {
                self.write_new(&stage, bytes.as_bytes())?;
            }
            self.rename(&stage, &marker)?;
        }
        if self.exists(&sealed)? && self.exists(&gc)? {
            return Err(Error::Conflict);
        }
        if self.exists(&sealed)? {
            if hash(&self.read(&sealed)?) != text(&segment["content_hash"])? {
                return Err(Error::Corrupt);
            }
            self.rename(&sealed, &gc)?;
        }
        if self.exists(&gc)? && hash(&self.read(&gc)?) != text(&segment["content_hash"])? {
            return Err(Error::Corrupt);
        }
        self.remove(&metadata)?;
        self.sync()?;
        self.remove(&gc)?;
        self.sync()?;
        self.remove(&marker)?;
        self.sync()
    }
}

/// Sealed-only descriptor capability derived from the actual WAL owner. It holds
/// the same physical writer lock's open-file description across I/O, but exposes
/// no create/append/seal/startup-repair operation and borrows no live recorder.
pub struct SealedWal {
    inner: Wal,
}
impl Wal {
    pub fn sealed_handle(&self) -> Result<SealedWal> {
        Ok(SealedWal {
            inner: Wal {
                directory: protected_files::duplicate_directory(std::os::fd::AsFd::as_fd(
                    &self.directory,
                ))?,
                _writer_lock: self._writer_lock.try_clone()?,
                capacity: self.capacity,
                open: None,
                drain_lifecycle: self.drain_lifecycle.clone(),
            },
        })
    }
}
impl SealedWal {
    pub fn load_segment(&mut self, segment: &str) -> Result<Value> {
        id(segment)?;
        // A normal drain cannot repair the recorder's publication transition.
        if !self.inner.exists(&format!("{segment}.segment.json"))? {
            return Err(Error::Conflict);
        }
        self.inner.load_segment(segment)
    }
    pub fn read_sealed(&self, segment: &str) -> Result<Vec<Value>> {
        self.inner.read_sealed(segment)
    }
    pub fn published_sealed(&self) -> Result<Vec<String>> {
        self.inner.published_sealed()
    }
    pub(crate) fn collect_verified(&mut self, segment: &Value) -> Result<()> {
        self.inner.collect_verified(segment)
    }
}

#[cfg(test)]
mod limits {
    use super::*;
    #[test]
    fn successful_append_always_fits_the_same_reader_and_record_budgets() {
        assert_eq!(append_length(MAX_READ - HEADER - 1, 1), Ok(HEADER + 1));
        assert_eq!(append_length(MAX_READ - HEADER, 1), Err(Error::Capacity));
        assert_eq!(append_length(0, MAX_RECORD + 1), Err(Error::Capacity));
        assert_eq!(append_length(usize::MAX, 1), Err(Error::Capacity));
    }
}
