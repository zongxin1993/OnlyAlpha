//! Immutable Strategy history and original-Command publication. Reading grants no READY authority.
use crate::is_sha256_hex;
use crate::persistence::authority_session::AuthoritySession;
use crate::security::protected_files::{self, FilePolicy, ReadError};
use onlyalpha_strategy::{SourceError, SourceRevision, record_fingerprint};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    ffi::OsStr,
    fmt,
    os::fd::{BorrowedFd, OwnedFd},
};
const DOCUMENT_WORK: usize = 8 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Missing,
    Corrupt,
    Unavailable,
    Authority,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "STRATEGY_NOT_FOUND",
            Self::Corrupt => "STRATEGY_CORRUPT",
            Self::Unavailable => "STRATEGY_STORE_UNAVAILABLE",
            Self::Authority => "STRATEGY_AUTHORITY_UNAVAILABLE",
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
    fn from(e: ReadError) -> Self {
        match e {
            ReadError::Missing => Self::Missing,
            ReadError::Invalid => Self::Corrupt,
            ReadError::Unavailable => Self::Unavailable,
        }
    }
}
fn exact<'a>(v: &'a Value, keys: &[&str]) -> Result<&'a serde_json::Map<String, Value>, Error> {
    let m = v.as_object().ok_or(Error::Corrupt)?;
    if m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(Error::Corrupt);
    }
    Ok(m)
}
fn sha(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|v| is_sha256_hex(v))
        .ok_or(Error::Corrupt)
}
/// Existing FreezeRelation1 identity; audit metadata is not semantic identity.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FreezeRelation {
    record: Value,
    fingerprint: String,
    strategy: String,
}
impl FreezeRelation {
    pub fn from_json(raw: &str, max_work: usize) -> Result<Self, Error> {
        if raw.len() > max_work {
            return Err(Error::Unavailable);
        }
        let v: Value = serde_json::from_str(raw).map_err(|_| Error::Corrupt)?;
        match v["schema_version"].as_u64() {
            Some(1)=>{
                exact(&v,&["schema_version","strategy_fingerprint","candidate_fingerprint","research_result_fingerprint",
                    "research_execution_evidence_fingerprints","admission_evidence_fingerprint","equivalence_evidence_fingerprints","relation_fingerprint"])?;
                for key in ["strategy_fingerprint","candidate_fingerprint","research_result_fingerprint","admission_evidence_fingerprint","relation_fingerprint"] {sha(&v[key])?;}
                for key in ["research_execution_evidence_fingerprints","equivalence_evidence_fingerprints"] {
                    let rows=v[key].as_array().filter(|a|!a.is_empty()).ok_or(Error::Corrupt)?;
                    let mut previous=None;
                    for row in rows {let current=sha(row)?;if previous.is_some_and(|p|p>=current){return Err(Error::Corrupt);}previous=Some(current);}
                }
            },
            Some(2)=>{
                exact(&v,&["schema_version","strategy_fingerprint","origin","relation_fingerprint"])?;
                sha(&v["strategy_fingerprint"])?;sha(&v["relation_fingerprint"])?;
                let origin=&v["origin"];
                exact(origin,&["kind","preparation_command_id","strategy_validation_fingerprint","private_strategy_id","private_strategy_revision_fingerprint"])?;
                if origin["kind"]!="MANUAL_BACKTEST" || origin["preparation_command_id"].as_str().is_none_or(|s|!crate::application::command::uuid4(s)){return Err(Error::Corrupt);}
                sha(&origin["strategy_validation_fingerprint"])?;sha(&origin["private_strategy_revision_fingerprint"])?;
                let id=crate::application::private_strategy::name(&origin["private_strategy_id"]).map_err(|_|Error::Corrupt)?;
                crate::application::private_assets::id(id,"STRATEGY").map_err(|_|Error::Corrupt)?;
            },
            _=>return Err(Error::Corrupt),
        }
        let mut semantic = v.clone();
        let m = semantic.as_object_mut().ok_or(Error::Corrupt)?;
        m.remove("relation_fingerprint");
        m.insert("domain".into(), json!("onlyalpha.strategy.freeze-relation"));
        let fingerprint = record_fingerprint(&semantic);
        if v["relation_fingerprint"] != fingerprint {
            return Err(Error::Corrupt);
        }
        Ok(Self {
            strategy: sha(&v["strategy_fingerprint"])?.to_owned(),
            record: v,
            fingerprint,
        })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn strategy_fingerprint(&self) -> &str {
        &self.strategy
    }
}
/// Complete observations of the two formal trees, never proof of Node READY.
/// Missing roots remain explicit so reconciliation can reject dangling projections.
pub struct Inventory {
    revisions: BTreeMap<String, SourceRevision>,
    relations: BTreeMap<String, FreezeRelation>,
    revision_tree_present: bool,
    relation_tree_present: bool,
}
impl Inventory {
    pub fn revisions(&self) -> &BTreeMap<String, SourceRevision> {
        &self.revisions
    }
    pub fn relations(&self) -> &BTreeMap<String, FreezeRelation> {
        &self.relations
    }
    pub fn revision_tree_present(&self) -> bool {
        self.revision_tree_present
    }
    pub fn relation_tree_present(&self) -> bool {
        self.relation_tree_present
    }
}
pub struct FrozenStore {
    research: OwnedFd,
}
impl FrozenStore {
    /// Duplicate the selected capability, never reopen the original absolute path.
    pub fn open(research: BorrowedFd<'_>) -> Result<Self, Error> {
        Ok(Self {
            research: protected_files::duplicate_directory(research)?,
        })
    }
    /// Host must close mutation admission and retain this exclusive same-session
    /// borrow throughout startup/upgrade. No concurrent publisher can be admitted.
    pub async fn inventory(
        &self,
        session: &mut AuthoritySession,
        max_work: usize,
    ) -> Result<Inventory, Error> {
        session.verify().await.map_err(|_| Error::Authority)?;
        let result = self.read_all(max_work);
        session.verify().await.map_err(|_| Error::Authority)?;
        result
    }
    /// Exact read only, not a complete/quiescent inventory or execution admission.
    pub fn load_verified(
        &self,
        fingerprint: &str,
        max_work: usize,
    ) -> Result<SourceRevision, Error> {
        if !is_sha256_hex(fingerprint) {
            return Err(Error::Corrupt);
        }
        self.read_all(max_work)?
            .revisions
            .remove(fingerprint)
            .ok_or(Error::Missing)
    }
    /// Exact historical relation read; it grants neither publication nor work.
    pub(crate) fn load_relation_verified(
        &self,
        fingerprint: &str,
        max_work: usize,
    ) -> Result<FreezeRelation, Error> {
        if !is_sha256_hex(fingerprint) {
            return Err(Error::Corrupt);
        }
        self.read_all(max_work)?
            .relations
            .remove(fingerprint)
            .ok_or(Error::Missing)
    }
    /// Bounded immutable history for a Product read; no publication capability.
    pub(crate) fn relations_verified(&self,subject:&str,max_work:usize)->Result<Vec<FreezeRelation>,Error> {
        if !is_sha256_hex(subject){return Err(Error::Corrupt);}
        let inventory=self.read_all(max_work)?;
        if !inventory.revisions.contains_key(subject){return Err(Error::Missing);}
        Ok(inventory.relations.into_values().filter(|r|r.strategy_fingerprint()==subject).collect())
    }
    pub(crate) fn namespace(
        &self,
    ) -> Result<crate::bootstrap::deployment::SemanticStoreId, crate::bootstrap::deployment::Error>
    {
        crate::bootstrap::deployment::load_semantic_store_id_at(&self.research)
    }
    fn tree(&self, name: &str) -> Result<Option<OwnedFd>, Error> {
        let mut fd = self.research.try_clone().map_err(ReadError::from)?;
        for part in ["strategy", name, "sha256"] {
            fd = match protected_files::open_directory_at(&fd, OsStr::new(part)) {
                Ok(fd) => fd,
                Err(ReadError::Missing) => return Ok(None),
                Err(e) => return Err(e.into()),
            };
        }
        Ok(Some(fd))
    }
    fn read_all(&self, max_work: usize) -> Result<Inventory, Error> {
        let mut work = Work(max_work);
        let revision_root = self.tree("frozen-revisions")?;
        let relation_root = self.tree("freeze-relations")?;
        let mut result = Inventory {
            revisions: BTreeMap::new(),
            relations: BTreeMap::new(),
            revision_tree_present: revision_root.is_some(),
            relation_tree_present: relation_root.is_some(),
        };
        if let Some(root) = relation_root {
            for (id, raw) in documents(&root, &mut work)? {
                let relation = FreezeRelation::from_json(&raw, DOCUMENT_WORK)?;
                if relation.fingerprint() != id {
                    return Err(Error::Corrupt);
                }
                result.relations.insert(id, relation);
            }
        }
        if let Some(root) = revision_root {
            for (id, raw) in documents(&root, &mut work)? {
                let v: Value = serde_json::from_str(&raw).map_err(|_| Error::Corrupt)?;
                exact(&v, &["schema_version", "strategy_fingerprint", "revision"])?;
                if v["schema_version"].as_u64() != Some(1) || v["strategy_fingerprint"] != id {
                    return Err(Error::Corrupt);
                }
                let source = SourceRevision::from_json(&v["revision"].to_string(), DOCUMENT_WORK)
                    .map_err(|e| match e {
                    SourceError::Invalid => Error::Corrupt,
                    SourceError::Unavailable => Error::Unavailable,
                })?;
                if source.fingerprint() != id {
                    return Err(Error::Corrupt);
                }
                result.revisions.insert(id, source);
            }
        }
        let mut matched = std::collections::BTreeSet::new();
        for relation in result.relations.values() {
            matched.insert(relation.strategy_fingerprint());
        }
        if result
            .revisions
            .keys()
            .any(|id| !matched.contains(id.as_str()))
        {
            return Err(Error::Corrupt);
        }
        Ok(result)
    }
}
struct Work(usize);
impl Work {
    fn take(&mut self, n: usize) -> Result<(), Error> {
        self.0 = self.0.checked_sub(n).ok_or(Error::Unavailable)?;
        Ok(())
    }
}
fn documents(root: &OwnedFd, work: &mut Work) -> Result<Vec<(String, String)>, Error> {
    let mut docs = Vec::new();
    for prefix in protected_files::directory_entries(root, &mut work.0)? {
        let p = prefix
            .to_str()
            .filter(|s| {
                s.len() == 2
                    && s.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
            .ok_or(Error::Corrupt)?;
        let dir = protected_files::open_directory_at(root, &prefix).map_err(published_error)?;
        for leaf in protected_files::directory_entries(&dir, &mut work.0)? {
            let id = leaf
                .to_str()
                .filter(|s| is_sha256_hex(s) && s.starts_with(p))
                .ok_or(Error::Corrupt)?;
            let target =
                protected_files::open_directory_at(&dir, &leaf).map_err(published_error)?;
            if protected_files::directory_entries(&target, &mut work.0)?
                != [OsStr::new("manifest.json")]
            {
                return Err(Error::Corrupt);
            }
            // Charge the entire per-document parse/expansion allowance, not only bytes.
            // This bounds cumulative work even for small decimal exponent spellings.
            work.take(DOCUMENT_WORK)?;
            let data = protected_files::read_file_at(
                &target,
                OsStr::new("manifest.json"),
                FilePolicy::HistoryDocument,
                DOCUMENT_WORK,
            )
            .map_err(published_error)?;
            let raw = std::str::from_utf8(&data).map_err(|_| Error::Corrupt)?;
            let v: Value = serde_json::from_str(raw).map_err(|_| Error::Corrupt)?;
            let canonical = serde_json::to_vec(&v).map_err(|_| Error::Corrupt)?;
            if canonical.as_slice() != raw.as_bytes() {
                return Err(Error::Corrupt);
            }
            docs.push((id.to_owned(), raw.to_owned()));
        }
    }
    Ok(docs)
}

fn published_error(e: ReadError) -> Error {
    if e == ReadError::Missing {
        Error::Corrupt
    } else {
        e.into()
    }
}

#[cfg(test)]
mod freeze_publication_tests {
    use super::*;
    use crate::persistence::research_evidence::VerifiedStrategyResearch;
    use crate::security::immutable_json::SourceLock;
    use std::{os::unix::fs::PermissionsExt, path::PathBuf, sync::Arc};

    struct CutRoot(PathBuf);
    impl CutRoot {
        fn new() -> Self {
            let mut entropy = [0u8; 16];
            getrandom::fill(&mut entropy).unwrap();
            let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
                "use-test-freeze-cut-{}",
                entropy
                    .iter()
                    .map(|b| format!("{b:02x}"))
                    .collect::<String>()
            ));
            std::fs::create_dir(&path).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
            std::fs::write(path.join(".source-cut.lock"), b"").unwrap();
            std::fs::set_permissions(
                path.join(".source-cut.lock"),
                std::fs::Permissions::from_mode(0o600),
            )
            .unwrap();
            Self(path)
        }
        fn evidence(&self) -> VerifiedStrategyResearch {
            let fixture: Value = serde_json::from_str(include_str!(
                "../../tests/application/fixtures/frozen_strategy.json"
            ))
            .unwrap();
            let relation = &fixture["relation"];
            VerifiedStrategyResearch::for_value_test(
                "00000000-0000-4000-8000-000000000701".into(),
                "7".repeat(64),
                SourceRevision::from_json(&fixture["source"].to_string(), DOCUMENT_WORK).unwrap(),
                relation["candidate_fingerprint"].as_str().unwrap().into(),
                relation["research_result_fingerprint"]
                    .as_str()
                    .unwrap()
                    .into(),
                relation["research_execution_evidence_fingerprints"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap().into())
                    .collect(),
                relation["admission_evidence_fingerprint"]
                    .as_str()
                    .unwrap()
                    .into(),
                relation["equivalence_evidence_fingerprints"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap().into())
                    .collect(),
                vec![Arc::new(SourceLock::publication(&self.0).unwrap())],
            )
        }
    }
    impl Drop for CutRoot {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }

    #[test]
    fn evaluator_sealed_plan_keeps_current_revision_and_relation_identity() {
        let root = CutRoot::new();
        let evidence = root.evidence();
        let plan = FrozenPlan::from_verified(&evidence).unwrap();
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/frozen_strategy.json"
        ))
        .unwrap();
        assert_eq!(plan.revision().to_record(), fixture["source"]);
        assert_eq!(plan.relation().to_record(), fixture["relation"]);
        assert_eq!(plan.manifest(), fixture["manifest"]);
        assert!(plan.manifest().get("actor").is_none());
        assert!(plan.relation().to_record().get("created_at").is_none());
    }

    #[test]
    fn exact_reads_budget_both_immutable_trees_without_raising_document_caps() {
        use std::os::fd::AsFd;
        let root=CutRoot::new();
        let fixture:Value=serde_json::from_str(include_str!("../../tests/application/fixtures/frozen_strategy.json")).unwrap();
        let strategy=fixture["source"]["strategy_fingerprint"].as_str().unwrap();
        let relation=fixture["relation"]["relation_fingerprint"].as_str().unwrap();
        for (tree,id,value) in [("frozen-revisions",strategy,&fixture["manifest"]),("freeze-relations",relation,&fixture["relation"])] {
            let path=root.0.join("strategy").join(tree).join("sha256").join(&id[..2]).join(id);
            std::fs::create_dir_all(&path).unwrap();std::fs::write(path.join("manifest.json"),serde_json::to_vec(value).unwrap()).unwrap();
        }
        let descriptor=protected_files::open_directory(&root.0).unwrap();let store=FrozenStore::open(descriptor.as_fd()).unwrap();
        assert_eq!(store.load_verified(strategy,DOCUMENT_WORK).unwrap_err(),Error::Unavailable);
        assert_eq!(store.load_relation_verified(relation,DOCUMENT_WORK).unwrap_err(),Error::Unavailable);
        assert_eq!(store.load_verified(strategy,64*1024*1024).unwrap().to_record(),fixture["source"]);
        assert_eq!(store.load_relation_verified(relation,64*1024*1024).unwrap().to_record(),fixture["relation"]);
    }
    #[test]
    fn substituted_evidence_cut_cannot_derive_a_publication_plan() {
        let root = CutRoot::new();
        let evidence = root.evidence();
        std::fs::rename(
            root.0.join(".source-cut.lock"),
            root.0.join("retained-lock"),
        )
        .unwrap();
        std::fs::write(root.0.join(".source-cut.lock"), b"").unwrap();
        std::fs::set_permissions(
            root.0.join(".source-cut.lock"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
        assert!(FrozenPlan::from_verified(&evidence).is_err());
    }
}

/// A publication plan borrows its owning evidence cut through the durable handoff.
/// SourceRevision parsing alone is deliberately insufficient to create this value.
#[derive(Clone,Copy)]
enum PlanEvidence<'a> {
    Research(&'a crate::persistence::research_evidence::VerifiedStrategyResearch),
    Manual(&'a crate::persistence::strategy_validation::VerifiedValidation),
}
pub(crate) struct FrozenPlan<'evidence> {
    evidence: PlanEvidence<'evidence>,
    relation: FreezeRelation,
}
impl<'evidence> FrozenPlan<'evidence> {
    pub(crate) fn from_verified(
        evidence: &'evidence crate::persistence::research_evidence::VerifiedStrategyResearch,
    ) -> Result<Self, Error> {
        evidence.verify_cut().map_err(|_| Error::Authority)?;
        if !crate::application::command::uuid4(evidence.run_id())
            || !is_sha256_hex(evidence.specification_fingerprint())
        {
            return Err(Error::Corrupt);
        }
        let mut record = json!({
            "schema_version":1,
            "strategy_fingerprint":evidence.source_revision().fingerprint(),
            "candidate_fingerprint":evidence.candidate_fingerprint(),
            "research_result_fingerprint":evidence.research_result_fingerprint(),
            "research_execution_evidence_fingerprints":evidence.research_execution_evidence_fingerprints(),
            "admission_evidence_fingerprint":evidence.admission_evidence_fingerprint(),
            "equivalence_evidence_fingerprints":evidence.equivalence_evidence_fingerprints()
        });
        let mut semantic = record.clone();
        semantic["domain"] = json!("onlyalpha.strategy.freeze-relation");
        record["relation_fingerprint"] = json!(record_fingerprint(&semantic));
        let relation = FreezeRelation::from_json(&record.to_string(), DOCUMENT_WORK)?;
        let plan = Self { evidence:PlanEvidence::Research(evidence), relation };
        if serde_json::to_vec(&plan.manifest())
            .map_err(|_| Error::Corrupt)?
            .len()
            > DOCUMENT_WORK
        {
            return Err(Error::Unavailable);
        }
        Ok(plan)
    }
    pub(crate) fn from_validation(evidence:&'evidence crate::persistence::strategy_validation::VerifiedValidation)->Result<Self,Error> {
        evidence.verify_cut().map_err(|_|Error::Authority)?;
        let mut record=json!({"schema_version":2,"strategy_fingerprint":evidence.source_revision().fingerprint(),
            "origin":{"kind":"MANUAL_BACKTEST","preparation_command_id":evidence.preparation_command_id(),
                "strategy_validation_fingerprint":evidence.fingerprint(),"private_strategy_id":evidence.private_strategy_id(),
                "private_strategy_revision_fingerprint":evidence.private_strategy_revision_fingerprint()}});
        let mut semantic=record.clone();semantic["domain"]=json!("onlyalpha.strategy.freeze-relation");
        record["relation_fingerprint"]=json!(record_fingerprint(&semantic));
        let relation=FreezeRelation::from_json(&record.to_string(),DOCUMENT_WORK)?;
        let plan=Self{evidence:PlanEvidence::Manual(evidence),relation};
        if serde_json::to_vec(&plan.manifest()).map_err(|_|Error::Corrupt)?.len()>DOCUMENT_WORK{return Err(Error::Unavailable);}
        Ok(plan)
    }
    pub(crate) fn research_evidence(&self)->Option<&'evidence crate::persistence::research_evidence::VerifiedStrategyResearch> {
        match self.evidence {PlanEvidence::Research(v)=>Some(v),PlanEvidence::Manual(_)=>None}
    }
    pub(crate) fn manual_evidence(&self)->Option<&'evidence crate::persistence::strategy_validation::VerifiedValidation> {
        match self.evidence {PlanEvidence::Manual(v)=>Some(v),PlanEvidence::Research(_)=>None}
    }
    pub(crate) fn revision(&self) -> &SourceRevision {
        match self.evidence {PlanEvidence::Research(v)=>v.source_revision(),PlanEvidence::Manual(v)=>v.source_revision()}
    }
    pub(crate) fn relation(&self) -> &FreezeRelation {
        &self.relation
    }
    pub(crate) fn manifest(&self) -> Value {
        json!({"schema_version":1,"strategy_fingerprint":self.revision().fingerprint(),"revision":self.revision().to_record()})
    }
    pub(crate) fn verify_cut(&self) -> Result<(), Error> {
        match self.evidence {PlanEvidence::Research(v)=>v.verify_cut(),PlanEvidence::Manual(v)=>v.verify_cut()}.map_err(|_|Error::Authority)
    }
}
impl FrozenStore {
    fn publication_capability(
        &self,
        prepared: &crate::application::strategy_projection::PreparedFreeze,
        plan: &FrozenPlan<'_>,
    ) -> Result<(), Error> {
        if !prepared.matches(plan)
            || self.namespace().map_err(|_| Error::Authority)? != *prepared.namespace()
        {
            return Err(Error::Authority);
        }
        plan.verify_cut()
    }
    /// Only the original durable PREPARED Command can lend this opaque capability.
    pub(crate) fn publish_relation(
        &self,
        prepared: &crate::application::strategy_projection::PreparedFreeze,
        plan: &FrozenPlan<'_>,
        max_work: usize,
    ) -> Result<(), Error> {
        use std::os::fd::AsFd;
        self.publication_capability(prepared, plan)?;
        self.read_all(max_work)?;
        let id = plan.relation().fingerprint();
        crate::security::immutable_json::put_at(
            self.research.as_fd(),
            &["strategy", "freeze-relations", "sha256", &id[..2], id],
            "manifest.json",
            &plan.relation().to_record(),
        )
        .map_err(|e| {
            if e == "IMMUTABLE_JSON_INVALID" {
                Error::Corrupt
            } else {
                Error::Unavailable
            }
        })?;
        self.publication_capability(prepared, plan)?;
        let actual = self.read_all(max_work)?;
        if actual.relations().get(id) != Some(plan.relation()) {
            return Err(Error::Corrupt);
        }
        Ok(())
    }
    pub(crate) fn publish_revision(
        &self,
        prepared: &crate::application::strategy_projection::PreparedFreeze,
        plan: &FrozenPlan<'_>,
        max_work: usize,
    ) -> Result<(), Error> {
        use std::os::fd::AsFd;
        self.publication_capability(prepared, plan)?;
        // Relation-first is enforced here as well as by the Command sequence.
        let before = self.read_all(max_work)?;
        if before.relations().get(plan.relation().fingerprint()) != Some(plan.relation()) {
            return Err(Error::Corrupt);
        }
        let id = plan.revision().fingerprint();
        // Every inventory Source has already been validated against its Strategy
        // identity. Reusing that identity preserves the first immutable record,
        // including presentation aliases, instead of publishing another encoding.
        let expected = before.revisions().get(id).unwrap_or(plan.revision());
        if !before.revisions().contains_key(id) {
            crate::security::immutable_json::put_at(
                self.research.as_fd(),
                &["strategy", "frozen-revisions", "sha256", &id[..2], id],
                "manifest.json",
                &plan.manifest(),
            )
            .map_err(|e| {
                if e == "IMMUTABLE_JSON_INVALID" {
                    Error::Corrupt
                } else {
                    Error::Unavailable
                }
            })?;
        }
        self.publication_capability(prepared, plan)?;
        let actual = self.read_all(max_work)?;
        if actual.revisions().get(id) != Some(expected) {
            return Err(Error::Corrupt);
        }
        Ok(())
    }
}

#[cfg(test)]
mod manual_relation_tests {
    use super::*;
    fn relation()->Value {json!({"schema_version":2,"strategy_fingerprint":"a".repeat(64),
        "origin":{"kind":"MANUAL_BACKTEST","preparation_command_id":"00000000-0000-4000-8000-000000008881",
            "strategy_validation_fingerprint":"b".repeat(64),"private_strategy_id":"private.strategy.btc_momentum",
            "private_strategy_revision_fingerprint":"c".repeat(64)},
        "relation_fingerprint":"b1c4d481c5e43e25debbaec6eec94e26e317f9acef4787780d011e120af6f81a"})}
    fn resign(value:&mut Value){let mut identity=value.clone();identity.as_object_mut().unwrap().remove("relation_fingerprint");identity["domain"]=json!("onlyalpha.strategy.freeze-relation");value["relation_fingerprint"]=json!(record_fingerprint(&identity));}
    #[test]
    fn manual_relation_binds_the_original_validation_without_fabricated_research() {
        let raw=relation();let parsed=FreezeRelation::from_json(&raw.to_string(),64*1024*1024).unwrap();
        assert_eq!(parsed.fingerprint(),"b1c4d481c5e43e25debbaec6eec94e26e317f9acef4787780d011e120af6f81a");
        assert_eq!(parsed.to_record(),raw);
        let mut another=raw.clone();another["origin"]["preparation_command_id"]=json!("00000000-0000-4000-8000-000000008882");resign(&mut another);
        assert_ne!(FreezeRelation::from_json(&another.to_string(),64*1024*1024).unwrap().fingerprint(),parsed.fingerprint());
        assert!(raw.get("research_result_fingerprint").is_none());
    }
    #[test]
    fn rehashed_manual_relation_rejects_wrong_identity_or_origin_fields() {
        for index in 0..8 {
            let mut raw=relation();match index {
                0=>raw["origin"]["kind"]=json!("RESEARCH"),
                1=>raw["origin"]["preparation_command_id"]=json!("b".repeat(64)),
                2=>raw["origin"]["private_strategy_id"]=json!("private.factor.btc_momentum"),
                3=>raw["origin"]["strategy_validation_fingerprint"]=json!("latest"),
                4=>raw["origin"]["private_strategy_revision_fingerprint"]=json!("latest"),
                5=>raw["research_result_fingerprint"]=json!("d".repeat(64)),
                6=>raw["origin"]["approved"]=json!(true),
                _=>{raw["origin"].as_object_mut().unwrap().remove("private_strategy_id");},
            }resign(&mut raw);assert!(FreezeRelation::from_json(&raw.to_string(),64*1024*1024).is_err(),"mutation {index}");
        }
    }
}

/// Only this owning read binds a genuine completed mathematical validation to
/// its exact immutable Frozen relation and the first stored Strategy encoding.
/// Parsing a SourceRevision, relation JSON or an APPROVED DTO grants no proof.
pub(crate) struct VerifiedManualBacktestEvidence {
    validation:std::sync::Arc<crate::persistence::strategy_validation::VerifiedValidation>,
    source:SourceRevision,relation:FreezeRelation,frozen:FrozenStore,
    namespace:crate::bootstrap::deployment::SemanticStoreId,
    files:Vec<crate::persistence::research_evidence::strategy::physical::Witness>,
}
impl VerifiedManualBacktestEvidence {
    pub(crate) fn validated_calculations(&self)->std::result::Result<&Value,&'static str> {
        self.verify_cut()?;Ok(&self.validation.record()["prepared_inputs"])
    }
    pub(crate) fn subject_strategy_fingerprint(&self)->&str {self.source.fingerprint()}
    pub(crate) fn validation_fingerprint(&self)->&str {self.validation.fingerprint()}
    pub(crate) fn freeze_relation_fingerprint(&self)->&str {self.relation.fingerprint()}
    pub(crate) fn preparation_command_id(&self)->&str {self.validation.preparation_command_id()}
    pub(crate) fn source_locks(&self)->Vec<std::sync::Arc<crate::security::immutable_json::SourceLock>> {self.validation.source_locks()}
    pub(crate) fn verify_cut(&self)->std::result::Result<(),&'static str> {
        self.validation.verify_cut()?;
        if self.files.is_empty()||self.frozen.namespace().map_err(|e|e.code())?!=self.namespace{return Err("STRATEGY_CORRUPT");}
        for witness in &self.files {witness.verify()?;}
        self.validation.verify_cut()
    }
    pub(crate) async fn require_running_parent_in_transaction(&self,tx:&tokio_postgres::Transaction<'_>,namespace:&crate::bootstrap::deployment::SemanticStoreId,actor:&str)->std::result::Result<(),&'static str> {
        if namespace!=&self.namespace{return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");}
        self.verify_cut()?;
        crate::persistence::research_preparation::require_running_manual_backtest_parent(tx,namespace,&self.validation,actor).await?;
        self.verify_cut()
    }
    pub(crate) async fn verify_in_transaction(&self,tx:&tokio_postgres::Transaction<'_>,namespace:&crate::bootstrap::deployment::SemanticStoreId)->std::result::Result<(),&'static str> {
        if namespace!=&self.namespace{return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");}
        self.verify_cut()?;self.validation.verify_in_transaction(tx,namespace).await?;self.verify_cut()
    }
}
impl FrozenStore {
    /// The Validation reader already retains its exact publication barriers.
    /// No additional lock is acquired, including while Source owns an EX cut.
    pub(crate) fn read_verified_manual(&self,validation:std::sync::Arc<crate::persistence::strategy_validation::VerifiedValidation>,relation_id:&str,max_work:usize)->Result<VerifiedManualBacktestEvidence,Error> {
        use crate::{persistence::research_evidence::strategy::physical::{document,exact_files},security::immutable_json::Directory};
        use std::{os::fd::AsFd,path::Path};
        validation.verify_cut().map_err(|_|Error::Authority)?;
        let plan=FrozenPlan::from_validation(&validation)?;
        if plan.relation().fingerprint()!=relation_id{return Err(Error::Corrupt);}
        let source=self.load_verified(plan.revision().fingerprint(),max_work)?;
        let relation=self.load_relation_verified(relation_id,max_work)?;
        if relation!=*plan.relation(){return Err(Error::Corrupt);}
        let namespace=self.namespace().map_err(|_|Error::Authority)?;
        if validation.record()["prepared_inputs"]["semantic_store_id"]!=namespace.value(){return Err(Error::Authority);}
        let locks=validation.source_locks();
        let owner=locks.iter().find(|lock|lock.directory.path.ends_with(Path::new("backtest/strategy-validation"))).ok_or(Error::Authority)?;
        let path=owner.directory.path.parent().and_then(Path::parent).ok_or(Error::Corrupt)?.to_path_buf();
        // Verify that the selected Frozen fd is the Validation's physical root,
        // rather than reopening another directory with the same namespace JSON.
        let root=Directory{path,fd:protected_files::duplicate_directory(self.research.as_fd())?};
        root.verify().map_err(|_|Error::Authority)?;
        let mut files=Vec::new();
        if document(&root,".onlyalpha-semantic-store.json",&mut files).map_err(|_|Error::Corrupt)?!=json!({"schema_version":1,"store_id":namespace.value()}){return Err(Error::Corrupt);}
        let id=source.fingerprint();
        let revision_root=root.path(&["strategy","frozen-revisions","sha256",&id[..2],id],false).map_err(|_|Error::Corrupt)?;
        exact_files(&revision_root,&["manifest.json"]).map_err(|_|Error::Corrupt)?;
        if document(&revision_root,"manifest.json",&mut files).map_err(|_|Error::Corrupt)?!=json!({"schema_version":1,"strategy_fingerprint":id,"revision":source.to_record()}){return Err(Error::Corrupt);}
        let relation_root=root.path(&["strategy","freeze-relations","sha256",&relation_id[..2],relation_id],false).map_err(|_|Error::Corrupt)?;
        exact_files(&relation_root,&["manifest.json"]).map_err(|_|Error::Corrupt)?;
        if document(&relation_root,"manifest.json",&mut files).map_err(|_|Error::Corrupt)?!=relation.to_record(){return Err(Error::Corrupt);}
        let frozen=FrozenStore::open(self.research.as_fd())?;
        let proof=VerifiedManualBacktestEvidence{validation,source,relation,frozen,namespace,files};
        proof.verify_cut().map_err(|_|Error::Authority)?;Ok(proof)
    }
}
