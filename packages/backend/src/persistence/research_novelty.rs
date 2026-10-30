//! Native consumption and publication of the existing Novelty/Memory authorities.
//! Missing roots/cuts/owners never mean an empty historical family. The first
//! native slice supports native TS Results and their real operational history;
//! other nonempty semantic families explicitly remain unavailable.
use crate::application::{
    command::CommandId,
    research_novelty::{
        self as n, FAMILIES, INVALID, LIMIT, Result, Subject, UNAVAILABLE, canonical, exact, fp,
        pin, signed, text, verify_signed,
    },
};
use crate::security::immutable_json::{Directory, SourceLock, parsed, put, read_path};
use crate::security::protected_files::{self as files, ReadError};
use rustix::fs;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    ffi::OsStr,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio_postgres::{Client, Transaction};
type CapturedLocks = (BTreeMap<String, Arc<SourceLock>>, Vec<Arc<SourceLock>>);

const MAX_ENTRIES: usize = 32768;
const PG_FAMILIES: [&str; 4] = [
    "PRODUCT_COMMAND_ADMISSION",
    "PRODUCT_COMMAND_RECEIPT",
    "RESEARCH_ATTEMPT",
    "RESEARCH_RUN",
];

fn io(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn identifier(value: &str, version: bool) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || if version {
            value.starts_with('0') || !value.bytes().all(|b| b.is_ascii_digit())
        } else {
            !value.bytes().enumerate().all(|(i, b)| {
                b.is_ascii_alphanumeric() || (i > 0 && matches!(b, b'.' | b'_' | b'-'))
            })
        }
    {
        return Err(INVALID);
    }
    Ok(())
}

#[derive(Clone)]
struct Observation {
    source_ref: Value,
    payload: Value,
}
struct Snapshot {
    projection: Value,
    frontier: i64,
    locks: Vec<Arc<SourceLock>>,
}
pub struct Authority {
    semantic_root: Directory,
    projection_root: Directory,
    source_roots: BTreeMap<String, PathBuf>,
}
impl Authority {
    /// Paths are supplied only by the backend's owning deployment composition.
    /// This constructor neither creates missing source authorities nor imports facts.
    pub fn new(
        semantic_root: &Path,
        projection_root: &Path,
        source_roots: BTreeMap<String, PathBuf>,
    ) -> Result<Self> {
        let expected: BTreeSet<String> = FAMILIES
            .into_iter()
            .filter(|f| !PG_FAMILIES.contains(f))
            .map(str::to_owned)
            .collect();
        if source_roots.keys().cloned().collect::<BTreeSet<_>>() != expected {
            return Err(INVALID);
        }
        let semantic_root = Directory::open(semantic_root)?;
        // Initialize only this owner's namespaces; external source roots are never initialized here.
        semantic_root.path(&["research", "novelty-decision-groups"], true)?;
        semantic_root.path(&["research", "novelty-decisions"], true)?;
        Ok(Self {
            semantic_root,
            projection_root: Directory::open(projection_root)?,
            source_roots,
        })
    }
    fn locks(&self) -> Result<CapturedLocks> {
        let paths = self.source_roots.values().cloned().collect::<BTreeSet<_>>();
        let mut by_path = BTreeMap::new();
        for path in paths {
            by_path.insert(path.clone(), Arc::new(SourceLock::acquire(&path)?));
        }
        let mut by_family = BTreeMap::new();
        for (family, path) in &self.source_roots {
            by_family.insert(family.clone(), by_path.get(path).ok_or(INVALID)?.clone());
        }
        Ok((by_family, by_path.into_values().collect()))
    }
    /// Native owner capture, exact source-cut publication and immutable projection.
    /// It has no model call, scientific calculation or Research execution effect.
    pub async fn refresh_projection(&self, client: &mut Client) -> Result<String> {
        let (by_family, locks) = self.locks()?;
        let tx = client.transaction().await.map_err(io)?;
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(io)?;
        let frontier = frontier(&tx, true).await?;
        let events = history(&tx, 0, frontier).await?;
        let mut cuts = Vec::new();
        let mut observations = Vec::new();
        for family in FAMILIES {
            let (cut, mut members) = if PG_FAMILIES.contains(&family) {
                let (cut, members) = pg_cut(family, frontier, &events)?;
                let document = canonical(&cut)?;
                tx.execute("INSERT INTO research_source_closed_cut(cut_fingerprint,source_family,frontier,canonical_document,schema_version) VALUES($1,$2,$3,$4,1) ON CONFLICT(cut_fingerprint) DO NOTHING",&[&text(&cut,"cut_fingerprint")?,&family,&frontier,&document]).await.map_err(io)?;
                verify_pg_cut(&tx, &cut, frontier).await?;
                (cut, members)
            } else {
                let source = by_family.get(family).ok_or(INVALID)?;
                let (cut, members) = self.file_cut(family, source)?;
                let fingerprint = text(&cut, "cut_fingerprint")?;
                put(
                    &source.directory,
                    &["closed-cuts", "sha256", &fingerprint[..2], fingerprint],
                    "manifest.json",
                    &cut,
                )?;
                (cut, members)
            };
            cuts.push(cut_reference(&cut)?);
            observations.append(&mut members);
            observation_budget(&observations)?;
        }
        let manifest = signed(
            json!({"schema_version":1,"mandatory_family_set_version":1,"cuts":cuts}),
            "manifest_fingerprint",
            None,
        )?;
        let projection = build_projection(manifest, &observations)?;
        let fingerprint = text(&projection, "revision_fingerprint")?.to_owned();
        put(
            &self.projection_root,
            &["revisions", "sha256", &fingerprint[..2], &fingerprint],
            "projection.json",
            &projection,
        )?;
        for lock in &locks {
            lock.verify()?;
        }
        tx.commit().await.map_err(io)?;
        Ok(fingerprint)
    }
    /// Seal through actual source owners and the selected existing Policy. Reuse
    /// of a sealed command preserves its original decision-time evidence.
    pub async fn seal(
        &self,
        client: &mut Client,
        command: &CommandId,
        subjects: &[Subject],
        policy_id: &str,
        policy_version: &str,
        projection_fp: &str,
    ) -> Result<Value> {
        n::subject_set(subjects)?;
        identifier(policy_id, false)?;
        identifier(policy_version, true)?;
        let lock_root = self
            .semantic_root
            .path(&["research", "novelty-decision-authority-locks"], true)?;
        let lock_name = format!("{}.lock", command.value());
        let lock = fs::openat(
            &lock_root.fd,
            &lock_name,
            fs::OFlags::RDWR
                | fs::OFlags::CREATE
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::NONBLOCK
                | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(io)?;
        let lock_metadata = fs::fstat(&lock).map_err(io)?;
        if fs::FileType::from_raw_mode(lock_metadata.st_mode) != fs::FileType::RegularFile
            || lock_metadata.st_nlink != 1
            || lock_metadata.st_mode & 0o022 != 0
            || (lock_metadata.st_uid != 0
                && lock_metadata.st_uid != rustix::process::geteuid().as_raw())
        {
            return Err(INVALID);
        }
        fs::flock(&lock, fs::FlockOperation::NonBlockingLockExclusive).map_err(io)?;
        // Never collide with the original single-Decision command namespace.
        let single_parent = self
            .semantic_root
            .path(&["research", "novelty-decisions"], false)?;
        match files::open_directory_at(&single_parent.fd, OsStr::new(command.value())) {
            Ok(_) => return Err("NOVELTY_DECISION_CONFLICT"),
            Err(ReadError::Missing) => {}
            Err(e) => return Err(io(e)),
        }
        let policy = self.load_policy(policy_id, policy_version)?;
        if let Some(group) = self.load_group_optional(command)? {
            let snapshot = self
                .snapshot(
                    client,
                    text(
                        &group["members"][0]["witness"],
                        "projection_revision_fingerprint",
                    )?,
                    false,
                )
                .await?;
            let expected = make_group(command, subjects, &policy, &snapshot)?;
            if group != expected {
                return Err("NOVELTY_DECISION_CONFLICT");
            }
            return Ok(group);
        }
        let snapshot = self.snapshot(client, projection_fp, false).await?;
        let group = make_group(command, subjects, &policy, &snapshot)?;
        lock_root.verify()?;
        let actual =
            fs::statat(&lock_root.fd, &lock_name, fs::AtFlags::SYMLINK_NOFOLLOW).map_err(io)?;
        if actual.st_ino != lock_metadata.st_ino || actual.st_dev != lock_metadata.st_dev {
            return Err(INVALID);
        }
        put(
            &self.semantic_root,
            &["research", "novelty-decision-groups", command.value()],
            "group.json",
            &group,
        )?;
        Ok(group)
    }
    /// Verify the original group against its exact retained projection/cuts and policy.
    /// No current projection head or current Source permission is selected.
    pub(crate) async fn retained_group(
        &self,
        client: &mut Client,
        command: &CommandId,
        subjects: &[Subject],
        policy_id: &str,
        policy_version: &str,
    ) -> Result<Value> {
        let group = self.retained_group_record(command)?;
        let policy = self.load_policy(policy_id, policy_version)?;
        let members = group["members"].as_array().ok_or(INVALID)?;
        if members.len() != subjects.len() || members.len() != 1 {
            return Err(INVALID);
        }
        let snapshot = self
            .snapshot(
                client,
                text(&members[0]["witness"], "projection_revision_fingerprint")?,
                false,
            )
            .await?;
        if group != make_group(command, subjects, &policy, &snapshot)? {
            return Err(INVALID);
        }
        Ok(group)
    }
    /// Re-prove from exact fresh sources. Only this reader can create ActionProof.
    pub async fn authorize_action(
        &self,
        client: &mut Client,
        command: &CommandId,
        subjects: &[Subject],
        fresh_projection_fp: &str,
    ) -> Result<ActionProof> {
        n::subject_set(subjects)?;
        let group = self
            .load_group_optional(command)?
            .ok_or("NOVELTY_DECISION_NOT_FOUND")?;
        let first = &group["members"][0]["witness"];
        let policy = self.load_policy(text(first, "policy_id")?, text(first, "policy_version")?)?;
        let original = self
            .snapshot(
                client,
                text(first, "projection_revision_fingerprint")?,
                false,
            )
            .await?;
        if make_group(command, subjects, &policy, &original)? != group {
            return Err(INVALID);
        }
        drop(original);
        if group["disposition"] != "ACTIONABLE" {
            return Err("NOVELTY_DECISION_NOT_ADMIT");
        }
        let snapshot = self.snapshot(client, fresh_projection_fp, true).await?;
        let mut members = Vec::new();
        for (ordinal, (subject, bundle)) in subjects
            .iter()
            .zip(group["members"].as_array().ok_or(INVALID)?)
            .enumerate()
        {
            let (_, current) = query(subject, &snapshot)?;
            let frozen = &bundle["witness"]["proofs"][0]["proof"];
            if !matches!(
                text(&current, "proof_status")?,
                "MATCH" | "CERTIFIED_NO_MATCH"
            ) {
                return Err("NOVELTY_PROOF_INCOMPLETE");
            }
            if current["proof_status"] != frozen["proof_status"]
                || current["ordered_matches"] != frozen["ordered_matches"]
            {
                return Err("NOVELTY_DECISION_STALE");
            }
            let subject_fp = subject.fingerprint()?;
            members.push(json!({"schema_version":1,"ordinal":ordinal,"evaluation_subject_fingerprint":subject_fp,"novelty_decision_fingerprint":bundle["decision"]["decision_fingerprint"],"canonical_intent_fingerprint":bundle["decision"]["canonical_intent_fingerprint"],"decision_time_proof_fingerprint":frozen["result_fingerprint"],"action_time_proof_fingerprint":current["result_fingerprint"],"same_subject_guard_key":fp(&json!({"domain":"onlyalpha.research.novelty-same-subject-guard-v1","evaluation_subject_fingerprint":subject_fp}))?}));
        }
        Ok(ActionProof {
            command: command.clone(),
            group,
            manifest: snapshot.projection["source_manifest"].clone(),
            members,
            frontier: snapshot.frontier,
            locks: snapshot.locks,
        })
    }
    fn load_policy(&self, id: &str, version: &str) -> Result<Value> {
        identifier(id, false)?;
        identifier(version, true)?;
        let p = read_path(
            &self.semantic_root,
            &["research", "novelty-policies", id, version],
            "manifest.json",
        )?;
        n::policy(&p, id, version)?;
        Ok(p)
    }
    fn retained_group_record(&self, command: &CommandId) -> Result<Value> {
        self.load_group_optional(command)?.ok_or(UNAVAILABLE)
    }
    fn load_group_optional(&self, command: &CommandId) -> Result<Option<Value>> {
        let parent = self
            .semantic_root
            .path(&["research", "novelty-decision-groups"], false)?;
        match files::open_directory_at(&parent.fd, OsStr::new(command.value())) {
            Err(ReadError::Missing) => Ok(None),
            Err(e) => Err(io(e)),
            Ok(fd) => {
                let selected = Directory {
                    path: parent.path.join(command.value()),
                    fd,
                };
                if selected.names()? != vec!["group.json".to_string()] {
                    return Err(INVALID);
                }
                let v = selected.read("group.json")?;
                verify_signed(
                    &v,
                    "group_fingerprint",
                    Some("onlyalpha.research.novelty-decision-group-v1"),
                )?;
                if v["product_command_id"] != command.value() {
                    return Err(INVALID);
                }
                for member in v["members"].as_array().ok_or(INVALID)? {
                    let resolved = &member["witness"]["subject"]["resolved_subject"];
                    if !resolved["qualification_binding"].is_null()
                        || resolved["related_failures"]
                            .as_array()
                            .is_none_or(|values| !values.is_empty())
                    {
                        return Err("NOVELTY_SELECTOR_UNSUPPORTED");
                    }
                }
                Ok(Some(v))
            }
        }
    }
    fn file_cut(&self, family: &str, source: &SourceLock) -> Result<(Value, Vec<Observation>)> {
        source.verify()?;
        let entries = inventory(&source.directory)?;
        let mut observations = Vec::new();
        let mut cut_entries = Vec::new();
        let mut remaining = LIMIT;
        for locator in entries {
            if let Some((identity, payload)) =
                self.file_observation(family, &source.directory, &locator)?
            {
                cut_entries.push(json!({"locator":locator,"identity":identity,"content_fingerprint":fp(&payload)?}));
                spend(&mut remaining, &payload)?;
                observations.push(Observation {
                    source_ref: Value::Null,
                    payload,
                });
            }
        }
        let version = source_version(family)?;
        let cut = signed(
            json!({"schema_version":1,"source_family":family,"source_schema_version":version,"enumeration_contract_version":1,"cut_boundary":"FILE_PUBLICATION_BARRIER_V1","completeness_proof":"SOURCE_OWNED_EXCLUSIVE_INVENTORY_V1","entries":cut_entries}),
            "cut_fingerprint",
            None,
        )?;
        for (observation, entry) in observations
            .iter_mut()
            .zip(cut["entries"].as_array().ok_or(INVALID)?)
        {
            observation.source_ref = source_ref(&cut, entry)?;
        }
        Ok((cut, observations))
    }
    fn file_observation(
        &self,
        family: &str,
        root: &Directory,
        locator: &str,
    ) -> Result<Option<(String, Value)>> {
        if !crate::is_sha256_hex(locator) {
            return Err(UNAVAILABLE);
        }
        match family {
            "RESEARCH_RESULT"
            | "RESEARCH_STATISTICS"
            | "RESEARCH_FACTOR_PAIR_STATISTICS"
            | "RESEARCH_SUMMARY_STATISTICS" => {
                let actual_family = if family == "RESEARCH_RESULT" {
                    "RESEARCH_RESULT"
                } else {
                    "RESEARCH_STATISTICS"
                };
                let (identity, value) =
                    crate::persistence::research_evidence::verify_native_source(
                        &root.path,
                        actual_family,
                        locator,
                    )?;
                // All three statistics families share the canonical owner root.
                // A verified native TS fact is a complete non-member of the
                // other two families, never an unknown/partial non-match.
                if matches!(
                    family,
                    "RESEARCH_FACTOR_PAIR_STATISTICS" | "RESEARCH_SUMMARY_STATISTICS"
                ) {
                    return Ok(None);
                }
                Ok(Some((identity, value)))
            }
            _ => Err(UNAVAILABLE),
        }
    }
    async fn snapshot(
        &self,
        client: &mut Client,
        projection_fp: &str,
        current: bool,
    ) -> Result<Snapshot> {
        if !crate::is_sha256_hex(projection_fp) {
            return Err(INVALID);
        }
        let (by_family, locks) = self.locks()?;
        let projection = read_path(
            &self.projection_root,
            &["revisions", "sha256", &projection_fp[..2], projection_fp],
            "projection.json",
        )?;
        verify_projection_envelope(&projection, projection_fp)?;
        let cuts = projection["source_manifest"]["cuts"]
            .as_array()
            .ok_or(INVALID)?;
        let tx = client.transaction().await.map_err(io)?;
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(io)?;
        let current_frontier = frontier(&tx, false).await?;
        let events = history(&tx, 0, current_frontier).await?;
        let mut observations = Vec::new();
        let mut selected_frontier = None;
        let mut remaining = LIMIT;
        for reference in cuts {
            let family = text(reference, "source_family")?;
            let cut_fp = text(reference, "cut_fingerprint")?;
            if PG_FAMILIES.contains(&family) {
                let row=tx.query_opt("SELECT frontier,canonical_document FROM research_source_closed_cut WHERE cut_fingerprint=$1 AND source_family=$2 AND schema_version=1",&[&cut_fp,&family]).await.map_err(io)?.ok_or(UNAVAILABLE)?;
                let n: i64 = row.try_get(0).map_err(io)?;
                if n < 0
                    || n > current_frontier
                    || selected_frontier.is_some_and(|selected| selected != n)
                {
                    return Err(INVALID);
                }
                selected_frontier = Some(n);
                let (expected, mut members) =
                    pg_cut(family, n, &events[..usize::try_from(n).map_err(io)?])?;
                let raw: String = row.try_get(1).map_err(io)?;
                if parsed(raw.as_bytes())? != expected || cut_reference(&expected)? != *reference {
                    return Err(INVALID);
                }
                for member in &members {
                    spend(&mut remaining, &member.payload)?;
                }
                observations.append(&mut members);
            } else {
                let source = by_family.get(family).ok_or(INVALID)?;
                let cut = read_path(
                    &source.directory,
                    &["closed-cuts", "sha256", &cut_fp[..2], cut_fp],
                    "manifest.json",
                )?;
                validate_cut(&cut)?;
                if cut_reference(&cut)? != *reference
                    || cut["source_schema_version"].as_u64() != Some(source_version(family)?)
                    || cut["cut_boundary"] != "FILE_PUBLICATION_BARRIER_V1"
                    || cut["completeness_proof"] != "SOURCE_OWNED_EXCLUSIVE_INVENTORY_V1"
                {
                    return Err(INVALID);
                }
                if current && self.file_cut(family, source)?.0 != cut {
                    return Err("NOVELTY_DECISION_STALE");
                }
                for entry in cut["entries"].as_array().ok_or(INVALID)? {
                    let locator = text(entry, "locator")?;
                    let (identity, payload) = self
                        .file_observation(family, &source.directory, locator)?
                        .ok_or(INVALID)?;
                    if entry["identity"] != identity
                        || fp(&payload)? != entry["content_fingerprint"]
                    {
                        return Err(INVALID);
                    }
                    spend(&mut remaining, &payload)?;
                    observations.push(Observation {
                        source_ref: source_ref(&cut, entry)?,
                        payload,
                    });
                }
            }
        }
        let rebuilt = build_projection(projection["source_manifest"].clone(), &observations)?;
        if rebuilt != projection {
            return Err(INVALID);
        }
        tx.commit().await.map_err(io)?;
        Ok(Snapshot {
            projection,
            frontier: selected_frontier.ok_or(INVALID)?,
            locks,
        })
    }
}

/// An action-time proof owns its physical source barriers until the Run transaction
/// commits. Copying parent/member DTOs cannot confer this capability.
pub struct ActionProof {
    command: CommandId,
    group: Value,
    manifest: Value,
    members: Vec<Value>,
    frontier: i64,
    locks: Vec<Arc<SourceLock>>,
}
impl ActionProof {
    pub fn group_fingerprint(&self) -> &str {
        self.group["group_fingerprint"]
            .as_str()
            .expect("verified group")
    }
    pub fn subject_set_fingerprint(&self) -> &str {
        self.group["subject_set_fingerprint"]
            .as_str()
            .expect("verified set")
    }
    pub fn source_frontier(&self) -> i64 {
        self.frontier
    }
    pub fn source_manifest_fingerprint(&self) -> &str {
        self.manifest["manifest_fingerprint"]
            .as_str()
            .expect("verified manifest")
    }
    pub fn policy_matches(&self, id: &str, version: &str) -> bool {
        self.group["members"][0]["witness"]["policy_id"] == id
            && self.group["members"][0]["witness"]["policy_version"] == version
    }
    pub fn member_records(&self) -> &[Value] {
        &self.members
    }
    pub fn command_id(&self) -> &CommandId {
        &self.command
    }
    pub fn parent_record(&self, command_fingerprint: &str, run_id: &str) -> Result<Value> {
        if !crate::is_sha256_hex(command_fingerprint) || CommandId::new(run_id).is_err() {
            return Err(INVALID);
        }
        signed(
            json!({"schema_version":2,"command_id":self.command.value(),"command_fingerprint":command_fingerprint,"decision_group_fingerprint":self.group_fingerprint(),"subject_set_fingerprint":self.subject_set_fingerprint(),"action_source_manifest_fingerprint":self.source_manifest_fingerprint(),"runtime_work_id":run_id,"run_id":run_id,"members":self.members}),
            "admission_fingerprint",
            Some("onlyalpha.research.novelty-admission-v2"),
        )
    }
    /// Must run inside the same short transaction that writes Run+Admission+Receipt.
    pub async fn recheck_in_transaction(&self, tx: &Transaction<'_>) -> Result<()> {
        for lock in &self.locks {
            lock.verify()?;
        }
        for member in &self.members {
            tx.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                &[&text(member, "same_subject_guard_key")?],
            )
            .await
            .map_err(io)?;
        }
        let current = frontier(tx, true).await?;
        if current < self.frontier {
            return Err(INVALID);
        }
        let events = history(tx, self.frontier, current).await?;
        let subjects = self
            .members
            .iter()
            .map(|v| text(v, "evaluation_subject_fingerprint").map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        for event in events {
            let family = text(&event, "source_family")?;
            let row = &event["source_row"];
            let run = match family {
                "RESEARCH_RUN" => row["run_id"].as_str(),
                "RESEARCH_ATTEMPT" => row["run_id"].as_str(),
                _ => None,
            };
            if let Some(run) = run {
                let relation=tx.query_opt("SELECT command_id::text FROM research_novelty_admission WHERE run_id=$1::text::uuid",&[&run]).await.map_err(io)?.ok_or(UNAVAILABLE)?;
                let command: String = relation.try_get(0).map_err(io)?;
                for subject in admitted_subjects(tx, &command).await? {
                    if subjects.contains(&subject) {
                        return Err("NOVELTY_DECISION_STALE");
                    }
                }
            } else if matches!(
                family,
                "PRODUCT_COMMAND_ADMISSION" | "PRODUCT_COMMAND_RECEIPT"
            ) {
                let command = text(row, "command_id")?;
                if command == self.command.value() {
                    return Err("NOVELTY_DECISION_STALE");
                }
                let relevant=tx.query_opt("SELECT 1 FROM research_novelty_admission_subject WHERE command_id=$1::text::uuid AND evaluation_subject_fingerprint=ANY($2) LIMIT 1",&[&command,&subjects]).await.map_err(io)?;
                if relevant.is_some() {
                    return Err("NOVELTY_DECISION_STALE");
                }
            }
        }
        let active=tx.query("SELECT r.run_id::text,a.command_id::text FROM research_run r LEFT JOIN research_novelty_admission a ON a.run_id=r.run_id WHERE r.state IN ('QUEUED','RUNNING','CANCEL_REQUESTED') ORDER BY r.run_id LIMIT 1025",&[]).await.map_err(io)?;
        if active.len() > 1024 {
            return Err(UNAVAILABLE);
        }
        for row in active {
            let command: Option<String> = row.try_get(1).map_err(io)?;
            let command = command.ok_or("NOVELTY_UNCLASSIFIED_RESEARCH_IN_FLIGHT")?;
            for subject in admitted_subjects(tx, &command).await? {
                if subjects.contains(&subject) {
                    return Err("NOVELTY_SAME_SUBJECT_IN_FLIGHT");
                }
            }
        }
        Ok(())
    }
}

async fn admitted_subjects(tx: &Transaction<'_>, command: &str) -> Result<Vec<String>> {
    CommandId::new(command).map_err(|_| INVALID)?;
    let parent=tx.query_opt("SELECT row_to_json(a)::text FROM research_novelty_admission a WHERE command_id=$1::text::uuid",&[&command]).await.map_err(io)?.ok_or(UNAVAILABLE)?;
    let raw: String = parent.try_get(0).map_err(io)?;
    if raw.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    let parent: Value = serde_json::from_str(&raw).map_err(|_| INVALID)?;
    if parent["schema_version"].as_u64() != Some(2) || parent["command_id"] != command {
        return Err(UNAVAILABLE);
    }
    for key in [
        "novelty_decision_fingerprint",
        "canonical_intent_fingerprint",
        "evaluation_subject_fingerprint",
        "decision_time_proof_fingerprint",
        "action_time_proof_fingerprint",
        "same_subject_guard_key",
    ] {
        if !parent[key].is_null() {
            return Err(INVALID);
        }
    }
    for key in [
        "command_fingerprint",
        "decision_group_fingerprint",
        "subject_set_fingerprint",
        "action_source_manifest_fingerprint",
        "admission_fingerprint",
    ] {
        pin(&parent[key])?;
    }
    let run = text(&parent, "run_id")?;
    CommandId::new(run).map_err(|_| INVALID)?;
    if parent["runtime_work_id"] != run {
        return Err(INVALID);
    }
    let run_row = tx
        .query_opt(
            "SELECT row_to_json(r)::text FROM research_run r WHERE run_id=$1::text::uuid",
            &[&run],
        )
        .await
        .map_err(io)?
        .ok_or(UNAVAILABLE)?;
    let raw: String = run_row.try_get(0).map_err(io)?;
    if raw.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    let record: Value = serde_json::from_str(&raw).map_err(|_| INVALID)?;
    crate::persistence::research_submission::verify_authorization(tx, &record).await?;
    let rows=tx.query("SELECT row_to_json(s)::text FROM research_novelty_admission_subject s WHERE command_id=$1::text::uuid ORDER BY ordinal LIMIT 33",&[&command]).await.map_err(io)?;
    if rows.is_empty() || rows.len() > 32 {
        return Err(INVALID);
    }
    let mut members = Vec::new();
    let mut subjects = Vec::new();
    for (ordinal, row) in rows.into_iter().enumerate() {
        let raw: String = row.try_get(0).map_err(io)?;
        if raw.len() > LIMIT {
            return Err(UNAVAILABLE);
        }
        let mut member: Value = serde_json::from_str(&raw).map_err(|_| INVALID)?;
        if member["schema_version"].as_u64() != Some(1)
            || member["command_id"] != command
            || member["admission_fingerprint"] != parent["admission_fingerprint"]
            || member["ordinal"].as_u64() != Some(ordinal as u64)
        {
            return Err(INVALID);
        }
        for key in [
            "evaluation_subject_fingerprint",
            "novelty_decision_fingerprint",
            "canonical_intent_fingerprint",
            "decision_time_proof_fingerprint",
            "action_time_proof_fingerprint",
            "same_subject_guard_key",
        ] {
            pin(&member[key])?;
        }
        let subject = text(&member, "evaluation_subject_fingerprint")?.to_owned();
        if member["same_subject_guard_key"]
            != fp(
                &json!({"domain":"onlyalpha.research.novelty-same-subject-guard-v1","evaluation_subject_fingerprint":subject}),
            )?
        {
            return Err(INVALID);
        }
        subjects.push(subject);
        let object = member.as_object_mut().ok_or(INVALID)?;
        object.remove("command_id");
        object.remove("admission_fingerprint");
        exact(
            &member,
            &[
                "schema_version",
                "ordinal",
                "evaluation_subject_fingerprint",
                "novelty_decision_fingerprint",
                "canonical_intent_fingerprint",
                "decision_time_proof_fingerprint",
                "action_time_proof_fingerprint",
                "same_subject_guard_key",
            ],
        )?;
        members.push(member);
    }
    if subjects.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(INVALID);
    }
    let candidate = json!({"domain":"onlyalpha.research.novelty-admission-v2","schema_version":2,"command_id":command,"command_fingerprint":parent["command_fingerprint"],"decision_group_fingerprint":parent["decision_group_fingerprint"],"subject_set_fingerprint":parent["subject_set_fingerprint"],"action_source_manifest_fingerprint":parent["action_source_manifest_fingerprint"],"runtime_work_id":run,"run_id":run,"members":members});
    if fp(&candidate)? != parent["admission_fingerprint"] {
        return Err(INVALID);
    }
    let id = CommandId::new(command).map_err(|_| INVALID)?;
    let binding = crate::persistence::postgres::Commands::verify_binding_in_transaction(tx, &id)
        .await
        .map_err(io)?;
    match binding {
        crate::application::command::Binding::Accepted(receipt)
            if receipt.admission().kind()
                == crate::application::command::CommandKind::CreateResearchRun
                && receipt.admission().fingerprint() == text(&parent, "command_fingerprint")?
                && receipt.outcome().kind()
                    == crate::application::command::OutcomeKind::ResearchRun
                && receipt.outcome().id() == run => {}
        _ => return Err(INVALID),
    }
    Ok(subjects)
}

fn validate_cut(cut: &Value) -> Result<()> {
    exact(
        cut,
        &[
            "schema_version",
            "source_family",
            "source_schema_version",
            "enumeration_contract_version",
            "cut_boundary",
            "completeness_proof",
            "entries",
            "cut_fingerprint",
        ],
    )?;
    verify_signed(cut, "cut_fingerprint", None)?;
    if cut["schema_version"].as_u64() != Some(1)
        || cut["enumeration_contract_version"].as_u64() != Some(1)
        || cut["source_schema_version"].as_u64().is_none_or(|n| n < 1)
    {
        return Err(INVALID);
    }
    let entries = cut["entries"].as_array().ok_or(INVALID)?;
    if entries.len() > MAX_ENTRIES {
        return Err(UNAVAILABLE);
    }
    let mut previous = None;
    for entry in entries {
        exact(entry, &["locator", "identity", "content_fingerprint"])?;
        let locator = text(entry, "locator")?;
        if locator.is_empty() || previous.is_some_and(|p| p >= locator) {
            return Err(INVALID);
        }
        previous = Some(locator);
        pin(&entry["identity"])?;
        pin(&entry["content_fingerprint"])?;
    }
    Ok(())
}
fn source_version(family: &str) -> Result<u64> {
    if !FAMILIES.contains(&family) {
        return Err(INVALID);
    }
    Ok(match family {
        "RESEARCH_RESULT" => 3,
        "RESEARCH_STATISTICS" => 2,
        "AGENT_PROVENANCE" => 2,
        "SEARCH_PROVENANCE" => 3,
        _ => 1,
    })
}
fn cut_reference(cut: &Value) -> Result<Value> {
    validate_cut(cut)?;
    let mut result = serde_json::Map::new();
    for k in [
        "source_family",
        "source_schema_version",
        "enumeration_contract_version",
        "cut_fingerprint",
        "cut_boundary",
        "completeness_proof",
    ] {
        result.insert(k.into(), cut[k].clone());
    }
    Ok(Value::Object(result))
}
fn source_ref(cut: &Value, entry: &Value) -> Result<Value> {
    Ok(
        json!({"source_family":cut["source_family"],"cut_fingerprint":cut["cut_fingerprint"],"locator":entry["locator"],"identity":entry["identity"],"content_fingerprint":entry["content_fingerprint"]}),
    )
}
fn inventory(root: &Directory) -> Result<Vec<String>> {
    let mut result = Vec::new();
    for name in root.names()? {
        if name == ".source-cut.lock" || name == "closed-cuts" {
            continue;
        }
        if name != "sha256" {
            return Err(UNAVAILABLE);
        }
        let sha = root.child(&name, false)?;
        for prefix in sha.names()? {
            if prefix.len() != 2
                || !prefix
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            {
                return Err(INVALID);
            }
            let branch = sha.child(&prefix, false)?;
            for locator in branch.names()? {
                if locator.strip_prefix(".stage-").is_some_and(|v| {
                    v.len() == 32
                        && v.bytes()
                            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                }) {
                    // Reserved pre-rename directories are not published semantic facts.
                    // Validate their physical owner; never treat unknown leaf names this way.
                    branch.child(&locator, false)?;
                    continue;
                }
                if !crate::is_sha256_hex(&locator) || !locator.starts_with(&prefix) {
                    return Err(INVALID);
                }
                branch.child(&locator, false)?;
                result.push(locator);
                if result.len() > MAX_ENTRIES {
                    return Err(UNAVAILABLE);
                }
            }
        }
    }
    result.sort();
    Ok(result)
}
async fn frontier(tx: &Transaction<'_>, locked: bool) -> Result<i64> {
    let sql = if locked {
        "SELECT last_index FROM research_source_history_frontier WHERE singleton=TRUE FOR UPDATE"
    } else {
        "SELECT last_index FROM research_source_history_frontier WHERE singleton=TRUE"
    };
    let row = tx
        .query_opt(sql, &[])
        .await
        .map_err(io)?
        .ok_or(UNAVAILABLE)?;
    let frontier: i64 = row.try_get(0).map_err(io)?;
    if frontier < 0 || frontier as u64 > MAX_ENTRIES as u64 {
        return Err(UNAVAILABLE);
    }
    Ok(frontier)
}
async fn history(tx: &Transaction<'_>, after: i64, end: i64) -> Result<Vec<Value>> {
    let budget=tx.query_one("SELECT COALESCE(sum(octet_length(source_row::text)),0)::bigint FROM research_source_history WHERE event_index>$1 AND event_index<=$2",&[&after,&end]).await.map_err(io)?;
    let bytes: i64 = budget.try_get(0).map_err(io)?;
    if bytes < 0 || bytes as u64 > LIMIT as u64 {
        return Err(UNAVAILABLE);
    }
    let rows=tx.query("SELECT event_index,source_family,native_locator,source_row::text,operation,schema_version FROM research_source_history WHERE event_index>$1 AND event_index<=$2 ORDER BY event_index LIMIT 32769",&[&after,&end]).await.map_err(io)?;
    if rows.len() != usize::try_from(end.checked_sub(after).ok_or(INVALID)?).map_err(io)? {
        return Err(INVALID);
    }
    let mut events = Vec::with_capacity(rows.len());
    for (offset, row) in rows.into_iter().enumerate() {
        let index: i64 = row.try_get(0).map_err(io)?;
        let family: String = row.try_get(1).map_err(io)?;
        let locator: String = row.try_get(2).map_err(io)?;
        let raw: String = row.try_get(3).map_err(io)?;
        let operation: String = row.try_get(4).map_err(io)?;
        let schema: i16 = row.try_get(5).map_err(io)?;
        if index != after + offset as i64 + 1
            || schema != 1
            || !PG_FAMILIES.contains(&family.as_str())
            || !matches!(operation.as_str(), "BASELINE" | "INSERT" | "UPDATE")
            || raw.len() > LIMIT
        {
            return Err(INVALID);
        }
        let payload: Value = serde_json::from_str(&raw).map_err(|_| INVALID)?;
        crate::persistence::research_execution::validate_source_history_event(&family, &payload)?;
        if family == "RESEARCH_RUN" {
            crate::persistence::research_submission::verify_authorization(tx, &payload).await?;
        }
        let key = match family.as_str() {
            "RESEARCH_RUN" => "run_id",
            "RESEARCH_ATTEMPT" => "attempt_id",
            _ => "command_id",
        };
        if payload[key] != locator {
            return Err(INVALID);
        }
        events.push(json!({"schema_version":1,"source_family":family,"native_locator":locator,"source_row":payload,"operation":operation,"event_index":index}));
    }
    Ok(events)
}
fn observation_budget(observations: &[Observation]) -> Result<()> {
    if observations.len() > MAX_ENTRIES {
        return Err(UNAVAILABLE);
    }
    let mut size = 0usize;
    for observation in observations {
        size = size
            .checked_add(observation.payload.to_string().len())
            .ok_or(UNAVAILABLE)?;
        if size > LIMIT {
            return Err(UNAVAILABLE);
        }
    }
    Ok(())
}
fn spend(remaining: &mut usize, payload: &Value) -> Result<()> {
    *remaining = remaining
        .checked_sub(payload.to_string().len())
        .ok_or(UNAVAILABLE)?;
    Ok(())
}
fn pg_cut(family: &str, frontier: i64, events: &[Value]) -> Result<(Value, Vec<Observation>)> {
    let mut entries = Vec::new();
    let mut observations = Vec::new();
    for event in events
        .iter()
        .filter(|event| event["source_family"] == family)
    {
        let index = event["event_index"].as_i64().ok_or(INVALID)?;
        if index > frontier {
            return Err(INVALID);
        }
        let content = fp(event)?;
        entries.push(json!({"locator":format!("{index:020}"),"identity":content,"content_fingerprint":content}));
        observations.push(Observation {
            source_ref: Value::Null,
            payload: event.clone(),
        });
    }
    let cut = signed(
        json!({"schema_version":1,"source_family":family,"source_schema_version":1,"enumeration_contract_version":1,"cut_boundary":format!("JOURNAL_INDEX:{frontier}"),"completeness_proof":"SOURCE_TRANSACTIONAL_JOURNAL_V1","entries":entries}),
        "cut_fingerprint",
        None,
    )?;
    for (observation, entry) in observations
        .iter_mut()
        .zip(cut["entries"].as_array().ok_or(INVALID)?)
    {
        observation.source_ref = source_ref(&cut, entry)?;
    }
    Ok((cut, observations))
}
async fn verify_pg_cut(tx: &Transaction<'_>, cut: &Value, frontier: i64) -> Result<()> {
    let row=tx.query_opt("SELECT source_family,frontier,canonical_document,schema_version FROM research_source_closed_cut WHERE cut_fingerprint=$1",&[&text(cut,"cut_fingerprint")?]).await.map_err(io)?.ok_or(INVALID)?;
    let family: String = row.try_get(0).map_err(io)?;
    let n: i64 = row.try_get(1).map_err(io)?;
    let raw: String = row.try_get(2).map_err(io)?;
    let schema: i16 = row.try_get(3).map_err(io)?;
    if cut["source_family"] != family
        || n != frontier
        || schema != 1
        || parsed(raw.as_bytes())? != *cut
    {
        return Err(INVALID);
    }
    Ok(())
}

fn verify_projection_envelope(projection: &Value, expected: &str) -> Result<()> {
    exact(
        projection,
        &[
            "projection_schema_version",
            "projector_algorithm_version",
            "source_manifest",
            "records",
            "logical_digest",
            "revision_fingerprint",
        ],
    )?;
    if projection["projection_schema_version"].as_u64() != Some(7)
        || projection["projector_algorithm_version"].as_u64() != Some(7)
        || projection["revision_fingerprint"] != expected
    {
        return Err(INVALID);
    }
    let manifest = &projection["source_manifest"];
    exact(
        manifest,
        &[
            "schema_version",
            "mandatory_family_set_version",
            "cuts",
            "manifest_fingerprint",
        ],
    )?;
    verify_signed(manifest, "manifest_fingerprint", None)?;
    if manifest["schema_version"].as_u64() != Some(1)
        || manifest["mandatory_family_set_version"].as_u64() != Some(1)
    {
        return Err(INVALID);
    }
    let cuts = manifest["cuts"].as_array().ok_or(INVALID)?;
    if cuts.len() != FAMILIES.len() {
        return Err(INVALID);
    }
    for (cut, family) in cuts.iter().zip(FAMILIES) {
        exact(
            cut,
            &[
                "source_family",
                "source_schema_version",
                "enumeration_contract_version",
                "cut_fingerprint",
                "cut_boundary",
                "completeness_proof",
            ],
        )?;
        if cut["source_family"] != family {
            return Err(INVALID);
        }
        pin(&cut["cut_fingerprint"])?;
    }
    let records = projection["records"].as_array().ok_or(INVALID)?;
    if records.len() > MAX_ENTRIES {
        return Err(UNAVAILABLE);
    }
    let strings = records.iter().map(canonical).collect::<Result<Vec<_>>>()?;
    if strings.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(INVALID);
    }
    let logical = fp(
        &json!({"projection_schema_version":7,"projector_algorithm_version":7,"records":records}),
    )?;
    let identity = fp(
        &json!({"source_cut_manifest_fingerprint":manifest["manifest_fingerprint"],"projection_schema_version":7,"projector_algorithm_version":7,"logical_digest":logical}),
    )?;
    if projection["logical_digest"] != logical || identity != expected {
        return Err(INVALID);
    }
    Ok(())
}

fn build_projection(manifest: Value, observations: &[Observation]) -> Result<Value> {
    let mut records = Vec::new();
    let results = observations
        .iter()
        .filter(|o| o.source_ref["source_family"] == "RESEARCH_RESULT")
        .collect::<Vec<_>>();
    let runs = observations
        .iter()
        .filter(|o| o.source_ref["source_family"] == "RESEARCH_RUN")
        .collect::<Vec<_>>();
    let statistics = observations
        .iter()
        .filter(|o| o.source_ref["source_family"] == "RESEARCH_STATISTICS")
        .collect::<Vec<_>>();
    verify_result_references(&runs, &results)?;
    // Every returned native owner manifest has already passed its physical,
    // semantic and upstream reads. Rebuild all derived evaluation membership.
    for result in &results {
        let v = &result.payload;
        let subject = Subject::new(v["evaluation_subject"].clone())?;
        let subject_record = subject.record();
        if v["schema_version"].as_u64() != Some(5)
            || v["research_result_plan_fingerprint"] != result.source_ref["locator"]
            || v["research_result_fingerprint"] != result.source_ref["identity"]
            || v["dataset_snapshot_fingerprint"] != subject_record["dataset_snapshot_fingerprint"]
        {
            return Err(INVALID);
        }
        let references = v["statistics_references"].as_array().ok_or(INVALID)?;
        let mut refs = vec![result.source_ref.clone()];
        let mut logical = Vec::new();
        for reference in references {
            exact(
                reference,
                &["statistics_fingerprint", "statistics_result_fingerprint"],
            )?;
            let matches = statistics
                .iter()
                .filter(|o| {
                    o.source_ref["locator"] == reference["statistics_fingerprint"]
                        && o.source_ref["identity"] == reference["statistics_result_fingerprint"]
                })
                .collect::<Vec<_>>();
            if matches.len() != 1 || matches[0].payload["evaluation_subject"] != subject.to_record()
            {
                return Err(INVALID);
            }
            refs.push(matches[0].source_ref.clone());
            logical.push(reference["statistics_fingerprint"].clone());
        }
        if json!(logical) != subject_record["statistics_fingerprints"] {
            return Err(INVALID);
        }
        let mut closures = Vec::new();
        let mut run_ids = BTreeSet::new();
        for observation in &runs {
            let row = &observation.payload["source_row"];
            if row["research_result_fingerprint"] != result.source_ref["identity"] {
                continue;
            }
            let actual = crate::application::research_run::source_subject(row)?;
            if actual != subject {
                return Err(INVALID);
            }
            let closure = run_context(observation, &actual);
            run_ids.insert(text(row, "run_id")?.to_owned());
            closures.push(closure);
            refs.push(observation.source_ref.clone());
        }
        closures.sort_by(|a, b| {
            (
                &a["run_id"].as_str(),
                a["run_revision"].as_i64(),
                a["run_source_ref"]["locator"].as_str(),
            )
                .cmp(&(
                    &b["run_id"].as_str(),
                    b["run_revision"].as_i64(),
                    b["run_source_ref"]["locator"].as_str(),
                ))
        });
        refs.sort_by(|a, b| {
            (a["source_family"].as_str(), a["locator"].as_str())
                .cmp(&(b["source_family"].as_str(), b["locator"].as_str()))
        });
        refs.dedup();
        let mut facets = serde_json::Map::new();
        for k in [
            "graph_fingerprint",
            "candidate_node_fingerprint",
            "output_name",
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
        ] {
            facets.insert(k.into(), subject_record[k].clone());
        }
        facets.extend(json!({"research_run_refs":run_ids,"run_evaluation_closures":closures,"specification_refs":[subject_record["specification_fingerprint"]],"search_experiment_refs":[],"catalog_generation_refs":[subject_record["catalog_generation_fingerprint"]],"authoring_generation_refs":if subject_record["authoring_generation_fingerprint"].is_null(){json!([])}else{json!([subject_record["authoring_generation_fingerprint"]])},"runtime_generation_refs":[subject_record["runtime_generation_fingerprint"]],"research_result_locator":result.source_ref["locator"],"research_result_fingerprint":result.source_ref["identity"],"statistics_references":references}).as_object().ok_or(INVALID)?.clone());
        records
            .push(json!({"kind":"EvaluationProjectionRecord","facets":facets,"source_refs":refs}));
    }
    for observation in &runs {
        let row = &observation.payload["source_row"];
        // Failure/cancellation history is retained even when it has no result.
        if matches!(row["state"].as_str(), Some("FAILED" | "CANCELLED")) {
            let subject = crate::application::research_run::source_subject(row)?;
            records.push(json!({"kind":"FailureEvidenceProjectionRecord","facets":{"owner_kind":"RESEARCH_RUN","classification":"OPERATIONAL_FAILURE","run_context":run_context(observation,&subject),"failure_code":row["failure_code"],"failure_phase":row["failure_phase"],"failure_detail":row["failure_detail"]},"source_refs":[observation.source_ref]}));
        }
    }
    let run_ids = runs
        .iter()
        .map(|o| text(&o.payload["source_row"], "run_id"))
        .collect::<Result<BTreeSet<_>>>()?;
    for observation in observations
        .iter()
        .filter(|o| o.source_ref["source_family"] == "RESEARCH_ATTEMPT")
    {
        if !run_ids.contains(text(&observation.payload["source_row"], "run_id")?) {
            return Err(INVALID);
        }
    }
    let mut sorted = records
        .into_iter()
        .map(|record| canonical(&record).map(|key| (key, record)))
        .collect::<Result<Vec<_>>>()?;
    sorted.sort_by(|a, b| a.0.cmp(&b.0));
    if sorted.windows(2).any(|pair| pair[0].0 == pair[1].0) {
        return Err(INVALID);
    }
    let records = sorted
        .into_iter()
        .map(|(_, record)| record)
        .collect::<Vec<_>>();
    let logical = fp(
        &json!({"projection_schema_version":7,"projector_algorithm_version":7,"records":records}),
    )?;
    let identity = fp(
        &json!({"source_cut_manifest_fingerprint":manifest["manifest_fingerprint"],"projection_schema_version":7,"projector_algorithm_version":7,"logical_digest":logical}),
    )?;
    Ok(
        json!({"projection_schema_version":7,"projector_algorithm_version":7,"source_manifest":manifest,"records":records,"logical_digest":logical,"revision_fingerprint":identity}),
    )
}
fn verify_result_references(runs: &[&Observation], results: &[&Observation]) -> Result<()> {
    for observation in runs {
        let row = &observation.payload["source_row"];
        let evidence = if row["calculation_execution_evidence_fingerprints"].is_null() {
            &[][..]
        } else {
            row["calculation_execution_evidence_fingerprints"]
                .as_array()
                .ok_or(INVALID)?
                .as_slice()
        };
        if row["research_result_fingerprint"].is_null() {
            if row["state"] == "COMPLETED"
                || !row["artifact_content_fingerprint"].is_null()
                || !evidence.is_empty()
            {
                return Err(INVALID);
            }
            continue;
        }
        pin(&row["research_result_fingerprint"])?;
        let matching = results
            .iter()
            .filter(|result| result.source_ref["identity"] == row["research_result_fingerprint"])
            .collect::<Vec<_>>();
        if matching.len() != 1 {
            return Err(UNAVAILABLE);
        }
        let owner = &matching[0].payload["calculation_execution_evidence_fingerprints"];
        if row["state"] == "COMPLETED" || !evidence.is_empty() {
            let owner = owner.as_array().ok_or(INVALID)?;
            if owner.is_empty() || owner.as_slice() != evidence {
                return Err(INVALID);
            }
            let pins = owner.iter().map(pin).collect::<Result<Vec<_>>>()?;
            if pins.windows(2).any(|pair| pair[0] >= pair[1]) {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}
fn run_context(observation: &Observation, subject: &Subject) -> Value {
    let row = &observation.payload["source_row"];
    let subject = subject.record();
    let evidence = if row["calculation_execution_evidence_fingerprints"].is_null() {
        json!([])
    } else {
        row["calculation_execution_evidence_fingerprints"].clone()
    };
    json!({"run_id":row["run_id"],"run_revision":row["revision"],"run_state":row["state"],"specification_fingerprint":row["specification_fingerprint"],"research_result_fingerprint":row["research_result_fingerprint"],"artifact_content_fingerprint":row["artifact_content_fingerprint"],"catalog_generation_fingerprint":subject["catalog_generation_fingerprint"],"runtime_generation_fingerprint":subject["runtime_generation_fingerprint"],"authoring_generation_fingerprint":subject["authoring_generation_fingerprint"],"calculation_execution_evidence_fingerprints":evidence,"run_source_ref":observation.source_ref,"search_lineage":null})
}
fn query(subject: &Subject, snapshot: &Snapshot) -> Result<(Value, Value)> {
    let mut matches = Vec::new();
    let mut incomplete = false;
    for record in snapshot.projection["records"].as_array().ok_or(INVALID)? {
        if record["kind"] != "EvaluationProjectionRecord" {
            continue;
        }
        let facets = &record["facets"];
        let closures = facets["run_evaluation_closures"]
            .as_array()
            .ok_or(INVALID)?;
        if closures.is_empty() {
            incomplete = true;
            continue;
        }
        let mut found = false;
        for closure in closures {
            if closure["run_state"] != "COMPLETED" {
                continue;
            }
            let mut value = subject.to_record();
            for key in [
                "graph_fingerprint",
                "candidate_node_fingerprint",
                "output_name",
                "candidate_fingerprint",
                "dataset_snapshot_fingerprint",
            ] {
                value[key] = facets[key].clone();
            }
            for key in [
                "specification_fingerprint",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
                "authoring_generation_fingerprint",
            ] {
                value[key] = closure[key].clone();
            }
            value["result_plan_fingerprint"] = facets["research_result_locator"].clone();
            value["statistics_fingerprints"] = json!(
                facets["statistics_references"]
                    .as_array()
                    .ok_or(INVALID)?
                    .iter()
                    .map(|r| r["statistics_fingerprint"].clone())
                    .collect::<Vec<_>>()
            );
            let actual = Subject::new(value)?;
            if closure["artifact_content_fingerprint"]
                .as_str()
                .is_none_or(|s| !crate::is_sha256_hex(s))
                || closure["calculation_execution_evidence_fingerprints"]
                    .as_array()
                    .is_none_or(Vec::is_empty)
            {
                return Err(INVALID);
            }
            if actual == *subject {
                found = true;
            }
        }
        if found {
            matches.push(json!({"record_kind":record["kind"],"facets":record["facets"],"source_refs":record["source_refs"]}));
        }
    }
    let mut sorted = matches
        .into_iter()
        .map(|v| canonical(&v).map(|k| (k, v)))
        .collect::<Result<Vec<_>>>()?;
    sorted.sort_by(|a, b| a.0.cmp(&b.0));
    sorted.dedup_by(|a, b| a.0 == b.0);
    n::historical_query(
        subject,
        &snapshot.projection,
        sorted.into_iter().map(|(_, v)| v).collect(),
        incomplete,
    )
}
fn make_group(
    command: &CommandId,
    subjects: &[Subject],
    policy: &Value,
    snapshot: &Snapshot,
) -> Result<Value> {
    let members = subjects
        .iter()
        .map(|subject| {
            let (query, proof) = query(subject, snapshot)?;
            n::decision_bundle(command, subject, policy, &snapshot.projection, query, proof)
        })
        .collect::<Result<Vec<_>>>()?;
    n::group(command, subjects, members)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn temp(name: &str) -> PathBuf {
        let mut nonce = [0u8; 16];
        getrandom::fill(&mut nonce).unwrap();
        let suffix = nonce.iter().map(|b| format!("{b:02x}")).collect::<String>();
        let path = std::env::temp_dir()
            .canonicalize()
            .unwrap()
            .join(format!("research-novelty-{name}-{suffix}"));
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        path
    }
    #[test]
    fn retained_group_missing_or_rebound_command_is_never_original_prepared_fact() {
        let root = temp("retained-group");
        let semantic = Directory::open(&root).unwrap();
        semantic
            .path(&["research", "novelty-decision-groups"], true)
            .unwrap();
        let authority = Authority {
            semantic_root: semantic,
            projection_root: Directory::open(&root).unwrap(),
            source_roots: BTreeMap::new(),
        };
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_novelty.json"
        ))
        .unwrap();
        let command = CommandId::new(fixture["command_id"].as_str().unwrap()).unwrap();
        assert_eq!(
            authority.retained_group_record(&command).unwrap_err(),
            UNAVAILABLE
        );
        let subject = Subject::new(fixture["subject"].clone()).unwrap();
        let snapshot = Snapshot {
            projection: fixture["projection"].clone(),
            frontier: 0,
            locks: vec![],
        };
        let original = make_group(&command, &[subject], &fixture["policy"], &snapshot).unwrap();
        put(
            &authority.semantic_root,
            &["research", "novelty-decision-groups", command.value()],
            "group.json",
            &original,
        )
        .unwrap();
        assert_eq!(authority.retained_group_record(&command).unwrap(), original);
        let mut changed = original;
        changed["product_command_id"] = json!("00000000-0000-4000-8000-000000000001");
        changed.as_object_mut().unwrap().remove("group_fingerprint");
        let changed = signed(
            changed,
            "group_fingerprint",
            Some("onlyalpha.research.novelty-decision-group-v1"),
        )
        .unwrap();
        let leaf = root
            .join("research/novelty-decision-groups")
            .join(command.value())
            .join("group.json");
        std::fs::write(&leaf, canonical(&changed).unwrap()).unwrap();
        assert!(authority.retained_group_record(&command).is_err());
        std::fs::remove_file(leaf).unwrap();
        assert!(authority.retained_group_record(&command).is_err());
        drop(authority);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn missing_source_owner_and_unknown_inventory_never_become_empty_cuts() {
        let root = temp("source");
        assert!(SourceLock::acquire(&root).is_err());
        let file = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join(".source-cut.lock"))
            .unwrap();
        std::fs::set_permissions(
            root.join(".source-cut.lock"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        drop(file);
        let locked = SourceLock::acquire(&root).unwrap();
        assert!(inventory(&locked.directory).unwrap().is_empty());
        std::fs::write(root.join("unknown.json"), b"{}").unwrap();
        assert_eq!(inventory(&locked.directory).unwrap_err(), UNAVAILABLE);
        drop(locked);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn abandoned_prepublication_stage_is_not_a_fact_or_an_unknown_final_leaf() {
        let root = temp("stage");
        let directory = Directory::open(&root).unwrap();
        let branch = directory.path(&["sha256", "ab"], true).unwrap();
        branch
            .child(".stage-0123456789abcdef0123456789abcdef", true)
            .unwrap();
        assert!(inventory(&directory).unwrap().is_empty());
        let id = format!("ab{}", "0".repeat(62));
        put(
            &directory,
            &["sha256", "ab", &id],
            "manifest.json",
            &json!({"value":"committed"}),
        )
        .unwrap();
        assert_eq!(inventory(&directory).unwrap(), vec![id]);
        branch.child(".stage-unknown", true).unwrap();
        assert!(inventory(&directory).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn original_put_once_namespace_reuses_exact_content_and_refuses_substitution() {
        let root = temp("put");
        let directory = Directory::open(&root).unwrap();
        let first = json!({"value":"original"});
        put(&directory, &["owner", "identity"], "group.json", &first).unwrap();
        put(&directory, &["owner", "identity"], "group.json", &first).unwrap();
        assert!(
            put(
                &directory,
                &["owner", "identity"],
                "group.json",
                &json!({"value":"different"})
            )
            .is_err()
        );
        assert_eq!(
            read_path(&directory, &["owner", "identity"], "group.json").unwrap(),
            first
        );
        let rebound = root.with_extension("old");
        std::fs::rename(&root, &rebound).unwrap();
        std::fs::create_dir(&root).unwrap();
        assert!(directory.verify().is_err());
        std::fs::remove_dir(root).unwrap();
        std::fs::remove_dir_all(rebound).unwrap();
    }
    #[test]
    fn incomplete_relevant_evaluation_never_certifies_no_match() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_novelty.json"
        ))
        .unwrap();
        let subject = Subject::new(fixture["subject"].clone()).unwrap();
        let command = CommandId::new(fixture["command_id"].as_str().unwrap()).unwrap();
        let mut projection = fixture["projection"].clone();
        projection["records"] = json!([{"kind":"EvaluationProjectionRecord","facets":{"run_evaluation_closures":[]},"source_refs":[]}]);
        let snapshot = Snapshot {
            projection,
            frontier: 0,
            locks: vec![],
        };
        let (_, proof) = query(&subject, &snapshot).unwrap();
        assert_eq!(proof["proof_status"], "PROOF_INCOMPLETE");
        assert!(proof["ordered_matches"].as_array().unwrap().is_empty());
        let group = make_group(&command, &[subject], &fixture["policy"], &snapshot).unwrap();
        assert_eq!(group["disposition"], "BLOCKED");
        assert_eq!(group["members"][0]["decision"]["outcome"], "FAIL_CLOSED");
    }
    #[test]
    fn rehashed_projection_still_requires_every_original_mandatory_family() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_novelty.json"
        ))
        .unwrap();
        verify_projection_envelope(
            &fixture["projection"],
            fixture["projection"]["revision_fingerprint"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        let mut manifest = fixture["projection"]["source_manifest"].clone();
        manifest["cuts"].as_array_mut().unwrap().pop();
        manifest
            .as_object_mut()
            .unwrap()
            .remove("manifest_fingerprint");
        let manifest = signed(manifest, "manifest_fingerprint", None).unwrap();
        let changed = build_projection(manifest, &[]).unwrap();
        assert!(
            verify_projection_envelope(&changed, changed["revision_fingerprint"].as_str().unwrap())
                .is_err()
        );
    }
    #[test]
    fn run_claimed_result_requires_actual_unique_owner_leaf_even_for_failed_runs() {
        let run = Observation {
            source_ref: Value::Null,
            payload: json!({"source_row":{"state":"FAILED","research_result_fingerprint":"1".repeat(64),"artifact_content_fingerprint":null,"calculation_execution_evidence_fingerprints":[]}}),
        };
        assert_eq!(
            verify_result_references(&[&run], &[]).unwrap_err(),
            UNAVAILABLE
        );
        let result = Observation {
            source_ref: json!({"identity":"1".repeat(64)}),
            payload: json!({"calculation_execution_evidence_fingerprints":["2".repeat(64)]}),
        };
        // Partial failure is a complete occurrence without copied final Evidence.
        verify_result_references(&[&run], &[&result]).unwrap();
        assert!(verify_result_references(&[&run], &[&result, &result]).is_err());
    }
    #[test]
    fn completed_run_cannot_substitute_or_omit_owner_execution_evidence() {
        let result = Observation {
            source_ref: json!({"identity":"1".repeat(64)}),
            payload: json!({"calculation_execution_evidence_fingerprints":["2".repeat(64)]}),
        };
        let mut run = Observation {
            source_ref: Value::Null,
            payload: json!({"source_row":{"state":"COMPLETED","research_result_fingerprint":"1".repeat(64),"artifact_content_fingerprint":"3".repeat(64),"calculation_execution_evidence_fingerprints":["2".repeat(64)]}}),
        };
        verify_result_references(&[&run], &[&result]).unwrap();
        for evidence in [json!([]), json!(["4".repeat(64)]), Value::Null] {
            run.payload["source_row"]["calculation_execution_evidence_fingerprints"] = evidence;
            assert!(verify_result_references(&[&run], &[&result]).is_err());
        }
    }
}
