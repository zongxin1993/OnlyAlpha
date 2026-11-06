//! Human's experimental Qualification and Promotion workflow. Original Command
//! facts are read first; only the actual owning Counts can drive the evaluator.
use crate::{
    application::{
        command::CommandId, frozen_strategy::FrozenStore,
        qualification::Request as QualificationRequest, qualification_policy::Store as Policies,
        strategy_projection,
    },
    bootstrap::{deployment, startup::Directory},
    persistence::{
        qualification_commands::{self, Qualifications},
        qualification_decision::{Store as Decisions, VerifiedDecision},
        research_evidence::{Store as Evidence, VerifiedResearchCounts},
        research_submission,
        strategy_promotion::{self, Promotions, Request as PromotionRequest},
    },
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, WORK, invalid, now, parameters},
        host_factor_studies::{failed, input},
        research_wire::{QualificationInput, QualificationResumeInput, QualifiedPromotionInput},
    },
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use serde_json::{Value, json};
use std::{collections::BTreeSet, sync::Arc, time::Instant};
type Result<T> = std::result::Result<T, Failure>;
fn response(value: Value, human: &human_access::Session) -> Response {
    ingress::attach(
        Json(value).into_response(),
        Release::Generation(human.metadata_session()),
    )
}
fn deadline(at: Instant) -> Result<()> {
    if Instant::now() >= at {
        return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
    }
    Ok(())
}
impl Host {
    fn qualification_stores(&self) -> Result<(Arc<FrozenStore>, Arc<Policies>, Arc<Decisions>)> {
        let fd = self.inputs.roots().directory(Directory::Research);
        let frozen = Arc::new(FrozenStore::open(fd).map_err(|e| failed(e.code()))?);
        let policies = Arc::new(Policies::open(fd).map_err(|e| failed(e.code()))?);
        let decisions = Arc::new(
            Decisions::open(&self.research_preparation_config.research_root).map_err(failed)?,
        );
        if frozen.namespace().map_err(|e| failed(e.code()))? != *self.inputs.namespace()
            || policies.namespace().map_err(failed)? != *self.inputs.namespace()
            || decisions.namespace().map_err(failed)? != *self.inputs.namespace()
        {
            return Err(failed("RESEARCH_SEMANTIC_STORE_MISMATCH"));
        }
        Ok((frozen, policies, decisions))
    }
    async fn qualification_counts(
        &self,
        human: &human_access::Session,
        run_id: &str,
        relation: &str,
        at: Instant,
    ) -> Result<(Arc<VerifiedResearchCounts>, Arc<FrozenStore>)> {
        deadline(at)?;
        self.human_access.check_session(human)?;
        let actor = human.subject_id()?;
        let run = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            research_submission::load(client, run_id, Some(actor))
                .await
                .map_err(failed)?
        };
        run.strategy_specification().map_err(failed)?;
        let (frozen, _, _) = self.qualification_stores()?;
        let research = self.research_preparation_config.research_root.clone();
        let runtime = self.research_preparation_config.runtime_root.clone();
        let selected = frozen.clone();
        let relation = relation.to_owned();
        let counts = tokio::task::spawn_blocking(move || {
            Evidence::open(&research)?
                .with_runtime_root(&runtime)?
                .read_verified_counts(&run, &selected, &relation)
        })
        .await
        .map_err(|_| Failure::unavailable("QUALIFICATION_EVIDENCE_UNAVAILABLE"))?
        .map_err(failed)?;
        deadline(at)?;
        self.human_access.check_session(human)?;
        counts.verify_cut().map_err(failed)?;
        Ok((Arc::new(counts), frozen))
    }
    async fn qualification_outcome(&self, subject: &str, id: &CommandId) -> Result<Value> {
        let mut reader = self.reader.lock().await;
        let client = reader
            .as_mut()
            .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        qualification_commands::command_outcome_readonly(
            client,
            self.inputs.namespace(),
            subject,
            id,
        )
        .await
        .map_err(failed)
    }
    async fn qualified_promotion_outcome(
        &self,
        subject: &str,
        id: &CommandId,
        human: &human_access::Session,
    ) -> Result<Value> {
        let mut reader = self.reader.lock().await;
        let client = reader
            .as_mut()
            .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        strategy_promotion::promotion_outcome_readonly(
            client,
            self.inputs.namespace(),
            subject,
            human.subject_id()?,
            id,
        )
        .await
        .map_err(failed)
    }
    /// Selectors and Freeze locators are reconstructed from the same original
    /// readonly PG cut. They grant no Decision, Promotion or Run capability.
    async fn qualification_decision_locators(
        &self,
        id: &str,
        human: &human_access::Session,
    ) -> Result<(QualificationRequest, Vec<String>)> {
        let mut reader = self.reader.lock().await;
        let client = reader
            .as_mut()
            .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
        let tx = client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Failure::unavailable("QUALIFICATION_COMMAND_UNAVAILABLE"))?;
        let requests = qualification_commands::decision_requests_in_transaction(
            &tx,
            self.inputs.namespace(),
            id,
        )
        .await
        .map_err(failed)?;
        let first = requests
            .first()
            .ok_or_else(|| failed("QUALIFICATION_DECISION_NOT_FOUND"))?;
        let mut candidates = BTreeSet::new();
        for request in &requests {
            if request.fingerprint().map_err(failed)? != first.fingerprint().map_err(failed)? {
                return Err(failed("QUALIFICATION_COMMAND_CORRUPT"));
            }
            for run_id in strategy_projection::freeze_run_locators_in_transaction(
                &tx,
                self.inputs.namespace(),
                human.subject_id()?,
                request.subject(),
                request.relation_fingerprint(),
            )
            .await
            .map_err(failed)?
            {
                let run = research_submission::load_in_transaction(
                    &tx,
                    &run_id,
                    Some(human.subject_id()?),
                )
                .await
                .map_err(failed)?;
                run.strategy_specification().map_err(failed)?;
                if run
                    .completion
                    .as_ref()
                    .is_none_or(|c| c.0 != request.result_fingerprint())
                {
                    return Err(failed("QUALIFICATION_COMMAND_CORRUPT"));
                }
                candidates.insert(run_id);
            }
        }
        deployment::verify_binding_in_transaction(&tx, self.inputs.namespace())
            .await
            .map_err(|e| failed(e.code()))?;
        tx.commit()
            .await
            .map_err(|_| Failure::unavailable("QUALIFICATION_COMMAND_UNAVAILABLE"))?;
        Ok((first.clone(), candidates.into_iter().collect()))
    }
    async fn qualification_decision(
        &self,
        id: &str,
        run_id: &str,
        selection: &QualificationRequest,
        human: &human_access::Session,
        at: Instant,
    ) -> Result<Arc<VerifiedDecision>> {
        let (counts, _) = self
            .qualification_counts(human, run_id, selection.relation_fingerprint(), at)
            .await?;
        selection.matches_counts(&counts).map_err(failed)?;
        let (_, policies, decisions) = self.qualification_stores()?;
        let decision = Arc::new(
            decisions
                .load_verified(policies, &counts, id)
                .map_err(failed)?,
        );
        if decision.namespace().map_err(failed)? != *self.inputs.namespace() {
            return Err(failed("RESEARCH_SEMANTIC_STORE_MISMATCH"));
        }
        decision.verify_cut().map_err(failed)?;
        Ok(decision)
    }
    pub(crate) async fn qualification_product(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        at: Instant,
    ) -> Result<Response> {
        self.human_access.check_session(&human)?;
        deadline(at)?;
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let query = parameters(request.uri())?;
        if method == Method::GET && path == "/api/v2/qualification-policies" {
            if !query.is_empty() {
                return Err(invalid());
            }
            let (_, policies, _) = self.qualification_stores()?;
            let records = policies
                .policies(WORK)
                .map_err(|e| failed(e.code()))?
                .into_iter()
                .map(|p| p.to_record())
                .collect::<Vec<_>>();
            self.human_access.check_session(&human)?;
            return Ok(response(
                json!({"schema_version":1,"policies":records}),
                &human,
            ));
        }
        if method == Method::GET && path.starts_with("/api/v2/qualification-policies/") {
            if !query.is_empty() {
                return Err(invalid());
            }
            let parts = path
                .trim_start_matches("/api/v2/qualification-policies/")
                .split('/')
                .collect::<Vec<_>>();
            if parts.len() != 3 || parts[1] != "revisions" {
                return Err(invalid());
            }
            let (_, policies, _) = self.qualification_stores()?;
            let policy = policies
                .load_exact(parts[0], parts[2], WORK)
                .map_err(|e| failed(e.code()))?;
            self.human_access.check_session(&human)?;
            return Ok(response(policy.to_record(), &human));
        }
        if method == Method::GET && path.starts_with("/api/v2/qualification-decisions/") {
            let id = path.trim_start_matches("/api/v2/qualification-decisions/");
            if !crate::is_sha256_hex(id)
                || query.len() > 1
                || query.keys().any(|k| k != "research_run_id")
            {
                return Err(invalid());
            }
            let (selection, candidates) = self.qualification_decision_locators(id, &human).await?;
            let chosen = if let Some(run) = query.get("research_run_id") {
                if !candidates.contains(run) {
                    return Err(invalid());
                }
                Some(run.clone())
            } else if candidates.len() == 1 {
                candidates.first().cloned()
            } else {
                None
            };
            let value = if let Some(run) = chosen {
                let decision = self
                    .qualification_decision(id, &run, &selection, &human, at)
                    .await?;
                decision.verify_cut().map_err(failed)?;
                json!({"schema_version":1,"decision_fingerprint":id,"state":"VERIFIED","decision":decision.record(),"research_run_id":run,"research_run_candidates":candidates})
            } else {
                if candidates.is_empty() {
                    return Err(failed("QUALIFICATION_EVIDENCE_LOCATOR_UNAVAILABLE"));
                }
                json!({"schema_version":1,"decision_fingerprint":id,"state":"LOCATOR_REQUIRED","decision":null,"research_run_id":null,"research_run_candidates":candidates})
            };
            self.human_access.check_session(&human)?;
            return Ok(response(value, &human));
        }
        if !query.is_empty() {
            return Err(invalid());
        }
        let tail = path
            .strip_prefix("/api/v2/strategies/")
            .ok_or_else(invalid)?;
        let parts = tail.split('/').collect::<Vec<_>>();
        let subject = parts[0];
        if !crate::is_sha256_hex(subject) {
            return Err(invalid());
        }
        if method == Method::GET && parts.len() == 1 {
            let (frozen, _, _) = self.qualification_stores()?;
            let source = frozen
                .load_verified(subject, WORK)
                .map_err(|e| failed(e.code()))?;
            let relations = frozen
                .relations_verified(subject, WORK)
                .map_err(|e| failed(e.code()))?
                .into_iter()
                .map(|r| r.to_record())
                .collect::<Vec<_>>();
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let ledger =
                strategy_promotion::ledger_readonly(client, self.inputs.namespace(), subject)
                    .await
                    .map_err(failed)?;
            let commands = qualification_commands::command_list_readonly(
                client,
                self.inputs.namespace(),
                subject,
            )
            .await
            .map_err(failed)?;
            self.human_access.check_session(&human)?;
            return Ok(response(
                json!({"schema_version":1,"strategy_fingerprint":subject,"stage":ledger["stage"],"source_revision":source.to_record(),"freeze_relations":relations,"promotion_records":ledger["promotion_records"],"qualification_commands":commands["items"]}),
                &human,
            ));
        }
        if method == Method::GET && parts.len() == 2 && parts[1] == "qualification-decisions" {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let value = qualification_commands::command_list_readonly(
                client,
                self.inputs.namespace(),
                subject,
            )
            .await
            .map_err(failed)?;
            self.human_access.check_session(&human)?;
            return Ok(response(value, &human));
        }
        let promotion = parts.get(1) == Some(&"qualification-promotions");
        if !promotion && parts.get(1) != Some(&"qualifications") {
            return Err(invalid());
        }
        let command_path = if parts.len() >= 4 && parts[2] == "commands" {
            Some(CommandId::new(parts[3]).map_err(|_| invalid())?)
        } else {
            None
        };
        if method == Method::GET && parts.len() == 4 {
            let id = command_path.as_ref().ok_or_else(invalid)?;
            let value = if promotion {
                self.qualified_promotion_outcome(subject, id, &human)
                    .await?
            } else {
                self.qualification_outcome(subject, id).await?
            };
            self.human_access.check_session(&human)?;
            return Ok(response(value, &human));
        }
        let resume = parts.len() == 5 && parts[4] == "resume" && command_path.is_some();
        if method != Method::POST || !(parts.len() == 2 || resume) {
            return Err(invalid());
        }
        let (id, body) = input(request).await?;
        if command_path
            .as_ref()
            .is_some_and(|original| *original != id)
        {
            return Err(invalid());
        }
        if promotion {
            let intent: QualifiedPromotionInput =
                serde_json::from_value(body).map_err(|_| invalid())?;
            intent.validate(subject).map_err(failed)?;
            let original = self
                .qualified_promotion_outcome(subject, &id, &human)
                .await?;
            let (selection, candidates) = self
                .qualification_decision_locators(&intent.qualification_decision_fingerprint, &human)
                .await?;
            if selection.subject() != subject
                || selection.relation_fingerprint() != intent.freeze_relation_fingerprint
                || selection.policy_id() != intent.policy_id
                || selection.policy_version() != intent.policy_version
            {
                return Err(failed("PRODUCT_COMMAND_CONFLICT"));
            }
            if original["state"] == "COMPLETED" {
                let record = &original["record"];
                if record["qualification_decision_fingerprint"]
                    != intent.qualification_decision_fingerprint
                    || record["reason"] != intent.reason
                    || record["evidence_fingerprints"]
                        .as_array()
                        .is_none_or(|refs| {
                            !refs.contains(&json!(intent.freeze_relation_fingerprint))
                        })
                {
                    return Err(failed("PRODUCT_COMMAND_CONFLICT"));
                }
                self.human_access.check_session(&human)?;
                return Ok(response(original, &human));
            }
            if original["state"] == "OUTCOME_UNKNOWN" {
                return Err(Failure::unavailable("PROMOTION_COMMAND_OUTCOME_UNKNOWN"));
            }
            if resume && original["state"] == "NOT_SUBMITTED" {
                return Err(failed("PROMOTION_COMMAND_NOT_FOUND"));
            }
            if !candidates.contains(&intent.research_run_id) {
                return Err(invalid());
            }
            let decision = self
                .qualification_decision(
                    &intent.qualification_decision_fingerprint,
                    &intent.research_run_id,
                    &selection,
                    &human,
                    at,
                )
                .await?;
            let request = PromotionRequest::new(
                id.clone(),
                subject,
                decision.fingerprint(),
                decision.record()["policy_fingerprint"]
                    .as_str()
                    .ok_or_else(invalid)?,
                &intent.reason,
            )
            .map_err(failed)?;
            deadline(at)?;
            self.human_access.check_session(&human)?;
            let (frozen, _, _) = self.qualification_stores()?;
            {
                let mut writer = self.writer.lock().await;
                let session = writer
                    .as_mut()
                    .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                Promotions::new(
                    session,
                    self.inputs.namespace(),
                    frozen,
                    &self.human_access,
                    &human,
                )
                .promote(&request, decision, now()?)
                .await
                .map_err(failed)?;
            }
            let value = self
                .qualified_promotion_outcome(subject, &id, &human)
                .await?;
            self.human_access.check_session(&human)?;
            return Ok(response(value, &human));
        }
        let original = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            qualification_commands::original_request_readonly(
                client,
                self.inputs.namespace(),
                subject,
                &id,
            )
            .await
            .map_err(failed)?
        };
        let (run_id, selection) = if resume {
            let intent: QualificationResumeInput =
                serde_json::from_value(body).map_err(|_| invalid())?;
            intent.validate().map_err(failed)?;
            (
                intent.research_run_id,
                Some(original.ok_or_else(|| failed("QUALIFICATION_COMMAND_NOT_FOUND"))?),
            )
        } else {
            let intent: QualificationInput = serde_json::from_value(body).map_err(|_| invalid())?;
            intent.validate(subject).map_err(failed)?;
            if let Some(original) = original {
                if original.policy_id() != intent.policy_id
                    || original.policy_version() != intent.policy_version
                    || original.relation_fingerprint() != intent.freeze_relation_fingerprint
                {
                    return Err(failed("PRODUCT_COMMAND_CONFLICT"));
                }
                self.human_access.check_session(&human)?;
                return Ok(response(
                    self.qualification_outcome(subject, &id).await?,
                    &human,
                ));
            }
            let (counts, frozen) = self
                .qualification_counts(
                    &human,
                    &intent.research_run_id,
                    &intent.freeze_relation_fingerprint,
                    at,
                )
                .await?;
            let request = QualificationRequest::from_counts(
                id.clone(),
                &intent.policy_id,
                &intent.policy_version,
                &counts,
            )
            .map_err(failed)?;
            if request.subject() != subject {
                return Err(failed("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH"));
            }
            self.run_qualification(&request, counts, frozen, &human, at)
                .await?;
            let value = self.qualification_outcome(subject, &id).await?;
            self.human_access.check_session(&human)?;
            return Ok(response(value, &human));
        };
        let selection = selection.ok_or_else(invalid)?;
        let observed = self.qualification_outcome(subject, &id).await?;
        if observed["state"] == "COMPLETED" {
            self.human_access.check_session(&human)?;
            return Ok(response(observed, &human));
        }
        let (counts, frozen) = self
            .qualification_counts(&human, &run_id, selection.relation_fingerprint(), at)
            .await?;
        selection.matches_counts(&counts).map_err(failed)?;
        self.run_qualification(&selection, counts, frozen, &human, at)
            .await?;
        let value = self.qualification_outcome(subject, &id).await?;
        self.human_access.check_session(&human)?;
        Ok(response(value, &human))
    }
    async fn run_qualification(
        &self,
        request: &QualificationRequest,
        counts: Arc<VerifiedResearchCounts>,
        frozen: Arc<FrozenStore>,
        human: &human_access::Session,
        at: Instant,
    ) -> Result<()> {
        deadline(at)?;
        self.human_access.check_session(human)?;
        let (_, policies, decisions) = self.qualification_stores()?;
        let mut writer = self.writer.lock().await;
        let session = writer
            .as_mut()
            .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        let result = Qualifications::new(
            session,
            self.inputs.namespace(),
            policies,
            decisions,
            frozen,
            &self.human_access,
            human,
        )
        .execute(request, counts, now()?)
        .await
        .map_err(failed)?;
        result.verify_cut().map_err(failed)?;
        Ok(())
    }
}
