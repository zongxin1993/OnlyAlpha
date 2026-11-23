//! Human observations use the original admitted Run and its owning evidence.
//! Financial values are projected from native owners; Web does not recompute them.
use crate::{
    application::{
        backtest_run::{self, CancelRequest},
        job_contract::{JobKind, MemberKind},
        source_access::{Reference, Selection},
    },
    persistence::{
        backtest_run::{self as runs, Backtests, RunState, RunStatus},
        job_publication::{PublicationError, PublicationRepository, PublishedJobResult, RunLocator},
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
use http::{Method, Request, StatusCode};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_observability::{Correlation, Operation};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Instant};
use tracing::Instrument;

const INVALID: &str = "BACKTEST_RESULT_CORRUPT";
const NOT_READY: &str = "BACKTEST_RESULT_NOT_READY";
struct BacktestPublication {
    publication: PublishedJobResult,
    result: BacktestResultView,
}

fn member(
    publication: &PublishedJobResult,
    key: &str,
    kind: MemberKind,
) -> Result<Value, PublicationError> {
    let raw = publication
        .content(key)
        .ok_or(PublicationError::MissingEvidence)?;
    let value: Value = serde_json::from_str(raw).map_err(|_| PublicationError::Integrity)?;
    if value["schema_version"] != 1 || value["kind"] != json!(kind) {
        return Err(PublicationError::Integrity);
    }
    Ok(value)
}

fn root_member(publication: &PublishedJobResult, kind: MemberKind) -> Result<Value, PublicationError> {
    let mut keys = publication.member_keys(kind);
    let key = keys.next().ok_or(PublicationError::MissingEvidence)?;
    if keys.next().is_some() {
        return Err(PublicationError::Integrity);
    }
    let mut value = member(publication, key, kind)?;
    value
        .as_object_mut()
        .and_then(|fields| fields.remove("body"))
        .filter(Value::is_object)
        .ok_or(PublicationError::Integrity)
}

fn member_rows(
    publication: &PublishedJobResult,
    kind: MemberKind,
) -> Result<Vec<Value>, PublicationError> {
    let mut rows = Vec::new();
    for key in publication.member_keys(kind) {
        let mut value = member(publication, key, kind)?;
        let partition = value
            .get_mut("rows")
            .and_then(Value::as_array_mut)
            .ok_or(PublicationError::Integrity)?;
        rows.append(partition);
    }
    Ok(rows)
}

impl BacktestPublication {
    fn verify(
        run: &backtest_run::VerifiedRun,
        publication: PublishedJobResult,
    ) -> Result<Self, Failure> {
        let fp = publication.fingerprint();
        let binding = publication.binding();
        let record = binding.record();
        let resolution = run.resolution();
        if binding.kind() != JobKind::Backtest
            || binding.run_id() != run.run_id()
            || binding.namespace() != run.namespace().value()
            || binding.owner() != run.owner()
            || publication.specification_fingerprint() != run.specification_fingerprint()
            || publication.admission_fingerprint() != run.admission_resolution_fingerprint()
            || run.completion_fingerprints() != Some((fp, fp, fp))
            || record["runtime_generation"] != run.runtime_generation_fingerprint()
            || record["kernel_artifact"] != resolution["backtest_binding"]["executor_artifact_sha256"]
            || record["market"]["dataset_snapshot"] != resolution["dataset_snapshot_fingerprint"]
        {
            return Err(publication_failure(PublicationError::Mismatch));
        }
        let causal = root_member(&publication, MemberKind::CausalEvidence)
            .map_err(publication_failure)?;
        let refs = binding
            .result_plan()
            .members()
            .iter()
            .filter(|member| member.kind() != MemberKind::CausalEvidence)
            .map(|member| {
                let key = member.key();
                let fingerprint = publication
                    .content_fingerprint(key)
                    .ok_or(PublicationError::MissingEvidence)?;
                Ok(json!({"key": key, "content": fingerprint}))
            })
            .collect::<Result<Vec<_>, PublicationError>>()
            .map_err(publication_failure)?;
        let execution = &causal["execution"];
        let execution_fingerprint = crate::application::factor_content::hash(&execution["execution_binding"])
            .map_err(|_| publication_failure(PublicationError::Integrity))?;
        if causal["binding"] != record
            || causal["members"] != json!(refs)
            || execution["runtime_binding"]["execution"] != record["execution_configuration"]
            || execution["native_image"]["artifact"] != record["kernel_artifact"]
            || execution_fingerprint != record["execution_configuration"]
        {
            return Err(publication_failure(PublicationError::Mismatch));
        }
        let economics = root_member(&publication, MemberKind::EconomicResult)
            .map_err(publication_failure)?;
        if economics["preparation"] != resolution["preparation"]
            || economics["economic_result"]["run"]["status"] != "COMPLETED"
        {
            return Err(publication_failure(PublicationError::Mismatch));
        }
        let result = crate::workers::backtest_profile::measure(run.run_id(), "http.result.project", || {
            display_result(run, &publication, &economics)
        })?;
        Ok(Self { publication, result })
    }
}
pub(super) fn worker_observation(
    status: Option<crate::workers::backtest_worker::Status>,
) -> BacktestWorkerObservation {
    use crate::workers::backtest_worker::Status;
    use BacktestWorkerState::*;
    let (state, code, run_id) = match status {
        Some(Status::Starting) => (Starting, None, None),
        Some(Status::Idle) => (Idle, None, None),
        Some(Status::Running(run)) => (Running, None, Some(run)),
        Some(Status::Uncertain(code)) => (Unknown, Some(code.into()), None),
        Some(Status::Unavailable(code)) => (Unavailable, Some(code.into()), None),
        Some(Status::Stopped) => (Stopped, None, None),
        None => (
            Unavailable,
            Some("BACKTEST_SERVICE_UNAVAILABLE".into()),
            None,
        ),
    };
    BacktestWorkerObservation {
        state,
        code,
        run_id,
    }
}
pub(super) fn require_worker(
    status: Option<crate::workers::backtest_worker::Status>,
) -> Result<(), Failure> {
    use crate::workers::backtest_worker::Status;
    match status {
        Some(Status::Starting | Status::Idle | Status::Running(_)) => Ok(()),
        _ => Err(Failure::unavailable("BACKTEST_SERVICE_UNAVAILABLE")),
    }
}
fn text(value: &Value) -> Result<String, Failure> {
    value
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| failed(INVALID))
}
fn optional_text(value: &Value, key: &str) -> Result<Option<String>, Failure> {
    match value.get(key).ok_or_else(|| failed(INVALID))? {
        Value::Null => Ok(None),
        value => text(value).map(Some),
    }
}
fn number(value: &Value) -> Result<u64, Failure> {
    value.as_u64().ok_or_else(|| failed(INVALID))
}
fn instant(value: &Value) -> Result<String, Failure> {
    let n = text(value)?
        .parse::<bigdecimal::num_bigint::BigInt>()
        .map_err(|_| failed(INVALID))?;
    OnlyTimestamp::from_unix_nanos(n)
        .to_datetime_exact()
        .map(|v| v.to_string())
        .map_err(|_| failed(INVALID))
}
fn run_view(
    run: &backtest_run::VerifiedRun,
    status: RunStatus,
    preparation: Option<String>,
    worker: Option<crate::workers::backtest_worker::Status>,
) -> Result<BacktestRunView, Failure> {
    let state = match status.state {
        RunState::Queued | RunState::Running | RunState::CancelRequested => {
            BacktestReportState::Pending
        }
        RunState::Cancelled | RunState::Failed => BacktestReportState::NotApplicable,
        RunState::Completed => BacktestReportState::NotChecked,
    };
    let cancel_requested_at = match status.state {
        RunState::CancelRequested | RunState::Cancelled => run
            .cancel_requested_at()
            .map(crate::transport::host::observation_time)
            .transpose()?
            .map(|at| at.to_string()),
        _ => None,
    };
    Ok(BacktestRunView {
        schema_version: 1,
        run_id: run.run_id().into(),
        strategy_fingerprint: text(&run.specification().record()["strategy_fingerprint"])?,
        state: status.state.as_str().into(),
        revision: status.revision.to_string(),
        accepted_at: text(&run.record()["accepted_at"])?,
        preparation_command_id: preparation,
        cancellation_reason: cancel_requested_at.as_ref().map(|_| BacktestCancellationReason::UserRequested),
        cancel_requested_at,
        report_status: BacktestReportAvailability { state, code: None },
        worker_observation: Some(worker_observation(worker)),
    })
}

fn display_result(
    run: &backtest_run::VerifiedRun,
    publication: &PublishedJobResult,
    economics: &Value,
) -> Result<BacktestResultView, Failure> {
    let result = &economics["economic_result"];
    let preparation = &economics["preparation"];
    let summary = &result["runtime_performance"]["summary"];
    let metrics = BacktestMetrics {
        initial_equity: text(&summary["initial_equity"])?,
        final_equity: text(&summary["final_equity"])?,
        return_since_start: optional_text(summary, "return_since_start")?,
        net_pnl: text(&summary["net_pnl"])?,
        realized_pnl: text(&summary["realized_pnl"])?,
        unrealized_pnl: text(&summary["unrealized_pnl"])?,
        fees: text(&summary["fees"])?,
        maximum_drawdown: optional_text(summary, "maximum_drawdown")?,
        fill_count: number(&result["execution"]["trade_count"])?,
        roundtrip_count: number(&economics["roundtrip_count"])?,
    };
    let curve = member_rows(publication, MemberKind::CloseCurve)
        .map_err(publication_failure)?
        .iter()
        .map(|v| {
            Ok(BacktestCurvePoint {
                at_ns: text(&v["bar_end_ns"])?,
                nav: text(&v["nav"])?,
                drawdown: optional_text(v, "drawdown")?,
            })
        })
        .collect::<Result<Vec<_>, Failure>>()?;
    let b = &economics["analytical_baseline"];
    let baseline = Some(BacktestBaseline {
        final_equity: text(&b["final_equity"])?,
        net_pnl: text(&b["net_pnl"])?,
        return_since_start: text(&b["return_since_start"])?,
    });
    let facts = member_rows(publication, MemberKind::ExecutionFacts)
        .map_err(publication_failure)?;
    let mut openings = BTreeMap::new();
    let mut execution_fills = Vec::new();
    for row in &facts {
        let body = &row["body"];
        if row["family"] == "OPEN" && body["status"] == "FILLED" {
            let order = body["order"].as_str().ok_or_else(|| failed(INVALID))?;
            if openings.insert(order, body).is_some() {
                return Err(failed(INVALID));
            }
        }
        if row["family"] == "EXECUTION" && body["input"]["op"] == "FILL" {
            execution_fills.push(body);
        }
    }
    let fills = result["trades"].as_array().ok_or_else(|| failed(INVALID))?;
    if openings.len() != fills.len()
        || execution_fills.len() != fills.len()
        || metrics.fill_count != fills.len() as u64
    {
        return Err(failed(INVALID));
    }
    let mut trades = Vec::with_capacity(fills.len());
    for (ordinal, (fact, applied)) in fills.iter().zip(execution_fills).enumerate() {
        let input = &fact["input"];
        let payload = &input["payload"];
        let order = text(&payload["order"])?;
        let opening = openings.remove(order.as_str()).ok_or_else(|| failed(INVALID))?;
        let side = text(&opening["signal"]["side"])?;
        let fee = &opening["economic_evidence"]["charge_target"];
        let signal_time = text(&opening["signal"]["signal_time"])?;
        let time = number(&input["time"])?;
        if input["op"] != "FILL"
            || fact["sequence"] != applied["sequence"]
            || fact["transaction"] != applied["transaction"]
            || *input != applied["input"]
            || payload["trade"] != opening["trade"]
            || payload["fees"]["charge_target"] != *fee
            || !matches!(side.as_str(), "BUY" | "SELL")
            || signal_time.parse::<u64>().map_err(|_| failed(INVALID))? > time
        {
            return Err(failed(INVALID));
        }
        trades.push(BacktestTradeView {
            ordinal: ordinal as u64 + 1,
            time_ns: time.to_string(),
            quantity: text(&payload["quantity"])?,
            price: text(&payload["price"])?,
            fee: text(fee)?,
            signal_time_ns: signal_time,
            signal: if side == "BUY" {
                "满足开仓条件"
            } else {
                "满足平仓条件"
            }
            .into(),
            side,
            order_id: order,
            trade_id: text(&payload["trade"])?,
        });
    }
    let positions = result["final_positions"]
        .as_array()
        .ok_or_else(|| failed(INVALID))?
        .iter()
        .map(|value| {
            let snapshot = &value["snapshot"];
            let state = text(&snapshot["status"])?;
            let instrument = text(&value["instrument"])?;
            if instrument != "BTCUSDT.BINANCE"
                || !matches!(state.as_str(), "OPEN" | "CLOSED" | "RECONCILING")
            {
                return Err(failed(INVALID));
            }
            let average_price = optional_text(snapshot, "average")?;
            Ok(BacktestPositionView {
                instrument,
                quantity: text(&snapshot["quantity"])?,
                average_price,
                state,
            })
        })
        .collect::<Result<Vec<_>, Failure>>()?;
    let rule_time =
        OnlyTimestamp::from_record(&preparation["policy_binding"]["rules_snapshot"]["captured_at"])
            .map_err(|_| failed(INVALID))?
            .to_datetime_exact()
            .map_err(|_| failed(INVALID))?
            .to_string();
    let value = BacktestResultView {
        schema_version: 1,
        run_id: run.run_id().into(),
        strategy_fingerprint: text(&run.specification().record()["strategy_fingerprint"])?,
        evidence_fingerprint: publication.fingerprint().into(),
        result_fingerprint: publication.fingerprint().into(),
        determinism_fingerprint: publication.fingerprint().into(),
        state: BacktestResultState::Completed,
        sample: BacktestSample {
            instrument: "BTCUSDT".into(),
            start_at: instant(&preparation["window"]["sample_start_ns"])?,
            end_at: instant(&preparation["window"]["sample_end_ns"])?,
            quantity: text(&preparation["settings"]["policy"]["quantity"]["value"])?,
            rule_observed_at: rule_time,
        },
        metrics,
        curve,
        baseline,
        trades,
        positions,
        limitations: vec![
            "样本较短，仅作探索，不能据此判断长期表现。".into(),
            "使用当前现货交易规则建模，不代表当时交易所的实际撮合与接单。".into(),
            "未平仓头寸按样本末尾收盘价估值；未读取保留样本。".into(),
        ],
    };
    Ok(value)
}

fn publication_failure(error: PublicationError) -> Failure {
    match error {
        PublicationError::Denied => failed(error.code()),
        _ => Failure::unavailable(error.code()),
    }
}

impl Host {
    async fn read_backtest_publication(
        &self,
        run: &backtest_run::VerifiedRun,
    ) -> Result<BacktestPublication, Failure> {
        let operation = Operation::start(
            "transport",
            "http.backtest.read_publication",
            Correlation {
                run_id: Some(run.run_id().into()),
                ..Default::default()
            },
        );
        let result = async {
            let locator = RunLocator::new(JobKind::Backtest, run.run_id()).map_err(publication_failure)?;
            let mut facts = self.job_fact_reader().await?;
            let facts = facts.client_mut().await?;
            let mut reader = self.reader.lock().await;
            let metadata = reader.as_mut().ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let publication = PublicationRepository::new(facts, run.namespace(), run.owner())
                .await
                .map_err(publication_failure)?
                .read_backtest(&locator, metadata)
                .await
                .map_err(publication_failure)?;
            BacktestPublication::verify(run, publication)
        }
        .instrument(operation.span().clone())
        .await;
        operation.finish(if result.is_ok() { "ok" } else { "failed" }, 1, 0);
        result
    }

    pub(crate) async fn backtest_product(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        if request.uri().query().is_some() {
            return Err(invalid());
        }
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let owner = human.subject_id()?.to_owned();
        if path == "/api/v2/backtest/runs" && method == Method::GET {
            let rows = {
                let mut reader_hold = crate::workers::backtest_profile::HoldEnd::pending();
                let wait =
                    Operation::start("transport", "http.reader.wait", Correlation::default());
                let mut reader = self.reader.lock().instrument(wait.span().clone()).await;
                wait.finish("acquired", 1, 0);
                reader_hold.acquired("reader", "reader.hold");
                let _reader_release = reader_hold.begin_release_marker();
                let client = reader
                    .as_mut()
                    .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                runs::recent_snapshots(client, self.inputs.namespace(), &owner)
                    .await
                    .map_err(failed)?
            };
            let worker = self.backtest_worker_status().await;
            let items = rows
                .into_iter()
                .map(|(run, status)| run_view(&run, status, None, worker.clone()))
                .collect::<Result<Vec<_>, _>>()?;
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(
                Json(BacktestRunInventory {
                    schema_version: 1,
                    items,
                })
                .into_response(),
                Release::Generation(human.metadata_session()),
            ));
        }
        let tail = path
            .strip_prefix("/api/v2/backtest/runs/")
            .ok_or_else(invalid)?;
        let (id, action) = tail.split_once('/').unwrap_or((tail, ""));
        if !crate::application::command::uuid4(id) {
            return Err(invalid());
        }
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        if method == Method::POST && action == "cancellation" {
            let (command, body) = input(request).await?;
            let body: BacktestCancellationInput =
                serde_json::from_value(body).map_err(|_| invalid())?;
            body.validate(id).map_err(failed)?;
            let (run, _) = {
                let mut reader_hold = crate::workers::backtest_profile::HoldEnd::pending();
                let wait =
                    Operation::start("transport", "http.reader.wait", Correlation::default());
                let mut reader = self.reader.lock().instrument(wait.span().clone()).await;
                wait.finish("acquired", 1, 0);
                reader_hold.acquired("reader", "reader.hold");
                let _reader_release = reader_hold.begin_release_marker();
                let client = reader
                    .as_mut()
                    .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                runs::read_snapshot(client, self.inputs.namespace(), id, Some(&owner))
                    .await
                    .map_err(failed)?
            };
            let selected = &run.resolution()["source_selection"];
            let reference = Reference::new(
                &text(&selected["integration_id"])?,
                &text(&selected["revision_fingerprint"])?,
                selected["expected_type_id"].as_str(),
            )
            .map_err(|_| invalid())?;
            let selection = Selection::new(
                reference,
                &text(&selected["source_id"])?,
                &text(&selected["environment"])?,
            )
            .map_err(|_| invalid())?;
            let (authority, source_session) = {
                let held = self.issuer.lock().await;
                (held.authority.clone(), held.session.clone())
            };
            let context = backtest_run::Context {
                human_authority: &self.human_access,
                human: &human,
                source_authority: &authority,
                source: &source_session,
                selection: &selection,
            };
            let cancel = CancelRequest::new(command, id).map_err(failed)?;
            {
                let mut writer = self.writer.lock().await;
                let session = writer
                    .as_mut()
                    .ok_or_else(|| failed("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                Backtests::new(session, self.inputs.namespace())
                    .request_cancel(&cancel, &context, now()?)
                    .await
                    .map_err(failed)?;
            }
            self.wake_backtest_after_commit();
            let (run, status) = {
                let mut reader_hold = crate::workers::backtest_profile::HoldEnd::pending();
                let wait =
                    Operation::start("transport", "http.reader.wait", Correlation::default());
                let mut reader = self.reader.lock().instrument(wait.span().clone()).await;
                wait.finish("acquired", 1, 0);
                reader_hold.acquired("reader", "reader.hold");
                let _reader_release = reader_hold.begin_release_marker();
                let client = reader
                    .as_mut()
                    .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                runs::read_snapshot(client, self.inputs.namespace(), id, Some(&owner))
                    .await
                    .map_err(failed)?
            };
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(
                Json(run_view(
                    &run,
                    status,
                    None,
                    self.backtest_worker_status().await,
                )?)
                .into_response(),
                Release::Generation(human.metadata_session()),
            ));
        }
        if method != Method::GET {
            return Err(invalid());
        }
        let artifact_name = action.strip_prefix("evidence/artifacts/");
        if !matches!(action, "" | "result" | "evidence") && artifact_name.is_none() {
            return Err(invalid());
        }
        let (run, status, preparation) = {
            let wait = Operation::start("transport", "http.reader.wait", Correlation::default());
            let mut reader = self.reader.lock().instrument(wait.span().clone()).await;
            wait.finish("acquired", 1, 0);
            let client = reader
                .as_mut()
                .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            runs::read_product_snapshot(client, self.inputs.namespace(), id, &owner)
                .await
                .map_err(|code| {
                    if code.ends_with("_MISSING") {
                        Failure::unavailable(code)
                    } else {
                        failed(code)
                    }
                })?
        };
        if action.is_empty() {
            let mut view = run_view(
                &run,
                status,
                Some(preparation.value().into()),
                self.backtest_worker_status().await,
            )?;
            if status.state == RunState::Completed {
                view.report_status = match self.read_backtest_publication(&run).await {
                    Ok(_) => BacktestReportAvailability {
                        state: BacktestReportState::Verified,
                        code: None,
                    },
                    Err(error) => BacktestReportAvailability {
                        state: BacktestReportState::Unavailable,
                        code: Some(error.code().into()),
                    },
                };
            }
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(
                Json(view).into_response(),
                Release::Generation(human.metadata_session()),
            ));
        }
        if status.state != RunState::Completed {
            return Err(failed(NOT_READY));
        }
        let BacktestPublication { publication, result } = self.read_backtest_publication(&run).await?;
        let resolution = run.resolution();
        let response = if action == "result" {
            crate::workers::backtest_profile::measure(id, "http.result.serialize", || {
                Ok::<_, Failure>(Json(result).into_response())
            })?
        } else if action == "evidence" {
            Json(BacktestEvidenceView {
                schema_version: 1,
                run_id: id.into(),
                publication_fingerprint: publication.fingerprint().into(),
                preparation_command_id: preparation.value().into(),
                freeze_relation_fingerprint: text(&resolution["freeze_relation_fingerprint"] )?,
                qualification_decision_fingerprint: text(&resolution["qualification_decision_fingerprint"] )?,
                promotion_fingerprint: text(&resolution["promotion_fingerprint"] )?,
                manifest: publication.manifest().clone(),
            })
            .into_response()
        } else {
            let key = artifact_name.ok_or_else(invalid)?;
            let bytes = publication.content(key)
                .ok_or_else(|| failed("BACKTEST_ARTIFACT_NOT_FOUND"))?;
            Response::builder()
                .status(StatusCode::OK)
                .header("content-type", "application/octet-stream")
                .header("content-disposition", "attachment")
                .body(Body::from(bytes.to_owned()))
                .map_err(|_| failed(INVALID))?
        };
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        self.human_access.check_session(&human)?;
        let session = human.metadata_session();
        let release = if artifact_name.is_some() {
            Release::BacktestArtifact(session)
        } else {
            Release::Generation(session)
        };
        Ok(ingress::attach(response, release))
    }
}

#[cfg(test)]
#[path = "../../tests/transport/backtest_worker_observation.rs"]
mod worker_observation_tests;
