//! Direct Human observation and cancellation use the original Run/Evidence owners.
use crate::{
    application::{command::CommandId, research_run::VerifiedRun},
    persistence::{
        research_evidence, research_execution::ResearchExecution, research_novelty::Authority,
        research_submission,
    },
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, invalid, now},
        host_factor_studies::{failed, input},
        research_wire::*,
    },
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use serde_json::Value;
use std::{path::Path, sync::Arc, time::Instant};

/// One read composition, without changing Run state or creating execution permission.
#[derive(serde::Serialize)]
pub struct ReportRead {
    pub report: Option<FactorResearchReport>,
    pub report_status: FactorResearchReportAvailability,
    pub decision_provenance: FactorResearchDecisionProvenance,
}
fn decision_provenance(
    run: &VerifiedRun,
    state: FactorResearchDecisionState,
) -> FactorResearchDecisionProvenance {
    let reference = &run.decision_reference;
    let code = if matches!(state, FactorResearchDecisionState::Unavailable) {
        Some("HISTORICAL_PROOF_UNAVAILABLE".into())
    } else {
        None
    };
    FactorResearchDecisionProvenance {
        state,
        code,
        command_id: reference.command.value().into(),
        group_fingerprint: reference.group_fingerprint.clone(),
        policy_id: reference.policy_id.clone(),
        policy_version: reference.policy_version.clone(),
    }
}
fn diagnostic_report(run: &VerifiedRun) -> ReportRead {
    ReportRead {
        report: None,
        report_status: FactorResearchReportAvailability {
            state: FactorResearchReportState::NotApplicable,
            code: None,
        },
        decision_provenance: decision_provenance(run, FactorResearchDecisionState::NotChecked),
    }
}
async fn numeric_report(
    root: &Path,
    run: &VerifiedRun,
) -> (
    Option<FactorResearchReport>,
    FactorResearchReportAvailability,
) {
    let root = root.to_owned();
    let original = run.clone();
    let loaded = tokio::task::spawn_blocking(move || {
        let artifact = research_evidence::Store::open(&root)?.read_report(&original)?;
        report_projection(&original, artifact)
    })
    .await;
    match loaded {
        Ok(Ok(report)) => (
            Some(report),
            FactorResearchReportAvailability {
                state: FactorResearchReportState::Verified,
                code: None,
            },
        ),
        _ => (
            None,
            FactorResearchReportAvailability {
                state: FactorResearchReportState::Unavailable,
                code: Some("RESEARCH_REPORT_UNAVAILABLE".into()),
            },
        ),
    }
}
/// Actual Host and integration checks share this owning historical reader.
/// The VerifiedRun comes from its immutable Human/DB admission, never supplied JSON.
pub async fn completed_report(
    client: &mut tokio_postgres::Client,
    authority: &Authority,
    root: &Path,
    run: &VerifiedRun,
) -> ReportRead {
    let reference = &run.decision_reference;
    let verified = async {
        let subject = run.specification().subject()?;
        let group = authority
            .retained_group(
                client,
                &reference.command,
                &[subject],
                &reference.policy_id,
                &reference.policy_version,
            )
            .await?;
        reference.verify_group(&group)
    }
    .await;
    let decision_provenance = decision_provenance(
        run,
        if verified.is_ok() {
            FactorResearchDecisionState::Verified
        } else {
            FactorResearchDecisionState::Unavailable
        },
    );
    let (report, report_status) = numeric_report(root, run).await;
    ReportRead {
        report,
        report_status,
        decision_provenance,
    }
}

fn report_projection(
    run: &VerifiedRun,
    artifact: Value,
) -> Result<FactorResearchReport, &'static str> {
    let invalid = "RESEARCH_REPORT_PROJECTION_INVALID";
    let spec = run.specification();
    let bindings = run.prepared_inputs["dataset_materialization"]["market_data_revision_bindings"]
        .as_array()
        .filter(|v| v.len() == 1)
        .ok_or(invalid)?;
    let instrument_id = bindings[0]["instrument_id"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or(invalid)?
        .to_owned();
    let minute_ns = 60_000_000_000;
    if spec.study.bar_ns == 0 || !spec.study.bar_ns.is_multiple_of(minute_ns) {
        return Err(invalid);
    }
    let timeframe_minutes = spec.study.bar_ns / minute_ns;
    let timestamp = |ns: u64| {
        onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(ns.into())
            .to_datetime_exact()
            .map(|v| v.to_string())
            .map_err(|_| invalid)
    };
    let statistics = artifact["statistics"].as_array().ok_or(invalid)?;
    if statistics.len() != spec.study.samples.len() {
        return Err(invalid);
    }
    let samples = spec
        .study
        .samples
        .iter()
        .map(|sample| {
            let expected = serde_json::to_value(sample).map_err(|_| invalid)?;
            let selected = statistics
                .iter()
                .filter(|s| s["intent"]["sample"] == expected)
                .collect::<Vec<_>>();
            if selected.len() != 1 {
                return Err(invalid);
            }
            let s = selected[0];
            Ok(FactorResearchSample {
                start_at: timestamp(sample.start_ns)?,
                end_at: timestamp(sample.end_ns)?,
                role: serde_json::to_value(sample.role)
                    .map_err(|_| invalid)?
                    .as_str()
                    .ok_or(invalid)?
                    .into(),
                diagnostics: s["analysis"]["diagnostics"].clone(),
                pearson: s["analysis"]["pearson"].clone(),
                spearman: s["analysis"]["spearman"].clone(),
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    // Do not parse through JavaScript numbers: timestamps and original fingerprints
    // remain exact in these canonical strings. This projection never re-estimates values.
    let canonical_artifact =
        onlyalpha_metadata_json::canonical_json(&artifact.to_string(), 8 * 1024 * 1024)
            .map_err(|_| invalid)?;
    Ok(FactorResearchReport{
        instrument_id,timeframe_minutes,horizon_bars:spec.study.horizon_bars,
        research_result_fingerprint:artifact["research_result_fingerprint"].as_str().ok_or(invalid)?.into(),
        artifact_content_fingerprint:artifact["artifact_content_fingerprint"].as_str().ok_or(invalid)?.into(),samples,
        confidence_bps:spec.study.confidence_bps,expected_block_length:spec.study.expected_block_length,replicates:spec.study.replicates,
        comparison_count:spec.study.comparison_family()?.len(),
        limitations:vec!["单标的时间序列关联；相关性不证明因果、交易收益或因子有效。".into(),
            "区间使用配对平稳块自助法，并对本次完整比较族调整；结果依赖预先确认的块长度和样本条件。".into(),
            "受保护样本未读取；本报告不提供 Backtest、SIM、LIVE 或自动收录授权。".into()],
        canonical_artifact,canonical_specification:run.canonical_specification_payload().into(),
    })
}
impl Host {
    pub(crate) async fn factor_research_run(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        let owner = human.subject_id()?.to_owned();
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let tail = path
            .strip_prefix("/api/v2/research/runs/")
            .ok_or_else(invalid)?;
        let id = tail
            .strip_suffix("/cancellation")
            .unwrap_or(tail)
            .to_owned();
        CommandId::new(&id).map_err(|_| invalid())?;
        let cancel = if method == Method::POST {
            if !path.ends_with("/cancellation") {
                return Err(invalid());
            }
            let (command, body) = input(request).await?;
            let body: FactorResearchCancellationInput =
                serde_json::from_value(body).map_err(|_| invalid())?;
            if body.schema_version != 1 || body.run_id != id {
                return Err(invalid());
            }
            Some(command)
        } else if method == Method::GET {
            None
        } else {
            return Err(invalid());
        };
        if Instant::now() >= deadline {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let cancellation_response = cancel.is_some();
        if let Some(command) = cancel {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            research_submission::cancel(client, (&self.human_access, &human), command, &id, now()?)
                .await
                .map_err(failed)?;
            drop(writer);
            self.wake_research_after_commit();
        }
        if Instant::now() >= deadline {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let (run, status, current_name, failure) = {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let current = research_submission::load(client, &id, Some(&owner))
                .await
                .map_err(failed)?;
            let status = ResearchExecution::new(client)
                .observe(&current)
                .await
                .map_err(failed)?;
            let names = crate::persistence::private_factor_postgres::Factors::new(client)
                .read(
                    current.specification().revision["factor_id"]
                        .as_str()
                        .ok_or_else(invalid)?,
                )
                .await
                .map_err(|e| failed(e.code()))?;
            let raw=client.query_one("SELECT failure_phase,failure_code,failure_detail FROM research_run WHERE run_id=$1::text::uuid AND revision=$2",&[&id,&status.revision]).await.map_err(|_|Failure::unavailable("RESEARCH_EXECUTION_STORE_UNAVAILABLE"))?;
            let failure=raw.get::<_,Option<String>>(1).map(|code|serde_json::json!({"phase":raw.get::<_,Option<String>>(0),"code":code,"detail":raw.get::<_,Option<String>>(2)}));
            (
                current,
                status,
                names["display"]["display_name"].as_str().map(str::to_owned),
                failure,
            )
        };
        let report = if !cancellation_response
            && status.state == crate::persistence::research_execution::RunState::Completed
        {
            let root = &self.research_preparation_config.research_root;
            let authority = root
                .parent()
                .ok_or("RESEARCH_OWNER_PROFILE_UNAVAILABLE")
                .and_then(crate::bootstrap::research_namespace::novelty);
            let mut reader = self.reader.lock().await;
            if let (Some(client), Ok(authority)) = (reader.as_mut(), authority.as_ref()) {
                completed_report(client, authority, root, &run).await
            } else {
                let (report, report_status) = numeric_report(root, &run).await;
                ReportRead {
                    report,
                    report_status,
                    decision_provenance: decision_provenance(
                        &run,
                        FactorResearchDecisionState::Unavailable,
                    ),
                }
            }
        } else {
            diagnostic_report(&run)
        };
        self.human_access.check_session(&human)?;
        use crate::workers::research_service::Status;
        let worker_observation = match self.research_worker_status().await {
            Some(Status::Starting) => serde_json::json!({"state":"STARTING"}),
            Some(Status::Idle) => serde_json::json!({"state":"IDLE"}),
            Some(Status::Running(work)) => serde_json::json!({"state":"RUNNING","run_id":work}),
            Some(Status::Uncertain(code)) => serde_json::json!({"state":"UNKNOWN","code":code}),
            Some(Status::Unavailable(code)) => {
                serde_json::json!({"state":"UNAVAILABLE","code":code})
            }
            Some(Status::Stopped) => serde_json::json!({"state":"STOPPED"}),
            None => {
                serde_json::json!({"state":"UNAVAILABLE","code":"RESEARCH_SERVICE_UNAVAILABLE"})
            }
        };
        Ok(ingress::attach(
            Json(FactorResearchRunView {
                schema_version: 1,
                run_id: id,
                state: status.state.as_str().into(),
                revision: status.revision.to_string(),
                name_snapshot: run.name_snapshot.clone(),
                current_name,
                accepted_at: run.accepted_at.clone(),
                specification_fingerprint: run.specification_fingerprint().into(),
                runtime_generation_fingerprint: run.runtime_generation_fingerprint().into(),
                report: report.report,
                report_status: report.report_status,
                decision_provenance: report.decision_provenance,
                failure,
                worker_observation,
            })
            .into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}
