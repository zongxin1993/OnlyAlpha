//! Put-once Dataset publication in the existing content-addressed namespace.
use crate::application::research_dataset::*;
use serde_json::{Value, json};
mod columnar;
use crate::security::protected_files;
use rustix::{fd::OwnedFd, fs};
use std::{
    ffi::OsStr,
    fs::File,
    io::{Read, Seek, SeekFrom, Write},
    os::fd::AsFd,
    path::{Path, PathBuf},
};
const CORRUPT: &str = "DATASET_SNAPSHOT_CORRUPT";
const UNAVAILABLE: &str = "DATASET_STORE_UNAVAILABLE";
struct Directory {
    fd: OwnedFd,
    parent: OwnedFd,
    name: String,
}
fn same(a: &impl AsFd, b: &impl AsFd) -> Result<bool> {
    let a = fs::fstat(a).map_err(|_| UNAVAILABLE)?;
    let b = fs::fstat(b).map_err(|_| UNAVAILABLE)?;
    Ok(a.st_dev == b.st_dev && a.st_ino == b.st_ino)
}
impl Directory {
    fn open(parent: &impl AsFd, name: &str, create: bool) -> Result<Self> {
        if create {
            match fs::mkdirat(parent, name, fs::Mode::from_raw_mode(0o700)) {
                Ok(()) => {}
                Err(rustix::io::Errno::EXIST) => {}
                Err(_) => return Err(UNAVAILABLE),
            }
        }
        let fd =
            protected_files::open_directory_at(parent, OsStr::new(name)).map_err(|_| CORRUPT)?;
        Ok(Self {
            fd,
            parent: protected_files::duplicate_directory(parent.as_fd())
                .map_err(|_| UNAVAILABLE)?,
            name: name.into(),
        })
    }
    fn verify(&self) -> Result<()> {
        let actual = protected_files::open_directory_at(&self.parent, OsStr::new(&self.name))
            .map_err(|_| CORRUPT)?;
        if !same(&actual, &self.fd)? {
            return Err(CORRUPT);
        }
        Ok(())
    }
}
fn open_file(parent: &impl AsFd, name: &str, write: bool) -> Result<File> {
    let flags = if write {
        fs::OFlags::RDWR | fs::OFlags::CREATE | fs::OFlags::EXCL
    } else {
        fs::OFlags::RDONLY
    };
    let fd = fs::openat(
        parent,
        name,
        flags | fs::OFlags::NOFOLLOW | fs::OFlags::NONBLOCK | fs::OFlags::CLOEXEC,
        fs::Mode::from_raw_mode(0o600),
    )
    .map_err(|_| CORRUPT)?;
    let stat = fs::fstat(&fd).map_err(|_| UNAVAILABLE)?;
    if fs::FileType::from_raw_mode(stat.st_mode) != fs::FileType::RegularFile
        || stat.st_nlink != 1
        || stat.st_mode & 0o077 != 0
        || stat.st_uid != rustix::process::geteuid().as_raw()
    {
        return Err(CORRUPT);
    }
    Ok(File::from(fd))
}
fn sync(dir: &impl AsFd) -> Result<()> {
    fs::fsync(dir).map_err(|_| UNAVAILABLE)
}
fn bytes(file: &mut File, budget: usize) -> Result<Vec<u8>> {
    let size = usize::try_from(file.metadata().map_err(|_| UNAVAILABLE)?.len())
        .map_err(|_| UNAVAILABLE)?;
    if size > budget {
        return Err("DATASET_READ_BUDGET_EXCEEDED");
    }
    file.seek(SeekFrom::Start(0)).map_err(|_| UNAVAILABLE)?;
    let mut raw = Vec::new();
    file.take((budget as u64) + 1)
        .read_to_end(&mut raw)
        .map_err(|_| UNAVAILABLE)?;
    if raw.len() > budget {
        return Err("DATASET_READ_BUDGET_EXCEEDED");
    }
    Ok(raw)
}
pub struct Store {
    root: PathBuf,
    fd: OwnedFd,
    max_rows: usize,
    max_bytes: usize,
}
/// Fully re-read Dataset and its persisted manifest. Does not grant execution.
#[derive(Debug)]
pub struct VerifiedDataset {
    dataset: Dataset,
    manifest: Value,
}
impl VerifiedDataset {
    pub fn dataset(&self) -> &Dataset {
        &self.dataset
    }
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }
}
impl Store {
    /// Host provisions the owned root; a missing/rebound root is never absence.
    pub fn open(root: &Path, max_rows: usize, max_bytes: usize) -> Result<Self> {
        if max_rows == 0 || max_bytes == 0 || max_bytes > LIMIT {
            return Err(INVALID);
        }
        let fd = protected_files::open_directory(root).map_err(|_| UNAVAILABLE)?;
        Ok(Self {
            root: root.into(),
            fd,
            max_rows,
            max_bytes,
        })
    }
    fn verify_root(&self) -> Result<()> {
        let actual = protected_files::open_directory(&self.root).map_err(|_| UNAVAILABLE)?;
        if !same(&actual, &self.fd)? {
            return Err(UNAVAILABLE);
        }
        Ok(())
    }
    fn chain(&self, fingerprint: &str, create: bool) -> Result<(Directory, Directory)> {
        if !crate::is_sha256_hex(fingerprint) {
            return Err(INVALID);
        }
        self.verify_root()?;
        let sha = Directory::open(&self.fd, "sha256", create)?;
        let prefix = Directory::open(&sha.fd, &fingerprint[..2], create)?;
        sha.verify()?;
        prefix.verify()?;
        Ok((sha, prefix))
    }
    pub fn commit(
        &self,
        dataset: &Dataset,
        provenance: &Value,
        created_at: &str,
    ) -> Result<VerifiedDataset> {
        if dataset.rows().len() > self.max_rows {
            return Err("DATASET_READ_BUDGET_EXCEEDED");
        }
        validate_provenance(provenance, dataset.definition())?;
        let created_at = iso(created_at)?;
        self.verify_root()?;
        // One writer for the owning namespace; no lock-based inference of truth.
        let lockfd = fs::openat(
            &self.fd,
            ".dataset.lock",
            fs::OFlags::RDWR | fs::OFlags::CREATE | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(|_| UNAVAILABLE)?;
        let lockstat = fs::fstat(&lockfd).map_err(|_| UNAVAILABLE)?;
        if fs::FileType::from_raw_mode(lockstat.st_mode) != fs::FileType::RegularFile
            || lockstat.st_nlink != 1
            || lockstat.st_mode & 0o077 != 0
            || lockstat.st_uid != rustix::process::geteuid().as_raw()
        {
            return Err(CORRUPT);
        }
        fs::flock(&lockfd, fs::FlockOperation::NonBlockingLockExclusive)
            .map_err(|_| "DATASET_STORE_BUSY")?;
        let (sha, prefix) = self.chain(dataset.snapshot_fingerprint(), true)?;
        match fs::statat(
            &prefix.fd,
            dataset.snapshot_fingerprint(),
            fs::AtFlags::SYMLINK_NOFOLLOW,
        ) {
            Ok(_) => return self.load(dataset.snapshot_fingerprint()),
            Err(rustix::io::Errno::NOENT) => {}
            Err(_) => return Err(UNAVAILABLE),
        }
        let mut entropy = [0_u8; 16];
        getrandom::fill(&mut entropy).map_err(|_| UNAVAILABLE)?;
        let stage_name = format!(".stage-{}", hash(&entropy));
        fs::mkdirat(
            &prefix.fd,
            stage_name.as_str(),
            fs::Mode::from_raw_mode(0o700),
        )
        .map_err(|_| UNAVAILABLE)?;
        let stage = Directory::open(&prefix.fd, &stage_name, false)?;
        let data = Directory::open(&stage.fd, "data", true)?;
        let mut partitions = vec![];
        let mut used = 0_usize;
        for (index, id) in dataset.definition()["instruments"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .enumerate()
        {
            let partition = dataset
                .rows()
                .iter()
                .filter(|r| r["instrument_id"] == *id)
                .cloned()
                .collect::<Vec<_>>();
            let partition_id = format!("p-{index:06}");
            let name = format!("{partition_id}.parquet");
            let mut file = open_file(&data.fd, &name, true)?;
            columnar::write(&file, &partition)?;
            let raw = bytes(
                &mut file,
                self.max_bytes
                    .checked_sub(used)
                    .ok_or("DATASET_READ_BUDGET_EXCEEDED")?,
            )?;
            used = used.checked_add(raw.len()).ok_or(UNAVAILABLE)?;
            file.seek(SeekFrom::Start(0)).map_err(|_| UNAVAILABLE)?;
            let actual = columnar::read(file, self.max_rows, self.max_bytes as u64)?;
            if actual != partition {
                return Err(CORRUPT);
            }
            partitions.push(json!({"partition_id":partition_id,"row_count":actual.len(),"semantic_fingerprint":content_fingerprint(&actual)?,"relative_path":format!("data/{name}"),"byte_sha256":hash(&raw)}));
        }
        let manifest = json!({"schema_version":2,"snapshot_fingerprint":dataset.snapshot_fingerprint(),"definition":dataset.definition(),"definition_fingerprint":fp(dataset.definition())?,"dataset_schema":schema(),"dataset_schema_fingerprint":fp(&schema())?,"content_fingerprint":dataset.content_fingerprint(),"row_count":dataset.rows().len(),"partitions":partitions,"provenance":provenance,"created_at":created_at,"construction_fingerprint":dataset.construction_fingerprint()});
        let raw = canonical(&manifest)?;
        if raw.len() > self.max_bytes.checked_sub(used).ok_or(UNAVAILABLE)? {
            return Err("DATASET_READ_BUDGET_EXCEEDED");
        }
        let mut file = open_file(&stage.fd, "manifest.json", true)?;
        file.write_all(raw.as_bytes()).map_err(|_| UNAVAILABLE)?;
        file.sync_all().map_err(|_| UNAVAILABLE)?;
        sync(&data.fd)?;
        sync(&stage.fd)?;
        data.verify()?;
        stage.verify()?;
        prefix.verify()?;
        sha.verify()?;
        self.verify_root()?;
        match fs::renameat_with(
            &prefix.fd,
            stage_name.as_str(),
            &prefix.fd,
            dataset.snapshot_fingerprint(),
            fs::RenameFlags::NOREPLACE,
        ) {
            Ok(()) => {}
            Err(rustix::io::Errno::EXIST) => return self.load(dataset.snapshot_fingerprint()),
            Err(_) => return Err("DATASET_PUBLICATION_UNKNOWN"),
        }
        sync(&prefix.fd)?;
        sync(&sha.fd)?;
        sync(&self.fd)?;
        let target = Directory::open(&prefix.fd, dataset.snapshot_fingerprint(), false)?;
        if !same(&target.fd, &stage.fd)? {
            return Err(CORRUPT);
        }
        self.load(dataset.snapshot_fingerprint())
    }
    pub fn load(&self, fingerprint: &str) -> Result<VerifiedDataset> {
        let (sha, prefix) = self.chain(fingerprint, false)?;
        let target = Directory::open(&prefix.fd, fingerprint, false)?;
        let mut manifest_file = open_file(&target.fd, "manifest.json", false)?;
        let raw = bytes(&mut manifest_file, self.max_bytes)?;
        let manifest_hash = hash(&raw);
        let mut used = raw.len();
        let raw = std::str::from_utf8(&raw).map_err(|_| CORRUPT)?;
        onlyalpha_metadata_json::canonical_json(raw, LIMIT).map_err(|_| CORRUPT)?;
        let m: Value = serde_json::from_str(raw).map_err(|_| CORRUPT)?;
        exact(
            &m,
            &[
                "schema_version",
                "snapshot_fingerprint",
                "definition",
                "definition_fingerprint",
                "dataset_schema",
                "dataset_schema_fingerprint",
                "content_fingerprint",
                "row_count",
                "partitions",
                "provenance",
                "created_at",
                "construction_fingerprint",
            ],
        )?;
        if m["schema_version"] != 2
            || m["snapshot_fingerprint"] != fingerprint
            || m["dataset_schema"] != schema()
            || m["dataset_schema_fingerprint"] != fp(&schema())?
            || m["definition_fingerprint"] != fp(&m["definition"])?
        {
            return Err(CORRUPT);
        }
        iso(text(&m["created_at"])?)?;
        validate_provenance(&m["provenance"], &m["definition"])?;
        let n = usize::try_from(number(&m["row_count"])?).map_err(|_| CORRUPT)?;
        if n > self.max_rows {
            return Err("DATASET_READ_BUDGET_EXCEEDED");
        }
        let ids = m["definition"]["instruments"].as_array().ok_or(CORRUPT)?;
        let partitions = m["partitions"].as_array().ok_or(CORRUPT)?;
        if partitions.len() != ids.len() {
            return Err(CORRUPT);
        }
        let data = Directory::open(&target.fd, "data", false)?;
        let mut rows = vec![];
        let mut selected_files = vec![];
        for (index, p) in partitions.iter().enumerate() {
            exact(
                p,
                &[
                    "partition_id",
                    "row_count",
                    "semantic_fingerprint",
                    "relative_path",
                    "byte_sha256",
                ],
            )?;
            let id = format!("p-{index:06}");
            let name = format!("{id}.parquet");
            if p["partition_id"] != id || p["relative_path"] != format!("data/{name}") {
                return Err(CORRUPT);
            }
            let mut file = open_file(&data.fd, &name, false)?;
            let raw = bytes(
                &mut file,
                self.max_bytes
                    .checked_sub(used)
                    .ok_or("DATASET_READ_BUDGET_EXCEEDED")?,
            )?;
            used = used.checked_add(raw.len()).ok_or(UNAVAILABLE)?;
            if p["byte_sha256"] != hash(&raw) {
                return Err(CORRUPT);
            }
            file.seek(SeekFrom::Start(0)).map_err(|_| UNAVAILABLE)?;
            let retained = file.try_clone().map_err(|_| UNAVAILABLE)?;
            let actual = columnar::read(
                file,
                self.max_rows.checked_sub(rows.len()).ok_or(CORRUPT)?,
                self.max_bytes as u64,
            )?;
            if p["row_count"] != json!(actual.len())
                || p["semantic_fingerprint"] != content_fingerprint(&actual)?
                || actual.iter().any(|r| r["instrument_id"] != ids[index])
            {
                return Err(CORRUPT);
            }
            selected_files.push((name, retained, hash(&raw)));
            rows.extend(actual);
        }
        let dataset = Dataset::from_bars(
            &m["definition"],
            &rows_to_bars(&rows)?,
            text(&m["construction_fingerprint"])?,
            self.max_rows,
        )?;
        if dataset.rows() != rows
            || dataset.snapshot_fingerprint() != fingerprint
            || dataset.content_fingerprint() != m["content_fingerprint"]
            || rows.len() != n
        {
            return Err(CORRUPT);
        }
        for (name, file, expected_hash) in &mut selected_files {
            verify_selected(&data.fd, name, file, expected_hash, self.max_bytes)?;
        }
        verify_selected(
            &target.fd,
            "manifest.json",
            &mut manifest_file,
            &manifest_hash,
            self.max_bytes,
        )?;
        data.verify()?;
        target.verify()?;
        prefix.verify()?;
        sha.verify()?;
        self.verify_root()?;
        Ok(VerifiedDataset {
            dataset,
            manifest: m,
        })
    }
}
fn validate_provenance(p: &Value, definition: &Value) -> Result<()> {
    let rows = p.as_array().ok_or(INVALID)?;
    let ids = definition["instruments"].as_array().ok_or(INVALID)?;
    if rows.len() != ids.len() {
        return Err(INVALID);
    }
    for (row, id) in rows.iter().zip(ids) {
        exact(
            row,
            &[
                "instrument_id",
                "source_id",
                "plugin_id",
                "plugin_version",
                "data_version",
                "cache_content_fingerprint",
                "resolved_ranges",
                "observed_ranges",
                "source_metadata",
            ],
        )?;
        if row["instrument_id"] != *id || !row["source_metadata"].is_object() {
            return Err(INVALID);
        }
        for k in ["source_id", "plugin_id", "plugin_version"] {
            if text(&row[k])?.trim().is_empty() {
                return Err(INVALID);
            }
        }
        for k in ["resolved_ranges", "observed_ranges"] {
            for range in row[k].as_array().ok_or(INVALID)? {
                let range = range.as_array().ok_or(INVALID)?;
                if range.len() != 2
                    || range
                        .iter()
                        .any(|v| v.as_str().is_none_or(|s| s.trim().is_empty()))
                {
                    return Err(INVALID);
                }
            }
        }
        if !row["data_version"].is_null() {
            text(&row["data_version"])?;
        }
        if !row["cache_content_fingerprint"].is_null()
            && !crate::is_sha256_hex(text(&row["cache_content_fingerprint"])?)
        {
            return Err(INVALID);
        }
    }
    Ok(())
}

fn verify_selected(
    parent: &impl AsFd,
    name: &str,
    original: &mut File,
    expected_hash: &str,
    budget: usize,
) -> Result<()> {
    let mut current = open_file(parent, name, false)?;
    if !same(&current, original)?
        || hash(&bytes(original, budget)?) != expected_hash
        || hash(&bytes(&mut current, budget)?) != expected_hash
    {
        return Err(CORRUPT);
    }
    Ok(())
}

impl Store {
    /// Exact retained materialization fact. No source query, creation or fallback.
    pub(crate) fn load_materialization(&self, id: &str) -> Result<Value> {
        let fingerprint = id
            .strip_prefix("dataset-materialization:")
            .filter(|s| crate::is_sha256_hex(s))
            .ok_or(INVALID)?;
        self.verify_root()?;
        let directory = Directory::open(&self.fd, "materializations", false)?;
        let sha = Directory::open(&directory.fd, "sha256", false)?;
        let prefix = Directory::open(&sha.fd, &fingerprint[..2], false)?;
        let name = format!("{fingerprint}.json");
        let mut file = open_file(&prefix.fd, &name, false)?;
        let bytes = bytes(&mut file, self.max_bytes)?;
        let expected = hash(&bytes);
        let raw = std::str::from_utf8(&bytes).map_err(|_| CORRUPT)?;
        if onlyalpha_metadata_json::canonical_json(raw, LIMIT).map_err(|_| CORRUPT)? != raw {
            return Err(CORRUPT);
        }
        let value: Value = serde_json::from_str(raw).map_err(|_| CORRUPT)?;
        lineage_semantic(&value)?;
        if value["materialization_id"] != id {
            return Err(CORRUPT);
        }
        self.load(text(&value["dataset_snapshot_fingerprint"])?)?;
        verify_selected(&prefix.fd, &name, &mut file, &expected, self.max_bytes)?;
        prefix.verify()?;
        sha.verify()?;
        directory.verify()?;
        self.verify_root()?;
        Ok(value)
    }
    pub(crate) fn commit_materialization(&self, value: &Value) -> Result<Value> {
        let semantic = lineage_semantic(value)?;
        let id = text(&value["materialization_id"])?;
        let fingerprint = id.strip_prefix("dataset-materialization:").ok_or(INVALID)?;
        self.load(text(&value["dataset_snapshot_fingerprint"])?)?;
        self.verify_root()?;
        let directory = Directory::open(&self.fd, "materializations", true)?;
        let sha = Directory::open(&directory.fd, "sha256", true)?;
        let prefix = Directory::open(&sha.fd, &fingerprint[..2], true)?;
        let name = format!("{fingerprint}.json");
        match fs::statat(&prefix.fd, name.as_str(), fs::AtFlags::SYMLINK_NOFOLLOW) {
            Ok(_) => {}
            Err(rustix::io::Errno::NOENT) => {
                let mut entropy = [0u8; 16];
                getrandom::fill(&mut entropy).map_err(|_| UNAVAILABLE)?;
                let stage = format!(".stage-{}.json", hash(&entropy));
                let mut file = open_file(&prefix.fd, &stage, true)?;
                let raw = canonical(value)?;
                if raw.len() > self.max_bytes {
                    return Err("DATASET_READ_BUDGET_EXCEEDED");
                }
                file.write_all(raw.as_bytes()).map_err(|_| UNAVAILABLE)?;
                file.sync_all().map_err(|_| UNAVAILABLE)?;
                match fs::renameat_with(
                    &prefix.fd,
                    stage.as_str(),
                    &prefix.fd,
                    name.as_str(),
                    fs::RenameFlags::NOREPLACE,
                ) {
                    Ok(()) | Err(rustix::io::Errno::EXIST) => {}
                    Err(_) => return Err("DATASET_PUBLICATION_UNKNOWN"),
                }
                sync(&prefix.fd)?;
                sync(&sha.fd)?;
                sync(&directory.fd)?;
                sync(&self.fd)?;
            }
            Err(_) => return Err(UNAVAILABLE),
        }
        let mut file = open_file(&prefix.fd, &name, false)?;
        let raw = bytes(&mut file, self.max_bytes)?;
        let expected = hash(&raw);
        let raw = std::str::from_utf8(&raw).map_err(|_| CORRUPT)?;
        onlyalpha_metadata_json::canonical_json(raw, LIMIT).map_err(|_| CORRUPT)?;
        let prior: Value = serde_json::from_str(raw).map_err(|_| CORRUPT)?;
        if lineage_semantic(&prior)? != semantic {
            return Err("DATASET_MATERIALIZATION_IDENTITY_CONFLICT");
        }
        verify_selected(&prefix.fd, &name, &mut file, &expected, self.max_bytes)?;
        prefix.verify()?;
        sha.verify()?;
        directory.verify()?;
        self.verify_root()?;
        Ok(prior)
    }
}
fn lineage_semantic(value: &Value) -> Result<Value> {
    exact(
        value,
        &[
            "schema_version",
            "materialization_id",
            "dataset_snapshot_fingerprint",
            "market_data_revision_bindings",
            "materializer_id",
            "materializer_version",
            "request_fingerprint",
            "created_at",
        ],
    )?;
    if value["schema_version"] != 1
        || value["materializer_id"] != "onlyalpha.sealed-market-data"
        || value["materializer_version"] != "1"
    {
        return Err(INVALID);
    }
    for k in ["dataset_snapshot_fingerprint", "request_fingerprint"] {
        if !crate::is_sha256_hex(text(&value[k])?) {
            return Err(INVALID);
        }
    }
    iso(text(&value["created_at"])?)?;
    let bindings = value["market_data_revision_bindings"]
        .as_array()
        .ok_or(INVALID)?;
    if bindings.is_empty() {
        return Err(INVALID);
    }
    let mut previous = None;
    for binding in bindings {
        exact(
            binding,
            &[
                "source_id",
                "instrument_id",
                "data_kind",
                "revision_id",
                "revision_fingerprint",
            ],
        )?;
        let key = (
            text(&binding["source_id"])?,
            text(&binding["instrument_id"])?,
            text(&binding["data_kind"])?,
        );
        if previous.is_some_and(|p| p >= key)
            || [key.0, key.1, key.2].iter().any(|s| s.trim().is_empty())
            || key.2 != "BAR"
            || !crate::is_sha256_hex(text(&binding["revision_fingerprint"])?)
            || binding["revision_id"]
                != format!(
                    "market-data-revision:{}",
                    text(&binding["revision_fingerprint"])?
                )
        {
            return Err(INVALID);
        }
        previous = Some(key);
    }
    let mut semantic = value.clone();
    for key in ["schema_version", "materialization_id", "created_at"] {
        semantic.as_object_mut().ok_or(INVALID)?.remove(key);
    }
    if value["materialization_id"] != format!("dataset-materialization:{}", fp(&semantic)?) {
        return Err(INVALID);
    }
    Ok(semantic)
}
