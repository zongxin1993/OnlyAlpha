//! Immutable evaluator-owned Qualification Decision1 facts (ADR 0118).
//! Publication never grants progression, Runtime admission or LIVE authority.
use crate::{
    application::{
        backtest_run::VerifiedRun,
        frozen_strategy::FrozenStore,
        job_contract::{JobKind, MemberKind},
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        backtest_run,
        build_fact_read::BuildFactRead,
        job_publication::PublishedJobResult,
        strategy_promotion::{self, BacktestAdmissionSelection, VerifiedBacktestHistory},
    },
};
use crate::{
    application::{
        factor_content::hash,
        frozen_strategy::VerifiedManualBacktestEvidence,
        qualification_policy::{
            BacktestQualificationMetrics, EvaluatedDecision, Policy, Store as Policies,
            canonical_plain_decimal,
        },
    },
    persistence::research_evidence::VerifiedResearchCounts,
    security::immutable_json::{Directory, SourceLock, inspect_source_layout, put_at, read_path},
};
use onlyalpha_domain::numeric::OnlyDecimal;
use serde_json::Value;
use std::{os::fd::AsFd, path::Path, sync::Arc};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "QUALIFICATION_DECISION_CORRUPT";
const UNAVAILABLE: &str = "QUALIFICATION_DECISION_UNAVAILABLE";
const WORK: usize = 64 * 1024 * 1024;

// Pure extraction from an already authenticated owning record. These helpers
// neither verify a PG proof nor manufacture a qualification/execution grant.
fn decision_record(value: &Value) -> Result<&Value> {
    if value["schema_version"] != 1
        || !value["decision_graph"].is_object()
        || !value["signal_semantics"].is_object()
        || !value["decision_graph_fingerprint"]
            .as_str()
            .is_some_and(crate::is_sha256_hex)
    {
        return Err(INVALID);
    }
    Ok(value)
}
fn research_decision(prepared: &Value) -> Result<&Value> {
    decision_record(&prepared["build_certification"]["context"]["decision"])
}
pub(super) fn manual_decision(prepared: &Value) -> Result<&Value> {
    let decision = decision_record(&prepared["decision"])?;
    if prepared.get("build_certification").is_some() && research_decision(prepared)? != decision {
        return Err(INVALID);
    }
    Ok(decision)
}

/// Closed owning evidence set; no copied JSON can implement an approval source.
#[derive(Clone)]
pub(crate) enum Evidence {
    Research(Arc<VerifiedResearchCounts>),
    Manual(Arc<VerifiedManualBacktestEvidence>),
    Backtest(Arc<VerifiedBacktestEvidence>),
}
impl Evidence {
    pub(crate) fn verify_cut(&self) -> Result<()> {
        match self {
            Self::Research(v) => v.verify_cut(),
            Self::Manual(v) => v.verify_cut(),
            Self::Backtest(v) => v.verify_cut(),
        }
    }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> {
        match self {
            Self::Research(v) => v.source_locks(),
            Self::Manual(v) => v.source_locks(),
            Self::Backtest(v) => v.source_locks(),
        }
    }
    pub(crate) fn evaluate(&self, policy: &Policy) -> Result<EvaluatedDecision> {
        match self {
            Self::Research(v) => policy.evaluate_research_counts(v),
            Self::Manual(v) => policy.evaluate_manual_validation(v),
            Self::Backtest(v) => policy.evaluate_backtest_evidence(v),
        }
    }
    pub(crate) fn matches(
        &self,
        request: &crate::application::qualification::Request,
    ) -> Result<()> {
        match self {
            Self::Research(v) => request.matches_counts(v),
            Self::Manual(v) => request.matches_manual(v),
            Self::Backtest(v) => request.matches_backtest(v),
        }
    }
    pub(crate) async fn require_running_parent_in_transaction(
        &self,
        tx: &crate::persistence::build_fact_read::BuildFactRead<'_, '_>,
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
        tx: &BuildFactRead<'_, '_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
    ) -> Result<()> {
        self.verify_cut()?;
        match self {
            Self::Research(v) => v.verify_in_transaction(tx, namespace).await?,
            Self::Manual(v) => v.verify_in_transaction(tx, namespace).await?,
            Self::Backtest(v) => v.verify_in_transaction(tx, namespace).await?,
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
    pub(crate) fn load_backtest_verified_captured(
        self: &Arc<Self>,
        policies: Arc<Policies>,
        evidence: &Arc<VerifiedBacktestEvidence>,
        id: &str,
        cut: Arc<SourceLock>,
    ) -> Result<VerifiedDecision> {
        self.load_evidence_captured(policies, Evidence::Backtest(evidence.clone()), id, cut)
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
        tx: &BuildFactRead<'_, '_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
        runtime_root: &Path,
        id: &str,
    ) -> Result<Arc<VerifiedDecision>> {
        if &self.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        let locks = [Arc::new(SourceLock::publication(&self.directory.path)?)];
        let mut verification = super::research_evidence::SourceVerification::new(&locks)
            .with_runtime_root(Some(runtime_root.to_path_buf()));
        verification
            .verify_qualification_in_transaction(&self.directory.path,id,tx)
            .await?;
        let decision = verification
            .qualification_cuts()
            .into_iter()
            .find(|proof| proof.fingerprint() == id)
            .ok_or(INVALID)?;
        if &decision.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        decision.verify_cut()?;
        crate::bootstrap::deployment::verify_binding_in_transaction(tx, namespace)
            .await
            .map_err(|e| e.code())?;
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

fn parse_member_json(
    publication: &PublishedJobResult,
    key: &str,
    kind: MemberKind,
) -> Result<Value> {
    let raw = publication.content(key).ok_or(INVALID)?;
    let value: Value = serde_json::from_str(raw).map_err(|_| INVALID)?;
    if value["schema_version"] != 1 || value["kind"] != serde_json::json!(kind) {
        return Err(INVALID);
    }
    Ok(value)
}

fn parse_optional_decimal(object: &Value, key: &str) -> Result<Option<String>> {
    match object.get(key) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(raw)) => Ok(Some(canonical_plain_decimal(raw).map_err(|_| INVALID)?)),
        _ => Err(INVALID),
    }
}

fn parse_required_decimal(object: &Value, key: &str) -> Result<String> {
    match object.get(key) {
        Some(Value::String(raw)) => canonical_plain_decimal(raw).map_err(|_| INVALID),
        _ => Err(INVALID),
    }
}

fn extract_backtest_metrics_from_values(
    sample_rows: u64,
    close_curve_point_count: u64,
    economics: &Value,
) -> Result<BacktestQualificationMetrics> {
    if close_curve_point_count != sample_rows {
        return Err(INVALID);
    }
    let result = &economics["economic_result"];
    if result["run"]["status"] != "COMPLETED" {
        return Err(INVALID);
    }
    let execution = &result["execution"];
    let summary = &result["runtime_performance"]["summary"];
    if summary["authority"] != "ACCOUNT" {
        return Err(INVALID);
    }
    let valuation_count = summary["valuation_count"].as_u64().ok_or(INVALID)?;
    let order_count = execution["order_count"].as_u64().ok_or(INVALID)?;
    let fill_count = execution["trade_count"].as_u64().ok_or(INVALID)?;
    let roundtrip_count = economics["roundtrip_count"].as_u64().ok_or(INVALID)?;
    let return_since_start = parse_optional_decimal(summary, "return_since_start")?;
    let maximum_drawdown = parse_optional_decimal(summary, "maximum_drawdown")?;
    if let Some(ref drawdown) = maximum_drawdown {
        let parsed = drawdown.parse::<OnlyDecimal>().map_err(|_| INVALID)?;
        let zero = "0".parse::<OnlyDecimal>().map_err(|_| INVALID)?;
        if parsed > zero {
            return Err(INVALID);
        }
    }
    Ok(BacktestQualificationMetrics {
        close_curve_point_count,
        valuation_count,
        order_count,
        fill_count,
        roundtrip_count,
        return_since_start,
        maximum_drawdown,
        net_pnl: parse_required_decimal(summary, "net_pnl")?,
        realized_pnl: parse_required_decimal(summary, "realized_pnl")?,
        unrealized_pnl: parse_required_decimal(summary, "unrealized_pnl")?,
        fees: parse_required_decimal(summary, "fees")?,
        final_equity: parse_required_decimal(summary, "final_equity")?,
    })
}

fn extract_backtest_metrics(
    publication: &PublishedJobResult,
) -> Result<BacktestQualificationMetrics> {
    if publication.binding().kind() != JobKind::Backtest {
        return Err(INVALID);
    }
    let sample_rows = publication.binding().record()["market"]["sample_rows"]
        .as_u64()
        .ok_or(INVALID)?;
    let mut curve_rows = 0_u64;
    for key in publication.member_keys(MemberKind::CloseCurve) {
        let member = parse_member_json(publication, key, MemberKind::CloseCurve)?;
        let rows = member["rows"].as_array().ok_or(INVALID)?;
        let count = u64::try_from(rows.len()).map_err(|_| INVALID)?;
        curve_rows = curve_rows.checked_add(count).ok_or(INVALID)?;
    }
    let mut econ_keys = publication.member_keys(MemberKind::EconomicResult);
    let econ_key = econ_keys.next().ok_or(INVALID)?;
    if econ_keys.next().is_some() {
        return Err(INVALID);
    }
    let econ_member = parse_member_json(publication, econ_key, MemberKind::EconomicResult)?;
    let economics = econ_member.get("body").filter(|v| v.is_object()).ok_or(INVALID)?;
    extract_backtest_metrics_from_values(sample_rows, curve_rows, economics)
}

/// 精确 PG 发布和原回测准入的联合证明。私有字段只由完整核验构造。
pub(crate) struct VerifiedBacktestEvidence {
    run: VerifiedRun,
    history: VerifiedBacktestHistory,
    publication: PublishedJobResult,
    metrics: BacktestQualificationMetrics,
}
impl VerifiedBacktestEvidence {
    pub(crate) fn run_id(&self) -> &str { self.run.run_id() }
    pub(crate) fn owner(&self) -> &str { self.run.owner() }
    pub(crate) fn subject_strategy_fingerprint(&self) -> &str { self.history.strategy_fingerprint() }
    pub(crate) fn evidence_fingerprint(&self) -> &str { self.publication.fingerprint() }
    pub(crate) fn freeze_relation_fingerprint(&self) -> &str { self.history.freeze_relation_fingerprint() }
    pub(crate) fn qualification_decision_fingerprint(&self) -> &str { self.history.qualification_decision_fingerprint() }
    pub(crate) fn promotion_fingerprint(&self) -> &str { self.history.promotion_fingerprint() }
    pub(crate) fn metrics(&self) -> &BacktestQualificationMetrics { &self.metrics }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> { Vec::new() }
    pub(crate) fn validated_decision(&self) -> Result<&Value> { self.history.validated_decision() }
    pub(crate) fn validated_calculations(&self) -> Result<&Value> { self.history.validated_calculations() }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        self.history.verify_cut()?;
        if self.history.is_manual() || self.run.namespace() != self.history.namespace() { return Err(INVALID); }
        Ok(())
    }
    pub(crate) async fn verify_in_transaction(&self, tx: &BuildFactRead<'_, '_>, namespace: &SemanticStoreId) -> Result<()> {
        if self.history.namespace() != namespace { return Err("RESEARCH_SEMANTIC_STORE_MISMATCH"); }
        self.verify_cut()?;
        let reloaded = backtest_run::load_in_transaction(tx, namespace, self.run.run_id()).await?;
        if reloaded.resolution() != self.run.resolution() || reloaded.completion_fingerprints() != self.run.completion_fingerprints() { return Err(INVALID); }
        let storage = tx.read_backtest_publication(namespace, &self.run).await.map_err(|error| error.code())?;
        let publication = storage.verify(tx).await.map_err(|error| error.code())?;
        let fp = publication.fingerprint();
        if fp != self.publication.fingerprint()
            || reloaded.completion_fingerprints() != Some((fp, fp, fp))
            || extract_backtest_metrics(&publication)? != self.metrics
        {
            return Err(INVALID);
        }
        self.verify_cut()
    }
}

pub(crate) async fn read_backtest_evidence(
    decisions: &Arc<Store>,
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    runtime_root: &Path,
    run_id: &str,
    expected_owner: Option<&str>,
    expected_strategy: Option<&str>,
) -> Result<Arc<VerifiedBacktestEvidence>> {
    let run = backtest_run::load_in_transaction(tx, namespace, run_id).await?;
    if let Some(owner) = expected_owner
        && run.owner() != owner
    {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    let strategy = pinned(run.resolution(), "strategy_fingerprint")?;
    if let Some(expected) = expected_strategy
        && strategy != expected
    {
        return Err("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH");
    }
    // The retained locator names the first-segment RESEARCH_TO_BACKTEST decision.
    // Reopen only that gate: the generic verifier dispatches BACKTEST_TO_SIM back here.
    let _ = runtime_root;
    let decision = read_research_admission(decisions, tx, namespace, text(run.resolution(), "qualification_decision_fingerprint")?).await?;
    let history = strategy_promotion::read_verified_history_in_transaction(tx, namespace, Arc::new(FrozenStore::open(decisions.research.fd.as_fd()).map_err(|error| error.code())?), decision, BacktestAdmissionSelection {
        strategy,
        relation: text(run.resolution(), "freeze_relation_fingerprint")?,
        promotion: text(run.resolution(), "promotion_fingerprint")?,
        max_work: WORK,
    }).await?;
    let storage = tx.read_backtest_publication(namespace, &run).await.map_err(|error| error.code())?;
    let publication = storage.verify(tx).await.map_err(|error| error.code())?;
    let fp = publication.fingerprint();
    if run.completion_fingerprints() != Some((fp, fp, fp)) {
        return Err(INVALID);
    }
    let metrics = extract_backtest_metrics(&publication)?;
    let proof = Arc::new(VerifiedBacktestEvidence { run, history, publication, metrics });
    proof.verify_cut()?;
    Ok(proof)
}

impl Store {
    pub(crate) async fn read_backtest_evidence(
        self: &Arc<Self>, metadata: &mut tokio_postgres::Client, facts: &mut tokio_postgres::Client, namespace: &SemanticStoreId,
        runtime_root: &Path, run_id: &str, owner: &str,
    ) -> Result<Arc<VerifiedBacktestEvidence>> {
        let tx = metadata.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_| UNAVAILABLE)?;
        let facts_tx = facts.build_transaction().read_only(true).start().await.map_err(|_| UNAVAILABLE)?;
        let context = BuildFactRead::reader(&tx, &facts_tx, namespace).await.map_err(|_| UNAVAILABLE)?;
        let proof = read_backtest_evidence(self, &context, namespace, runtime_root, run_id, Some(owner), None).await?;
        facts_tx.commit().await.map_err(|_| UNAVAILABLE)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok(proof)
    }
}
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key].as_str().ok_or(INVALID)
}
fn pinned<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    let value = text(value, key)?;
    if crate::is_sha256_hex(value) { Ok(value) } else { Err(INVALID) }
}
fn exact_fields(value: &Value, keys: &[&str]) -> Result<()> {
    let object = value.as_object().ok_or(INVALID)?;
    if object.len() == keys.len() && keys.iter().all(|key| object.contains_key(*key)) { Ok(()) } else { Err(INVALID) }
}

/// Reopen the exact RESEARCH_TO_BACKTEST decision named by a backtest admission.
/// This never enters the generic source verifier, whose BACKTEST_TO_SIM branch
/// reads backtest evidence and would recurse into the caller.
async fn read_research_admission(
    decisions: &Arc<Store>, tx: &BuildFactRead<'_, '_>, namespace: &SemanticStoreId, id: &str,
) -> Result<Arc<VerifiedDecision>> {
    use crate::application::qualification_policy::Store as Policies;
    use crate::persistence::research_evidence::ResearchPublication;
    if &decisions.namespace()? != namespace { return Err("RESEARCH_SEMANTIC_STORE_MISMATCH"); }
    let source = Arc::new(SourceLock::publication(&decisions.directory.path)?);
    let candidate = decisions.source_candidate(id, &source)?;
    if candidate["gate"] != "RESEARCH_TO_BACKTEST" { return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH"); }
    let rows = candidate["evidence"].as_array().filter(|rows| rows.len() == 1).ok_or(INVALID)?;
    let evidence = &rows[0];
    exact_fields(evidence, &["kind", "evidence_fingerprint", "locator_fingerprint", "subject_binding_fingerprint"])?;
    if evidence["kind"] != "RESEARCH_RESULT" { return Err("NOVELTY_PROOF_UNAVAILABLE"); }
    let result = pinned(evidence, "evidence_fingerprint")?;
    let plan = pinned(evidence, "locator_fingerprint")?;
    let relation = pinned(evidence, "subject_binding_fingerprint")?;
    let subject = pinned(&candidate, "subject_strategy_fingerprint")?;
    let original = crate::application::strategy_projection::freeze_research_locators_in_transaction(tx, namespace, None, subject, relation)
        .await?.into_iter().next().ok_or("NOVELTY_PROOF_UNAVAILABLE")?;
    let run = crate::persistence::research_submission::load_in_transaction(tx, &original.run_id, Some(&original.owner)).await?;
    if !run.completed() { return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED"); }
    let published = tx.read_research_publication(namespace, &run).await.map_err(|error| error.code())?;
    let publication = ResearchPublication::from_published(&run, published).map_err(|error| error.code())?;
    if publication.candidate_fingerprint() != original.candidate { return Err(INVALID); }
    let frozen = Arc::new(FrozenStore::open(decisions.research.fd.as_fd()).map_err(|error| error.code())?);
    let counts = Arc::new(VerifiedResearchCounts::from_publication(publication, frozen, relation)?);
    if counts.subject_strategy_fingerprint() != subject
        || counts.research_result_fingerprint() != result
        || counts.research_result_plan_fingerprint() != plan
        || counts.freeze_relation_fingerprint() != relation
    {
        return Err(INVALID);
    }
    let policies = Arc::new(Policies::open(decisions.research.fd.as_fd()).map_err(|error| error.code())?);
    let decision = Arc::new(decisions.load_verified_captured(policies, &counts, id, source)?);
    if decision.record() != &candidate { return Err(INVALID); }
    decision.verify_cut()?;
    if &decision.namespace()? != namespace { return Err("RESEARCH_SEMANTIC_STORE_MISMATCH"); }
    Ok(decision)
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
    /// Original mathematical decision selected by the closed evidence owner.
    /// Research and manual validation retain deliberately different wire shapes.
    pub(crate) fn validated_decision(&self) -> Result<&Value> {
        self.verify_cut()?;
        match &self.evidence {
            Evidence::Research(v) => research_decision(v.validated_calculations()?),
            Evidence::Manual(v) => manual_decision(v.validated_calculations()?),
            Evidence::Backtest(v) => v.validated_decision(),
        }
    }
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        match &self.evidence {
            Evidence::Research(v) => v.validated_calculations(),
            Evidence::Manual(v) => v.validated_calculations(),
            Evidence::Backtest(v) => v.validated_calculations(),
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
    pub(crate) fn backtest_evidence(&self) -> Option<&Arc<VerifiedBacktestEvidence>> {
        match &self.evidence {
            Evidence::Backtest(v) => Some(v),
            _ => None,
        }
    }
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &BuildFactRead<'_, '_>,
        namespace: &crate::bootstrap::deployment::SemanticStoreId,
    ) -> Result<()> {
        if &self.namespace()? != namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        self.verify_cut()?;
        self.evidence.verify_in_transaction(tx,namespace).await?;
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
#[path = "../tests/qualification_decision_inputs.rs"]
mod decision_input_tests;

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
