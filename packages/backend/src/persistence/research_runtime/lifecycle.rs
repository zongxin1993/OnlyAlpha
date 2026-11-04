//! Mutations of the original Generation journal, sharing its lock and replay.
//! The hosting Product owner authenticates Human commands; this is no API proxy.
use super::{History, INVALID, INVENTORY_LOCK_BUSY, LIMIT, Result, RuntimeInputHold, UNAVAILABLE, hash};
use crate::application::command::CommandId;
use onlyalpha_domain::time::OnlyUtcDateTime;
use rustix::fs;
use serde_json::{Value, json};
use std::{fs::File, io::Write, path::Path};

pub struct Registry {
    held: RuntimeInputHold,
    history: History,
}
impl Registry {
    /// Read the original journal without taking a mutation lock or admitting work.
    pub fn inspect(root: &Path) -> Result<Value> {
        let mut held = RuntimeInputHold::acquire(root, fs::FlockOperation::NonBlockingLockShared)?;
        let history = held.replay()?;
        held.verify()?;
        Ok(json!({"active_for_new_work":history.active,"states":history.states}))
    }
    /// Observations of unreleased original work, not admission or permission.
    /// Tuple fields are work ID, exact Generation, and the original owner reason.
    pub(crate) fn unreleased_work_bindings(root: &Path) -> Result<Vec<(String, String, String)>> {
        Self::try_unreleased_work_bindings(root)?.ok_or(UNAVAILABLE)
    }

    /// Optional background scan. None is lock contention and carries no inventory evidence.
    pub(crate) fn try_unreleased_work_bindings(
        root: &Path,
    ) -> Result<Option<Vec<(String, String, String)>>> {
        let mut held = match RuntimeInputHold::acquire_with_contention(
            root,
            fs::FlockOperation::NonBlockingLockShared,
            INVENTORY_LOCK_BUSY,
        ) {
            Ok(held) => held,
            Err(INVENTORY_LOCK_BUSY) => return Ok(None),
            Err(error) => return Err(error),
        };
        let history = held.replay()?;
        let mut bindings = Vec::new();
        for (work, (generation, active, original)) in &history.bindings {
            if *active {
                if original["kind"] != "RuntimeWorkBound" || history.closed.contains(work) { return Err(INVALID); }
                let reason = original["reason"].as_str().ok_or(INVALID)?;
                bindings.push((work.clone(), generation.clone(), reason.to_owned()));
            }
        }
        held.verify()?;
        Ok(Some(bindings))
    }
    /// Read the exact original work occurrence and release status under the
    /// existing shared lock. These values cannot admit or reopen work.
    pub(crate) fn inspect_work(root:&Path,work:&str,generation:&str,owner:&str)->Result<Value> {
        let mut held=RuntimeInputHold::acquire(root,fs::FlockOperation::NonBlockingLockShared)?;
        let history=held.replay()?;
        let (original,active,event)=history.bindings.get(work).ok_or("RESEARCH_RUNTIME_WORK_UNBOUND")?;
        if original!=generation || event["kind"]!="RuntimeWorkBound" || event["reason"]!=owner {return Err("RESEARCH_RUNTIME_WORK_MISMATCH");}
        held.verify()?;Ok(json!({"binding":event,"active":active,"closed":history.closed.contains(work)}))
    }
    /// Explicit fresh provisioning only. Never fallback for a missing/corrupt existing journal.
    pub fn initialize_fresh(root: &Path) -> Result<Self> {
        super::publication::initialize_fresh(root)?;
        Self::open_existing(root)
    }
    pub fn open_existing(root: &Path) -> Result<Self> {
        let mut held =
            RuntimeInputHold::acquire(root, fs::FlockOperation::NonBlockingLockExclusive)?;
        let history = held.replay()?;
        Ok(Self { held, history })
    }
    pub fn snapshot(&self) -> Value {
        json!({"active_for_new_work":self.history.active,"states":self.history.states})
    }
    pub fn install_artifact(&mut self, manifest: &Value, bytes: &[u8]) -> Result<()> {
        use sha2::{Digest, Sha256};
        self.held.verify()?;
        super::contracts::artifact(manifest)?;
        super::digest(manifest, "manifest_fingerprint")?;
        let sha = Sha256::digest(bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        if bytes.is_empty()
            || bytes.len() > 128 * 1024 * 1024
            || manifest["artifact_sha256"] != sha
            || manifest["artifact_size"] != bytes.len() as u64
        {
            return Err(INVALID);
        }
        let executable = manifest["artifact_logical_name"]
            .as_str()
            .ok_or(INVALID)?
            .ends_with(".elf");
        if executable {
            let machine = if manifest["artifact_logical_name"]
                .as_str()
                .ok_or(INVALID)?
                .ends_with("-aarch64-unknown-linux-gnu.elf")
            {
                183_u16
            } else {
                62_u16
            };
            if bytes.len() < 64
                || bytes[..7] != *b"\x7fELF\x02\x01\x01"
                || !matches!(u16::from_le_bytes([bytes[16], bytes[17]]), 2 | 3)
                || u16::from_le_bytes([bytes[18], bytes[19]]) != machine
                || u32::from_le_bytes([bytes[20], bytes[21], bytes[22], bytes[23]]) != 1
                || u16::from_le_bytes([bytes[52], bytes[53]]) != 64
            {
                return Err(INVALID);
            }
        }
        let directory = crate::security::immutable_json::Directory::open(&self.held.root_path)?;
        super::publication::put_pair(
            &directory,
            &["artifacts", &sha[..2], &sha],
            manifest,
            if executable {
                "artifact.elf"
            } else {
                "artifact.whl"
            },
            bytes,
            executable,
        )?;
        self.held.verify()
    }
    pub fn install_private_factor(&mut self, runtime: &Value, source: &[u8]) -> Result<()> {
        use sha2::{Digest, Sha256};
        self.held.verify()?;
        let id = super::digest(runtime, "runtime_artifact_fingerprint")?;
        let manifest = &runtime["source_artifact"];
        let sid = super::digest(manifest, "source_artifact_fingerprint")?;
        let sha = Sha256::digest(source)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        if source.is_empty() || source.len() > LIMIT || manifest["source_sha256"] != sha {
            return Err(INVALID);
        }
        let directory = crate::security::immutable_json::Directory::open(&self.held.root_path)?;
        super::publication::put_pair(
            &directory,
            &["artifacts", "private-factor", &sid[..2], &sid],
            manifest,
            "source.py",
            source,
            false,
        )?;
        super::publication::put_file(
            &directory,
            &["artifacts", "private-factor-runtime", &id[..2]],
            &format!("{id}.json"),
            runtime,
        )?;
        self.held.private_factor(&id)?;
        self.held.verify()
    }
    pub(crate) fn retain_abi_vectors(&mut self, vectors: &Value, expected: &Value) -> Result<()> {
        self.held.verify()?;
        let id = hash(vectors).map_err(|_| INVALID)?;
        if expected.as_str() != Some(id.as_str()) {
            return Err(INVALID);
        }
        let directory = crate::security::immutable_json::Directory::open(&self.held.root_path)?;
        super::publication::put_file(
            &directory,
            &["artifacts", "private-factor-equivalence", &id[..2]],
            &format!("{id}.json"),
            vectors,
        )?;
        self.held.verify()
    }
    pub(crate) fn retain_installed_proof(&mut self, manifest: &Value, proof: &Value) -> Result<()> {
        self.held.verify()?;
        let proof_id = super::digest(proof, "installed_proof_fingerprint")?;
        let id = super::digest(manifest, "runtime_generation_fingerprint")?;
        if !matches!(
            (proof["schema_version"].as_u64(), proof["contract"].as_str()),
            (Some(1), Some("ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V1"))
                | (Some(2), Some("ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V2"))
        ) || proof["runtime_generation_fingerprint"] != id
        {
            return Err(INVALID);
        }
        let directory = crate::security::immutable_json::Directory::open(&self.held.root_path)?;
        super::publication::put_file(
            &directory,
            &["runtime-generation-installed-proof", &id],
            &format!("{proof_id}.json"),
            proof,
        )?;
        self.held.verify()
    }
    /// Storage publication only. The native Product owner first requires an actual
    /// installed PreparedGeneration; this grants no activation or Research permission.
    pub fn prepare_generation(
        &mut self,
        manifest: &Value,
        actor: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Value> {
        self.held.verify()?;
        let id = super::digest(manifest, "runtime_generation_fingerprint")?;
        let directory = crate::security::immutable_json::Directory::open(&self.held.root_path)?;
        super::publication::put_file(
            &directory,
            &["runtime-generations"],
            &format!("{id}.json"),
            manifest,
        )?;
        let selected = self.held.load_manifest(&id)?;
        self.held.manifest = selected;
        self.held.verify_artifacts()?;
        for binding in manifest["private_factor_bindings"]
            .as_array()
            .ok_or(INVALID)?
        {
            self.held
                .private_factor(super::text(binding, "runtime_artifact_fingerprint")?)?;
        }
        if !self.history.states.contains_key(&id) {
            self.append(
                json!({"kind":"GenerationPrepared","generation_fingerprint":id}),
                actor,
                at,
            )?;
        }
        if !matches!(
            self.history.states.get(&id),
            Some(&"PREPARING" | &"READY" | &"ACTIVE_FOR_NEW_WORK" | &"DRAINING")
        ) {
            return Err("RUNTIME_GENERATION_NOT_PREPARING");
        }
        let mut validation = json!({"schema_version":1,"validation_contract_version":"ONLYALPHA_RUNTIME_GENERATION_VALIDATION@1",
            "runtime_generation_fingerprint":id,"core_execution_fingerprint":hash(&manifest["core_execution"]).map_err(|_|INVALID)?});
        for key in [
            "artifact_manifest_fingerprints",
            "artifact_sha256s",
            "providers",
            "catalog_generation_fingerprint",
            "implementations",
            "private_factor_bindings",
        ] {
            validation[key] = manifest[key].clone();
        }
        validation["validation_evidence_fingerprint"] =
            hash(&validation).map_err(|_| INVALID)?.into();
        super::publication::put_file(
            &directory,
            &["runtime-generation-validation"],
            &format!("{id}.json"),
            &validation,
        )?;
        if self.history.states.get(&id) == Some(&"PREPARING") {
            self.append(json!({"kind":"GenerationValidated","generation_fingerprint":id,"validation_evidence_fingerprint":validation["validation_evidence_fingerprint"]}),actor,at)?;
        }
        self.held.verify()?;
        Ok(validation)
    }
    pub fn activate(
        &mut self,
        command: &CommandId,
        target: &str,
        expected: Option<&str>,
        actor: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Value> {
        if !crate::is_sha256_hex(target)
            || expected.is_some_and(|s| !crate::is_sha256_hex(s))
            || actor.trim().is_empty()
            || actor.len() > 256
        {
            return Err(INVALID);
        }
        self.held.verify()?;
        let request = hash(&json!({"operation":"ACTIVATE","target":target,"expected_current":expected,"actor":actor})).map_err(|_|INVALID)?;
        let mut prior = None;
        let ledger = self.held.record("generation-events.jsonl")?;
        for raw in std::str::from_utf8(&ledger).map_err(|_| INVALID)?.lines() {
            let e: Value = serde_json::from_str(raw).map_err(|_| INVALID)?;
            let reason = e["reason"]
                .as_str()
                .and_then(|s| serde_json::from_str::<Value>(s).ok());
            if e["kind"] == "GenerationActivated"
                && let Some(reason) = reason
                && reason["contract"] == "ONLYALPHA_GENERATION_COMMAND_V1"
                && reason["command_id"] == command.value()
            {
                if prior.is_some()
                    || reason["request_fingerprint"] != request
                    || e["generation_fingerprint"] != target
                    || e["expected_current"] != json!(expected)
                    || e["actor"] != actor
                {
                    return Err("RUNTIME_GENERATION_COMMAND_CONFLICT");
                }
                prior = Some(e);
            }
        }
        if let Some(event) = prior {
            return Ok(event);
        }
        if self.history.active.as_deref() != expected {
            return Err("GENERATION_ACTIVATION_CONFLICT");
        }
        if !matches!(
            self.history.states.get(target),
            Some(&"READY" | &"DRAINING")
        ) {
            return Err("RUNTIME_GENERATION_NOT_READY");
        }
        self.append(json!({"kind":"GenerationActivated","generation_fingerprint":target,"expected_current":expected,
            "reason":json!({"contract":"ONLYALPHA_GENERATION_COMMAND_V1","command_id":command.value(),"request_fingerprint":request}).to_string()}), actor, at)
    }
    pub fn bind_new_work_exact(
        &mut self,
        work: &str,
        generation: &str,
        owner: &str,
        actor: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Value> {
        if work.trim().is_empty()
            || work.len() > 512
            || owner.trim().is_empty()
            || owner.len() > 256
            || !crate::is_sha256_hex(generation)
        {
            return Err(INVALID);
        }
        self.held.verify()?;
        if self.history.closed.contains(work) {
            return Err("RUNTIME_WORK_ADMISSION_CLOSED");
        }
        if let Some((g, active, event)) = self.history.bindings.get(work) {
            if !active
                || g != generation
                || event["kind"] != "RuntimeWorkBound"
                || event["reason"] != owner
            {
                return Err("RUNTIME_WORK_GENERATION_BINDING_CONFLICT");
            }
            return Ok(event.clone());
        }
        if self.history.active.as_deref() != Some(generation) {
            return Err("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK");
        }
        self.append(json!({"kind":"RuntimeWorkBound","generation_fingerprint":generation,"work_id":work,"reason":owner}), actor, at)
    }
    /// Terminal lifecycle release of this original work/Generation/owner binding.
    /// The worker must first join its children, persist terminal work, and drop
    /// InputHolds. The existing exclusive journal lock enforces the last boundary.
    pub fn release_work_exact(
        &mut self,
        work: &str,
        generation: &str,
        owner: &str,
        actor: &str,
        at: OnlyUtcDateTime,
    ) -> Result<Value> {
        if work.trim().is_empty() || work.len() > 512 || owner.trim().is_empty()
            || owner.len() > 256 || actor.trim().is_empty() || actor.len() > 256
            || !crate::is_sha256_hex(generation) {
            return Err(INVALID);
        }
        self.held.verify()?;
        let (original_generation, active, origin) = self.history.bindings.get(work)
            .ok_or("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")?;
        if original_generation != generation || origin["kind"] != "RuntimeWorkBound" || origin["reason"] != owner {
            return Err("RUNTIME_WORK_GENERATION_BINDING_CONFLICT");
        }
        if !active {
            let ledger=self.held.record("generation-events.jsonl")?;
            let mut original=None;
            for line in std::str::from_utf8(&ledger).map_err(|_|INVALID)?.lines() {
                let event:Value=serde_json::from_str(line).map_err(|_|INVALID)?;
                if event["kind"]=="RuntimeWorkReleased" && event["work_id"]==work {
                    if original.is_some() || event["generation_fingerprint"]!=generation || event["reason"]!=owner { return Err(INVALID); }
                    original=Some(event);
                }
            }
            return original.ok_or(INVALID);
        }
        self.append(json!({"kind":"RuntimeWorkReleased","generation_fingerprint":generation,"work_id":work,"reason":owner}),actor,at)
    }
    fn append(&mut self, fields: Value, actor: &str, at: OnlyUtcDateTime) -> Result<Value> {
        if actor.trim().is_empty() || actor.len() > 256 {
            return Err(INVALID);
        }
        self.held.verify()?;
        let old = self.held.record("generation-events.jsonl")?;
        let lines = std::str::from_utf8(&old)
            .map_err(|_| INVALID)?
            .lines()
            .collect::<Vec<_>>();
        let prior = lines
            .last()
            .map(|s| serde_json::from_str::<Value>(s))
            .transpose()
            .map_err(|_| INVALID)?;
        let mut event = json!({"schema_version":1,"sequence":lines.len()+1,"kind":null,"occurred_at":format!("{}+00:00",at.to_string().trim_end_matches('Z')),
            "actor":actor,"generation_fingerprint":null,"previous_event_fingerprint":prior.map(|v|v["event_fingerprint"].clone()),
            "expected_current":null,"work_id":null,"reason":null,"validation_evidence_fingerprint":null});
        for (key, value) in fields.as_object().ok_or(INVALID)? {
            event[key] = value.clone();
        }
        event["event_fingerprint"] = hash(&event).map_err(|_| INVALID)?.into();
        let mut bytes = old.clone();
        let canonical = onlyalpha_metadata_json::canonical_json(&event.to_string(), LIMIT)
            .map_err(|_| INVALID)?;
        bytes.extend_from_slice(canonical.as_bytes());
        bytes.push(b'\n');
        if bytes.len() > LIMIT {
            return Err(UNAVAILABLE);
        }
        // Validate the prospective journal through the same reader before publishing.
        let history = self.held.replay_ledger(&bytes)?;
        self.held.verify()?;
        let mut entropy = [0; 16];
        getrandom::fill(&mut entropy).map_err(|_| UNAVAILABLE)?;
        let stage = format!(
            ".generation-stage-{}",
            entropy
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        );
        let fd = fs::openat(
            &self.held.root,
            stage.as_str(),
            fs::OFlags::WRONLY
                | fs::OFlags::CREATE
                | fs::OFlags::EXCL
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(|_| UNAVAILABLE)?;
        let mut file = File::from(fd);
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| UNAVAILABLE)?;
        self.held.verify()?;
        // Atomic physical replacement preserves the exact immutable byte prefix.
        fs::renameat(
            &self.held.root,
            stage.as_str(),
            &self.held.root,
            "generation-events.jsonl",
        )
        .map_err(|_| UNAVAILABLE)?;
        fs::fsync(&self.held.root).map_err(|_| "RUNTIME_GENERATION_OUTCOME_UNKNOWN")?;
        self.held
            .records
            .retain(|(path, _)| path != "generation-events.jsonl");
        self.held
            .records
            .push(("generation-events.jsonl".into(), bytes));
        self.held
            .verify()
            .map_err(|_| "RUNTIME_GENERATION_OUTCOME_UNKNOWN")?;
        self.history = history;
        Ok(event)
    }
}
