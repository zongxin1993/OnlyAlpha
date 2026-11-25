//! Evidence-backed append-only PostgreSQL Promotion owner (ADR 0118).
//! Portable records and a readable historical stage never grant Backtest or SIM work.
use crate::{
    application::{
        backtest_preparation::BacktestOrigin,
        backtest_run::VerifiedRun,
        command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
        factor_content::hash,
        frozen_strategy::{FreezeRelation, FrozenStore},
        strategy_promotion::{PromotionChain, PromotionRecord},
    },
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        authority_session::AuthoritySession,
        backtest_run::{self, RunState},
        postgres::{self, Commands, bounds},
        qualification_decision::VerifiedDecision,
        research_preparation,
    },
    security::{human_access, immutable_json::SourceLock},
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_strategy::SourceRevision;
use serde_json::{Value, json};
use std::sync::Arc;
use tokio_postgres::{Client, Transaction};
use super::build_fact_read::BuildFactRead;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PROMOTION_LEDGER_CORRUPT";
const UNAVAILABLE: &str = "PROMOTION_LEDGER_UNAVAILABLE";
const UNKNOWN: &str = "PROMOTION_COMMAND_OUTCOME_UNKNOWN";
const WORK: usize = 64 * 1024 * 1024;
const ROWS: usize = 8192;
/// Pure exact Human request; only the owning writer validates the actual Decision.
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct Request {
    command: CommandId,
    strategy: String,
    decision: String,
    policy: String,
    reason: String,
}
impl Request {
    pub(crate) fn new(
        command: CommandId,
        strategy: &str,
        decision: &str,
        policy: &str,
        reason: &str,
    ) -> Result<Self> {
        if [strategy, decision, policy]
            .iter()
            .any(|s| !crate::is_sha256_hex(s))
            || reason.trim().is_empty()
            || reason.len() > 4096
            || reason.contains('\0')
        {
            return Err("PROMOTION_REQUEST_INVALID");
        }
        Ok(Self {
            command,
            strategy: strategy.into(),
            decision: decision.into(),
            policy: policy.into(),
            reason: reason.into(),
        })
    }
    fn admission(&self, actor: &str, to_stage: &str) -> Result<Admission> {
        if actor.trim().is_empty() || actor.len() > 512 || actor.chars().any(char::is_control) {
            return Err("PROMOTION_ACCESS_DENIED");
        }
        Admission::new(self.command.clone(),CommandKind::PromoteStrategy,&hash(&json!({"strategy_fingerprint":self.strategy,"to_stage":to_stage,"qualification_decision_fingerprint":self.decision,"policy_fingerprint":self.policy,"decision":"APPROVED","reason":self.reason,"actor":actor}))?).map_err(|e|e.code())
    }
}
enum Failure {
    Known(&'static str),
    Uncertain(&'static str),
}
type Work<T> = std::result::Result<T, Failure>;
fn code(e: Failure) -> &'static str {
    match e {
        Failure::Known(v) | Failure::Uncertain(v) => v,
    }
}
fn uncertain(code: &'static str) -> Failure {
    Failure::Uncertain(code)
}
fn db(_: impl std::fmt::Debug) -> Failure {
    uncertain(UNAVAILABLE)
}
fn stage_guard(code: &'static str) -> Failure {
    match code {
        "MANUAL_BACKTEST_PREPARATION_NOT_RUNNING"
        | "MANUAL_BACKTEST_PREPARATION_OWNER_MISMATCH" => Failure::Known(code),
        _ => Failure::Uncertain(code),
    }
}
fn cmd(e: crate::application::command::Error) -> Failure {
    if e == crate::application::command::Error::Conflict {
        Failure::Known(e.code())
    } else {
        uncertain(e.code())
    }
}
#[derive(Clone, Copy)]
enum Progression<'a> {
    Backtest(&'a VerifiedDecision),
    Sim {
        history: &'a VerifiedBacktestHistory,
        backtest_run: &'a VerifiedRun,
        decision: &'a VerifiedDecision,
    },
}
impl<'a> Progression<'a> {
    fn target(self) -> &'static str {
        match self {
            Self::Backtest(_) => "BACKTEST",
            Self::Sim { .. } => "SIM",
        }
    }
    fn root_decision(self) -> &'a VerifiedDecision {
        match self {
            Self::Backtest(decision) => decision,
            Self::Sim { history, .. } => &history.decision,
        }
    }
    async fn cut(
        self,
        tx: &BuildFactRead<'_, '_>,
        namespace: &SemanticStoreId,
        actor: &str,
        subject: &str,
        relation: &FreezeRelation,
        required: Option<&str>,
    ) -> Result<PgCut> {
        match self {
            Self::Backtest(decision) => {
                read_cut_with_prefix(
                    tx,
                    namespace,
                    subject,
                    relation,
                    decision,
                    PromotionCutSelection {
                        required,
                        prefix: required,
                    },
                    WORK,
                )
                .await
            }
            Self::Sim {
                history,
                backtest_run,
                decision,
            } => read_sim_cut(
                tx,
                namespace,
                history,
                backtest_run,
                actor,
                decision,
                required,
                WORK,
            )
            .await
            .map(|(cut, _)| cut),
        }
    }
}

/// Product owner of qualified BACKTEST and SIM progression.
pub(crate) struct Promotions<'a> {
    session: &'a mut AuthoritySession,
    namespace: &'a SemanticStoreId,
    frozen: Arc<FrozenStore>,
    access: &'a human_access::Access,
    human: &'a human_access::Session,
    #[cfg(test)]
    stop: Option<String>,
}
impl<'a> Promotions<'a> {
    pub(crate) fn new(
        session: &'a mut AuthoritySession,
        namespace: &'a SemanticStoreId,
        frozen: Arc<FrozenStore>,
        access: &'a human_access::Access,
        human: &'a human_access::Session,
    ) -> Self {
        Self {
            session,
            namespace,
            frozen,
            access,
            human,
            #[cfg(test)]
            stop: None,
        }
    }
    fn actor(&self) -> Result<&str> {
        self.access
            .check_session(self.human)
            .map_err(|_| "PROMOTION_ACCESS_DENIED")?;
        self.human
            .subject_id()
            .map_err(|_| "PROMOTION_ACCESS_DENIED")
    }
    pub(crate) async fn promote(
        &mut self,
        request: &Request,
        decision: Arc<VerifiedDecision>,
        at: OnlyUtcDateTime,
    ) -> Result<PromotionRecord> {
        self.promote_step(request, Progression::Backtest(&decision), at).await
    }
    pub(crate) async fn promote_to_sim(
        &mut self,
        request: &Request,
        history: &VerifiedBacktestHistory,
        backtest_run: &VerifiedRun,
        decision: Arc<VerifiedDecision>,
        at: OnlyUtcDateTime,
    ) -> Result<PromotionRecord> {
        self.promote_step(
            request,
            Progression::Sim {
                history,
                backtest_run,
                decision: &decision,
            },
            at,
        )
        .await
    }
    async fn promote_step(
        &mut self,
        request: &Request,
        step: Progression<'_>,
        at: OnlyUtcDateTime,
    ) -> Result<PromotionRecord> {
        let actor = self.actor()?.to_owned();
        let admission = request.admission(&actor, step.target())?;
        let mut owned = self.session.take_ownership();
        let result = self
            .promote_owned(&mut owned, request, &actor, &admission, step, at)
            .await;
        match result {
            Err(Failure::Uncertain(code)) => {
                let _ = owned.close().await;
                Err(code)
            }
            result => {
                owned.verify().await.map_err(|e| e.code())?;
                self.session.restore_ownership(owned);
                result.map_err(code)
            }
        }
    }
    async fn promote_owned(
        &self,
        owned: &mut AuthoritySession,
        request: &Request,
        actor: &str,
        admission: &Admission,
        step: Progression<'_>,
        at: OnlyUtcDateTime,
    ) -> Work<PromotionRecord> {
        let roles=owned.control_roles().map_err(db)?;
        let tx = owned
            .client_mut()
            .await
            .map_err(db)?
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::Serializable)
            .start()
            .await
            .map_err(db)?;
        transaction(&tx, self.namespace).await.map_err(uncertain)?;
        Commands::lock_command(&tx, &request.command)
            .await
            .map_err(cmd)?;
        let binding = Commands::verify_binding_in_transaction(&tx, &request.command)
            .await
            .map_err(cmd)?;
        let accepted = match binding {
            Binding::Accepted(receipt) => {
                if receipt.admission() != admission
                    || receipt.outcome().kind() != OutcomeKind::StrategyPromotion
                {
                    return Err(Failure::Known("PRODUCT_COMMAND_CONFLICT"));
                }
                Some(receipt)
            }
            Binding::Admitted(a) if a != *admission => {
                return Err(Failure::Known("PRODUCT_COMMAND_CONFLICT"));
            }
            Binding::Admitted(_) => return Err(uncertain(UNKNOWN)),
            Binding::None => None,
        };
        let new_admission = accepted.is_none();
        if new_admission
            && let Progression::Backtest(backtest_decision) = step
            && let Some(proof) = backtest_decision.manual_evidence()
        {
            proof
                .require_running_parent_in_transaction(&crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles), self.namespace, actor)
                .await
                .map_err(stage_guard)?;
        }
        // The catalog row is the one writer serialization point for this chain.
        if tx.query_opt("SELECT strategy_fingerprint FROM public.strategy_catalog WHERE strategy_fingerprint=$1 FOR UPDATE",&[&request.strategy]).await.map_err(db)?.is_none(){return Err(Failure::Known("STRATEGY_NOT_FOUND"));}
        decision_request(self.namespace, actor, request, step).map_err(|e| match e {
            "QUALIFICATION_DECISION_POLICY_MISMATCH"
            | "QUALIFICATION_DECISION_NOT_APPROVED"
            | "QUALIFICATION_DECISION_SUBJECT_MISMATCH"
            | "QUALIFICATION_EVIDENCE_GATE_MISMATCH"
            | "ILLEGAL_PROMOTION_TRANSITION"
            | "BACKTEST_ACCESS_DENIED" => Failure::Known(e),
            "QUALIFIED_PROMOTION_PROOF_REQUIRED" if new_admission => Failure::Known(e),
            _ => uncertain(e),
        })?;
        let relation_id = step.root_decision().record()["evidence"][0]["subject_binding_fingerprint"]
            .as_str()
            .ok_or_else(|| uncertain(INVALID))?;
        if let Progression::Sim { history, .. } = step
            && relation_id != history.freeze_relation_fingerprint()
        {
            return Err(uncertain(INVALID));
        }
        let source = self
            .frozen
            .load_verified(&request.strategy, WORK)
            .map_err(|e| uncertain(e.code()))?;
        let relation = self
            .frozen
            .load_relation_verified(relation_id, WORK)
            .map_err(|e| uncertain(e.code()))?;
        files(
            self.namespace,
            &self.frozen,
            step.root_decision(),
            &source,
            &relation,
            WORK,
        )
        .map_err(uncertain)?;
        let required = accepted.as_ref().map(|r| r.outcome().id());
        let before = step
            .cut(
                &BuildFactRead::control(&tx, &roles),
                self.namespace,
                actor,
                &request.strategy,
                &relation,
                required,
            )
            .await
            .map_err(|e| {
                if new_admission
                    && matches!(e, "ILLEGAL_PROMOTION_TRANSITION" | "BACKTEST_ACCESS_DENIED")
                {
                    Failure::Known(e)
                } else {
                    uncertain(e)
                }
            })?;
        let (record, expected) = if let Some(receipt) = accepted {
            let record = before
                .chain
                .iter()
                .find(|r| r.fingerprint() == receipt.outcome().id())
                .ok_or_else(|| uncertain(INVALID))?
                .clone();
            if record.record()["actor"] != actor
                || record.record()["reason"] != request.reason
                || record.record()["to_stage"] != step.target()
                || record.record()["qualification_decision_fingerprint"] != request.decision
                || public_time(receipt.accepted_at()) != record.record()["recorded_at"]
            {
                return Err(uncertain(INVALID));
            }
            (record, before)
        } else {
            let chain = PromotionChain::from_records(&request.strategy, before.chain.clone())
                .map_err(uncertain)?;
            let (precursor, to_stage, schema, evidence, origin) = match step {
                Progression::Backtest(decision) => {
                    let manual = decision.manual_evidence();
                    let precursor = if manual.is_some() {
                        "FROZEN"
                    } else {
                        "RESEARCH"
                    };
                    if (!chain.records().is_empty() && chain.stage() != precursor)
                        || (chain.records().is_empty() && chain.stage() != "FROZEN")
                    {
                        return Err(Failure::Known("ILLEGAL_PROMOTION_TRANSITION"));
                    }
                    let schema: i32 = if manual.is_some() { 3 } else { 2 };
                    let evidence = backtest_evidence_fingerprints(
                        &request.decision,
                        relation_id,
                        manual.map(|proof| proof.validation_fingerprint()),
                    );
                    let origin = manual.map(|proof| {
                        json!({"kind":"MANUAL_BACKTEST","strategy_validation_fingerprint":proof.validation_fingerprint()})
                    });
                    (precursor, "BACKTEST", schema, evidence, origin)
                }
                Progression::Sim { history, .. } => {
                    if history.is_manual()
                        || chain.stage() != "BACKTEST"
                        || chain.head_fingerprint() != Some(history.promotion_fingerprint())
                        || chain.records() != history.ledger.chain.as_slice()
                    {
                        return Err(Failure::Known("ILLEGAL_PROMOTION_TRANSITION"));
                    }
                    ("BACKTEST", "SIM", 2i32, vec![request.decision.clone()], None)
                }
            };
            let mut value = json!({"schema_version":schema,"strategy_fingerprint":request.strategy,"from_stage":precursor,"to_stage":to_stage,"evidence_fingerprints":evidence,"decision":"APPROVED","reason":request.reason,"actor":actor,"recorded_at":public_time(at),"previous_record_fingerprint":chain.head_fingerprint(),"qualification_decision_fingerprint":request.decision});
            if let Some(origin) = &origin {
                value["origin"] = origin.clone();
            }
            value["record_fingerprint"] = json!(hash(&value).map_err(uncertain)?);
            let record = PromotionRecord::from_record(&value).map_err(uncertain)?;
            let time = postgres::system_time(at).map_err(cmd)?;
            Commands::admit_exact_in_transaction(&tx, admission)
                .await
                .map_err(cmd)?;
            let origin = origin.map(|value| value.to_string());
            tx.execute("INSERT INTO public.strategy_promotion_record(promotion_record_fingerprint,strategy_fingerprint,from_stage,to_stage,evidence_fingerprints,previous_record_fingerprint,decision,reason,actor,recorded_at,schema_version,qualification_decision_fingerprint,origin) VALUES($1,$2,$3,$4,$5,$6,'APPROVED',$7,$8,$9,$10,$11,$12::pg_catalog.text::pg_catalog.jsonb)",&[&record.fingerprint(),&request.strategy,&precursor,&to_stage,&evidence,&chain.head_fingerprint(),&request.reason,&actor,&time,&schema,&request.decision,&origin]).await.map_err(db)?;
            let receipt = Receipt::new(
                admission.clone(),
                Outcome::new(OutcomeKind::StrategyPromotion, record.fingerprint()).map_err(cmd)?,
                &at.to_string(),
            )
            .map_err(cmd)?;
            Commands::put_verified_receipt_in_transaction(&tx, &receipt)
                .await
                .map_err(cmd)?;
            let mut expected = before;
            expected.chain.push(record.clone());
            expected.receipts.push(receipt_record(&receipt));
            (record, expected)
        };
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(db)?;
        let after = step
            .cut(
                &BuildFactRead::control(&tx, &roles),
                self.namespace,
                actor,
                &request.strategy,
                &relation,
                Some(record.fingerprint()),
            )
            .await
            .map_err(uncertain)?;
        if after != expected {
            return Err(uncertain(INVALID));
        }
        if new_admission
            && let Progression::Backtest(backtest_decision) = step
            && let Some(proof) = backtest_decision.manual_evidence()
        {
            proof
                .require_running_parent_in_transaction(&crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles), self.namespace, actor)
                .await
                .map_err(stage_guard)?;
        }
        let Binding::Accepted(receipt) =
            Commands::verify_binding_in_transaction(&tx, &request.command)
                .await
                .map_err(cmd)?
        else {
            return Err(uncertain(INVALID));
        };
        if receipt.admission() != admission
            || receipt.outcome().kind() != OutcomeKind::StrategyPromotion
            || receipt.outcome().id() != record.fingerprint()
            || public_time(receipt.accepted_at()) != record.record()["recorded_at"]
        {
            return Err(uncertain(INVALID));
        }
        files(
            self.namespace,
            &self.frozen,
            step.root_decision(),
            &source,
            &relation,
            WORK,
        )
        .map_err(uncertain)?;
        if let Progression::Sim {
            history,
            backtest_run,
            decision,
        } = step
        {
            history.verify_cut().map_err(uncertain)?;
            let evidence_fp = sim_decision_record(
                decision,
                history,
                Some(&request.policy),
                backtest_run,
            )
            .map_err(uncertain)?;
            verify_backtest_run_lineage(
                self.namespace,
                history,
                backtest_run,
                actor,
                evidence_fp,
            )
            .map_err(uncertain)?;
        }
        self.actor().map_err(Failure::Known)?;
        deployment::verify_binding_in_transaction(&tx, self.namespace)
            .await
            .map_err(|e| uncertain(e.code()))?;
        AuthoritySession::verify_transaction(&tx)
            .await
            .map_err(db)?;
        #[cfg(test)]
        self.checkpoint("before_commit")?;
        tx.commit().await.map_err(|_| uncertain(UNKNOWN))?;
        #[cfg(test)]
        self.checkpoint("after_commit")?;
        Ok(record)
    }
    #[cfg(test)]
    pub(crate) fn stop_at(&mut self, boundary: &str) -> Result<()> {
        if !["before_commit", "after_commit"].contains(&boundary) {
            return Err(INVALID);
        }
        self.stop = Some(boundary.into());
        Ok(())
    }
    #[cfg(test)]
    fn checkpoint(&self, value: &str) -> Work<()> {
        if self.stop.as_deref() == Some(value) {
            Err(uncertain(UNKNOWN))
        } else {
            Ok(())
        }
    }
}
fn decision_request(
    namespace: &SemanticStoreId,
    actor: &str,
    request: &Request,
    step: Progression<'_>,
) -> Result<()> {
    match step {
        Progression::Backtest(decision) => {
            decision.verify_cut()?;
            let record = decision.record();
            if decision.fingerprint() != request.decision
                || record["subject_strategy_fingerprint"] != request.strategy
            {
                return Err("QUALIFICATION_DECISION_SUBJECT_MISMATCH");
            }
            if record["outcome"] != "APPROVED" {
                return Err("QUALIFICATION_DECISION_NOT_APPROVED");
            }
            if record["gate"]
                != if decision.manual_evidence().is_some() {
                    "MANUAL_STRATEGY_TO_BACKTEST"
                } else {
                    "RESEARCH_TO_BACKTEST"
                }
            {
                return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
            }
            if record["policy_fingerprint"] != request.policy {
                return Err("QUALIFICATION_DECISION_POLICY_MISMATCH");
            }
            Ok(())
        }
        Progression::Sim {
            history,
            backtest_run,
            decision,
        } => {
            if history.namespace() != namespace || decision.namespace()? != *namespace {
                return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
            }
            if history.is_manual() {
                return Err("ILLEGAL_PROMOTION_TRANSITION");
            }
            if history.strategy_fingerprint() != request.strategy
                || decision.fingerprint() != request.decision
            {
                return Err("QUALIFICATION_DECISION_SUBJECT_MISMATCH");
            }
            if history.decision.record()["gate"] != "RESEARCH_TO_BACKTEST"
                || decision.fingerprint() == history.qualification_decision_fingerprint()
            {
                return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
            }
            history.verify_cut()?;
            let evidence_fp = sim_decision_record(
                decision,
                history,
                Some(&request.policy),
                backtest_run,
            )?;
            verify_backtest_run_lineage(namespace, history, backtest_run, actor, evidence_fp)
        }
    }
}
fn sim_decision_record<'a>(
    decision: &'a VerifiedDecision,
    history: &VerifiedBacktestHistory,
    expected_policy: Option<&str>,
    run: &VerifiedRun,
) -> Result<&'a str> {
    decision.verify_cut()?;
    let proof = decision
        .backtest_evidence()
        .ok_or("QUALIFICATION_EVIDENCE_GATE_MISMATCH")?;
    if proof.owner() != run.owner() {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    if proof.run_id() != run.run_id()
        || proof.subject_strategy_fingerprint() != history.strategy_fingerprint()
        || proof.freeze_relation_fingerprint() != history.freeze_relation_fingerprint()
        || proof.qualification_decision_fingerprint() != history.qualification_decision_fingerprint()
        || proof.promotion_fingerprint() != history.promotion_fingerprint()
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    verify_sim_decision_record(
        decision.record(),
        decision.fingerprint(),
        history.strategy_fingerprint(),
        history.freeze_relation_fingerprint(),
        proof.evidence_fingerprint(),
        expected_policy,
        run.run_id(),
    )?;
    Ok(proof.evidence_fingerprint())
}
fn verify_sim_decision_record(
    record: &Value,
    decision_fp: &str,
    strategy: &str,
    freeze_relation: &str,
    published_evidence: &str,
    expected_policy: Option<&str>,
    backtest_run_id: &str,
) -> Result<()> {
    if record["decision_fingerprint"] != decision_fp
        || record["subject_strategy_fingerprint"] != strategy
    {
        return Err("QUALIFICATION_DECISION_SUBJECT_MISMATCH");
    }
    if record["outcome"] != "APPROVED" {
        return Err("QUALIFICATION_DECISION_NOT_APPROVED");
    }
    if record["gate"] != "BACKTEST_TO_SIM" {
        return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
    }
    if let Some(policy) = expected_policy
        && record["policy_fingerprint"] != policy
    {
        return Err("QUALIFICATION_DECISION_POLICY_MISMATCH");
    }
    let [item] = record["evidence"].as_array().map(Vec::as_slice).unwrap_or_default() else {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    };
    if item["kind"] != "BACKTEST_EVIDENCE" {
        return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
    }
    if !crate::is_sha256_hex(published_evidence)
        || !crate::application::command::uuid4(backtest_run_id)
        || item != &json!({
            "kind": "BACKTEST_EVIDENCE",
            "evidence_fingerprint": published_evidence,
            "backtest_run_id": backtest_run_id,
            "subject_binding_fingerprint": freeze_relation,
        })
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    Ok(())
}
fn verify_backtest_run_lineage(
    namespace: &SemanticStoreId,
    history: &VerifiedBacktestHistory,
    run: &VerifiedRun,
    expected_owner: &str,
    evidence_fp: &str,
) -> Result<()> {
    if expected_owner.trim().is_empty() {
        return Err(INVALID);
    }
    if history.is_manual() {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    if history.namespace() != namespace || run.namespace() != namespace {
        return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
    }
    if run.owner() != expected_owner {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    verify_backtest_run_binding(
        namespace.value(),
        run.owner(),
        expected_owner,
        run.state(),
        run.completion_fingerprints(),
        run.resolution(),
        run.specification().record(),
        history.strategy_fingerprint(),
        history.freeze_relation_fingerprint(),
        history.qualification_decision_fingerprint(),
        history.promotion_fingerprint(),
        evidence_fp,
    )
}
#[allow(clippy::too_many_arguments)]
fn verify_backtest_run_binding(
    namespace: &str,
    run_owner: &str,
    expected_owner: &str,
    state: RunState,
    completion: Option<(&str, &str, &str)>,
    resolution: &Value,
    specification: &Value,
    strategy: &str,
    relation: &str,
    research_decision: &str,
    backtest_promotion: &str,
    evidence_fp: &str,
) -> Result<()> {
    if expected_owner.trim().is_empty() {
        return Err(INVALID);
    }
    if run_owner != expected_owner {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    if state != RunState::Completed {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    let Some((run_evidence, run_result, run_determinism)) = completion else {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    };
    if ![run_evidence, run_result, run_determinism]
        .iter()
        .all(|pin| crate::is_sha256_hex(pin))
        || run_evidence != evidence_fp
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    if resolution["semantic_store_id"] != namespace
        || resolution["strategy_fingerprint"] != strategy
        || resolution["freeze_relation_fingerprint"] != relation
        || resolution["qualification_decision_fingerprint"] != research_decision
        || resolution["promotion_fingerprint"] != backtest_promotion
        || specification["strategy_fingerprint"] != strategy
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    Ok(())
}
fn verify_research_backtest_origin(
    origin: &BacktestOrigin,
    validation_fingerprint: &Value,
    strategy: &str,
    relation: &str,
    research_decision: &str,
    backtest_promotion: &str,
) -> Result<()> {
    let BacktestOrigin::FrozenStrategy {
        strategy_fingerprint,
        freeze_relation_fingerprint,
        qualification_decision_fingerprint,
        promotion_fingerprint,
    } = origin
    else {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    };
    if strategy_fingerprint != strategy
        || freeze_relation_fingerprint != relation
        || qualification_decision_fingerprint != research_decision
        || promotion_fingerprint != backtest_promotion
        || !validation_fingerprint.is_null()
    {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    Ok(())
}
async fn verify_backtest_run_in_transaction(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    history: &VerifiedBacktestHistory,
    run: &VerifiedRun,
    expected_owner: &str,
    evidence_fp: &str,
) -> Result<Value> {
    verify_backtest_run_lineage(namespace, history, run, expected_owner, evidence_fp)?;
    let reloaded = backtest_run::load_in_transaction(tx, namespace, run.run_id()).await?;
    verify_backtest_run_lineage(namespace, history, &reloaded, expected_owner, evidence_fp)?;
    if reloaded.run_id() != run.run_id()
        || reloaded.owner() != run.owner()
        || reloaded.namespace() != run.namespace()
        || reloaded.specification_fingerprint() != run.specification_fingerprint()
        || reloaded.admission_resolution_fingerprint() != run.admission_resolution_fingerprint()
        || reloaded.completion_fingerprints() != run.completion_fingerprints()
        || reloaded.resolution() != run.resolution()
    {
        return Err(INVALID);
    }
    let operation = research_preparation::original_backtest_preparation(tx, &reloaded).await?;
    if operation.owner != reloaded.owner() {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    let input = operation.request.backtest()?;
    verify_research_backtest_origin(
        &input.origin,
        &operation.outputs["ready"]["validation_fingerprint"],
        history.strategy_fingerprint(),
        history.freeze_relation_fingerprint(),
        history.qualification_decision_fingerprint(),
        history.promotion_fingerprint(),
    )?;
    let (run_evidence, run_result, run_determinism) = reloaded
        .completion_fingerprints()
        .ok_or("QUALIFIED_PROMOTION_PROOF_REQUIRED")?;
    Ok(json!({
        "run_id": reloaded.run_id(),
        "owner": reloaded.owner(),
        "specification_fingerprint": reloaded.specification_fingerprint(),
        "admission_resolution_fingerprint": reloaded.admission_resolution_fingerprint(),
        "evidence_fingerprint": run_evidence,
        "result_fingerprint": run_result,
        "determinism_fingerprint": run_determinism,
        "preparation_command_id": operation.command.value(),
    }))
}
fn files(
    namespace: &SemanticStoreId,
    frozen: &FrozenStore,
    decision: &VerifiedDecision,
    source: &SourceRevision,
    relation: &FreezeRelation,
    max_work: usize,
) -> Result<()> {
    decision.verify_cut()?;
    if frozen.namespace().map_err(|e| e.code())? != *namespace
        || decision.namespace()? != *namespace
    {
        return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
    }
    let id = source.fingerprint();
    let record = decision.record();
    if record["subject_strategy_fingerprint"] != id
        || record["outcome"] != "APPROVED"
        || relation.strategy_fingerprint() != id
        || record["evidence"].as_array().is_none_or(|v| v.len() != 1)
        || record["evidence"][0]["subject_binding_fingerprint"] != relation.fingerprint()
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    if let Some(proof) = decision.manual_evidence() {
        proof.verify_cut()?;
        if record["gate"] != "MANUAL_STRATEGY_TO_BACKTEST"
            || record["evidence"][0]["kind"] != "STRATEGY_VALIDATION"
            || proof.subject_strategy_fingerprint() != id
            || proof.freeze_relation_fingerprint() != relation.fingerprint()
            || record["evidence"][0]["evidence_fingerprint"] != proof.validation_fingerprint()
            || record["evidence"][0]["preparation_command_id"] != proof.preparation_command_id()
        {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
    } else if record["gate"] != "RESEARCH_TO_BACKTEST"
        || record["evidence"][0]["kind"] != "RESEARCH_RESULT"
        || record["evidence"][0]["evidence_fingerprint"]
            != relation.to_record()["research_result_fingerprint"]
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    if frozen
        .load_verified(id, max_work)
        .map_err(|e| e.code())?
        .to_record()
        != source.to_record()
        || frozen
            .load_relation_verified(relation.fingerprint(), max_work)
            .map_err(|e| e.code())?
            .to_record()
            != relation.to_record()
    {
        return Err(INVALID);
    }
    Ok(())
}
/// Exact private PG cut, not a cache or a second Promotion ledger.
#[derive(Clone, PartialEq, Eq)]
struct PgCut {
    catalog: Value,
    freeze: Value,
    qualifications: Vec<Value>,
    chain: Vec<PromotionRecord>,
    receipts: Vec<Value>,
}
/// Only this exact owning read can seal a new Backtest admission. It retains all
/// original physical owners and both independent (FS and PG) proof obligations.
pub struct VerifiedBacktestAdmission {
    source: SourceRevision,
    namespace: SemanticStoreId,
    relation: String,
    decision: String,
    promotion: String,
    cut: Vec<Arc<SourceLock>>,
    verified_decision: Arc<VerifiedDecision>,
    frozen: Arc<FrozenStore>,
    freeze: FreezeRelation,
    ledger: PgCut,
    max_work: usize,
}
impl VerifiedBacktestAdmission {
    pub(crate) fn manual_validation_for_preparation(
        &self,
        command: &str,
    ) -> Option<Arc<crate::persistence::strategy_validation::VerifiedValidation>> {
        self.verified_decision
            .manual_evidence()
            .map(|proof| proof.validation())
            .filter(|validation| validation.preparation_command_id() == command)
            .cloned()
    }
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.verified_decision.validated_calculations()
    }
    pub fn source_revision(&self) -> &SourceRevision {
        &self.source
    }
    pub fn strategy_fingerprint(&self) -> &str {
        self.source.fingerprint()
    }
    pub fn freeze_relation_fingerprint(&self) -> &str {
        &self.relation
    }
    pub fn qualification_decision_fingerprint(&self) -> &str {
        &self.decision
    }
    pub fn promotion_fingerprint(&self) -> &str {
        &self.promotion
    }
    pub fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
    pub fn verify_cut(&self) -> Result<()> {
        if self.cut.is_empty() {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
        for cut in &self.cut {
            cut.verify()?;
        }
        files(
            &self.namespace,
            &self.frozen,
            &self.verified_decision,
            &self.source,
            &self.freeze,
            self.max_work,
        )
    }
    /// Called before new Backtest admission and after deferred effects in its
    /// existing guarded transaction. No new socket, write or blocking DB bridge.
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &BuildFactRead<'_, '_>,
        namespace: &SemanticStoreId,
    ) -> Result<()> {
        if namespace != &self.namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        self.verify_cut()?;
        bounds(tx).await.map_err(|e| e.code())?;
        deployment::verify_binding_in_transaction(tx, namespace)
            .await
            .map_err(|e| e.code())?;
        let actual = read_cut(
            tx,
            namespace,
            self.strategy_fingerprint(),
            &self.freeze,
            &self.verified_decision,
            Some(&self.promotion),
            self.max_work,
        )
        .await?;
        if actual != self.ledger {
            return Err(INVALID);
        }
        self.verify_cut()
    }
}
pub(crate) struct BacktestAdmissionSelection<'a> {
    pub(crate) strategy: &'a str,
    pub(crate) relation: &'a str,
    pub(crate) promotion: &'a str,
    pub(crate) max_work: usize,
}

pub(crate) struct SelectedBacktestAdmission<'a> {
    pub(crate) strategy: &'a str,
    pub(crate) relation: &'a str,
    pub(crate) decision: &'a str,
    pub(crate) promotion: &'a str,
    pub(crate) max_work: usize,
}

struct AdmissionSealContext<'a> {
    namespace: &'a SemanticStoreId,
    promotion: &'a str,
    max_work: usize,
}

struct PromotionCutSelection<'a> {
    required: Option<&'a str>,
    prefix: Option<&'a str>,
}

pub(crate) async fn read_verified_admission(
    client: &mut Client,
    facts: &mut Client,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decision: Arc<VerifiedDecision>,
    selection: BacktestAdmissionSelection<'_>,
) -> Result<VerifiedBacktestAdmission> {
    let BacktestAdmissionSelection {
        strategy,
        relation,
        promotion,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || [strategy, relation, promotion]
            .iter()
            .any(|v| !crate::is_sha256_hex(v))
    {
        return Err(INVALID);
    }
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let fact_tx = facts.build_transaction().read_only(true).start().await.map_err(|_|UNAVAILABLE)?;
    let context = BuildFactRead::reader(&tx,&fact_tx,namespace).await.map_err(|_|UNAVAILABLE)?;
    let sealed = admission_in_transaction(
        &context,
        namespace,
        frozen,
        decision,
        BacktestAdmissionSelection {
            strategy,
            relation,
            promotion,
            max_work,
        },
    )
    .await?;
    fact_tx.commit().await.map_err(|_|UNAVAILABLE)?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(sealed)
}
/// Exact Q/P observation on one owning snapshot, with the same bounded SQL
/// environment as standalone admission. No caller JSON can construct a proof.
pub(crate) async fn read_selected_admission_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decisions: Arc<super::qualification_decision::Store>,
    runtime_root: &std::path::Path,
    selection: SelectedBacktestAdmission<'_>,
) -> Result<VerifiedBacktestAdmission> {
    let SelectedBacktestAdmission {
        strategy,
        relation,
        decision,
        promotion,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || [strategy, relation, decision, promotion]
            .iter()
            .any(|id| !crate::is_sha256_hex(id))
    {
        return Err(INVALID);
    }
    transaction(tx, namespace).await?;
    let snapshot=tx.query_one("SELECT pg_catalog.current_setting('transaction_isolation')='repeatable read' AND pg_catalog.current_setting('transaction_read_only')='on'",&[]).await.map_err(|_|UNAVAILABLE)?;
    if !snapshot.try_get::<_, bool>(0).map_err(|_| UNAVAILABLE)? {
        return Err(UNAVAILABLE);
    }
    let decision = decisions
        .read_verified_in_transaction(tx, namespace, runtime_root, decision)
        .await?;
    let source = frozen
        .load_verified(strategy, max_work)
        .map_err(|e| e.code())?;
    let freeze = frozen
        .load_relation_verified(relation, max_work)
        .map_err(|e| e.code())?;
    files(namespace, &frozen, &decision, &source, &freeze, max_work)?;
    // The Q owner just verified this exact capability in this same read-only
    // snapshot. P still reads every original ledger/receipt relation itself.
    let ledger = read_promotion_cut_with_prefix(
        tx,
        namespace,
        strategy,
        &freeze,
        &decision,
        PromotionCutSelection {
            required: Some(promotion),
            prefix: None,
        },
        max_work,
    )
    .await?;
    seal_admission(
        tx,
        AdmissionSealContext {
            namespace,
            promotion,
            max_work,
        },
        frozen,
        decision,
        source,
        freeze,
        ledger,
    )
    .await
}
async fn admission_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decision: Arc<VerifiedDecision>,
    selection: BacktestAdmissionSelection<'_>,
) -> Result<VerifiedBacktestAdmission> {
    let BacktestAdmissionSelection {
        strategy,
        relation,
        promotion,
        max_work,
    } = selection;
    let source = frozen
        .load_verified(strategy, max_work)
        .map_err(|e| e.code())?;
    let freeze = frozen
        .load_relation_verified(relation, max_work)
        .map_err(|e| e.code())?;
    files(namespace, &frozen, &decision, &source, &freeze, max_work)?;
    let ledger = read_cut(
        tx,
        namespace,
        strategy,
        &freeze,
        &decision,
        Some(promotion),
        max_work,
    )
    .await?;
    seal_admission(
        tx,
        AdmissionSealContext {
            namespace,
            promotion,
            max_work,
        },
        frozen,
        decision,
        source,
        freeze,
        ledger,
    )
    .await
}
async fn seal_admission(
    tx: &Transaction<'_>,
    context: AdmissionSealContext<'_>,
    frozen: Arc<FrozenStore>,
    decision: Arc<VerifiedDecision>,
    source: SourceRevision,
    freeze: FreezeRelation,
    ledger: PgCut,
) -> Result<VerifiedBacktestAdmission> {
    let AdmissionSealContext {
        namespace,
        promotion,
        max_work,
    } = context;
    let relation = freeze.fingerprint().to_owned();
    let chain = PromotionChain::from_records(source.fingerprint(), ledger.chain.clone())?;
    if chain.stage() != "BACKTEST" {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    let row = ledger
        .chain
        .iter()
        .find(|r| r.fingerprint() == promotion)
        .ok_or(INVALID)?
        .record();
    qualified_backtest_record(row, &decision)?;
    let cut = decision.source_locks();
    let sealed = VerifiedBacktestAdmission {
        source,
        namespace: namespace.clone(),
        relation,
        decision: decision.fingerprint().into(),
        promotion: promotion.into(),
        cut,
        verified_decision: decision,
        frozen,
        freeze,
        ledger,
        max_work,
    };
    sealed.verify_cut()?;
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(|e| e.code())?;
    Ok(sealed)
}
/// Reuse the single canonical BACKTEST grant for an identical Strategy Revision.
/// A new validation occurrence does not authorize BACKTEST -> BACKTEST or change
/// the prior immutable Freeze, Qualification or Promotion identities.
pub(crate) async fn read_existing_backtest_admission_for_strategy(
    clients: (&mut Client, &mut Client),
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decisions: Arc<super::qualification_decision::Store>,
    runtime_root: &std::path::Path,
    strategy: &str,
    max_work: usize,
) -> Result<Option<VerifiedBacktestAdmission>> {
    let (client,facts) = clients;
    let max_work = max_work.min(WORK);
    if max_work == 0 || !crate::is_sha256_hex(strategy) {
        return Err(INVALID);
    }
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let chain = checked_ledger(&tx, namespace, strategy).await?;
    if chain.records().is_empty() {
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        return Ok(None);
    }
    if chain.stage() != "BACKTEST" {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    let selected = chain
        .records()
        .iter()
        .rev()
        .find(|record| {
            record.record()["to_stage"] == "BACKTEST" && record.record()["decision"] == "APPROVED"
        })
        .ok_or("QUALIFIED_PROMOTION_PROOF_REQUIRED")?;
    let decision_id = text(selected.record(), "qualification_decision_fingerprint")?;
    let fact_tx = facts.build_transaction().read_only(true).start().await.map_err(|_|UNAVAILABLE)?;
    let context = BuildFactRead::reader(&tx,&fact_tx,namespace).await.map_err(|_|UNAVAILABLE)?;
    let decision = decisions
        .read_verified_in_transaction(&context, namespace, runtime_root, decision_id)
        .await?;
    let relation = text(
        &decision.record()["evidence"][0],
        "subject_binding_fingerprint",
    )?
    .to_owned();
    let value = admission_in_transaction(
        &context,
        namespace,
        frozen,
        decision,
        BacktestAdmissionSelection {
            strategy,
            relation: &relation,
            promotion: selected.fingerprint(),
            max_work,
        },
    )
    .await?;
    fact_tx.commit().await.map_err(|_|UNAVAILABLE)?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(Some(value))
}
fn backtest_evidence_fingerprints(
    decision: &str,
    relation: &str,
    validation: Option<&str>,
) -> Vec<String> {
    let mut evidence = vec![decision.to_owned(), relation.to_owned()];
    evidence.extend(validation.map(str::to_owned));
    evidence.sort_unstable();
    evidence.dedup();
    evidence
}
fn qualified_backtest_record(row: &Value, decision: &VerifiedDecision) -> Result<()> {
    let reference = &decision.record()["evidence"][0];
    let validation = decision.manual_evidence().map(|proof| proof.validation_fingerprint());
    verify_backtest_record(
        row,
        decision.fingerprint(),
        text(reference, "subject_binding_fingerprint")?,
        validation,
    )
}
fn verify_backtest_record(
    row: &Value,
    decision: &str,
    relation: &str,
    validation: Option<&str>,
) -> Result<()> {
    if row["to_stage"] != "BACKTEST"
        || row["decision"] != "APPROVED"
        || row["qualification_decision_fingerprint"] != decision
        || row["evidence_fingerprints"] != json!(backtest_evidence_fingerprints(decision, relation, validation))
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    if let Some(validation) = validation {
        if row["schema_version"] != 3
            || row["from_stage"] != "FROZEN"
            || row["origin"]
                != json!({"kind":"MANUAL_BACKTEST","strategy_validation_fingerprint":validation})
        {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
    } else if row["schema_version"] != 2 || row["from_stage"] != "RESEARCH" {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    Ok(())
}
fn public_time(time: OnlyUtcDateTime) -> String {
    format!(
        "{}+00:00",
        time.to_string()
            .strip_suffix('Z')
            .expect("UTC Domain representation")
    )
}

fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or(INVALID)
}
fn date(v: &Value, key: &str) -> Result<OnlyUtcDateTime> {
    text(v, key)?.parse().map_err(|_| INVALID)
}
fn receipt_record(receipt: &Receipt) -> Value {
    json!({"command_id":receipt.admission().id().value(),"command_kind":receipt.admission().kind().as_str(),"command_fingerprint":receipt.admission().fingerprint(),"outcome_kind":receipt.outcome().kind().as_str(),"outcome_id":receipt.outcome().id(),"accepted_at":receipt.accepted_at().to_string()})
}
async fn transaction(tx: &Transaction<'_>, namespace: &SemanticStoreId) -> Result<()> {
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(|_| UNAVAILABLE)?;
    bounds(tx).await.map_err(|e| e.code())?;
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(|e| e.code())
}
struct Budget(usize);
impl Budget {
    fn take(&mut self, n: usize) -> Result<()> {
        self.0 = self.0.checked_sub(n).ok_or(UNAVAILABLE)?;
        Ok(())
    }
}
// A repeatable/serializable transaction keeps preflight and transfer on one cut.
// Null capped documents fail closed rather than being interpreted as absence.
async fn records(
    tx: &Transaction<'_>,
    sql: &str,
    key: &str,
    budget: &mut Budget,
) -> Result<Vec<Value>> {
    let preflight = format!(
        "SELECT pg_catalog.count(*),COALESCE(pg_catalog.sum(pg_catalog.octet_length(record)),0)::pg_catalog.text,COALESCE(pg_catalog.bool_and(record IS NOT NULL),TRUE) FROM ({sql}) selected"
    );
    let meta = tx
        .query_one(&preflight, &[&key])
        .await
        .map_err(|_| UNAVAILABLE)?;
    let count: i64 = meta.try_get(0).map_err(|_| INVALID)?;
    let bytes: usize = meta
        .try_get::<_, String>(1)
        .map_err(|_| INVALID)?
        .parse()
        .map_err(|_| UNAVAILABLE)?;
    if count < 0 || count as usize > ROWS || !meta.try_get::<_, bool>(2).map_err(|_| INVALID)? {
        return Err(UNAVAILABLE);
    }
    budget.take(
        bytes
            .checked_mul(3)
            .ok_or(UNAVAILABLE)?
            .checked_add(count as usize * 256)
            .ok_or(UNAVAILABLE)?,
    )?;
    let rows = tx.query(sql, &[&key]).await.map_err(|_| UNAVAILABLE)?;
    if rows.len() != count as usize {
        return Err(INVALID);
    }
    let mut result = Vec::new();
    for row in rows {
        let raw = row
            .try_get::<_, Option<String>>(0)
            .map_err(|_| INVALID)?
            .ok_or(INVALID)?;
        result.push(serde_json::from_str(&raw).map_err(|_| INVALID)?);
    }
    Ok(result)
}
async fn read_cut(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    subject: &str,
    relation: &FreezeRelation,
    decision: &VerifiedDecision,
    required: Option<&str>,
    max_work: usize,
) -> Result<PgCut> {
    read_cut_with_prefix(
        tx,
        namespace,
        subject,
        relation,
        decision,
        PromotionCutSelection {
            required,
            prefix: None,
        },
        max_work,
    )
    .await
}
async fn read_cut_with_prefix(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    subject: &str,
    relation: &FreezeRelation,
    decision: &VerifiedDecision,
    selection: PromotionCutSelection<'_>,
    max_work: usize,
) -> Result<PgCut> {
    let PromotionCutSelection { required, prefix } = selection;
    decision.verify_in_transaction(tx, namespace).await?;
    read_promotion_cut_with_prefix(
        tx,
        namespace,
        subject,
        relation,
        decision,
        PromotionCutSelection { required, prefix },
        max_work,
    )
    .await
}
async fn read_promotion_cut_with_prefix(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
    relation: &FreezeRelation,
    decision: &VerifiedDecision,
    selection: PromotionCutSelection<'_>,
    max_work: usize,
) -> Result<PgCut> {
    let PromotionCutSelection { required, prefix } = selection;
    let mut budget = Budget(max_work.min(WORK));
    let (catalog, chain) = if let Some(prefix) = prefix {
        read_ledger_prefix(tx, namespace, subject, prefix, &mut budget).await?
    } else {
        read_ledger(tx, namespace, subject, &mut budget).await?
    };
    let mut freeze=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(actor)<=512 AND pg_catalog.octet_length(COALESCE(comment,''))<=4096 AND COALESCE(pg_catalog.cardinality(research_execution_evidence_fingerprints),0)<=8192 AND COALESCE(pg_catalog.cardinality(equivalence_evidence_fingerprints),0)<=8192 THEN pg_catalog.to_jsonb(f)::pg_catalog.text ELSE NULL END AS record FROM public.strategy_freeze_record f WHERE freeze_record_fingerprint=$1 LIMIT 2",relation.fingerprint(),&mut budget).await?;
    if freeze.len() != 1 {
        return Err(INVALID);
    }
    let mut freeze = freeze.remove(0);
    let original = relation.to_record();
    if freeze["freeze_record_fingerprint"] != relation.fingerprint()
        || freeze["strategy_fingerprint"] != subject
        || text(&freeze, "actor")?.trim().is_empty()
    {
        return Err(INVALID);
    }
    if let Some(proof) = decision.manual_evidence() {
        if freeze["schema_version"] != 5
            || freeze["origin_kind"] != "MANUAL_BACKTEST"
            || freeze["preparation_command_id"] != proof.preparation_command_id()
            || freeze["strategy_validation_fingerprint"] != proof.validation_fingerprint()
            || original["schema_version"] != 2
            || original["origin"]["kind"] != "MANUAL_BACKTEST"
            || original["origin"]["preparation_command_id"] != proof.preparation_command_id()
            || original["origin"]["strategy_validation_fingerprint"]
                != proof.validation_fingerprint()
        {
            return Err(INVALID);
        }
        for field in [
            "candidate_fingerprint",
            "research_result_fingerprint",
            "admission_evidence_fingerprint",
            "research_execution_evidence_fingerprints",
            "equivalence_evidence_fingerprints",
        ] {
            if !freeze[field].is_null() {
                return Err(INVALID);
            }
        }
    } else {
        if freeze["schema_version"] != 4 {
            return Err(INVALID);
        }
        for field in [
            "candidate_fingerprint",
            "research_result_fingerprint",
            "admission_evidence_fingerprint",
            "research_execution_evidence_fingerprints",
            "equivalence_evidence_fingerprints",
        ] {
            if freeze[field] != original[field] {
                return Err(INVALID);
            }
        }
    }
    freeze["created_at"] = json!(date(&freeze, "created_at")?.to_string());
    let qualifications = qualification_cut(tx, decision, &mut budget).await?;
    let mut receipts = Vec::new();
    let mut found = required.is_none();
    for record in chain.records() {
        let selected = Some(record.fingerprint()) == required;
        found |= selected;
        verify_record_receipts(
            tx,
            subject,
            record,
            decision,
            "BACKTEST",
            selected,
            &mut budget,
            &mut receipts,
        )
        .await?;
    }
    if !found {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    Ok(PgCut {
        catalog,
        freeze,
        qualifications,
        chain: chain.records().to_vec(),
        receipts,
    })
}
#[allow(clippy::too_many_arguments)]
async fn verify_record_receipts(
    tx: &Transaction<'_>,
    subject: &str,
    record: &PromotionRecord,
    decision: &VerifiedDecision,
    expected_to_stage: &str,
    selected: bool,
    budget: &mut Budget,
    receipts: &mut Vec<Value>,
) -> Result<()> {
    let rows=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(command_fingerprint)=64 THEN pg_catalog.to_jsonb(r)::pg_catalog.text ELSE NULL END AS record FROM public.product_command_receipt r WHERE outcome_kind='STRATEGY_PROMOTION' AND outcome_id=$1 ORDER BY command_id LIMIT 8193",record.fingerprint(),budget).await?;
    let qualified = record.record()["schema_version"]
        .as_u64()
        .is_some_and(|v| v >= 2);
    if qualified {
        if record.record()["qualification_decision_fingerprint"] != decision.fingerprint()
            || record.record()["to_stage"] != expected_to_stage
            || rows.len() != 1
        {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
    } else if selected {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    for row in rows {
        let command = CommandId::new(text(&row, "command_id")?).map_err(|_| INVALID)?;
        let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(tx, &command)
            .await
            .map_err(|e| e.code())?
        else {
            return Err(INVALID);
        };
        if receipt.admission().kind() != CommandKind::PromoteStrategy
            || receipt.outcome().kind() != OutcomeKind::StrategyPromotion
            || receipt.outcome().id() != record.fingerprint()
            || public_time(receipt.accepted_at()) != record.record()["recorded_at"]
        {
            return Err(INVALID);
        }
        if qualified {
            let request = Request::new(
                command,
                subject,
                decision.fingerprint(),
                text(decision.record(), "policy_fingerprint")?,
                text(record.record(), "reason")?,
            )?;
            if receipt.admission()
                != &request.admission(text(record.record(), "actor")?, expected_to_stage)?
            {
                return Err(INVALID);
            }
        }
        receipts.push(receipt_record(&receipt));
    }
    Ok(())
}
/// Independently verifies both the Research-backed BACKTEST prefix and the
/// BACKTEST_TO_SIM successor on one consistent transaction snapshot.
#[allow(clippy::too_many_arguments)]
async fn read_sim_cut(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    history: &VerifiedBacktestHistory,
    backtest_run: &VerifiedRun,
    expected_owner: &str,
    sim_decision: &VerifiedDecision,
    required: Option<&str>,
    max_work: usize,
) -> Result<(PgCut, Value)> {
    read_sim_cut_mode(
        tx,
        namespace,
        history,
        backtest_run,
        expected_owner,
        sim_decision,
        required,
        max_work,
        false,
    )
    .await
}

async fn read_sim_cut_mode(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    history: &VerifiedBacktestHistory,
    backtest_run: &VerifiedRun,
    expected_owner: &str,
    sim_decision: &VerifiedDecision,
    required: Option<&str>,
    max_work: usize,
    fresh_in_tx: bool,
) -> Result<(PgCut, Value)> {
    if history.namespace() != namespace || sim_decision.namespace()? != *namespace {
        return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
    }
    if history.is_manual() {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    if history.decision.record()["gate"] != "RESEARCH_TO_BACKTEST" {
        return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
    }
    let evidence_fp = sim_decision_record(
        sim_decision,
        history,
        None,
        backtest_run,
    )?;
    if sim_decision.fingerprint() == history.qualification_decision_fingerprint() {
        return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
    }
    if fresh_in_tx {
        history.verify_cut()?;
        sim_decision.verify_cut()?;
    } else {
        history.verify_in_transaction(tx).await?;
    }
    if history.ledger.freeze["schema_version"] != 4 {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    if !fresh_in_tx {
        sim_decision.verify_in_transaction(tx, namespace).await?;
    }
    let backtest_proof = verify_backtest_run_in_transaction(
        tx,
        namespace,
        history,
        backtest_run,
        expected_owner,
        evidence_fp,
    )
    .await?;
    let mut budget = Budget(max_work.min(WORK));
    let sim_qualifications = qualification_cut(tx, sim_decision, &mut budget).await?;
    let (catalog, chain) =
        read_ledger(tx, namespace, history.strategy_fingerprint(), &mut budget).await?;
    if catalog != history.ledger.catalog {
        return Err(INVALID);
    }
    let mut qualifications = history.ledger.qualifications.clone();
    qualifications.extend(sim_qualifications);
    let mut receipts = history.ledger.receipts.clone();
    match required {
        None => {
            if chain.records() != history.ledger.chain.as_slice()
                || chain.stage() != "BACKTEST"
                || chain.head_fingerprint() != Some(history.promotion_fingerprint())
            {
                return Err("ILLEGAL_PROMOTION_TRANSITION");
            }
            if chain
                .sim_successor(
                    &history.ledger.chain,
                    history.promotion_fingerprint(),
                    sim_decision.fingerprint(),
                )?
                .is_some()
            {
                return Err("ILLEGAL_PROMOTION_TRANSITION");
            }
        }
        Some(sim_promotion) => {
            let Some(sim_record) = chain.sim_successor(
                &history.ledger.chain,
                history.promotion_fingerprint(),
                sim_decision.fingerprint(),
            )?
            else {
                return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
            };
            if sim_record.fingerprint() != sim_promotion {
                return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
            }
            verify_record_receipts(
                tx,
                history.strategy_fingerprint(),
                sim_record,
                sim_decision,
                "SIM",
                true,
                &mut budget,
                &mut receipts,
            )
            .await?;
        }
    }
    Ok((
        PgCut {
            catalog,
            freeze: history.ledger.freeze.clone(),
            qualifications,
            chain: chain.records().to_vec(),
            receipts,
        },
        backtest_proof,
    ))
}
async fn qualification_cut(
    tx: &Transaction<'_>,
    decision: &VerifiedDecision,
    budget: &mut Budget,
) -> Result<Vec<Value>> {
    let mut rows=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(evidence_payload::pg_catalog.text)<=65536 THEN pg_catalog.to_jsonb(q)::pg_catalog.text ELSE NULL END AS record FROM public.qualification_command_admission q WHERE decision_fingerprint=$1 ORDER BY command_id LIMIT 8193",decision.fingerprint(),budget).await?;
    if rows.is_empty() {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    for row in &mut rows {
        let command = CommandId::new(text(row, "command_id")?).map_err(|_| INVALID)?;
        let request = crate::application::qualification::Request::new(
            command.clone(),
            text(row, "subject_strategy_fingerprint")?,
            text(row, "policy_id")?,
            text(row, "policy_version")?,
            &row["evidence_payload"],
        )?;
        if row["state"] != "COMPLETED"
            || row["schema_version"] != 1
            || row["command_fingerprint"] != request.fingerprint()?
            || row["subject_strategy_fingerprint"]
                != decision.record()["subject_strategy_fingerprint"]
            || row["policy_id"] != decision.record()["policy_id"]
            || row["policy_version"] != decision.record()["policy_version"]
            || row["evidence_payload"] != decision.record()["evidence"]
        {
            return Err(INVALID);
        }
        let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(tx, &command)
            .await
            .map_err(|e| e.code())?
        else {
            return Err(INVALID);
        };
        if receipt.admission().kind() != CommandKind::EvaluateQualification
            || receipt.admission().fingerprint() != request.fingerprint()?
            || receipt.outcome().kind() != OutcomeKind::QualificationDecision
            || receipt.outcome().id() != decision.fingerprint()
            || receipt.accepted_at() != date(row, "completed_at")?
        {
            return Err(INVALID);
        }
        row["prepared_at"] = json!(date(row, "prepared_at")?.to_string());
        row["completed_at"] = json!(date(row, "completed_at")?.to_string());
        row["receipt"] = receipt_record(&receipt);
    }
    Ok(rows)
}

async fn read_ledger(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
    budget: &mut Budget,
) -> Result<(Value, PromotionChain)> {
    let catalog = read_catalog(tx, namespace, subject, budget).await?;
    let raw=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(reason)<=4096 AND pg_catalog.octet_length(actor)<=512 AND pg_catalog.cardinality(evidence_fingerprints)<=8192 THEN pg_catalog.to_jsonb(p)::pg_catalog.text ELSE NULL END AS record FROM public.strategy_promotion_record p WHERE strategy_fingerprint=$1 ORDER BY promotion_record_fingerprint COLLATE pg_catalog.\"C\" LIMIT 8193",subject,budget).await?;
    let chain = decode_chain(subject, raw)?;
    Ok((catalog, chain))
}

/// Canonical ledger/receipt projection only; this grants no admission and does
/// not reopen Counts or source programs. Historical schema1 remains readable.
async fn checked_ledger(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
) -> Result<PromotionChain> {
    if !crate::is_sha256_hex(subject) {
        return Err("PROMOTION_REQUEST_INVALID");
    }
    let mut budget = Budget(WORK);
    let (_, chain) = read_ledger(tx, namespace, subject, &mut budget).await?;
    for record in chain.records() {
        let rows=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(command_fingerprint)=64 THEN pg_catalog.to_jsonb(r)::pg_catalog.text END AS record FROM public.product_command_receipt r WHERE outcome_kind='STRATEGY_PROMOTION' AND outcome_id=$1 ORDER BY command_id LIMIT 8193",record.fingerprint(),&mut budget).await?;
        if record.record()["schema_version"]
            .as_u64()
            .is_some_and(|v| v >= 2)
            && rows.len() != 1
        {
            return Err(INVALID);
        }
        for row in rows {
            let id = CommandId::new(text(&row, "command_id")?).map_err(|_| INVALID)?;
            let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(tx, &id)
                .await
                .map_err(|e| e.code())?
            else {
                return Err(INVALID);
            };
            if receipt.admission().kind() != CommandKind::PromoteStrategy
                || receipt.outcome().kind() != OutcomeKind::StrategyPromotion
                || receipt.outcome().id() != record.fingerprint()
                || public_time(receipt.accepted_at()) != record.record()["recorded_at"]
            {
                return Err(INVALID);
            }
        }
    }
    Ok(chain)
}
pub(crate) async fn ledger_readonly(
    client: &mut Client,
    namespace: &SemanticStoreId,
    subject: &str,
) -> Result<Value> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let chain = checked_ledger(&tx, namespace, subject).await?;
    let value = json!({"stage":chain.stage(),"promotion_records":chain.records().iter().map(|r|r.record().clone()).collect::<Vec<_>>()});
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(value)
}
pub(crate) async fn promotion_outcome_readonly(
    client: &mut Client,
    namespace: &SemanticStoreId,
    subject: &str,
    actor: &str,
    id: &CommandId,
) -> Result<Value> {
    if actor.is_empty() || actor.len() > 512 || actor.chars().any(char::is_control) {
        return Err("PROMOTION_ACCESS_DENIED");
    }
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let chain = checked_ledger(&tx, namespace, subject).await?;
    let binding = Commands::verify_binding_in_transaction(&tx, id)
        .await
        .map_err(|e| e.code())?;
    let (state, record) = match binding {
        Binding::None => ("NOT_SUBMITTED", Value::Null),
        Binding::Admitted(_) => ("OUTCOME_UNKNOWN", Value::Null),
        Binding::Accepted(receipt)
            if receipt.admission().kind() == CommandKind::PromoteStrategy
                && receipt.outcome().kind() == OutcomeKind::StrategyPromotion =>
        {
            let record = chain
                .records()
                .iter()
                .find(|record| record.fingerprint() == receipt.outcome().id())
                .ok_or("PRODUCT_COMMAND_CONFLICT")?;
            if record.record()["actor"] != actor {
                return Err("PROMOTION_ACCESS_DENIED");
            }
            if public_time(receipt.accepted_at()) != record.record()["recorded_at"] {
                return Err(INVALID);
            }
            ("COMPLETED", record.record().clone())
        }
        _ => return Err("PRODUCT_COMMAND_CONFLICT"),
    };
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(
        json!({"schema_version":1,"command_id":id.value(),"strategy_fingerprint":subject,"state":state,"record":record}),
    )
}

async fn read_catalog(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
    budget: &mut Budget,
) -> Result<Value> {
    let mut catalog=records(tx,"SELECT CASE WHEN pg_catalog.octet_length(strategy_fingerprint)=64 AND pg_catalog.octet_length(COALESCE(display_name,''))<=4096 AND pg_catalog.octet_length(COALESCE(catalog_family,''))<=4096 THEN pg_catalog.to_jsonb(c)::pg_catalog.text ELSE NULL END AS record FROM public.strategy_catalog c WHERE strategy_fingerprint=$1 LIMIT 2",subject,budget).await?;
    if catalog.len() != 1 {
        return Err(INVALID);
    }
    let mut catalog = catalog.remove(0);
    if catalog["strategy_fingerprint"] != subject
        || catalog["semantic_namespace_id"] != namespace.value()
        || catalog["schema_version"] != 1
    {
        return Err(INVALID);
    }
    catalog["created_at"] = json!(date(&catalog, "created_at")?.to_string());
    Ok(catalog)
}

fn decode_chain(subject: &str, raw: Vec<Value>) -> Result<PromotionChain> {
    let mut parsed = Vec::new();
    for mut row in raw {
        if row["schema_version"] != 3 {
            if !row["origin"].is_null() {
                return Err(INVALID);
            }
            row.as_object_mut().ok_or(INVALID)?.remove("origin");
        }
        let id = row
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("promotion_record_fingerprint")
            .ok_or(INVALID)?;
        row["record_fingerprint"] = id;
        row["recorded_at"] = json!(public_time(date(&row, "recorded_at")?));
        if row["schema_version"] == 1 {
            if !row["qualification_decision_fingerprint"].is_null() {
                return Err(INVALID);
            }
            row.as_object_mut()
                .ok_or(INVALID)?
                .remove("qualification_decision_fingerprint");
        }
        parsed.push(PromotionRecord::from_record(&row)?);
    }
    let chain = PromotionChain::from_records(subject, parsed)?;
    Ok(chain)
}

/// Exact historical evidence prefix. This has no current eligibility or
/// admission conversion; later Promotion records cannot redefine this cut.
pub(crate) struct VerifiedBacktestHistory {
    source: SourceRevision,
    namespace: SemanticStoreId,
    relation: FreezeRelation,
    promotion: String,
    decision: Arc<VerifiedDecision>,
    frozen: Arc<FrozenStore>,
    ledger: PgCut,
    max_work: usize,
}
impl VerifiedBacktestHistory {
    pub(crate) fn strategy_fingerprint(&self) -> &str {
        self.source.fingerprint()
    }
    pub(crate) fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
    pub(crate) fn freeze_relation_fingerprint(&self) -> &str {
        self.relation.fingerprint()
    }
    pub(crate) fn qualification_decision_fingerprint(&self) -> &str {
        self.decision.fingerprint()
    }
    pub(crate) fn promotion_fingerprint(&self) -> &str {
        &self.promotion
    }
    pub(crate) fn is_manual(&self) -> bool {
        self.decision.manual_evidence().is_some()
    }
    pub(crate) fn validated_decision(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.decision.validated_decision()
    }
    pub(crate) fn source_revision(&self) -> &SourceRevision {
        &self.source
    }
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.decision.validated_calculations()
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        files(
            &self.namespace,
            &self.frozen,
            &self.decision,
            &self.source,
            &self.relation,
            self.max_work,
        )
    }
    pub(crate) async fn verify_in_transaction(&self, tx: &BuildFactRead<'_, '_>) -> Result<()> {
        self.verify_cut()?;
        transaction(tx, &self.namespace).await?;
        let actual = read_cut_with_prefix(
            tx,
            &self.namespace,
            self.source.fingerprint(),
            &self.relation,
            &self.decision,
            PromotionCutSelection {
                required: Some(&self.promotion),
                prefix: Some(&self.promotion),
            },
            self.max_work,
        )
        .await?;
        if actual != self.ledger {
            return Err(INVALID);
        }
        self.verify_cut()
    }
}

/// Sealed owning proof of a qualified BACKTEST -> SIM Promotion.
/// Produces SIM eligibility only (ADR 0118); never grants LIVE or a running Runtime.
pub struct VerifiedSimPromotion {
    history: VerifiedBacktestHistory,
    backtest_run: VerifiedRun,
    backtest_proof: Value,
    backtest_evidence: String,
    sim_decision: Arc<VerifiedDecision>,
    sim_policy: String,
    promotion: String,
    cut: Vec<Arc<SourceLock>>,
    ledger: PgCut,
    max_work: usize,
}
impl VerifiedSimPromotion {
    pub fn source_revision(&self) -> &SourceRevision {
        self.history.source_revision()
    }
    pub fn strategy_fingerprint(&self) -> &str {
        self.history.strategy_fingerprint()
    }
    pub fn namespace(&self) -> &SemanticStoreId {
        self.history.namespace()
    }
    pub fn freeze_relation_fingerprint(&self) -> &str {
        self.history.freeze_relation_fingerprint()
    }
    pub fn backtest_qualification_decision_fingerprint(&self) -> &str {
        self.history.qualification_decision_fingerprint()
    }
    pub fn backtest_promotion_fingerprint(&self) -> &str {
        self.history.promotion_fingerprint()
    }
    pub fn backtest_run_id(&self) -> &str {
        self.backtest_run.run_id()
    }
    pub fn owner(&self) -> &str {
        self.backtest_run.owner()
    }
    pub fn backtest_evidence_fingerprint(&self) -> &str {
        &self.backtest_evidence
    }
    pub fn policy_fingerprint(&self) -> &str {
        &self.sim_policy
    }
    pub fn qualification_decision_fingerprint(&self) -> &str {
        self.sim_decision.fingerprint()
    }
    pub fn promotion_fingerprint(&self) -> &str {
        &self.promotion
    }
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.history.validated_calculations()
    }
    pub(crate) fn validated_decision(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.history.validated_decision()
    }
    pub fn verify_cut(&self) -> Result<()> {
        if self.cut.is_empty() {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
        for lock in &self.cut {
            lock.verify()?;
        }
        if self.history.is_manual() {
            return Err("ILLEGAL_PROMOTION_TRANSITION");
        }
        self.history.verify_cut()?;
        if &self.sim_decision.namespace()? != self.namespace() {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        let evidence_fp = sim_decision_record(
            &self.sim_decision,
            &self.history,
            Some(&self.sim_policy),
            &self.backtest_run,
        )?;
        if evidence_fp != self.backtest_evidence {
            return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        }
        verify_backtest_run_lineage(
            self.namespace(),
            &self.history,
            &self.backtest_run,
            self.backtest_run.owner(),
            evidence_fp,
        )
    }
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &BuildFactRead<'_, '_>,
        namespace: &SemanticStoreId,
    ) -> Result<()> {
        if namespace != self.namespace() {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        self.verify_cut()?;
        bounds(tx).await.map_err(|e| e.code())?;
        deployment::verify_binding_in_transaction(tx, namespace)
            .await
            .map_err(|e| e.code())?;
        let (actual_ledger, actual_proof) = read_sim_cut(
            tx,
            namespace,
            &self.history,
            &self.backtest_run,
            self.backtest_run.owner(),
            &self.sim_decision,
            Some(&self.promotion),
            self.max_work,
        )
        .await?;
        if actual_ledger != self.ledger || actual_proof != self.backtest_proof {
            return Err(INVALID);
        }
        self.verify_cut()
    }
}

pub(crate) struct SimPromotionSelection<'a> {
    pub(crate) strategy: &'a str,
    pub(crate) owner: &'a str,
    pub(crate) policy: &'a str,
    pub(crate) promotion: &'a str,
    pub(crate) max_work: usize,
}

pub(crate) struct SelectedSimPromotion<'a> {
    pub(crate) strategy: &'a str,
    pub(crate) owner: &'a str,
    pub(crate) backtest_run_id: &'a str,
    pub(crate) policy: &'a str,
    pub(crate) decision: &'a str,
    pub(crate) promotion: &'a str,
    pub(crate) max_work: usize,
}

pub(crate) async fn read_verified_sim_promotion(
    clients: (&mut Client, &mut Client),
    namespace: &SemanticStoreId,
    history: VerifiedBacktestHistory,
    backtest_run: VerifiedRun,
    decision: Arc<VerifiedDecision>,
    selection: SimPromotionSelection<'_>,
) -> Result<VerifiedSimPromotion> {
    let (client, facts) = clients;
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let fact_tx = facts
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    let context = BuildFactRead::reader(&tx, &fact_tx, namespace)
        .await
        .map_err(|_| UNAVAILABLE)?;
    let sealed = read_verified_sim_promotion_in_transaction(
        &context,
        namespace,
        history,
        backtest_run,
        decision,
        selection,
    )
    .await?;
    fact_tx.commit().await.map_err(|_| UNAVAILABLE)?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(sealed)
}

pub(crate) async fn read_verified_sim_promotion_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    history: VerifiedBacktestHistory,
    backtest_run: VerifiedRun,
    decision: Arc<VerifiedDecision>,
    selection: SimPromotionSelection<'_>,
) -> Result<VerifiedSimPromotion> {
    read_verified_sim_promotion_mode(
        tx,
        namespace,
        history,
        backtest_run,
        decision,
        selection,
        false,
    )
    .await
}

async fn read_verified_sim_promotion_mode(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    history: VerifiedBacktestHistory,
    backtest_run: VerifiedRun,
    decision: Arc<VerifiedDecision>,
    selection: SimPromotionSelection<'_>,
    fresh_in_tx: bool,
) -> Result<VerifiedSimPromotion> {
    let SimPromotionSelection {
        strategy,
        owner,
        policy,
        promotion,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || owner.trim().is_empty()
        || [strategy, policy, promotion]
            .iter()
            .any(|v| !crate::is_sha256_hex(v))
    {
        return Err(INVALID);
    }
    if history.namespace() != namespace || &decision.namespace()? != namespace {
        return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
    }
    if history.is_manual() {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    if history.strategy_fingerprint() != strategy {
        return Err("QUALIFICATION_DECISION_SUBJECT_MISMATCH");
    }
    let backtest_evidence =
        sim_decision_record(&decision, &history, Some(policy), &backtest_run)?.to_owned();
    verify_backtest_run_lineage(
        namespace,
        &history,
        &backtest_run,
        owner,
        &backtest_evidence,
    )?;
    transaction(tx, namespace).await?;
    let (ledger, backtest_proof) = read_sim_cut_mode(
        tx,
        namespace,
        &history,
        &backtest_run,
        owner,
        &decision,
        Some(promotion),
        max_work,
        fresh_in_tx,
    )
    .await?;
    let mut cut = history.decision.source_locks();
    cut.extend(decision.source_locks());
    let sealed = VerifiedSimPromotion {
        history,
        backtest_run,
        backtest_proof,
        backtest_evidence,
        sim_decision: decision,
        sim_policy: policy.into(),
        promotion: promotion.into(),
        cut,
        ledger,
        max_work,
    };
    sealed.verify_cut()?;
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(|e| e.code())?;
    Ok(sealed)
}

pub(crate) struct VerifiedSimPromotionInputs {
    pub(crate) history: VerifiedBacktestHistory,
    pub(crate) backtest_run: VerifiedRun,
    pub(crate) decision: Arc<VerifiedDecision>,
}

pub(crate) struct SimPromotionInputSelection<'a> {
    pub(crate) strategy: &'a str,
    pub(crate) owner: &'a str,
    pub(crate) backtest_run_id: &'a str,
    pub(crate) decision: &'a str,
    pub(crate) max_work: usize,
}

async fn load_sim_promotion_inputs_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decisions: Arc<super::qualification_decision::Store>,
    runtime_root: &std::path::Path,
    selection: SimPromotionInputSelection<'_>,
) -> Result<VerifiedSimPromotionInputs> {
    let SimPromotionInputSelection {
        strategy,
        owner,
        backtest_run_id,
        decision,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || owner.trim().is_empty()
        || !crate::application::command::uuid4(backtest_run_id)
        || [strategy, decision]
            .iter()
            .any(|id| !crate::is_sha256_hex(id))
    {
        return Err(INVALID);
    }
    transaction(tx, namespace).await?;
    let backtest_run = backtest_run::load_in_transaction(tx, namespace, backtest_run_id).await?;
    if backtest_run.owner() != owner {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    if backtest_run.state() != RunState::Completed
        || backtest_run.resolution()["semantic_store_id"] != namespace.value()
        || backtest_run.resolution()["strategy_fingerprint"] != strategy
    {
        return Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
    }
    let relation = text(backtest_run.resolution(), "freeze_relation_fingerprint")?.to_owned();
    let research_decision_id =
        text(backtest_run.resolution(), "qualification_decision_fingerprint")?.to_owned();
    let backtest_promotion = text(backtest_run.resolution(), "promotion_fingerprint")?.to_owned();
    let research_decision = decisions
        .read_verified_in_transaction(tx, namespace, runtime_root, &research_decision_id)
        .await?;
    let history = read_verified_history_in_transaction(
        tx,
        namespace,
        frozen,
        research_decision,
        BacktestAdmissionSelection {
            strategy,
            relation: &relation,
            promotion: &backtest_promotion,
            max_work,
        },
    )
    .await?;
    if history.is_manual() {
        return Err("ILLEGAL_PROMOTION_TRANSITION");
    }
    let sim_decision = decisions
        .read_verified_in_transaction(tx, namespace, runtime_root, decision)
        .await?;
    if sim_decision.fingerprint() == history.qualification_decision_fingerprint() {
        return Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH");
    }
    let evidence_fp = sim_decision_record(&sim_decision, &history, None, &backtest_run)?;
    verify_backtest_run_in_transaction(tx, namespace, &history, &backtest_run, owner, evidence_fp)
        .await?;
    Ok(VerifiedSimPromotionInputs {
        history,
        backtest_run,
        decision: sim_decision,
    })
}

/// Readonly single-snapshot loader for transport/command callers preparing
/// `Promotions::promote_to_sim`. Grants no stage transition on its own.
pub(crate) async fn read_sim_promotion_inputs(
    clients: (&mut Client, &mut Client),
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decisions: Arc<super::qualification_decision::Store>,
    runtime_root: &std::path::Path,
    selection: SimPromotionInputSelection<'_>,
) -> Result<VerifiedSimPromotionInputs> {
    let (client, facts) = clients;
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await?;
    let fact_tx = facts
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    let context = BuildFactRead::reader(&tx, &fact_tx, namespace)
        .await
        .map_err(|_| UNAVAILABLE)?;
    let inputs = load_sim_promotion_inputs_in_transaction(
        &context,
        namespace,
        frozen,
        decisions,
        runtime_root,
        selection,
    )
    .await?;
    fact_tx.commit().await.map_err(|_| UNAVAILABLE)?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(inputs)
}

/// Exact two-segment Q/P observation on one owning transaction for SIM start/recovery.
/// No caller JSON can substitute for evaluator-owned Decisions or the original Backtest Run.
pub(crate) async fn read_selected_sim_promotion_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decisions: Arc<super::qualification_decision::Store>,
    runtime_root: &std::path::Path,
    selection: SelectedSimPromotion<'_>,
) -> Result<VerifiedSimPromotion> {
    let SelectedSimPromotion {
        strategy,
        owner,
        backtest_run_id,
        policy,
        decision,
        promotion,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || owner.trim().is_empty()
        || !crate::application::command::uuid4(backtest_run_id)
        || [strategy, policy, decision, promotion]
            .iter()
            .any(|id| !crate::is_sha256_hex(id))
    {
        return Err(INVALID);
    }
    let inputs = load_sim_promotion_inputs_in_transaction(
        tx,
        namespace,
        frozen,
        decisions,
        runtime_root,
        SimPromotionInputSelection {
            strategy,
            owner,
            backtest_run_id,
            decision,
            max_work,
        },
    )
    .await?;
    read_verified_sim_promotion_mode(
        tx,
        namespace,
        inputs.history,
        inputs.backtest_run,
        inputs.decision,
        SimPromotionSelection {
            strategy,
            owner,
            policy,
            promotion,
            max_work,
        },
        true,
    )
    .await
}
pub(crate) async fn read_verified_history_in_transaction(
    tx: &BuildFactRead<'_, '_>,
    namespace: &SemanticStoreId,
    frozen: Arc<FrozenStore>,
    decision: Arc<VerifiedDecision>,
    selection: BacktestAdmissionSelection<'_>,
) -> Result<VerifiedBacktestHistory> {
    let BacktestAdmissionSelection {
        strategy,
        relation,
        promotion,
        max_work,
    } = selection;
    let max_work = max_work.min(WORK);
    if max_work == 0
        || [strategy, relation, promotion]
            .iter()
            .any(|p| !crate::is_sha256_hex(p))
    {
        return Err(INVALID);
    }
    let source = frozen
        .load_verified(strategy, max_work)
        .map_err(|e| e.code())?;
    let relation = frozen
        .load_relation_verified(relation, max_work)
        .map_err(|e| e.code())?;
    files(namespace, &frozen, &decision, &source, &relation, max_work)?;
    transaction(tx, namespace).await?;
    let ledger = read_cut_with_prefix(
        tx,
        namespace,
        strategy,
        &relation,
        &decision,
        PromotionCutSelection {
            required: Some(promotion),
            prefix: Some(promotion),
        },
        max_work,
    )
    .await?;
    let chain = PromotionChain::from_records(strategy, ledger.chain.clone())?;
    if chain.head_fingerprint() != Some(promotion) || chain.stage() != "BACKTEST" {
        return Err(INVALID);
    }
    let selected = chain.records().last().ok_or(INVALID)?.record();
    qualified_backtest_record(selected, &decision)?;
    let value = VerifiedBacktestHistory {
        source,
        namespace: namespace.clone(),
        relation,
        promotion: promotion.into(),
        decision,
        frozen,
        ledger,
        max_work,
    };
    value.verify_in_transaction(tx).await?;
    Ok(value)
}
async fn read_ledger_prefix(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
    promotion: &str,
    budget: &mut Budget,
) -> Result<(Value, PromotionChain)> {
    if !crate::is_sha256_hex(promotion) {
        return Err(INVALID);
    }
    let catalog = read_catalog(tx, namespace, subject, budget).await?;
    let raw=records(tx,r#"WITH RECURSIVE ancestors AS (
        SELECT p.promotion_record_fingerprint,p.previous_record_fingerprint,ARRAY[p.promotion_record_fingerprint] AS visited
        FROM public.strategy_promotion_record p WHERE p.promotion_record_fingerprint=$1
        UNION ALL
        SELECT p.promotion_record_fingerprint,p.previous_record_fingerprint,a.visited||p.promotion_record_fingerprint
        FROM public.strategy_promotion_record p JOIN ancestors a ON p.promotion_record_fingerprint=a.previous_record_fingerprint
        WHERE pg_catalog.cardinality(a.visited)<=8192 AND NOT (p.promotion_record_fingerprint=ANY(a.visited))
    ) SELECT CASE WHEN pg_catalog.octet_length(p.reason)<=4096 AND pg_catalog.octet_length(p.actor)<=512
        AND pg_catalog.cardinality(p.evidence_fingerprints)<=8192 THEN pg_catalog.to_jsonb(p)::pg_catalog.text ELSE NULL END AS record
    FROM public.strategy_promotion_record p JOIN ancestors a ON a.promotion_record_fingerprint=p.promotion_record_fingerprint
    ORDER BY p.promotion_record_fingerprint COLLATE pg_catalog."C" LIMIT 8193"#,promotion,budget).await?;
    let chain = decode_chain(subject, raw)?;
    if chain.head_fingerprint() != Some(promotion) {
        return Err(INVALID);
    }
    Ok((catalog, chain))
}

#[cfg(test)]
mod backtest_record_tests {
    use super::*;

    #[test]
    fn historical_promotion_requires_the_exact_freeze_and_validation_evidence() {
        let decision = "b".repeat(64);
        let relation = "c".repeat(64);
        let validation_id = "d".repeat(64);
        let other = "e".repeat(64);
        for validation in [None, Some(validation_id.as_str())] {
            let mut row = json!({
                "schema_version": if validation.is_some() { 3 } else { 2 },
                "from_stage": if validation.is_some() { "FROZEN" } else { "RESEARCH" },
                "to_stage":"BACKTEST", "decision":"APPROVED",
                "qualification_decision_fingerprint":decision,
            });
            let mut expected = vec![decision.as_str(), relation.as_str()];
            if let Some(id) = validation {
                row["origin"] = json!({"kind":"MANUAL_BACKTEST","strategy_validation_fingerprint":id});
                expected.push(id);
            }
            row["evidence_fingerprints"] = json!(expected);
            verify_backtest_record(&row, &decision, &relation, validation).unwrap();
            let mut missing = expected.clone();
            missing.remove(1);
            let mut replaced = expected.clone();
            replaced[1] = other.as_str();
            let mut extra = expected;
            extra.push(other.as_str());
            for mut refs in [missing, replaced, extra] {
                refs.sort_unstable();
                row["evidence_fingerprints"] = json!(refs);
                assert_eq!(
                    verify_backtest_record(&row, &decision, &relation, validation),
                    Err("QUALIFIED_PROMOTION_PROOF_REQUIRED"),
                );
            }
        }
    }
}

#[cfg(test)]
mod sim_promotion_verification_tests {
    use super::*;

    #[test]
    fn promotion_command_admission_separates_backtest_and_sim_stages() {
        let command = CommandId::new("00000000-0000-4000-8000-000000000901").unwrap();
        let request = Request::new(
            command,
            &"a".repeat(64),
            &"b".repeat(64),
            &"c".repeat(64),
            "stage-bound promotion",
        )
        .unwrap();
        let backtest = request.admission("local-developer", "BACKTEST").unwrap();
        let sim = request.admission("local-developer", "SIM").unwrap();
        assert_ne!(backtest, sim);
        assert_ne!(backtest.fingerprint(), sim.fingerprint());
    }

    #[test]
    fn sim_decision_record_requires_exact_gate_policy_outcome_and_backtest_evidence() {
        let strategy = "a".repeat(64);
        let relation = "1".repeat(64);
        let backtest_promotion = "2".repeat(64);
        let policy = "b".repeat(64);
        let decision_fp = "c".repeat(64);
        let evidence_fp = "d".repeat(64);
        let other = "e".repeat(64);
        let run_id = "00000000-0000-4000-8000-000000000902";

        let item = json!({
            "kind": "BACKTEST_EVIDENCE", "evidence_fingerprint": evidence_fp,
            "backtest_run_id": run_id, "subject_binding_fingerprint": relation,
        });
        let base = json!({
            "decision_fingerprint": decision_fp, "subject_strategy_fingerprint": strategy,
            "policy_fingerprint": policy, "outcome": "APPROVED", "gate": "BACKTEST_TO_SIM",
            "evidence": [item],
        });
        let verify = |record: &Value| verify_sim_decision_record(
            record, &decision_fp, &strategy, &relation, &evidence_fp, Some(&policy), run_id,
        );
        assert_eq!(verify(&base), Ok(()));
        for (key, value, code) in [
            ("decision_fingerprint", other.as_str(), "QUALIFICATION_DECISION_SUBJECT_MISMATCH"),
            ("subject_strategy_fingerprint", &other, "QUALIFICATION_DECISION_SUBJECT_MISMATCH"),
            ("policy_fingerprint", &other, "QUALIFICATION_DECISION_POLICY_MISMATCH"),
            ("outcome", "REJECTED", "QUALIFICATION_DECISION_NOT_APPROVED"),
            ("gate", "RESEARCH_TO_BACKTEST", "QUALIFICATION_EVIDENCE_GATE_MISMATCH"),
            ("gate", "MANUAL_STRATEGY_TO_BACKTEST", "QUALIFICATION_EVIDENCE_GATE_MISMATCH"),
            ("gate", "SIM_TO_LIVE", "QUALIFICATION_EVIDENCE_GATE_MISMATCH"),
        ] {
            let mut record = base.clone();
            record[key] = json!(value);
            assert_eq!(verify(&record), Err(code), "{key}");
        }
        let required = Err("QUALIFIED_PROMOTION_PROOF_REQUIRED");
        for key in ["backtest_run_id", "subject_binding_fingerprint", "evidence_fingerprint"] {
            let mut record = base.clone();
            record["evidence"][0].as_object_mut().unwrap().remove(key);
            assert_eq!(verify(&record), required, "missing {key}");
            record["evidence"][0][key] = Value::Null;
            assert_eq!(verify(&record), required, "null {key}");
        }
        for (key, value) in [
            ("backtest_run_id", json!("00000000-0000-4000-8000-000000000999")),
            ("subject_binding_fingerprint", json!(backtest_promotion)),
            ("evidence_fingerprint", json!(other)),
            ("run_id", json!(run_id)),
            ("locator_fingerprint", Value::Null),
            ("preparation_command_id", json!(run_id)),
        ] {
            let mut record = base.clone();
            record["evidence"][0][key] = value;
            assert_eq!(verify(&record), required, "{key}");
        }
        for items in [json!([]), json!([item, item])] {
            let mut record = base.clone();
            record["evidence"] = items;
            assert_eq!(verify(&record), required);
        }
        for kind in ["STRATEGY_VALIDATION", "RESEARCH_RESULT"] {
            let mut record = base.clone();
            record["evidence"][0]["kind"] = json!(kind);
            assert_eq!(verify(&record), Err("QUALIFICATION_EVIDENCE_GATE_MISMATCH"));
        }
    }

    #[test]
    fn backtest_run_binding_requires_completed_run_and_exact_history_lineage() {
        let namespace = "00000000-0000-4000-8000-000000000903";
        let owner = "local-developer";
        let strategy = "a".repeat(64);
        let relation = "b".repeat(64);
        let research_decision = "c".repeat(64);
        let backtest_promotion = "d".repeat(64);
        let evidence_fp = "e".repeat(64);
        let other = "f".repeat(64);

        let resolution = json!({
            "semantic_store_id": namespace,
            "strategy_fingerprint": strategy,
            "freeze_relation_fingerprint": relation,
            "qualification_decision_fingerprint": research_decision,
            "promotion_fingerprint": backtest_promotion,
        });
        let specification = json!({
            "strategy_fingerprint": strategy,
        });
        let completion = Some((evidence_fp.as_str(), evidence_fp.as_str(), evidence_fp.as_str()));

        verify_backtest_run_binding(
            namespace,
            owner,
            owner,
            RunState::Completed,
            completion,
            &resolution,
            &specification,
            &strategy,
            &relation,
            &research_decision,
            &backtest_promotion,
            &evidence_fp,
        )
        .unwrap();

        assert_eq!(
            verify_backtest_run_binding(
                namespace,
                owner,
                "other-developer",
                RunState::Completed,
                completion,
                &resolution,
                &specification,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
                &evidence_fp,
            ),
            Err("BACKTEST_ACCESS_DENIED")
        );
        assert_eq!(
            verify_backtest_run_binding(
                namespace,
                owner,
                "   ",
                RunState::Completed,
                completion,
                &resolution,
                &specification,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
                &evidence_fp,
            ),
            Err(INVALID)
        );

        for state in [
            RunState::Queued,
            RunState::Running,
            RunState::CancelRequested,
            RunState::Failed,
            RunState::Cancelled,
        ] {
            assert_eq!(
                verify_backtest_run_binding(
                    namespace,
                    owner,
                    owner,
                    state,
                    completion,
                    &resolution,
                    &specification,
                    &strategy,
                    &relation,
                    &research_decision,
                    &backtest_promotion,
                    &evidence_fp,
                ),
                Err("QUALIFIED_PROMOTION_PROOF_REQUIRED")
            );
        }

        assert_eq!(
            verify_backtest_run_binding(
                namespace,
                owner,
                owner,
                RunState::Completed,
                None,
                &resolution,
                &specification,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
                &evidence_fp,
            ),
            Err("QUALIFIED_PROMOTION_PROOF_REQUIRED")
        );
        assert_eq!(
            verify_backtest_run_binding(
                namespace,
                owner,
                owner,
                RunState::Completed,
                completion,
                &resolution,
                &specification,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
                &other,
            ),
            Err("QUALIFIED_PROMOTION_PROOF_REQUIRED")
        );

        for key in [
            "semantic_store_id",
            "strategy_fingerprint",
            "freeze_relation_fingerprint",
            "qualification_decision_fingerprint",
            "promotion_fingerprint",
        ] {
            let mut mutated = resolution.clone();
            mutated[key] = json!(other);
            assert_eq!(
                verify_backtest_run_binding(
                    namespace,
                    owner,
                    owner,
                    RunState::Completed,
                    completion,
                    &mutated,
                    &specification,
                    &strategy,
                    &relation,
                    &research_decision,
                    &backtest_promotion,
                    &evidence_fp,
                ),
                Err("QUALIFIED_PROMOTION_PROOF_REQUIRED"),
                "mutated {key}"
            );
        }

        let wrong_spec = json!({ "strategy_fingerprint": other });
        assert_eq!(
            verify_backtest_run_binding(
                namespace,
                owner,
                owner,
                RunState::Completed,
                completion,
                &resolution,
                &wrong_spec,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
                &evidence_fp,
            ),
            Err("QUALIFIED_PROMOTION_PROOF_REQUIRED")
        );
    }

    #[test]
    fn research_backtest_origin_rejects_manual_preparation_reusing_research_grant() {
        let strategy = "a".repeat(64);
        let relation = "b".repeat(64);
        let research_decision = "c".repeat(64);
        let backtest_promotion = "d".repeat(64);
        let other = "f".repeat(64);

        let frozen = BacktestOrigin::FrozenStrategy {
            strategy_fingerprint: strategy.clone(),
            freeze_relation_fingerprint: relation.clone(),
            qualification_decision_fingerprint: research_decision.clone(),
            promotion_fingerprint: backtest_promotion.clone(),
        };
        verify_research_backtest_origin(
            &frozen,
            &Value::Null,
            &strategy,
            &relation,
            &research_decision,
            &backtest_promotion,
        )
        .unwrap();

        let manual = BacktestOrigin::ManualStrategy {
            strategy_id: "private.strategy.btc_momentum".into(),
            strategy_revision_fingerprint: strategy.clone(),
        };
        assert_eq!(
            verify_research_backtest_origin(
                &manual,
                &Value::Null,
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
            ),
            Err("ILLEGAL_PROMOTION_TRANSITION")
        );
        assert_eq!(
            verify_research_backtest_origin(
                &frozen,
                &json!(other),
                &strategy,
                &relation,
                &research_decision,
                &backtest_promotion,
            ),
            Err("ILLEGAL_PROMOTION_TRANSITION")
        );
        for wrong in [
            BacktestOrigin::FrozenStrategy {
                strategy_fingerprint: other.clone(),
                freeze_relation_fingerprint: relation.clone(),
                qualification_decision_fingerprint: research_decision.clone(),
                promotion_fingerprint: backtest_promotion.clone(),
            },
            BacktestOrigin::FrozenStrategy {
                strategy_fingerprint: strategy.clone(),
                freeze_relation_fingerprint: other.clone(),
                qualification_decision_fingerprint: research_decision.clone(),
                promotion_fingerprint: backtest_promotion.clone(),
            },
            BacktestOrigin::FrozenStrategy {
                strategy_fingerprint: strategy.clone(),
                freeze_relation_fingerprint: relation.clone(),
                qualification_decision_fingerprint: other.clone(),
                promotion_fingerprint: backtest_promotion.clone(),
            },
            BacktestOrigin::FrozenStrategy {
                strategy_fingerprint: strategy.clone(),
                freeze_relation_fingerprint: relation.clone(),
                qualification_decision_fingerprint: research_decision.clone(),
                promotion_fingerprint: other,
            },
        ] {
            assert_eq!(
                verify_research_backtest_origin(
                    &wrong,
                    &Value::Null,
                    &strategy,
                    &relation,
                    &research_decision,
                    &backtest_promotion,
                ),
                Err("ILLEGAL_PROMOTION_TRANSITION")
            );
        }
    }
}

#[cfg(test)]
mod public_time_tests {
    #[test]
    fn public_promotion_time_preserves_the_original_python_microsecond_spelling() {
        for (input, expected) in [
            ("2026-11-02T00:00:00Z", "2026-11-02T00:00:00+00:00"),
            (
                "2026-11-02T00:00:00.123000Z",
                "2026-11-02T00:00:00.123000+00:00",
            ),
            (
                "2026-11-02T00:00:00.000001Z",
                "2026-11-02T00:00:00.000001+00:00",
            ),
        ] {
            assert_eq!(super::public_time(input.parse().unwrap()), expected);
        }
    }
}

