//! Discover verified original operations and new-work prerequisites. This admits no work.
use crate::{
    application::factor_studies::Advice,
    persistence::{
        factor_studies::Studies,
        private_factor_postgres::Factors,
        research_preparation::{Operation, Preparations},
        research_runtime::Registry,
    },
    security::{
        human_access,
        ingress::{self, Release},
        protected_files::{self, FilePolicy},
    },
    transport::{
        host::{Failure, Host, now},
        host_factor_studies::failed,
        research_wire::{
            FactorResearchNewWorkStatus, FactorResearchPreparationContext,
            FactorResearchPreparationSummary,
        },
    },
};
use axum::{
    Json,
    response::{IntoResponse, Response},
};
use serde_json::Value;
use std::sync::Arc;

fn preparation_summary(operation: Operation) -> Result<FactorResearchPreparationSummary, Failure> {
    Ok(FactorResearchPreparationSummary {
        command_id: operation.command.value().into(),
        revision: operation.revision.to_string(),
        state: operation.state.as_str().into(),
        study_proposal_fingerprint: operation.request.study_proposal_fingerprint,
        accepted_at: operation.accepted["accepted_at"]
            .as_str()
            .ok_or(Failure::unavailable("RESEARCH_PREPARATION_CORRUPT"))?
            .into(),
    })
}

impl Host {
    pub(crate) async fn research_preparation_context(
        self: &Arc<Self>,
        human: human_access::Session,
        pin: &str,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        let owner = human.subject_id()?.to_owned();
        let (view, names, operations, runtime_retained, conditions_unavailable) = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let view = Studies::new(client)
                .read(pin, &owner, None, &now()?.to_string())
                .await
                .map_err(failed)?;
            let factor = view["snapshot"]["factor_id"]
                .as_str()
                .ok_or(Failure::unavailable("FACTOR_STUDY_PROPOSAL_CORRUPT"))?;
            let names = Factors::new(client)
                .read(factor)
                .await
                .map_err(|e| failed(e.code()))?;
            let operations = Preparations::new(client)
                .for_factor(factor, &owner)
                .await
                .map_err(failed)?;
            let tx = client
                .transaction()
                .await
                .map_err(|_| Failure::unavailable("RESEARCH_PREPARATION_UNAVAILABLE"))?;
            crate::persistence::postgres::bounds(&tx)
                .await
                .map_err(|_| Failure::unavailable("RESEARCH_PREPARATION_UNAVAILABLE"))?;
            let factor_proposal = view["snapshot"]["factor_proposal_fingerprint"]
                .as_str()
                .ok_or(Failure::unavailable("FACTOR_STUDY_PROPOSAL_CORRUPT"))?;
            let confirmed = crate::persistence::factor_proposals::confirmed_research_input(
                &tx,
                factor_proposal,
                &owner,
                false,
            )
            .await
            .map_err(failed)?;
            let conditions_unavailable =
                crate::persistence::research_preparation::validated_inputs(
                    &view["snapshot"],
                    &confirmed,
                )
                .err()
                .map(str::to_owned);
            let runtime_retained =
                crate::persistence::research_preparation::runtime_history_exists(&tx)
                    .await
                    .map_err(failed)?;
            tx.commit()
                .await
                .map_err(|_| Failure::unavailable("RESEARCH_PREPARATION_UNAVAILABLE"))?;
            (
                view,
                names,
                operations,
                runtime_retained,
                conditions_unavailable,
            )
        };
        let advice: Advice = serde_json::from_value(view["snapshot"]["advice"].clone())
            .map_err(|_| Failure::unavailable("FACTOR_STUDY_PROPOSAL_CORRUPT"))?;
        // Current execution prerequisites are observations, not prerequisites for
        // discovering a previously accepted operation and its original Run.
        let source = self
            .snapshots()
            .await
            .map_err(|e| e.code().to_owned())
            .and_then(|snapshots| {
                snapshots
                    .iter()
                    .find(|s| {
                        s.integration().record().integration_id.value()
                            == advice.source.integration_id
                    })
                    .map(|s| s.integration().record().display_name.clone())
                    .ok_or_else(|| "RESEARCH_SOURCE_METADATA_UNAVAILABLE".to_owned())
            });
        let config = self.research_preparation_config.clone();
        let selected = tokio::task::spawn_blocking(move || -> Result<_, &'static str> {
            crate::bootstrap::research_namespace::open_existing(
                config
                    .research_root
                    .parent()
                    .ok_or("RESEARCH_OWNER_PROFILE_INVALID")?,
            )?;
            let (active, fresh) = match std::fs::symlink_metadata(&config.runtime_root) {
                Ok(_) => {
                    let record = Registry::inspect(&config.runtime_root)?;
                    let active = record["active_for_new_work"].as_str().map(str::to_owned);
                    (active, false)
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound && !runtime_retained => {
                    (None, true)
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    return Err("RESEARCH_RUNTIME_HISTORY_UNAVAILABLE");
                }
                Err(_) => return Err("RESEARCH_RUNTIME_UNAVAILABLE"),
            };
            let directory = protected_files::open_directory(&config.release_root)
                .map_err(|_| "RESEARCH_RELEASE_UNAVAILABLE")?;
            let raw = protected_files::read_file_at(
                &directory,
                "manifest.json".as_ref(),
                FilePolicy::HistoryDocument,
                8 * 1024 * 1024,
            )
            .map_err(|_| "RESEARCH_RELEASE_UNAVAILABLE")?;
            use sha2::{Digest, Sha256};
            if Sha256::digest(&raw)
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
                != config.release_manifest_fingerprint
            {
                return Err("RESEARCH_RELEASE_CHANGED");
            }
            let selected: Value =
                serde_json::from_slice(&raw).map_err(|_| "RESEARCH_RELEASE_UNAVAILABLE")?;
            let artifact = selected["algorithm_artifact"]
                .as_str()
                .filter(|s| crate::is_sha256_hex(s))
                .ok_or("RESEARCH_RELEASE_UNAVAILABLE")?
                .to_owned();
            Ok((active, fresh, artifact))
        })
        .await
        .unwrap_or(Err("RESEARCH_PREPARATION_CONTEXT_UNAVAILABLE"));
        let code = conditions_unavailable
            .or_else(|| source.as_ref().err().cloned())
            .or_else(|| selected.as_ref().err().map(|e| (*e).to_owned()));
        let source_label = source.ok();
        let (active, fresh, algorithm) = match selected {
            Ok((active, fresh, algorithm)) => (active, fresh, Some(algorithm)),
            Err(_) => (None, false, None),
        };
        let new_work_status = FactorResearchNewWorkStatus {
            state: if code.is_none() {
                "AVAILABLE"
            } else {
                "UNAVAILABLE"
            }
            .into(),
            code,
        };
        // for_factor already verifies each original owner/Command/Factor relation.
        // History discovery must not reopen every retained physical proof. The
        // selected operation and Human confirmation still verify their own proof.
        let existing = operations
            .into_iter()
            .map(preparation_summary)
            .collect::<Result<Vec<_>, _>>()?;
        let display = &names["display"];
        self.human_access.check_session(&human)?;
        Ok(ingress::attach(
            Json(FactorResearchPreparationContext {
                schema_version: 1,
                study_proposal_fingerprint: pin.into(),
                factor_proposal_fingerprint: view["snapshot"]["factor_proposal_fingerprint"]
                    .as_str()
                    .ok_or(Failure::unavailable("FACTOR_STUDY_PROPOSAL_CORRUPT"))?
                    .into(),
                factor_name: display["display_name"]
                    .as_str()
                    .ok_or(Failure::unavailable("PRIVATE_FACTOR_DISPLAY_UNAVAILABLE"))?
                    .into(),
                usage_summary: display["usage_summary"]
                    .as_str()
                    .ok_or(Failure::unavailable("PRIVATE_FACTOR_DISPLAY_UNAVAILABLE"))?
                    .into(),
                source_label,
                advice,
                is_current: view["is_current"] == true,
                withdrawn: view["withdrawn"] == true,
                release_manifest_fingerprint: self
                    .research_preparation_config
                    .release_manifest_fingerprint
                    .clone(),
                backend_version: self.research_preparation_config.native_version.clone(),
                algorithm_artifact_fingerprint: algorithm,
                expected_active_generation: active,
                initialize_fresh_runtime: fresh,
                profile: crate::bootstrap::research_namespace::profile(),
                policy: crate::bootstrap::research_namespace::policy(),
                new_work_status,
                existing_preparations: existing,
            })
            .into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        application::{command::CommandId, factor_studies::PrepareInput},
        persistence::research_preparation::State,
    };
    use serde_json::json;

    fn operation() -> Operation {
        Operation {
            command: CommandId::new("00000000-0000-4000-8000-000000000001").unwrap(),
            owner: "owner".into(),
            request: PrepareInput {
                schema_version: 1,
                study_proposal_fingerprint: "a".repeat(64),
                release_manifest_fingerprint: "b".repeat(64),
                expected_active_generation: None,
                initialize_fresh_runtime: false,
                research_command_id: "00000000-0000-4000-8000-000000000002".into(),
            },
            accepted: json!({"accepted_at":"2026-10-30T00:00:00Z"}),
            revision: 9_007_199_254_740_993,
            state: State::Ready,
            phase: "READY_FOR_HUMAN_CONFIRMATION".into(),
            // Discovery cannot certify a physical proof or an accepted Run from
            // retained outputs. Those must be read at the selected owner.
            outputs: json!({"ready":{"proof":"not observed by discovery"}}),
            detail: Value::Null,
        }
    }

    #[test]
    fn discovery_retains_every_workflow_state_without_claiming_execution_proof() {
        for state in [
            State::Accepted,
            State::Running,
            State::InputPending,
            State::Ready,
            State::Blocked,
            State::Unknown,
            State::CancelRequested,
            State::Cancelled,
        ] {
            let mut original = operation();
            original.state = state;
            let summary = preparation_summary(original).ok().unwrap();
            let value = serde_json::to_value(summary).unwrap();
            assert_eq!(
                value,
                json!({
                    "command_id":"00000000-0000-4000-8000-000000000001",
                    "revision":"9007199254740993",
                    "state":state.as_str(),
                    "study_proposal_fingerprint":"a".repeat(64),
                    "accepted_at":"2026-10-30T00:00:00Z"
                })
            );
            for field in ["readiness", "research_outcome", "run_id"] {
                let mut invalid = value.clone();
                invalid[field] = json!("VERIFIED");
                assert!(
                    serde_json::from_value::<FactorResearchPreparationSummary>(invalid).is_err()
                );
            }
        }
    }

    #[test]
    fn discovery_does_not_replace_a_missing_accepted_fact_with_a_default() {
        let mut original = operation();
        original.accepted = Value::Null;
        assert!(preparation_summary(original).is_err());
    }
}
