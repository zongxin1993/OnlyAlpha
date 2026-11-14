//! Opaque read-only source proof. This cannot recover or acknowledge a Store.
use crate::{RunBacktestResult, SqliteStore};
use onlyalpha_execution::{Components, Error, Record};
use onlyalpha_observability::{Correlation, Operation, measure};
use serde_json::Value;
#[cfg(not(target_os = "linux"))]
use std::io::Read;
#[cfg(target_os = "linux")]
use std::os::unix::fs::{FileExt, MetadataExt};
use std::{
    fs::{self, File},
    path::{Path, PathBuf},
};
fn bad(reason: &str) -> Error {
    Error(format!("RUNTIME_READ_ONLY_{reason}"))
}
fn io<T>(value: std::io::Result<T>) -> Result<T, Error> {
    value.map_err(|e| bad(&e.to_string()))
}
pub(crate) fn source_path(root: &Path) -> Result<PathBuf, Error> {
    if !cfg!(target_os = "linux") || !root.is_absolute() {
        return Err(bad("PLATFORM_OR_PATH"));
    }
    let actual = io(root.canonicalize())?;
    if actual != root || !io(fs::symlink_metadata(root))?.is_dir() {
        return Err(bad("ROOT"));
    }
    for suffix in ["-wal", "-shm", "-journal"] {
        match fs::symlink_metadata(root.join(format!("runtime.sqlite3{suffix}"))) {
            Ok(_) => return Err(bad("SIDECAR_REQUIRES_RECOVERY")),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(bad(&e.to_string())),
        }
    }
    let path = root.join("runtime.sqlite3");
    let metadata = io(fs::symlink_metadata(&path))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(bad("FILE"));
    }
    Ok(path)
}
pub(crate) fn verify_file(path: &Path, lease: &File) -> Result<(), Error> {
    let current = source_path(path.parent().ok_or_else(|| bad("ROOT"))?)?;
    if current != path {
        return Err(bad("PATH"));
    }
    let actual = io(fs::symlink_metadata(path))?;
    let held = io(lease.metadata())?;
    #[cfg(target_os = "linux")]
    if actual.dev() != held.dev()
        || actual.ino() != held.ino()
        || actual.nlink() != 1
        || held.nlink() != 1
    {
        return Err(bad("INODE_OR_LINK"));
    }
    if actual.len() != held.len() {
        return Err(bad("SIZE"));
    }
    let mut header = [0u8; 100];
    #[cfg(target_os = "linux")]
    io(lease.read_exact_at(&mut header, 0))?;
    #[cfg(not(target_os = "linux"))]
    {
        let mut file = io(File::open(path))?;
        io(file.read_exact(&mut header))?;
    }
    if &header[..16] != b"SQLite format 3\0" || header[18] != 1 || header[19] != 1 {
        return Err(bad("FORMAT_OR_WAL"));
    }
    let encoded = u16::from_be_bytes([header[16], header[17]]);
    let page = if encoded == 1 {
        65536
    } else {
        u64::from(encoded)
    };
    let count = u64::from(u32::from_be_bytes(
        header[28..32].try_into().map_err(|_| bad("HEADER"))?,
    ));
    if !page.is_power_of_two()
        || !(512..=65536).contains(&page)
        || count.checked_mul(page) != Some(held.len())
    {
        return Err(bad("UNANCHORED_FILE_TAIL"));
    }
    Ok(())
}
struct Source {
    store: SqliteStore,
    components: Components,
    records: Vec<Record>,
    binding: Value,
    refs: Vec<crate::ReplayEntryRef>,
    state: Value,
    checkpoints: Value,
}
impl Source {
    fn read(
        root: &Path,
        configuration: Value,
        artifact: &str,
        expected: Option<&[crate::ReplayEntryRef]>,
    ) -> Result<Self, Error> {
        let operation = Operation::start("runtime", "source.read", Correlation::default());
        let result: Result<Self, Error> = operation.span().in_scope(|| {
            let store = measure("runtime", "source.open", Correlation::default(), || {
                SqliteStore::read_only(root, configuration, artifact)
            })?;
            let (components, records, checkpoints) = measure(
                "runtime",
                "source.checkpoints.rebuild",
                Correlation::default(),
                || store.read_ready_components(),
            )?;
            let binding = measure("runtime", "source.binding", Correlation::default(), || {
                store.replay_binding()
            })?
            .ok_or_else(|| bad("UNBOUND"))?;
            let refs = measure(
                "runtime",
                "source.replay_refs",
                Correlation::default(),
                || store.replay_refs_from_source(&records),
            )?;
            if refs.iter().any(|row| !row.ready()) {
                return Err(bad("REPLAY_NOT_READY"));
            }
            if let Some(expected) = expected {
                if refs != expected {
                    return Err(bad("SOURCE_CHANGED"));
                }
            } else {
                for reference in &refs {
                    measure(
                        "runtime",
                        "source.replay_step.validate",
                        Correlation::default(),
                        || store.logical_step(reference),
                    )?;
                }
            }
            let state = measure(
                "runtime",
                "source.final_state",
                Correlation::default(),
                || store.with_ready_source(&components, |source| source.state(&components)),
            )?;
            verify_file(&source_path(root)?, &store.read_lease()?)?;
            Ok(Self {
                store,
                components,
                records,
                binding,
                refs,
                state,
                checkpoints,
            })
        });
        let count = result
            .as_ref()
            .map_or(0, |source| source.records.len() as u64);
        operation.finish(if result.is_ok() { "ok" } else { "failed" }, count, 0);
        result
    }
}
/// The held shared lease excludes legitimate writers. Ref expectations are
/// data only; every complete cut opens a fresh read-only connection and source.
pub struct VerifiedReplaySnapshot {
    root: PathBuf,
    configuration: Value,
    artifact: String,
    lease: File,
    storage_version: u32,
    reader: std::sync::Mutex<SqliteStore>,
    binding: Value,
    refs: Vec<crate::ReplayEntryRef>,
    state: Value,
    records: Vec<Record>,
    checkpoints: Value,
}
impl VerifiedReplaySnapshot {
    pub fn read(root: &Path, configuration: Value, artifact: &str) -> Result<Self, Error> {
        let source = Source::read(root, configuration.clone(), artifact, None)?;
        Ok(Self {
            root: root.into(),
            configuration,
            artifact: artifact.into(),
            lease: source.store.read_lease()?,
            storage_version: source.store.storage_version,
            reader: std::sync::Mutex::new(source.store),
            binding: source.binding,
            refs: source.refs,
            state: source.state,
            records: source.records,
            checkpoints: source.checkpoints,
        })
    }
    fn current(&self) -> Result<Source, Error> {
        verify_file(&source_path(&self.root)?, &self.lease)?;
        let source = Source::read(
            &self.root,
            self.configuration.clone(),
            &self.artifact,
            Some(&self.refs),
        )?;
        #[cfg(target_os = "linux")]
        {
            let old = io(self.lease.metadata())?;
            let new = io(source.store.read_lease()?.metadata())?;
            if old.dev() != new.dev() || old.ino() != new.ino() {
                return Err(bad("INODE"));
            }
        }
        measure(
            "runtime",
            "source.cut.compare",
            Correlation::default(),
            || {
                if source.store.storage_version != self.storage_version
                    || source.binding != self.binding
                    || source.state != self.state
                    || source.records != self.records
                    || source.checkpoints != self.checkpoints
                {
                    return Err(bad("SOURCE_CHANGED"));
                }
                Ok(())
            },
        )?;
        verify_file(&source_path(&self.root)?, &self.lease)?;
        Ok(source)
    }
    pub fn storage_version(&self) -> u32 {
        self.storage_version
    }
    pub fn verify_cut(&self) -> Result<(), Error> {
        self.current().map(drop)
    }
    pub fn binding(&self) -> &Value {
        &self.binding
    }
    pub fn refs(&self) -> &[crate::ReplayEntryRef] {
        &self.refs
    }
    pub fn read_step(&self, reference: &crate::ReplayEntryRef) -> Result<Value, Error> {
        verify_file(&source_path(&self.root)?, &self.lease)?;
        if self.refs.get(
            usize::try_from(
                reference
                    .index()
                    .checked_sub(1)
                    .ok_or_else(|| bad("INDEX"))?,
            )
            .map_err(|_| bad("INDEX"))?,
        ) != Some(reference)
        {
            return Err(bad("REFERENCE"));
        }
        let value = {
            let reader = self.reader.lock().map_err(|_| bad("READER_POISONED"))?;
            reader.logical_step(reference)?
        };
        verify_file(&source_path(&self.root)?, &self.lease)?;
        Ok(value)
    }
    pub fn for_each_step(
        &self,
        mut visit: impl FnMut(&Value, &crate::ReplayEntryRef) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.verify_cut()?;
        for reference in &self.refs {
            let value = self.read_step(reference)?;
            visit(&value, reference)?;
        }
        self.verify_cut()
    }
    pub fn write_encoded_step(
        &self,
        reference: &crate::ReplayEntryRef,
        writer: &mut dyn std::io::Write,
    ) -> Result<u64, Error> {
        verify_file(&source_path(&self.root)?, &self.lease)?;
        if self.refs.get(
            usize::try_from(
                reference
                    .index()
                    .checked_sub(1)
                    .ok_or_else(|| bad("INDEX"))?,
            )
            .map_err(|_| bad("INDEX"))?,
        ) != Some(reference)
        {
            return Err(bad("REFERENCE"));
        }
        let raw = {
            let reader = self.reader.lock().map_err(|_| bad("READER_POISONED"))?;
            reader.encoded_step(reference)?
        };
        writer
            .write_all(raw.as_bytes())
            .map_err(|e| bad(&e.to_string()))?;
        verify_file(&source_path(&self.root)?, &self.lease)?;
        Ok(raw.len() as u64)
    }
    /// Explicit bounded technical expansion. Production trace streams use refs.
    pub fn steps(&self) -> Result<Vec<Value>, Error> {
        self.verify_cut()?;
        let mut total = 0_u64;
        let mut result = Vec::with_capacity(self.refs.len());
        for reference in &self.refs {
            total = total
                .checked_add(reference.decoded_size())
                .filter(|n| *n <= 128 * 1024 * 1024)
                .ok_or_else(|| bad("EXPANSION_BOUND"))?;
            result.push(
                serde_json::json!({"step":self.read_step(reference)?,"ready":reference.ready()}),
            );
        }
        self.verify_cut()?;
        Ok(result)
    }
    pub fn state(&self) -> &Value {
        &self.state
    }
    pub fn records(&self) -> &[Record] {
        &self.records
    }
    pub fn backtest_result(
        &self,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<RunBacktestResult, Error> {
        let source = self.current()?;
        if manifest["kernel_artifact"] != self.artifact {
            return Err(bad("RESULT_ARTIFACT"));
        }
        source
            .store
            .backtest_result_at_ready(&source.components, manifest, outcome)
    }
}
