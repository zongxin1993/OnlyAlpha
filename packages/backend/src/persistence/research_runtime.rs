//! Existing Generation journal: retained input reads and native lifecycle mutations.
mod contracts;
mod lifecycle;
mod publication;
use crate::{application::factor_content::hash, security::protected_files as protected};
pub use lifecycle::Registry;
use rustix::{fd::OwnedFd, fs};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsStr,
    os::fd::AsFd,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_RUNTIME_PROOF_INVALID";
const UNAVAILABLE: &str = "RESEARCH_RUNTIME_UNAVAILABLE";
const LIMIT: usize = 8 * 1024 * 1024;
fn digest(v: &Value, field: &str) -> Result<String> {
    let mut v = v.clone();
    let expected = v
        .as_object_mut()
        .ok_or(INVALID)?
        .remove(field)
        .ok_or(INVALID)?;
    let actual = hash(&v).map_err(|_| INVALID)?;
    if expected.as_str() != Some(actual.as_str()) {
        return Err(INVALID);
    }
    Ok(actual)
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or(INVALID)
}
fn sha(v: &Value, k: &str) -> Result<String> {
    let s = text(v, k)?;
    if !crate::is_sha256_hex(s) {
        return Err(INVALID);
    }
    Ok(s.into())
}
fn exact(v: &Value, fields: &[&str]) -> Result<()> {
    let m = v.as_object().ok_or(INVALID)?;
    if m.len() != fields.len() || fields.iter().any(|f| !m.contains_key(*f)) {
        return Err(INVALID);
    }
    Ok(())
}
fn same(a: &impl AsFd, b: &impl AsFd) -> Result<bool> {
    let a = fs::fstat(a).map_err(|_| UNAVAILABLE)?;
    let b = fs::fstat(b).map_err(|_| UNAVAILABLE)?;
    Ok(a.st_dev == b.st_dev && a.st_ino == b.st_ino)
}
fn read(root: &OwnedFd, path: &str) -> Result<Vec<u8>> {
    let mut parts = path.split('/').peekable();
    let mut dir = protected::duplicate_directory(root.as_fd()).map_err(|_| UNAVAILABLE)?;
    while let Some(name) = parts.next() {
        if parts.peek().is_some() {
            dir = protected::open_directory_at(&dir, OsStr::new(name)).map_err(|_| UNAVAILABLE)?
        } else {
            return protected::read_file_at(
                &dir,
                OsStr::new(name),
                protected::FilePolicy::HistoryDocument,
                LIMIT,
            )
            .map(|b| b.to_vec())
            .map_err(|_| UNAVAILABLE);
        }
    }
    Err(INVALID)
}
/// A live shared-lock hold. Its private fields cannot be constructed from a JSON claim.
/// Keep this guard through the bounded durable input handoff, then drop it.
pub struct RuntimeInputHold {
    root_path: PathBuf,
    root: OwnedFd,
    lock: OwnedFd,
    records: Vec<(String, Vec<u8>)>,
    manifest: Value,
    binding: Value,
    artifacts: Vec<(String, String, u64)>,
    executor: Option<Value>,
    core: Option<Value>,
}
struct History {
    states: BTreeMap<String, &'static str>,
    active: Option<String>,
    bindings: BTreeMap<String, (String, bool, Value)>,
    closed: BTreeSet<String>,
    validated: BTreeMap<String, Value>,
}
impl RuntimeInputHold {
    pub fn open(root: &Path, work: &str, owner: &str, generation: &str) -> Result<Self> {
        if work.trim().is_empty() || owner.trim().is_empty() || !crate::is_sha256_hex(generation) {
            return Err(INVALID);
        }
        let mut hold = Self::acquire(root, fs::FlockOperation::NonBlockingLockShared)?;
        let history = hold.replay()?;
        let (g, is_active, origin) = history
            .bindings
            .get(work)
            .ok_or("RESEARCH_RUNTIME_WORK_UNBOUND")?;
        if g != generation
            || !*is_active
            || history.closed.contains(work)
            || origin["kind"] != "RuntimeWorkBound"
            || origin["reason"] != owner
            || !matches!(
                history.states.get(g),
                Some(&"READY" | &"ACTIVE_FOR_NEW_WORK" | &"DRAINING")
            )
        {
            return Err("RESEARCH_RUNTIME_WORK_MISMATCH");
        }
        hold.manifest = history.validated.get(g).cloned().ok_or(INVALID)?;
        hold.binding = origin.clone();
        hold.verify()?;
        Ok(hold)
    }
    fn acquire(root: &Path, operation: fs::FlockOperation) -> Result<Self> {
        let fd = protected::open_directory(root).map_err(|_| UNAVAILABLE)?;
        let lock = fs::openat(
            &fd,
            ".generation-authority.lock",
            fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC | fs::OFlags::NONBLOCK,
            fs::Mode::empty(),
        )
        .map_err(|_| UNAVAILABLE)?;
        let st = fs::fstat(&lock).map_err(|_| UNAVAILABLE)?;
        if fs::FileType::from_raw_mode(st.st_mode) != fs::FileType::RegularFile
            || st.st_nlink != 1
            || st.st_mode & 0o077 != 0
            || st.st_uid != rustix::process::geteuid().as_raw()
        {
            return Err(INVALID);
        }
        fs::flock(&lock, operation).map_err(|_| UNAVAILABLE)?;
        Ok(Self {
            root_path: root.into(),
            root: fd,
            lock,
            records: Vec::new(),
            manifest: Value::Null,
            binding: Value::Null,
            artifacts: Vec::new(),
            executor: None,
            core: None,
        })
    }
    fn replay(&mut self) -> Result<History> {
        let ledger = self.record("generation-events.jsonl")?;
        self.replay_ledger(&ledger)
    }
    fn replay_ledger(&mut self, ledger: &[u8]) -> Result<History> {
        let mut states: BTreeMap<String, &str> = BTreeMap::new();
        let mut active: Option<String> = None;
        let mut bindings: BTreeMap<String, (String, bool, Value)> = BTreeMap::new();
        let mut closed = BTreeSet::new();
        let mut previous = Value::Null;
        let mut validated = BTreeMap::new();
        if !ledger.is_empty() && !ledger.ends_with(b"\n") {
            return Err(INVALID);
        }
        let lines = std::str::from_utf8(ledger).map_err(|_| INVALID)?.lines();
        for (i, line) in lines.enumerate() {
            if i >= 32768 {
                return Err(UNAVAILABLE);
            }
            let e: Value = serde_json::from_str(line).map_err(|_| INVALID)?;
            exact(
                &e,
                &[
                    "schema_version",
                    "sequence",
                    "kind",
                    "occurred_at",
                    "actor",
                    "generation_fingerprint",
                    "previous_event_fingerprint",
                    "expected_current",
                    "work_id",
                    "reason",
                    "validation_evidence_fingerprint",
                    "event_fingerprint",
                ],
            )?;
            if e["schema_version"].as_u64() != Some(1)
                || e["sequence"].as_u64() != Some(i as u64 + 1)
                || e["previous_event_fingerprint"] != previous
            {
                return Err(INVALID);
            }
            let at = text(&e, "occurred_at")?
                .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()
                .map_err(|_| INVALID)?;
            let mut canonical = e.clone();
            canonical["occurred_at"] =
                format!("{}+00:00", at.to_string().trim_end_matches('Z')).into();
            for k in ["previous_event_fingerprint", "expected_current"] {
                if !e[k].is_null() {
                    sha(&e, k)?;
                }
            }
            if !e["reason"].is_null() && !e["reason"].is_string() {
                return Err(INVALID);
            }
            let ef = digest(&canonical, "event_fingerprint")?;
            previous = json!(ef);
            text(&e, "actor")?;
            let g = sha(&e, "generation_fingerprint")?;
            let kind = text(&e, "kind")?;
            let state = states.get(&g).copied();
            if kind != "GenerationPrepared" && state.is_none() {
                return Err(INVALID);
            }
            let work_event = matches!(
                kind,
                "RuntimeWorkBound"
                    | "RuntimeExactWorkBound"
                    | "RuntimeWorkReleased"
                    | "RuntimeNewWorkClosed"
            );
            if work_event {
                text(&e, "work_id")?;
            } else if !e["work_id"].is_null() {
                return Err(INVALID);
            }
            if kind != "GenerationValidated" && !e["validation_evidence_fingerprint"].is_null() {
                return Err(INVALID);
            }
            match kind {
                "GenerationPrepared" => {
                    if state.is_some() {
                        return Err(INVALID);
                    }
                    states.insert(g, "PREPARING");
                }
                "GenerationValidated" => {
                    if state != Some("PREPARING") {
                        return Err(INVALID);
                    }
                    let m = self.load_manifest(&g)?;
                    let v = self.json(&format!("runtime-generation-validation/{g}.json"))?;
                    exact(
                        &v,
                        &[
                            "schema_version",
                            "validation_contract_version",
                            "runtime_generation_fingerprint",
                            "core_execution_fingerprint",
                            "artifact_manifest_fingerprints",
                            "artifact_sha256s",
                            "providers",
                            "catalog_generation_fingerprint",
                            "implementations",
                            "private_factor_bindings",
                            "validation_evidence_fingerprint",
                        ],
                    )?;
                    if e["validation_evidence_fingerprint"]
                        != digest(&v, "validation_evidence_fingerprint")?
                        || v["validation_contract_version"]
                            != "ONLYALPHA_RUNTIME_GENERATION_VALIDATION@1"
                        || v["schema_version"].as_u64() != Some(1)
                        || v["runtime_generation_fingerprint"] != g
                        || v["core_execution_fingerprint"]
                            != hash(&m["core_execution"]).map_err(|_| INVALID)?
                    {
                        return Err(INVALID);
                    }
                    for k in [
                        "artifact_manifest_fingerprints",
                        "artifact_sha256s",
                        "providers",
                        "catalog_generation_fingerprint",
                        "implementations",
                        "private_factor_bindings",
                    ] {
                        if v[k] != m[k] {
                            return Err(INVALID);
                        }
                    }
                    validated.insert(g.clone(), m);
                    states.insert(g, "READY");
                }
                "GenerationRejected" => {
                    if state != Some("PREPARING") {
                        return Err(INVALID);
                    }
                    states.insert(g, "REJECTED");
                }
                "GenerationActivated" => {
                    if !matches!(state, Some("READY" | "DRAINING"))
                        || e["expected_current"] != json!(active)
                        || active.as_deref() == Some(&g)
                    {
                        return Err(INVALID);
                    }
                    if let Some(old) = active.replace(g.clone()) {
                        states.insert(old, "DRAINING");
                    }
                    states.insert(g, "ACTIVE_FOR_NEW_WORK");
                }
                "GenerationRetired" => {
                    if state != Some("DRAINING")
                        || active.as_deref() == Some(&g)
                        || bindings.values().any(|(bg, a, _)| bg == &g && *a)
                    {
                        return Err(INVALID);
                    }
                    states.insert(g, "RETIRED");
                }
                "RuntimeWorkBound" | "RuntimeExactWorkBound" => {
                    let w = text(&e, "work_id")?.to_owned();
                    if bindings.contains_key(&w)
                        || closed.contains(&w)
                        || !matches!(state, Some("READY" | "ACTIVE_FOR_NEW_WORK" | "DRAINING"))
                        || (kind == "RuntimeWorkBound" && active.as_deref() != Some(&g))
                    {
                        return Err(INVALID);
                    }
                    bindings.insert(w, (g, true, e));
                }
                "RuntimeWorkReleased" => {
                    let b = bindings.get_mut(text(&e, "work_id")?).ok_or(INVALID)?;
                    if !b.1 || b.0 != g {
                        return Err(INVALID);
                    }
                    b.1 = false;
                }
                "RuntimeNewWorkClosed" => {
                    let w = text(&e, "work_id")?.to_owned();
                    let reason: Value =
                        serde_json::from_str(text(&e, "reason")?).map_err(|_| INVALID)?;
                    exact(&reason, &["owner", "closure_reason"])?;
                    text(&reason, "owner")?;
                    text(&reason, "closure_reason")?;
                    let canonical_reason = reason.to_string();
                    if !e["expected_current"].is_null()
                        || e["reason"].as_str() != Some(canonical_reason.as_str())
                        || !closed.insert(w.clone())
                    {
                        return Err(INVALID);
                    }
                    if let Some((bg, a, origin)) = bindings.get(&w) {
                        if *a
                            || bg != &g
                            || origin["kind"] != "RuntimeWorkBound"
                            || origin["reason"] != reason["owner"]
                        {
                            return Err(INVALID);
                        }
                    } else if !matches!(
                        state,
                        Some("READY" | "ACTIVE_FOR_NEW_WORK" | "DRAINING" | "RETIRED")
                    ) {
                        return Err(INVALID);
                    }
                }
                _ => return Err(INVALID),
            }
        }
        for g in states.keys() {
            self.load_manifest(g)?;
        }
        Ok(History {
            states,
            active,
            bindings,
            closed,
            validated,
        })
    }
    fn record(&mut self, path: &str) -> Result<Vec<u8>> {
        if let Some((_, raw)) = self.records.iter().find(|(p, _)| p == path) {
            return Ok(raw.clone());
        }
        let raw = read(&self.root, path)?;
        if self
            .records
            .iter()
            .map(|(_, b)| b.len())
            .sum::<usize>()
            .saturating_add(raw.len())
            > LIMIT
        {
            return Err(UNAVAILABLE);
        }
        self.records.push((path.into(), raw.clone()));
        Ok(raw)
    }
    fn json(&mut self, path: &str) -> Result<Value> {
        serde_json::from_slice(&self.record(path)?).map_err(|_| INVALID)
    }
    fn load_manifest(&mut self, g: &str) -> Result<Value> {
        let m = self.json(&format!("runtime-generations/{g}.json"))?;
        exact(
            &m,
            &[
                "schema_version",
                "core_execution",
                "artifact_manifest_fingerprints",
                "artifact_sha256s",
                "providers",
                "catalog_generation_fingerprint",
                "implementations",
                "private_factor_bindings",
                "runtime_generation_fingerprint",
            ],
        )?;
        if digest(&m, "runtime_generation_fingerprint")? != g
            || m["schema_version"].as_u64() != Some(1)
        {
            return Err(INVALID);
        }
        for k in ["artifact_manifest_fingerprints", "artifact_sha256s"] {
            let a = m[k].as_array().ok_or(INVALID)?;
            if a.is_empty()
                || a.windows(2).any(|w| w[0].as_str() >= w[1].as_str())
                || a.iter()
                    .any(|x| !x.as_str().is_some_and(crate::is_sha256_hex))
            {
                return Err(INVALID);
            }
        }
        if m["artifact_manifest_fingerprints"].as_array().map(Vec::len)
            != m["artifact_sha256s"].as_array().map(Vec::len)
            || !m["artifact_sha256s"]
                .as_array()
                .ok_or(INVALID)?
                .contains(&m["core_execution"]["artifact_sha256"])
        {
            return Err(INVALID);
        }
        sha(&m, "catalog_generation_fingerprint")?;
        contracts::generation(&m)?;
        Ok(m)
    }
    /// Physical bytes of every originally admitted distribution, independently of SDK installation.
    pub(crate) fn verify_artifacts(&mut self) -> Result<()> {
        self.verify()?;
        // These are derived read proofs, not new facts. Rebuild them so
        // repeated verification of the same selected Generation is idempotent.
        self.artifacts.clear();
        self.executor = None;
        self.core = None;
        let ids = self.manifest["artifact_sha256s"]
            .as_array()
            .ok_or(INVALID)?
            .clone();
        let mut manifests = BTreeSet::new();
        let mut distributions = BTreeSet::new();
        let mut native_roles = BTreeSet::new();
        let mut providers = Vec::new();
        let mut implementations = BTreeSet::new();
        let mut remaining = 512_u64 * 1024 * 1024;
        for id in ids {
            let id = id.as_str().ok_or(INVALID)?;
            let prefix = format!("artifacts/{}/{id}", &id[..2]);
            let m = self.json(&format!("{prefix}/manifest.json"))?;
            contracts::artifact(&m)?;
            let mf = digest(&m, "manifest_fingerprint")?;
            if m["artifact_sha256"] != id
                || !manifests.insert(mf)
                || m["schema_version"].as_u64() != Some(1)
            {
                return Err(INVALID);
            }
            if !distributions.insert(text(&m, "distribution_name")?.to_owned()) {
                return Err(INVALID);
            }
            let size = m["artifact_size"]
                .as_u64()
                .filter(|n| *n > 0)
                .ok_or(INVALID)?;
            remaining = remaining.checked_sub(size).ok_or(UNAVAILABLE)?;
            if m["role"] == "QUANT_ASSET" {
                providers.push(json!({"provider_id":m["provider_id"],"provider_version":m["provider_version"],"provider_content_fingerprint":m["provider_content_fingerprint"],"artifact_sha256":m["artifact_sha256"]}));
            }
            for i in m["implementations"].as_array().ok_or(INVALID)? {
                implementations.insert(i.to_string());
            }
            let native = m["artifact_logical_name"]
                .as_str()
                .ok_or(INVALID)?
                .ends_with(".elf");
            let path = format!(
                "{prefix}/{}",
                if native {
                    "artifact.elf"
                } else {
                    "artifact.whl"
                }
            );
            if native
                && (!matches!(text(&m, "role")?, "BACKTEST_RUNTIME" | "RESEARCH_RUNTIME")
                    || !native_roles.insert(text(&m, "role")?.to_owned()))
            {
                return Err(INVALID);
            }
            verify_bytes(&self.root, &path, id, size)?;
            if m["role"] == "RESEARCH_RUNTIME" {
                if self.executor.is_some() {
                    return Err(INVALID);
                }
                self.executor = Some(m.clone());
            }
            if id
                == self.manifest["core_execution"]["artifact_sha256"]
                    .as_str()
                    .ok_or(INVALID)?
            {
                self.core = Some(
                    json!({"path":self.root_path.join(&path),"sha256":id,"size":size,"distribution_version":m["distribution_version"]}),
                );
                if m["role"] != "CORE"
                    || m["distribution_name"]
                        != self.manifest["core_execution"]["distribution_name"]
                    || m["distribution_version"]
                        != self.manifest["core_execution"]["distribution_version"]
                {
                    return Err(INVALID);
                }
            } else if !m["tested_core_execution_fingerprint"].is_null()
                && m["tested_core_execution_fingerprint"]
                    != hash(&self.manifest["core_execution"]).map_err(|_| INVALID)?
            {
                return Err(INVALID);
            }
            self.artifacts.push((path, id.into(), size));
        }
        for b in self.manifest["private_factor_bindings"]
            .as_array()
            .ok_or(INVALID)?
        {
            for (backend, key) in [
                ("RESEARCH", "research_implementation_fingerprint"),
                ("TRADING", "trading_implementation_fingerprint"),
            ] {
                let e = &b["entry"];
                implementations.insert(json!({"kind":"FACTOR","type_id":e["factor_id"],"semantic_version":e["semantic_version"],"backend":backend,"implementation_fingerprint":e[key]}).to_string());
            }
        }
        let expected = self.manifest["implementations"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .map(Value::to_string)
            .collect::<BTreeSet<_>>();
        if providers.len() != self.manifest["providers"].as_array().ok_or(INVALID)?.len()
            || providers.iter().any(|p| {
                !self.manifest["providers"]
                    .as_array()
                    .is_some_and(|v| v.contains(p))
            })
            || !implementations.is_subset(&expected)
        {
            return Err(INVALID);
        }
        if json!(manifests) != self.manifest["artifact_manifest_fingerprints"] {
            return Err(INVALID);
        }
        Ok(())
    }
    pub(crate) fn core_artifact(&self) -> Result<&Value> {
        if self.manifest["core_execution"]["distribution_name"] != "onlyalpha" {
            return Err(INVALID);
        }
        self.core.as_ref().ok_or(INVALID)
    }
    pub(crate) fn execution_binding(&self) -> Result<Value> {
        let e = self
            .executor
            .as_ref()
            .ok_or("RESEARCH_EXECUTOR_UNAVAILABLE")?;
        if e["tested_core_execution_fingerprint"]
            != hash(&self.manifest["core_execution"]).map_err(|_| INVALID)?
        {
            return Err(INVALID);
        }
        Ok(
            json!({"executor_manifest_fingerprint":e["manifest_fingerprint"],"executor_artifact_sha256":e["artifact_sha256"],"executor_version":e["distribution_version"],"core_execution_fingerprint":e["tested_core_execution_fingerprint"],"protocol":"onlyalpha.research.executor/1"}),
        )
    }
    /// Exact immutable runtime/source record from the existing owning artifact namespace.
    pub(crate) fn private_factor(&mut self, fingerprint: &str) -> Result<Value> {
        if !crate::is_sha256_hex(fingerprint) {
            return Err(INVALID);
        }
        let v = self.json(&format!(
            "artifacts/private-factor-runtime/{}/{}.json",
            &fingerprint[..2],
            fingerprint
        ))?;
        exact(
            &v,
            &[
                "schema_version",
                "revision_metadata",
                "source_artifact",
                "equivalence_evidence",
                "provider_snapshot",
                "provider",
                "runtime_artifact_fingerprint",
            ],
        )?;
        if digest(&v, "runtime_artifact_fingerprint")? != fingerprint
            || v["schema_version"].as_u64() != Some(1)
        {
            return Err(INVALID);
        }
        let source = &v["source_artifact"];
        let source_fp = sha(source, "source_artifact_fingerprint")?;
        let saved = self.json(&format!(
            "artifacts/private-factor/{}/{}/manifest.json",
            &source_fp[..2],
            source_fp
        ))?;
        if saved != *source {
            return Err(INVALID);
        }
        let raw = self.record(&format!(
            "artifacts/private-factor/{}/{}/source.py",
            &source_fp[..2],
            source_fp
        ))?;
        use sha2::{Digest, Sha256};
        if text(source, "source_sha256")?
            != Sha256::digest(&raw)
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        {
            return Err(INVALID);
        }
        Ok(v)
    }
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }
    pub fn binding(&self) -> &Value {
        &self.binding
    }
    pub fn verify(&self) -> Result<()> {
        let actual = protected::open_directory(&self.root_path).map_err(|_| UNAVAILABLE)?;
        let lock = fs::openat(
            &actual,
            ".generation-authority.lock",
            fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC | fs::OFlags::NONBLOCK,
            fs::Mode::empty(),
        )
        .map_err(|_| UNAVAILABLE)?;
        if !same(&actual, &self.root)? || !same(&lock, &self.lock)? {
            return Err(INVALID);
        }
        for (path, id, size) in &self.artifacts {
            verify_bytes(&self.root, path, id, *size)?;
        }
        for (p, raw) in &self.records {
            if read(&self.root, p)? != *raw {
                return Err(INVALID);
            }
        }
        Ok(())
    }
}

fn verify_bytes(root: &OwnedFd, path: &str, expected: &str, size: u64) -> Result<()> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut parts = path.split('/').peekable();
    let mut dir = protected::duplicate_directory(root.as_fd()).map_err(|_| UNAVAILABLE)?;
    while let Some(name) = parts.next() {
        if parts.peek().is_some() {
            dir = protected::open_directory_at(&dir, OsStr::new(name)).map_err(|_| UNAVAILABLE)?;
            continue;
        }
        let fd = fs::openat(
            &dir,
            name,
            fs::OFlags::RDONLY | fs::OFlags::NOFOLLOW | fs::OFlags::CLOEXEC | fs::OFlags::NONBLOCK,
            fs::Mode::empty(),
        )
        .map_err(|_| UNAVAILABLE)?;
        let st = fs::fstat(&fd).map_err(|_| UNAVAILABLE)?;
        if fs::FileType::from_raw_mode(st.st_mode) != fs::FileType::RegularFile
            || st.st_nlink != 1
            || (st.st_uid != 0 && st.st_uid != rustix::process::geteuid().as_raw())
            || st.st_mode & 0o022 != 0
            || st.st_size < 0
            || st.st_size as u64 != size
        {
            return Err(INVALID);
        }
        let mut file = std::fs::File::from(fd).take(size + 1);
        let mut hash = Sha256::new();
        let mut buffer = [0; 65536];
        let mut total = 0;
        loop {
            let n = file.read(&mut buffer).map_err(|_| UNAVAILABLE)?;
            if n == 0 {
                break;
            }
            total += n as u64;
            hash.update(&buffer[..n]);
        }
        if total != size
            || hash
                .finalize()
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
                != expected
        {
            return Err(INVALID);
        }
        return Ok(());
    }
    Err(INVALID)
}
