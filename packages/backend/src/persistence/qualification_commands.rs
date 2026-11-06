//! Qualification's original Command/PREPARED/Decision/receipt lifecycle.
//! Immutable Decision publication belongs to the evaluator; progression belongs to Promotion.
use crate::{
    application::{
        command::{Admission, Binding, CommandKind, Outcome, OutcomeKind, Receipt},
        frozen_strategy::{FrozenStore, VerifiedManualBacktestEvidence},
        qualification::Request,
        qualification_policy::Store as Policies,
    },
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        authority_session::AuthoritySession,
        postgres::{self, Commands, bounds},
        qualification_decision::{Evidence, Store as Decisions, VerifiedDecision},
        research_evidence::VerifiedResearchCounts,
    },
    security::human_access,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use std::{sync::Arc, time::SystemTime};
use tokio_postgres::Transaction;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "QUALIFICATION_COMMAND_CORRUPT";
const UNAVAILABLE: &str = "QUALIFICATION_COMMAND_UNAVAILABLE";
const UNKNOWN: &str = "QUALIFICATION_COMMAND_OUTCOME_UNKNOWN";
const WORK: usize = 64 * 1024 * 1024;
enum Failure {
    Known(&'static str),
    Uncertain(&'static str),
}
type Work<T> = std::result::Result<T, Failure>;
fn corrupt(_: impl std::fmt::Debug) -> Failure {
    Failure::Uncertain(INVALID)
}
fn db(_: impl std::fmt::Debug) -> Failure {
    Failure::Uncertain(UNAVAILABLE)
}
fn proof(code: &'static str) -> Failure {
    Failure::Uncertain(code)
}
fn stage_guard(code: &'static str) -> Failure {
    match code {
        "MANUAL_BACKTEST_PREPARATION_NOT_RUNNING"
        | "MANUAL_BACKTEST_PREPARATION_OWNER_MISMATCH" => Failure::Known(code),
        _ => Failure::Uncertain(code),
    }
}
fn command(error: crate::application::command::Error) -> Failure {
    if error == crate::application::command::Error::Conflict {
        Failure::Known(error.code())
    } else {
        Failure::Uncertain(error.code())
    }
}
#[derive(Clone, PartialEq, Eq)]
struct Prepared {
    at: OnlyUtcDateTime,
    completion: Option<(String, OnlyUtcDateTime)>,
}
pub(crate) struct Qualifications<'a> {
    session: &'a mut AuthoritySession,
    namespace: &'a SemanticStoreId,
    policies: Arc<Policies>,
    decisions: Arc<Decisions>,
    frozen: Arc<FrozenStore>,
    access: &'a human_access::Access,
    human: &'a human_access::Session,
    #[cfg(test)]
    stop: Option<String>,
}
impl<'a> Qualifications<'a> {
    pub(crate) fn new(
        session: &'a mut AuthoritySession,
        namespace: &'a SemanticStoreId,
        policies: Arc<Policies>,
        decisions: Arc<Decisions>,
        frozen: Arc<FrozenStore>,
        access: &'a human_access::Access,
        human: &'a human_access::Session,
    ) -> Self {
        Self {
            session,
            namespace,
            policies,
            decisions,
            frozen,
            access,
            human,
            #[cfg(test)]
            stop: None,
        }
    }
    fn human(&self) -> Work<()> {
        self.access
            .check_session(self.human)
            .map_err(|_| Failure::Known("QUALIFICATION_ACCESS_DENIED"))
    }
    fn files(&self, request: &Request, evidence: &Evidence) -> Work<()> {
        evidence.matches(request).map_err(|e| {
            if e == "QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH" {
                Failure::Known(e)
            } else {
                proof(e)
            }
        })?;
        if self.frozen.namespace().map_err(corrupt)? != *self.namespace
            || self.policies.namespace().map_err(proof)? != *self.namespace
            || self.decisions.namespace().map_err(proof)? != *self.namespace
        {
            return Err(Failure::Uncertain("RESEARCH_SEMANTIC_STORE_MISMATCH"));
        }
        let source = self
            .frozen
            .load_verified(request.subject(), WORK)
            .map_err(|e| proof(e.code()))?;
        let relation = self
            .frozen
            .load_relation_verified(request.relation_fingerprint(), WORK)
            .map_err(|e| proof(e.code()))?;
        if source.fingerprint() != request.subject()
            || relation.strategy_fingerprint() != request.subject()
        {
            return Err(Failure::Known("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"));
        }
        match evidence {
            Evidence::Research(_)
                if relation.to_record()["research_result_fingerprint"]
                    != request.evidence_fingerprint() =>
            {
                return Err(Failure::Known("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"));
            }
            Evidence::Manual(proof)
                if proof.freeze_relation_fingerprint() != relation.fingerprint()
                    || proof.subject_strategy_fingerprint() != source.fingerprint() =>
            {
                return Err(Failure::Known("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"));
            }
            _ => {}
        }
        Ok(())
    }
    pub(crate) async fn execute(
        &mut self,
        request: &Request,
        counts: Arc<VerifiedResearchCounts>,
        at: OnlyUtcDateTime,
    ) -> Result<Arc<VerifiedDecision>> {
        self.execute_evidence(request, Evidence::Research(counts), at)
            .await
    }
    pub(crate) async fn execute_manual(
        &mut self,
        request: &Request,
        evidence: Arc<VerifiedManualBacktestEvidence>,
        at: OnlyUtcDateTime,
    ) -> Result<Arc<VerifiedDecision>> {
        self.execute_evidence(request, Evidence::Manual(evidence), at)
            .await
    }
    async fn execute_evidence(
        &mut self,
        request: &Request,
        evidence: Evidence,
        at: OnlyUtcDateTime,
    ) -> Result<Arc<VerifiedDecision>> {
        self.human().map_err(code)?;
        let mut owned = self.session.take_ownership();
        let result = self.execute_owned(&mut owned, request, evidence, at).await;
        match result {
            Err(Failure::Uncertain(value)) => {
                let _ = owned.close().await;
                Err(value)
            }
            result => {
                owned.verify().await.map_err(|e| e.code())?;
                self.session.restore_ownership(owned);
                result.map_err(code)
            }
        }
    }
    async fn execute_owned(
        &self,
        owned: &mut AuthoritySession,
        request: &Request,
        evidence: Evidence,
        at: OnlyUtcDateTime,
    ) -> Work<Arc<VerifiedDecision>> {
        let admission = Admission::new(
            request.command_id().clone(),
            CommandKind::EvaluateQualification,
            &request.fingerprint().map_err(corrupt)?,
        )
        .map_err(command)?;
        let prepared = {
            let tx = owned
                .client_mut()
                .await
                .map_err(db)?
                .build_transaction()
                .isolation_level(tokio_postgres::IsolationLevel::Serializable)
                .start()
                .await
                .map_err(db)?;
            transaction(&tx, self.namespace).await?;
            evidence
                .verify_in_transaction(&tx, self.namespace)
                .await
                .map_err(proof)?;
            Commands::lock_command(&tx, request.command_id())
                .await
                .map_err(command)?;
            let original = read(&tx, request, &admission).await?;
            let new_admission = original.is_none();
            let prepared = match original {
                Some(value) => value,
                None => {
                    evidence
                        .require_running_parent_in_transaction(
                            &tx,
                            self.namespace,
                            self.human
                                .subject_id()
                                .map_err(|_| Failure::Known("QUALIFICATION_ACCESS_DENIED"))?,
                        )
                        .await
                        .map_err(stage_guard)?;
                    self.files(request, &evidence)?;
                    catalog(&tx, self.namespace, request.subject()).await?;
                    let policy = self
                        .policies
                        .load_exact(request.policy_id(), request.policy_version(), WORK)
                        .map_err(|e| {
                            if e == crate::application::qualification_policy::Error::Missing {
                                Failure::Known(e.code())
                            } else {
                                proof(e.code())
                            }
                        })?;
                    evidence.evaluate(&policy).map_err(Failure::Known)?;
                    Commands::admit_exact_in_transaction(&tx, &admission)
                        .await
                        .map_err(command)?;
                    let time = postgres::system_time(at).map_err(command)?;
                    tx.execute("INSERT INTO public.qualification_command_admission(command_id,command_fingerprint,subject_strategy_fingerprint,policy_id,policy_version,evidence_payload,state,prepared_at,schema_version) VALUES($1::pg_catalog.text::pg_catalog.uuid,$2,$3,$4,$5,$6::pg_catalog.text::pg_catalog.jsonb,'PREPARED',$7,1)",&[&request.command_id().value(),&admission.fingerprint(),&request.subject(),&request.policy_id(),&request.policy_version(),&request.evidence().to_string(),&time]).await.map_err(db)?;
                    Prepared {
                        at,
                        completion: None,
                    }
                }
            };
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(db)?;
            if read(&tx, request, &admission).await? != Some(prepared.clone()) {
                return Err(corrupt(()));
            }
            catalog(&tx, self.namespace, request.subject()).await?;
            if new_admission {
                evidence
                    .require_running_parent_in_transaction(
                        &tx,
                        self.namespace,
                        self.human
                            .subject_id()
                            .map_err(|_| Failure::Known("QUALIFICATION_ACCESS_DENIED"))?,
                    )
                    .await
                    .map_err(stage_guard)?;
            }
            self.files(request, &evidence)?;
            evidence
                .verify_in_transaction(&tx, self.namespace)
                .await
                .map_err(proof)?;
            self.human()?;
            deployment::verify_binding_in_transaction(&tx, self.namespace)
                .await
                .map_err(corrupt)?;
            AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(db)?;
            tx.commit().await.map_err(|_| Failure::Uncertain(UNKNOWN))?;
            prepared
        };
        #[cfg(test)]
        self.checkpoint("prepared")?;
        owned.verify().await.map_err(db)?;
        self.files(request, &evidence)?;
        self.human()?;
        let decision = if let Some((id, _)) = &prepared.completion {
            // A completed Command can only read its original immutable Decision.
            self.decisions
                .load_evidence(self.policies.clone(), evidence.clone(), id)
                .map_err(proof)?
        } else {
            self.decisions
                .publish_evidence(
                    self.policies.clone(),
                    request.policy_id(),
                    request.policy_version(),
                    evidence.clone(),
                )
                .map_err(proof)?
        };
        if decision.record()["subject_strategy_fingerprint"] != request.subject()
            || decision.record()["policy_id"] != request.policy_id()
            || decision.record()["policy_version"] != request.policy_version()
            || decision.record()["evidence"] != *request.evidence()
        {
            return Err(corrupt(()));
        }
        let decision = Arc::new(decision);
        #[cfg(test)]
        self.checkpoint("decision")?;
        let tx = owned
            .client_mut()
            .await
            .map_err(db)?
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::Serializable)
            .start()
            .await
            .map_err(db)?;
        transaction(&tx, self.namespace).await?;
        evidence
            .verify_in_transaction(&tx, self.namespace)
            .await
            .map_err(proof)?;
        Commands::lock_command(&tx, request.command_id())
            .await
            .map_err(command)?;
        let original = read(&tx, request, &admission)
            .await?
            .ok_or_else(|| corrupt(()))?;
        if original != prepared {
            return Err(corrupt(()));
        }
        let completion = if let Some(completion) = original.completion.clone() {
            if completion.0 != decision.fingerprint() {
                return Err(corrupt(()));
            }
            completion
        } else {
            let time = postgres::system_time(at).map_err(command)?;
            let changed=tx.execute("UPDATE public.qualification_command_admission SET state='COMPLETED',decision_fingerprint=$2,completed_at=$3 WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid AND state='PREPARED' AND decision_fingerprint IS NULL AND completed_at IS NULL",&[&request.command_id().value(),&decision.fingerprint(),&time]).await.map_err(db)?;
            if changed != 1 {
                return Err(corrupt(()));
            }
            let receipt = Receipt::new(
                admission.clone(),
                Outcome::new(OutcomeKind::QualificationDecision, decision.fingerprint())
                    .map_err(command)?,
                &at.to_string(),
            )
            .map_err(command)?;
            Commands::put_verified_receipt_in_transaction(&tx, &receipt)
                .await
                .map_err(command)?;
            (decision.fingerprint().into(), at)
        };
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(db)?;
        if read(&tx, request, &admission).await?
            != Some(Prepared {
                at: prepared.at,
                completion: Some(completion),
            })
        {
            return Err(corrupt(()));
        }
        catalog(&tx, self.namespace, request.subject()).await?;
        self.files(request, &evidence)?;
        decision
            .verify_in_transaction(&tx, self.namespace)
            .await
            .map_err(proof)?;
        self.human()?;
        deployment::verify_binding_in_transaction(&tx, self.namespace)
            .await
            .map_err(corrupt)?;
        AuthoritySession::verify_transaction(&tx)
            .await
            .map_err(db)?;
        #[cfg(test)]
        self.checkpoint("before_commit")?;
        tx.commit().await.map_err(|_| Failure::Uncertain(UNKNOWN))?;
        #[cfg(test)]
        self.checkpoint("after_commit")?;
        Ok(decision)
    }
    #[cfg(test)]
    pub(crate) fn stop_at(&mut self, value: &str) -> Result<()> {
        if !["prepared", "decision", "before_commit", "after_commit"].contains(&value) {
            return Err(INVALID);
        }
        self.stop = Some(value.into());
        Ok(())
    }
    #[cfg(test)]
    fn checkpoint(&self, value: &str) -> Work<()> {
        if self.stop.as_deref() == Some(value) {
            Err(Failure::Uncertain(UNKNOWN))
        } else {
            Ok(())
        }
    }
}
fn code(failure: Failure) -> &'static str {
    match failure {
        Failure::Known(v) | Failure::Uncertain(v) => v,
    }
}
async fn transaction(tx: &Transaction<'_>, namespace: &SemanticStoreId) -> Work<()> {
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(db)?;
    bounds(tx).await.map_err(command)?;
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(corrupt)
}
async fn catalog(tx: &Transaction<'_>, namespace: &SemanticStoreId, subject: &str) -> Work<()> {
    let row=tx.query_opt("SELECT semantic_namespace_id::pg_catalog.text,schema_version FROM public.strategy_catalog WHERE strategy_fingerprint=$1",&[&subject]).await.map_err(db)?.ok_or(Failure::Known("STRATEGY_NOT_FOUND"))?;
    if row.try_get::<_, String>(0).map_err(corrupt)? != namespace.value()
        || row.try_get::<_, i32>(1).map_err(corrupt)? != 1
    {
        return Err(corrupt(()));
    }
    Ok(())
}
async fn read(
    tx: &Transaction<'_>,
    request: &Request,
    expected: &Admission,
) -> Work<Option<Prepared>> {
    let binding = Commands::verify_binding_in_transaction(tx, request.command_id())
        .await
        .map_err(command)?;
    let row=tx.query_opt("SELECT command_fingerprint,subject_strategy_fingerprint,policy_id,policy_version,CASE WHEN pg_catalog.octet_length(evidence_payload::pg_catalog.text)<=65536 THEN evidence_payload::pg_catalog.text ELSE NULL END,state,decision_fingerprint,prepared_at,completed_at,schema_version FROM public.qualification_command_admission WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid",&[&request.command_id().value()]).await.map_err(db)?;
    if let Binding::Admitted(admission) = &binding
        && admission != expected
    {
        return Err(Failure::Known("PRODUCT_COMMAND_CONFLICT"));
    }
    if let Binding::Accepted(receipt) = &binding
        && receipt.admission() != expected
    {
        return Err(Failure::Known("PRODUCT_COMMAND_CONFLICT"));
    }
    let Some(row) = row else {
        return if matches!(binding, Binding::None) {
            Ok(None)
        } else {
            Err(corrupt(()))
        };
    };
    let raw = row
        .try_get::<_, Option<String>>(4)
        .map_err(corrupt)?
        .ok_or_else(|| corrupt(()))?;
    let evidence: Value = serde_json::from_str(&raw).map_err(corrupt)?;
    if row.try_get::<_, String>(0).map_err(corrupt)? != expected.fingerprint()
        || row.try_get::<_, String>(1).map_err(corrupt)? != request.subject()
        || row.try_get::<_, String>(2).map_err(corrupt)? != request.policy_id()
        || row.try_get::<_, String>(3).map_err(corrupt)? != request.policy_version()
        || evidence != *request.evidence()
        || row.try_get::<_, i16>(9).map_err(corrupt)? != 1
    {
        return Err(corrupt(()));
    }
    let at =
        postgres::datetime(row.try_get::<_, SystemTime>(7).map_err(corrupt)?).map_err(command)?;
    let completed = row
        .try_get::<_, Option<SystemTime>>(8)
        .map_err(corrupt)?
        .map(postgres::datetime)
        .transpose()
        .map_err(command)?;
    let id = row.try_get::<_, Option<String>>(6).map_err(corrupt)?;
    match (
        row.try_get::<_, String>(5).map_err(corrupt)?.as_str(),
        id,
        completed,
        binding,
    ) {
        ("PREPARED", None, None, Binding::Admitted(_)) => Ok(Some(Prepared {
            at,
            completion: None,
        })),
        ("COMPLETED", Some(id), Some(time), Binding::Accepted(receipt))
            if crate::is_sha256_hex(&id)
                && receipt.outcome().kind() == OutcomeKind::QualificationDecision
                && receipt.outcome().id() == id
                && receipt.accepted_at() == time =>
        {
            Ok(Some(Prepared {
                at,
                completion: Some((id, time)),
            }))
        }
        _ => Err(corrupt(())),
    }
}

/// Read the original accepted facts without acquiring the writer or publishing a
/// Decision. PREPARED is a recoverable Command, never a caller-authored approval.
async fn original_in_transaction(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    subject: &str,
    id: &crate::application::command::CommandId,
) -> Result<Option<(Request, Prepared)>> {
    if !crate::is_sha256_hex(subject) {
        return Err("QUALIFICATION_REQUEST_INVALID");
    }
    catalog(tx, namespace, subject).await.map_err(code)?;
    let row=tx.query_opt("SELECT CASE WHEN pg_catalog.octet_length(subject_strategy_fingerprint)=64 THEN subject_strategy_fingerprint END,CASE WHEN pg_catalog.octet_length(policy_id)<=128 THEN policy_id END,CASE WHEN pg_catalog.octet_length(policy_version)<=128 THEN policy_version END,CASE WHEN pg_catalog.octet_length(evidence_payload::pg_catalog.text)<=65536 THEN evidence_payload::pg_catalog.text END FROM public.qualification_command_admission WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid",&[&id.value()]).await.map_err(|_|UNAVAILABLE)?;
    let Some(row) = row else {
        return match Commands::verify_binding_in_transaction(tx, id)
            .await
            .map_err(|e| e.code())?
        {
            Binding::None => Ok(None),
            _ => Err(INVALID),
        };
    };
    if row.try_get::<_, String>(0).map_err(|_| INVALID)? != subject {
        return Err("PRODUCT_COMMAND_CONFLICT");
    }
    let evidence: Value = serde_json::from_str(
        &row.try_get::<_, Option<String>>(3)
            .map_err(|_| INVALID)?
            .ok_or(INVALID)?,
    )
    .map_err(|_| INVALID)?;
    let request = Request::new(
        id.clone(),
        subject,
        &row.try_get::<_, String>(1).map_err(|_| INVALID)?,
        &row.try_get::<_, String>(2).map_err(|_| INVALID)?,
        &evidence,
    )?;
    let admission = Admission::new(
        id.clone(),
        CommandKind::EvaluateQualification,
        &request.fingerprint()?,
    )
    .map_err(|e| e.code())?;
    let prepared = read(tx, &request, &admission)
        .await
        .map_err(code)?
        .ok_or(INVALID)?;
    Ok(Some((request, prepared)))
}
fn projection(
    subject: &str,
    id: &crate::application::command::CommandId,
    original: Option<(Request, Prepared)>,
) -> Value {
    let (request, prepared_at, completed_at, decision, state) = if let Some((request, prepared)) =
        original
    {
        let (decision, completed) = prepared
            .completion
            .map(|(id, time)| (Some(id), Some(time.to_string())))
            .unwrap_or_default();
        let state = if completed.is_some() {
            "COMPLETED"
        } else {
            "PREPARED"
        };
        (
            Some(
                json!({"subject_strategy_fingerprint":request.subject(),"policy_id":request.policy_id(),"policy_version":request.policy_version(),"evidence":request.evidence()}),
            ),
            Some(prepared.at.to_string()),
            completed,
            decision,
            state,
        )
    } else {
        (None, None, None, None, "NOT_SUBMITTED")
    };
    json!({"schema_version":1,"command_id":id.value(),"strategy_fingerprint":subject,"state":state,"request":request,"prepared_at":prepared_at,"completed_at":completed_at,"decision_fingerprint":decision})
}
pub(crate) async fn command_outcome_readonly(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    subject: &str,
    id: &crate::application::command::CommandId,
) -> Result<Value> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await.map_err(code)?;
    let value = projection(
        subject,
        id,
        original_in_transaction(&tx, namespace, subject, id).await?,
    );
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(value)
}
pub(crate) async fn original_request_readonly(
    client: &mut tokio_postgres::Client,
    namespace: &SemanticStoreId,
    subject: &str,
    id: &crate::application::command::CommandId,
) -> Result<Option<Request>> {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    transaction(&tx, namespace).await.map_err(code)?;
    let value = original_in_transaction(&tx, namespace, subject, id)
        .await?
        .map(|(request, _)| request);
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(value)
}
/// References only. This list cannot substitute for the actual Counts/Decision read.
pub(crate) async fn command_list_readonly(
    client: &mut tokio_postgres::Client,
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
    transaction(&tx, namespace).await.map_err(code)?;
    catalog(&tx, namespace, subject).await.map_err(code)?;
    let rows=tx.query("SELECT command_id::pg_catalog.text FROM public.qualification_command_admission WHERE subject_strategy_fingerprint=$1 ORDER BY command_id LIMIT 8193",&[&subject]).await.map_err(|_|UNAVAILABLE)?;
    if rows.len() > 8192 {
        return Err(UNAVAILABLE);
    }
    let mut items = Vec::new();
    let mut remaining = WORK;
    for row in rows {
        let id = crate::application::command::CommandId::new(
            &row.try_get::<_, String>(0).map_err(|_| INVALID)?,
        )
        .map_err(|_| INVALID)?;
        let value = projection(
            subject,
            &id,
            original_in_transaction(&tx, namespace, subject, &id).await?,
        );
        remaining = remaining
            .checked_sub(serde_json::to_vec(&value).map_err(|_| INVALID)?.len())
            .ok_or(UNAVAILABLE)?;
        items.push(value);
    }
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(json!({"schema_version":1,"strategy_fingerprint":subject,"items":items}))
}
/// Original completed Command facts used solely to locate the actual owning
/// Research occurrence. The caller must still read Counts and verify Decision.
pub(crate) async fn decision_requests_in_transaction(
    tx: &Transaction<'_>,
    namespace: &SemanticStoreId,
    decision: &str,
) -> Result<Vec<Request>> {
    if !crate::is_sha256_hex(decision) {
        return Err("QUALIFICATION_REQUEST_INVALID");
    }
    transaction(tx, namespace).await.map_err(code)?;
    let rows=tx.query("SELECT command_id::pg_catalog.text,CASE WHEN pg_catalog.octet_length(subject_strategy_fingerprint)=64 THEN subject_strategy_fingerprint END FROM public.qualification_command_admission WHERE decision_fingerprint=$1 ORDER BY command_id LIMIT 8193",&[&decision]).await.map_err(|_|UNAVAILABLE)?;
    if rows.len() > 8192 {
        return Err(UNAVAILABLE);
    }
    let mut result = Vec::new();
    let mut remaining = WORK;
    for row in rows {
        let id = crate::application::command::CommandId::new(
            &row.try_get::<_, String>(0).map_err(|_| INVALID)?,
        )
        .map_err(|_| INVALID)?;
        let subject: String = row.try_get(1).map_err(|_| INVALID)?;
        let (request, prepared) = original_in_transaction(tx, namespace, &subject, &id)
            .await?
            .ok_or(INVALID)?;
        if prepared.completion.as_ref().map(|c| c.0.as_str()) != Some(decision) {
            return Err(INVALID);
        }
        remaining = remaining
            .checked_sub(request.evidence().to_string().len())
            .ok_or(UNAVAILABLE)?;
        result.push(request);
    }
    Ok(result)
}
