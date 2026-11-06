//! Immutable evaluator-owned Qualification Decision1 facts (ADR 0118).
//! Publication never grants progression, Runtime admission or LIVE authority.
use crate::{
    application::{
        factor_content::hash,
        frozen_strategy::VerifiedManualBacktestEvidence,
        qualification_policy::{EvaluatedDecision, Policy, Store as Policies},
    },
    persistence::research_evidence::VerifiedResearchCounts,
    security::immutable_json::{Directory, SourceLock, inspect_source_layout, put_at, read_path},
};
use serde_json::Value;
use std::{os::fd::AsFd, path::Path, sync::Arc};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "QUALIFICATION_DECISION_CORRUPT";
const UNAVAILABLE: &str = "QUALIFICATION_DECISION_UNAVAILABLE";
const WORK: usize = 64 * 1024 * 1024;

/// Closed owning evidence set; no copied JSON can implement an approval source.
#[derive(Clone)]
pub(crate) enum Evidence {
    Research(Arc<VerifiedResearchCounts>),
    Manual(Arc<VerifiedManualBacktestEvidence>),
}
impl Evidence {
    pub(crate) fn verify_cut(&self) -> Result<()> {
        match self {
            Self::Research(v) => v.verify_cut(),
            Self::Manual(v) => v.verify_cut(),
        }
    }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> {
        match self {
            Self::Research(v) => v.source_locks(),
            Self::Manual(v) => v.source_locks(),
        }
    }
    pub(crate) fn evaluate(&self, policy: &Policy) -> Result<EvaluatedDecision> {
        match self {
            Self::Research(v) => policy.evaluate_research_counts(v),
            Self::Manual(v) => policy.evaluate_manual_validation(v),
        }
    }
    pub(crate) fn matches(
        &self,
        request: &crate::application::qualification::Request,
    ) -> Result<()> {
        match self {
            Self::Research(v) => request.matches_counts(v),
            Self::Manual(v) => request.matches_manual(v),
        }
    }
    pub(crate) async fn require_running_parent_in_transaction(
        &self,
        tx: &tokio_postgres::Transaction<'_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        actor: &str,
    ) -> Result<()> {
        if let Self::Manual(proof) = self {
            proof
                .require_running_parent_in_transaction(tx, namespace, actor)
                .await?;
        }
        Ok(())
    }
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &tokio_postgres::Transaction<'_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
    ) -> Result<()> {
        self.verify_cut()?;
        if let Self::Manual(v) = self {
            v.verify_in_transaction(tx, namespace).await?;
        }
        self.verify_cut()
    }
}
pub struct Store {
    directory: Directory,
    research: Directory,
}
impl Store {
    pub fn open(research: &Path) -> Result<Self> {
        let path = research.join("strategy/qualification-decisions");
        inspect_source_layout(&path).map_err(|_| UNAVAILABLE)?;
        let directory = Directory::open(&path)?;
        directory.child("sha256", false)?;
        Ok(Self {
            directory,
            research: Directory::open(research)?,
        })
    }
    /// The evaluator consumes only proofs produced by an owning evidence reader.
    pub(crate) fn publish_evidence(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        id: &str,
        version: &str,
        evidence: Evidence,
    ) -> Result<VerifiedDecision> {
        evidence.verify_cut()?;
        let policy = policies
            .load_exact(id, version, WORK)
            .map_err(|e| e.code())?;
        let decision = evidence.evaluate(&policy)?;
        let record = decision.to_record();
        let cut = Arc::new(SourceLock::publication(&self.directory.path)?);
        let fingerprint = decision.fingerprint();
        put_at(
            self.directory.fd.as_fd(),
            &["sha256", &fingerprint[..2], fingerprint],
            "manifest.json",
            &record,
        )?;
        cut.verify()?;
        evidence.verify_cut()?;
        self.load_evidence_captured(policies, evidence, fingerprint, cut)
    }
    pub(crate) fn load_verified(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        counts: &Arc<VerifiedResearchCounts>,
        id: &str,
    ) -> Result<VerifiedDecision> {
        self.load_evidence(policies, Evidence::Research(counts.clone()), id)
    }
    pub(crate) fn load_evidence(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        evidence: Evidence,
        id: &str,
    ) -> Result<VerifiedDecision> {
        evidence.verify_cut()?;
        let cut = Arc::new(SourceLock::publication(&self.directory.path)?);
        self.load_evidence_captured(policies, evidence, id, cut)
    }
    /// Reuse the original Source-owned barrier; no receipt prerequisite for a Q fact.
    pub(crate) fn load_verified_captured(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        counts: &Arc<VerifiedResearchCounts>,
        id: &str,
        cut: Arc<SourceLock>,
    ) -> Result<VerifiedDecision> {
        self.load_evidence_captured(policies, Evidence::Research(counts.clone()), id, cut)
    }
    pub(crate) fn load_manual_verified_captured(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        evidence: &Arc<VerifiedManualBacktestEvidence>,
        id: &str,
        cut: Arc<SourceLock>,
    ) -> Result<VerifiedDecision> {
        self.load_evidence_captured(policies, Evidence::Manual(evidence.clone()), id, cut)
    }
    fn load_evidence_captured(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        evidence: Evidence,
        id: &str,
        cut: Arc<SourceLock>,
    ) -> Result<VerifiedDecision> {
        evidence.verify_cut()?;
        let record = self.source_candidate(id, &cut)?;
        let policy = policies
            .load_exact(
                text(&record, "policy_id")?,
                text(&record, "policy_version")?,
                WORK,
            )
            .map_err(|e| e.code())?;
        if evidence.evaluate(&policy)?.to_record() != record {
            return Err(INVALID);
        }
        let mut locks = evidence.source_locks();
        locks.push(cut);
        let sealed = VerifiedDecision {
            record,
            policy,
            policies,
            store: self.clone(),
            evidence,
            locks,
        };
        sealed.verify_cut()?;
        Ok(sealed)
    }
    /// Reopen either exact evidence origin through the existing source verifier.
    /// Its immutable inventories are locators; the retained proof authenticates owners.
    pub(crate) async fn read_verified_in_transaction(
        self: &Arc<Self>,
        tx: &tokio_postgres::Transaction<'_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        runtime_root: &Path,
        id: &str,
    ) -> Result<Arc<VerifiedDecision>> {
        if &self.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        let evidence = super::research_evidence::Store::open(&self.research.path)?;
        let mut locks = evidence
            .locks()?
            .into_iter()
            .map(Arc::new)
            .collect::<Vec<_>>();
        locks.push(Arc::new(SourceLock::publication(&self.directory.path)?));
        let mut verification = super::research_evidence::SourceVerification::new(&locks)
            .with_runtime_root(Some(runtime_root.to_path_buf()));
        verification
            .verify_qualification_in_transaction(&self.directory.path, id, tx)
            .await?;
        let decision = verification
            .qualification_cuts()
            .into_iter()
            .find(|proof| proof.fingerprint() == id)
            .ok_or(INVALID)?;
        if &decision.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        decision.verify_in_transaction(tx, namespace).await?;
        Ok(decision)
    }
    pub(crate) fn namespace(&self) -> Result<crate::bootstrap::deployment::SemanticStoreId> {
        self.research.verify()?;
        crate::bootstrap::deployment::load_semantic_store_id_at(&self.research.fd)
            .map_err(|e| e.code())
    }
    /// A verified locator candidate only. SourceVerification must still obtain
    /// owning Counts and call load_verified_captured before using this fact.
    pub(crate) fn source_candidate(&self, id: &str, cut: &SourceLock) -> Result<Value> {
        if cut.directory.path != self.directory.path {
            return Err(INVALID);
        }
        cut.verify()?;
        let record = self.read_record(id)?;
        cut.verify()?;
        Ok(record)
    }
    fn read_record(&self, id: &str) -> Result<Value> {
        if !crate::is_sha256_hex(id) {
            return Err(INVALID);
        }
        let value = read_path(&self.directory, &["sha256", &id[..2], id], "manifest.json")?;
        let fields = [
            "schema_version",
            "subject_strategy_fingerprint",
            "gate",
            "policy_id",
            "policy_version",
            "policy_fingerprint",
            "evidence",
            "criterion_results",
            "outcome",
            "decision_fingerprint",
        ];
        if value
            .as_object()
            .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
            || value["schema_version"].as_u64() != Some(1)
            || value["decision_fingerprint"] != id
        {
            return Err(INVALID);
        }
        let mut identity = value.clone();
        identity
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("decision_fingerprint");
        identity["domain"] = serde_json::json!("onlyalpha.strategy.qualification-decision");
        if hash(&identity)? != id {
            return Err(INVALID);
        }
        Ok(value)
    }
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key].as_str().ok_or(INVALID)
}

/// Owning-read proof, retaining exact Policy, Decision and Research cuts.
/// It cannot be reconstructed from a DTO or a self-declared APPROVED value.
pub struct VerifiedDecision {
    record: Value,
    policy: Policy,
    policies: Arc<Policies>,
    store: Arc<Store>,
    locks: Vec<Arc<SourceLock>>,
    evidence: Evidence,
}
impl VerifiedDecision {
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        match &self.evidence {
            Evidence::Research(v) => v.validated_calculations(),
            Evidence::Manual(v) => v.validated_calculations(),
        }
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn fingerprint(&self) -> &str {
        self.record["decision_fingerprint"]
            .as_str()
            .expect("verified Decision identity")
    }
    pub fn verify_cut(&self) -> Result<()> {
        if self.locks.is_empty() {
            return Err(INVALID);
        }
        for lock in &self.locks {
            lock.verify()?;
        }
        self.evidence.verify_cut()?;
        if self.store.read_record(self.fingerprint())? != self.record
            || self
                .policies
                .load_exact(
                    text(&self.record, "policy_id")?,
                    text(&self.record, "policy_version")?,
                    WORK,
                )
                .map_err(|e| e.code())?
                != self.policy
            || self.evidence.evaluate(&self.policy)?.to_record() != self.record
        {
            return Err(INVALID);
        }
        Ok(())
    }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> {
        self.locks.clone()
    }
    pub(crate) fn manual_evidence(&self) -> Option<&Arc<VerifiedManualBacktestEvidence>> {
        match &self.evidence {
            Evidence::Manual(v) => Some(v),
            _ => None,
        }
    }
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &tokio_postgres::Transaction<'_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
    ) -> Result<()> {
        if &self.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        self.verify_cut()?;
        self.evidence.verify_in_transaction(tx, namespace).await?;
        self.verify_cut()
    }
    pub(crate) fn namespace(&self) -> Result<crate::bootstrap::deployment::SemanticStoreId> {
        let namespace = self.store.namespace()?;
        if self.policies.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        Ok(namespace)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::{
        factor_content::hash,
        qualification_policy::{Policy, Store as Policies},
    };
    use crate::persistence::research_evidence::VerifiedResearchCounts;
    use crate::security::{immutable_json::SourceLock, protected_files};
    use serde_json::{Value, json};
    use std::{
        os::{fd::AsFd, unix::fs::PermissionsExt},
        path::PathBuf,
        sync::Arc,
    };
    struct Root(PathBuf);
    impl Root {
        fn new() -> Self {
            let mut bytes = [0u8; 8];
            getrandom::fill(&mut bytes).unwrap();
            let path = std::env::temp_dir().canonicalize().unwrap().join(format!(
                "oa-qualification-{}",
                bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
            ));
            std::fs::create_dir(&path).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
            for relative in ["", "strategy/qualification-decisions"] {
                let directory = path.join(relative);
                std::fs::create_dir_all(&directory).unwrap();
                std::fs::write(directory.join(".source-cut.lock"), b"").unwrap();
                std::fs::set_permissions(
                    directory.join(".source-cut.lock"),
                    std::fs::Permissions::from_mode(0o600),
                )
                .unwrap();
            }
            std::fs::create_dir(path.join("strategy/qualification-decisions/sha256")).unwrap();
            Self(path)
        }
        fn policies(&self) -> Arc<Policies> {
            let mut value = json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST","missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
                {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
                {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
            let mut identity = value.clone();
            identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
            value["policy_fingerprint"] = json!(hash(&identity).unwrap());
            Policy::from_json(&value.to_string(), 8 * 1024 * 1024).unwrap();
            let path = self
                .0
                .join("strategy/qualification-policies/experimental-backtest/1");
            std::fs::create_dir_all(&path).unwrap();
            std::fs::write(
                path.join("manifest.json"),
                onlyalpha_metadata_json::canonical_json(&value.to_string(), 8 * 1024 * 1024)
                    .unwrap(),
            )
            .unwrap();
            let fd = protected_files::open_directory(&self.0).unwrap();
            Arc::new(Policies::open(fd.as_fd()).unwrap())
        }
        fn counts(&self, n: u64) -> Arc<VerifiedResearchCounts> {
            Arc::new(VerifiedResearchCounts::for_persistence_test(
                "a".repeat(64),
                "b".repeat(64),
                "c".repeat(64),
                "d".repeat(64),
                n,
                1,
                Arc::new(SourceLock::publication(&self.0).unwrap()),
            ))
        }
    }
    impl Drop for Root {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }
    #[test]
    fn evaluator_owned_decision1_publication_is_exact_put_once_and_replayable() {
        let root = Root::new();
        let policies = root.policies();
        let counts = root.counts(2);
        let store = Arc::new(Store::open(&root.0).unwrap());
        let first = store
            .publish_evidence(
                policies.clone(),
                "experimental-backtest",
                "1",
                Evidence::Research(counts.clone()),
            )
            .unwrap();
        assert_eq!(first.record()["outcome"], "APPROVED");
        assert_eq!(
            first.record()["evidence"][0]["subject_binding_fingerprint"],
            "d".repeat(64)
        );
        assert_eq!(
            store
                .publish_evidence(
                    policies.clone(),
                    "experimental-backtest",
                    "1",
                    Evidence::Research(counts.clone())
                )
                .unwrap()
                .record(),
            first.record()
        );
        assert_eq!(
            store
                .load_verified(policies, &counts, first.fingerprint())
                .unwrap()
                .record(),
            first.record()
        );
        first.verify_cut().unwrap();
        for key in ["actor", "recorded_at", "created_at", "host", "reason"] {
            assert!(first.record().get(key).is_none());
        }
    }
    #[test]
    fn rejected_decision_is_a_durable_fact_and_cannot_be_reinterpreted_as_approved() {
        let root = Root::new();
        let policies = root.policies();
        let store = Arc::new(Store::open(&root.0).unwrap());
        let counts = root.counts(1);
        let rejected = store
            .publish_evidence(
                policies.clone(),
                "experimental-backtest",
                "1",
                Evidence::Research(counts.clone()),
            )
            .unwrap();
        assert_eq!(rejected.record()["outcome"], "REJECTED");
        assert!(
            store
                .load_verified(policies, &root.counts(2), rejected.fingerprint())
                .is_err()
        );
    }
    #[test]
    fn corruption_or_replaced_source_cut_cannot_reseal_a_decision() {
        let root = Root::new();
        let policies = root.policies();
        let counts = root.counts(2);
        let store = Arc::new(Store::open(&root.0).unwrap());
        let value = store
            .publish_evidence(
                policies.clone(),
                "experimental-backtest",
                "1",
                Evidence::Research(counts.clone()),
            )
            .unwrap();
        let id = value.fingerprint();
        let path = root
            .0
            .join("strategy/qualification-decisions/sha256")
            .join(&id[..2])
            .join(id)
            .join("manifest.json");
        let original = std::fs::read(&path).unwrap();
        let mut changed: Value = serde_json::from_slice(&original).unwrap();
        changed["outcome"] = json!("REJECTED");
        std::fs::write(
            &path,
            onlyalpha_metadata_json::canonical_json(&changed.to_string(), 8 * 1024 * 1024).unwrap(),
        )
        .unwrap();
        assert!(value.verify_cut().is_err());
        assert!(store.load_verified(policies.clone(), &counts, id).is_err());
        std::fs::write(&path, original).unwrap();
        let lock = root.0.join(".source-cut.lock");
        std::fs::rename(&lock, root.0.join("old-lock")).unwrap();
        std::fs::write(&lock, b"").unwrap();
        std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(
            store
                .publish_evidence(
                    policies,
                    "experimental-backtest",
                    "1",
                    Evidence::Research(counts.clone())
                )
                .is_err()
        );
    }
}
