//! Actual original connections and admitted Ready/Run3 are supplied by the
//! existing owner fixture. No Runtime, joined-product or completion factory.
#[path = "job_fact_connection.rs"]
mod fact_connection;
use super::*;
use crate::{
    application::{
        backtest_run::{CancelRequest, Context, VerifiedRun},
        command::{CommandId, CommandKind, OutcomeKind, Receipt},
    },
    bootstrap::workstation_startup::ResearchConnection,
    persistence::{
        authority_session::AuthoritySession,
        backtest_run::{Backtests, RunState},
        job_publication::PublicationObservation,
        research_runtime::Registry,
    },
    workers::research::SharedAuthority,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{
    collections::BTreeMap,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio::sync::Notify;

#[test]
fn scheduler_uses_original_infrastructure_owners_and_concrete_producer() {
    type Clock = fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >;
    type Start = fn(
        ResearchConnection,
        ResearchConnection,
        SharedAuthority,
        SourceSessions,
        Arc<crate::persistence::market_data::ClickHouse>,
        Configuration,
        Clock,
    ) -> std::result::Result<Service, &'static str>;
    let _: Start = Service::start;
    let _: fn(&Service) -> Wake = Service::wake;
    let _: fn(&Wake) -> bool = Wake::notify;
    let _: fn(&Wake) = Wake::stop;
    let _: fn(&Service) -> Status = Service::status;
    let _ = Service::drain;
}

// Deterministic barriers at real blocking phases. They never return a Run,
// observation, completion or joined grant and are absent from production.
#[derive(Default)]
pub(super) struct Gate {
    entered: AtomicBool,
    changed: Notify,
    released: Mutex<bool>,
    resume: Condvar,
}
impl Gate {
    fn hit(&self) {
        self.entered.store(true, Ordering::Release);
        self.changed.notify_waiters();
        let mut released = self.released.lock().unwrap();
        while !*released {
            released = self.resume.wait(released).unwrap();
        }
    }
    fn release(&self) {
        *self.released.lock().unwrap() = true;
        self.resume.notify_all();
    }
}
pub(crate) struct RegisteredGate {
    key: (String, &'static str),
    gate: Arc<Gate>,
}
impl RegisteredGate {
    pub(crate) async fn entered(&self) {
        let reached = tokio::time::timeout(std::time::Duration::from_secs(45), async {
            loop {
                let notified = self.gate.changed.notified();
                if self.gate.entered.load(Ordering::Acquire) {
                    return;
                }
                notified.await;
            }
        }).await;
        assert!(reached.is_ok(), "Run {} never reached {}", self.key.0, self.key.1);
    }

    fn release(&self) {
        self.gate.release();
    }
}
impl Drop for RegisteredGate {
    fn drop(&mut self) {
        GATES.get_or_init(Default::default).lock().unwrap().remove(&self.key);
        self.gate.release();
    }
}
type Gates = Mutex<BTreeMap<(String, &'static str), Arc<Gate>>>;
static GATES: std::sync::OnceLock<Gates> = std::sync::OnceLock::new();
pub(crate) fn gate(run: &str, phase: &'static str) -> RegisteredGate {
    let key = (run.to_owned(), phase);
    let gate = Arc::new(Gate::default());
    let mut gates = GATES.get_or_init(Default::default).lock().unwrap();
    let std::collections::btree_map::Entry::Vacant(slot) = gates.entry(key.clone()) else {
        drop(gates);
        panic!("Run {run} already registered {phase}");
    };
    slot.insert(gate.clone());
    RegisteredGate { key, gate }
}
pub(crate) fn blocking_phase(run: &str, phase: &'static str) {
    let gate = GATES
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .get(&(run.into(), phase))
        .cloned();
    if let Some(gate) = gate {
        gate.hit();
    }
}
/// Async control observations never block the executor or retain a SQL guard.
pub(super) fn observed_phase(run: &str, phase: &'static str) {
    let gate = GATES
        .get_or_init(Default::default)
        .lock()
        .unwrap()
        .get(&(run.into(), phase))
        .cloned();
    if let Some(gate) = gate {
        gate.entered.store(true, Ordering::Release);
        gate.changed.notify_waiters();
    }
}

type PublicationResult = std::result::Result<&'static str, PublicationError>;
type FirstPublications = Mutex<BTreeMap<String, tokio::sync::oneshot::Sender<PublicationResult>>>;
static FIRST_PUBLICATIONS: std::sync::OnceLock<FirstPublications> = std::sync::OnceLock::new();

pub(super) fn record_first_publication(
    run: &str,
    attempt: i32,
    result: &std::result::Result<crate::persistence::job_publication::PublishOutcome, PublicationError>,
) {
    use crate::persistence::job_publication::PublishOutcome;

    if attempt == 1 {
        let sender = FIRST_PUBLICATIONS.get_or_init(Default::default).lock().unwrap().remove(run);
        if let Some(sender) = sender {
            let result = match result {
                Ok(PublishOutcome::Committed { .. }) => Ok("Committed"),
                Ok(PublishOutcome::AlreadyPublished(_)) => Ok("AlreadyPublished"),
                Err(error) => Err(*error),
            };
            let _ = sender.send(result);
        }
    }
}

tokio::task_local! {
    static ECONOMIC_REJECTION: std::cell::RefCell<Option<String>>;
}

pub(crate) fn record_economic_rejection(code: &str) {
    let _ = ECONOMIC_REJECTION.try_with(|rejection| {
        assert!(rejection.replace(Some(code.to_owned())).is_none());
    });
}

#[derive(Clone, Copy, Debug)]
enum EconomicFault {
    AccountFees,
    AccountCause,
    OrderFillTime,
    LedgerFees,
    Position(&'static str, &'static str),
    LedgerReturn(&'static str),
}

fn amount(value: &serde_json::Value) -> bigdecimal::BigDecimal {
    value.as_str().unwrap().parse().unwrap()
}

fn omit_first_trade_fee(
    mut points: Vec<(Option<String>, &mut serde_json::Value)>,
    causes: &[String; 2],
    fees: &[bigdecimal::BigDecimal; 2],
) {
    let trade_points = points.iter().enumerate().filter_map(|(index, (cause, _))| {
        cause.as_ref().filter(|cause| causes.contains(cause)).map(|_| index)
    }).collect::<Vec<_>>();
    let [first, second] = trade_points[..] else { panic!("expected two real trade snapshots") };
    assert!(first > 0);
    assert_eq!(points[first].0.as_ref(), Some(&causes[0]));
    assert_eq!(points[second].0.as_ref(), Some(&causes[1]));
    assert!(fees.iter().all(|fee| fee > &bigdecimal::BigDecimal::from(0)));
    let previous = points[first - 1].1["fees"].clone();
    let first_total = amount(&previous) + &fees[0];
    assert_eq!(amount(&points[second].1["fees"]), &first_total + &fees[1]);
    for (_, snapshot) in &mut points[first..second] {
        assert_eq!(amount(&snapshot["fees"]), first_total);
        snapshot["fees"] = previous.clone();
    }
}

fn alter_economic_result(result: &mut serde_json::Value, fault: EconomicFault) {
    use crate::persistence::job_publication::content_fingerprint as hash;
    use serde_json::{Value, json};
    let [first, second] = result["trades"].as_array().unwrap().as_slice() else {
        panic!("expected two real trades in the fixture");
    };
    let inputs = [&first["input"], &second["input"]];
    assert!(inputs.iter().all(|input| input["op"] == "FILL"));
    let causes = inputs.map(|input| hash(input).unwrap());
    assert_eq!(first["transaction"], format!("ETX-{}", causes[0]));
    assert_eq!(second["transaction"], format!("ETX-{}", causes[1]));
    assert_ne!(inputs[0]["payload"]["order"], inputs[1]["payload"]["order"]);
    let cluster = inputs[0]["cluster"].clone();
    assert_eq!(inputs[1]["cluster"], cluster);
    let price = inputs[0]["payload"]["price"].clone();
    let fees = inputs.map(|input| {
        let fees = &input["payload"]["fees"];
        amount(&fees["charge_target"]) - amount(&fees["rebate_target"])
    });

    match fault {
        EconomicFault::AccountFees | EconomicFault::AccountCause => {
            assert_eq!(result["account_equity_timeline"], result["runtime_performance"]["timeline"]);
            let performance = &mut result["runtime_performance"];
            let original = performance.as_object_mut().unwrap().remove("id").unwrap();
            assert_eq!(original, format!("AP-{}", hash(performance).unwrap()));
            let timeline = performance["timeline"].as_array_mut().unwrap();
            if matches!(fault, EconomicFault::AccountFees) {
                let points = timeline.iter_mut().map(|point| {
                    let cause = (point["source"] == "TRADE").then(|| {
                        point["provenance"]["upstream_cause"].as_str().unwrap().to_owned()
                    });
                    (cause, &mut point["snapshot"])
                }).collect();
                omit_first_trade_fee(points, &causes, &fees);
            } else {
                let point = timeline.iter_mut().find(|point| {
                    point["source"] == "TRADE" && point["provenance"]["upstream_cause"] == causes[0]
                }).unwrap();
                assert_eq!(point["cause"], point["provenance"]["cause"]);
                let changed = json!("f".repeat(64));
                assert_ne!(point["cause"], changed);
                point["cause"] = changed.clone();
                point["provenance"]["cause"] = changed;
            }
            performance["id"] = json!(format!("AP-{}", hash(performance).unwrap()));
            result["account_equity_timeline"] = performance["timeline"].clone();
        }
        EconomicFault::OrderFillTime => {
            let input = inputs[0];
            let order = input["payload"]["order"].clone();
            let time = input["time"].as_i64().unwrap();
            let snapshot = &mut result["orders"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|row| row["snapshot"]["order_id"]["value"] == order)
                .unwrap()["snapshot"];
            assert_eq!(snapshot["status"], "FILLED");
            assert_eq!(snapshot["filled_at"]["unix_nanos"], time);
            snapshot["filled_at"]["unix_nanos"] = json!(time + 1);
        }
        EconomicFault::Position(member, field) => {
            let [row] = result[member].as_array_mut().unwrap().as_mut_slice() else {
                panic!("expected one {member} row");
            };
            let snapshot = &mut row["snapshot"];
            assert_eq!(snapshot["status"], "CLOSED");
            assert_eq!(amount(&snapshot["quantity"]), 0);
            if field == "cost" {
                assert_eq!(amount(&snapshot["cost"]), 0);
                snapshot["cost"] = json!("1");
            } else {
                assert!(snapshot["average"].is_null());
                assert!(amount(&price) > 0);
                snapshot["average"] = price;
            }
        }
        EconomicFault::LedgerFees | EconomicFault::LedgerReturn(_) => {
            let timeline = result["cluster_equity_timelines"].as_array_mut().unwrap().iter_mut()
                .find(|timeline| timeline["cluster"] == cluster).unwrap();
            let points = timeline["points"].as_array_mut().unwrap();
            if matches!(fault, EconomicFault::LedgerFees) {
                let [initial, occurrences @ ..] = points.as_mut_slice() else { panic!("missing Ledger genesis") };
                assert_eq!(initial["source"], "LEDGER_CREATED");
                let mut snapshots = vec![(None, &mut initial["snapshot"])];
                snapshots.extend(occurrences.iter_mut().map(|entry| {
                    let point = &mut entry["point"];
                    let cause = point["cause"].as_str().map(str::to_owned);
                    (cause, &mut point["snapshot"])
                }));
                omit_first_trade_fee(snapshots, &causes, &fees);
            } else if let EconomicFault::LedgerReturn(field) = fault {
                let snapshot = &mut points.last_mut().unwrap()["point"]["snapshot"];
                let original = snapshot[field].clone();
                let wrong = Value::String("1.00000000".into());
                assert_ne!(amount(&original), amount(&wrong));
                snapshot[field] = wrong.clone();
                let ledger = result["final_ledgers"].as_array_mut().unwrap().iter_mut()
                    .find(|ledger| ledger["cluster"] == cluster).unwrap();
                assert_eq!(ledger[field], original);
                let before = ledger.clone();
                ledger[field] = wrong.clone();
                let after = ledger.clone();
                let cluster_result = result["cluster_results"].as_array_mut().unwrap().iter_mut()
                    .find(|row| row["cluster"] == cluster).unwrap();
                assert_eq!(cluster_result["final_ledger"], before);
                cluster_result["final_ledger"] = after;
                if field == "simple_return" {
                    let summary = &mut cluster_result["cluster_performance"]["summary"];
                    assert_eq!(summary[field], original);
                    summary[field] = wrong;
                }
            }
        }
    }
}

async fn economic_publication_state(
    connection: &mut Option<InputConnections>,
    claim: &Claim,
) -> tokio_postgres::Row {
    let (_, facts) = connection.as_mut().unwrap().clients_mut().await.unwrap();
    facts.query_one(
        "SELECT r.revision,r.state,r.finished_at IS NULL AS run_open,
                r.evidence_fingerprint,r.result_fingerprint,r.determinism_fingerprint,
                a.state AS attempt_state,a.finished_at IS NULL AS attempt_open,
                a.lease_expires_at > clock_timestamp() AS lease_valid,
                (SELECT count(*) FROM public.backtest_run_attempt WHERE run_id=r.run_id) AS attempts,
                (SELECT count(*) FROM public.job_result_member WHERE job_kind='BACKTEST' AND run_id=r.run_id) AS members,
                p.publication_fingerprint,
                COALESCE(p.attempt_id=a.attempt_id AND p.worker_id=a.worker_instance_id
                         AND p.attempt_number=a.attempt_number AND p.fence=a.fencing_token,false) AS original_winner
         FROM public.backtest_run r
         JOIN public.backtest_run_attempt a ON a.run_id=r.run_id
         LEFT JOIN public.job_publication p ON p.job_kind='BACKTEST' AND p.run_id=r.run_id
         WHERE r.run_id=$1::text::uuid AND a.attempt_id=$2::text::uuid AND a.worker_instance_id=$3::text::uuid
           AND a.attempt_number=$4 AND a.fencing_token=$5",
        &[&claim.run_id(), &claim.attempt_id(), &claim.worker_instance_id(), &claim.attempt_number(), &claim.fencing_token()],
    ).await.unwrap()
}

fn assert_unpublished_economic_state(row: &tokio_postgres::Row) {
    assert_eq!(row.get::<_, String>("state"), "RUNNING");
    assert_eq!(row.get::<_, String>("attempt_state"), "ACTIVE");
    for field in ["run_open", "attempt_open", "lease_valid"] {
        assert!(row.get::<_, bool>(field), "{field}");
    }
    assert_eq!(row.get::<_, i64>("attempts"), 1);
    assert_eq!(row.get::<_, i64>("members"), 0);
    for field in ["publication_fingerprint", "evidence_fingerprint", "result_fingerprint", "determinism_fingerprint"] {
        assert_eq!(row.get::<_, Option<String>>(field), None, "{field}");
    }
}

pub(super) async fn verify_economic_publication_rollbacks(
    connection: &mut Option<InputConnections>,
    writer: &SharedAuthority,
    run: &VerifiedRun,
    claim: &Claim,
    original: &crate::persistence::job_publication::CompletedJobCandidate,
) -> Option<i64> {
    let enabled = GATES.get_or_init(Default::default).lock().unwrap()
        .contains_key(&(run.run_id().into(), "economic_publication"));
    if !enabled {
        return None;
    }
    assert_eq!(claim.run_id(), run.run_id());
    let prior = economic_publication_state(connection, claim).await;
    assert_unpublished_economic_state(&prior);
    let revision: i64 = prior.get("revision");
    let claim_binding = AttemptClaim::from_backtest(claim);
    for (fault, expected) in [
        (EconomicFault::AccountFees, "RESULT_FINITE_TRADE_FEES"),
        (EconomicFault::LedgerFees, "RESULT_FINITE_TRADE_FEES"),
        (EconomicFault::AccountCause, "RESULT_FINITE_ACCOUNT_RECEIPT"),
        (EconomicFault::OrderFillTime, "RESULT_FINITE_ORDER_SNAPSHOT"),
        (EconomicFault::Position("final_positions", "cost"), "RESULT_FINITE_POSITION_COST"),
        (EconomicFault::Position("final_allocations", "cost"), "RESULT_FINITE_POSITION_COST"),
        (EconomicFault::Position("final_positions", "average"), "RESULT_FINITE_POSITION_AVERAGE"),
        (EconomicFault::Position("final_allocations", "average"), "RESULT_FINITE_POSITION_AVERAGE"),
        (EconomicFault::LedgerReturn("simple_return"), "RESULT_FINITE_LEDGER_RETURN"),
        (EconomicFault::LedgerReturn("daily_return"), "RESULT_FINITE_LEDGER_RETURN"),
    ] {
        let altered = original.with_test_economic_result(|result| alter_economic_result(result, fault));
        let (result, rejection) = ECONOMIC_REJECTION.scope(Default::default(), async {
            let mut held = writer.lock().await;
            let result = PublicationRepository::publish_guarded(
                held.as_mut().unwrap(), run.namespace(), &claim_binding, &altered,
            ).await;
            (result, ECONOMIC_REJECTION.with(|rejection| rejection.take()))
        }).await;
        assert_eq!(result.err(), Some(PublicationError::Integrity), "{fault:?}");
        assert_eq!(rejection.as_deref(), Some(expected), "{fault:?}");
        let state = economic_publication_state(connection, claim).await;
        assert_eq!(state.get::<_, i64>("revision"), revision, "{fault:?}");
        assert_unpublished_economic_state(&state);
    }
    let fixture = fact_connection::Connection::operator().await.unwrap();
    fixture.client.batch_execute(
        "ALTER TABLE public.job_result_member DISABLE TRIGGER job_result_member_immutable;
         CREATE FUNCTION public.test_backtest_deferred_body() RETURNS trigger
         LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
         BEGIN
             UPDATE public.job_result_member
             SET content=content || ' ',
                 content_fingerprint=encode(sha256(convert_to(content || ' ','UTF8')),'hex')
             WHERE job_kind='BACKTEST' AND run_id=NEW.run_id AND member_key='economic_result';
             IF NOT FOUND THEN RAISE EXCEPTION 'missing test member' USING ERRCODE='55000'; END IF;
             RETURN NEW;
         END $$;
         CREATE CONSTRAINT TRIGGER zz_test_backtest_deferred_body AFTER UPDATE ON public.backtest_run
         DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
         WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state)
         EXECUTE FUNCTION public.test_backtest_deferred_body()",
    ).await.unwrap();
    let result = {
        let mut held = writer.lock().await;
        PublicationRepository::publish_guarded(
            held.as_mut().unwrap(), run.namespace(), &claim_binding, original,
        ).await
    };
    fixture.client.batch_execute(
        "DROP TRIGGER zz_test_backtest_deferred_body ON public.backtest_run;
         DROP FUNCTION public.test_backtest_deferred_body();
         ALTER TABLE public.job_result_member ENABLE TRIGGER job_result_member_immutable",
    ).await.unwrap();
    assert_eq!(result.err(), Some(PublicationError::Integrity));
    let state = economic_publication_state(connection, claim).await;
    assert_eq!(state.get::<_, i64>("revision"), revision);
    assert_unpublished_economic_state(&state);
    Some(revision)
}

pub(super) async fn assert_original_economic_publication(
    connection: &mut Option<InputConnections>,
    claim: &Claim,
    original: &crate::persistence::job_publication::CompletedJobCandidate,
    revision: i64,
) {
    let row = economic_publication_state(connection, claim).await;
    assert_eq!(row.get::<_, String>("state"), "COMPLETED");
    assert_eq!(row.get::<_, String>("attempt_state"), "SUCCEEDED");
    assert!(!row.get::<_, bool>("run_open"));
    assert!(!row.get::<_, bool>("attempt_open"));
    assert!(row.get::<_, bool>("original_winner"));
    assert_eq!(row.get::<_, i64>("attempts"), 1);
    assert_eq!(row.get::<_, i64>("members"), original.member_count() as i64);
    assert_eq!(row.get::<_, i64>("revision"), revision + 1);
    for field in ["publication_fingerprint", "evidence_fingerprint", "result_fingerprint", "determinism_fingerprint"] {
        assert_eq!(row.get::<_, String>(field), original.fingerprint(), "{field}");
    }
    observed_phase(claim.run_id(), "economic_publication");
}

async fn writer_row(
    writer: &SharedAuthority,
    run: &str,
) -> (String, Option<String>, Option<String>, Option<String>) {
    let mut held = writer.lock().await;
    let client = held.as_mut().unwrap().client_mut().await.unwrap();
    let row=client.query_one("SELECT state,evidence_fingerprint,result_fingerprint,determinism_fingerprint FROM backtest_run WHERE run_id=$1::text::uuid",&[&run]).await.unwrap();
    (row.get(0), row.get(1), row.get(2), row.get(3))
}
async fn attempts(writer: &SharedAuthority, run: &VerifiedRun) -> Vec<(String, i32, i64, String)> {
    let mut held = writer.lock().await;
    held.as_mut()
        .unwrap()
        .client_mut()
        .await
        .unwrap()
        .query(
            "SELECT attempt_id::text, attempt_number, fencing_token, state FROM public.backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",
            &[&run.run_id()],
        )
        .await
        .unwrap()
        .iter()
        .map(|row| (row.get(0), row.get(1), row.get(2), row.get(3)))
        .collect()
}

pub(crate) async fn expire_original(run: &str) {
    let fixture = fact_connection::Connection::operator().await.unwrap();
    let updated = fixture.client.execute(
        "UPDATE public.backtest_run_attempt SET lease_expires_at=last_heartbeat_at WHERE run_id=$1::text::uuid AND state='ACTIVE' AND last_heartbeat_at<=clock_timestamp() AND lease_expires_at>clock_timestamp()",
        &[&run],
    ).await.unwrap();
    assert_eq!(updated, 1);
}
async fn wait_for_idle(mut observed: watch::Receiver<Status>) {
    loop {
        match observed.borrow().clone() {
            Status::Idle => return,
            Status::Uncertain(CLEANUP_PENDING) => {}
            Status::Uncertain(code) | Status::Unavailable(code) => panic!("{code}"),
            _ => {}
        }
        observed.changed().await.unwrap();
    }
}

#[tokio::test]
async fn cleanup_pending_waits_for_idle() {
    let (status, observed) = watch::channel(Status::Uncertain(CLEANUP_PENDING));
    let waiting = wait_for_idle(observed);
    tokio::pin!(waiting);
    tokio::select! {
        biased;
        () = &mut waiting => panic!("worker cleanup is still pending"),
        () = std::future::ready(()) => {}
    }
    status.send(Status::Idle).unwrap();
    tokio::select! {
        biased;
        () = &mut waiting => {},
        () = std::future::ready(()) => panic!("worker idle was not observed"),
    }
}

async fn assert_terminal(writer: &SharedAuthority, run: &VerifiedRun, status: &str) {
    let mut held = writer.lock().await;
    let mut backtests = Backtests::new(held.as_mut().unwrap(), run.namespace());
    let current = backtests.load(run.run_id()).await.unwrap();
    assert_eq!(current.state().as_str(), status);
    assert_eq!(current.record(), run.record());
    match backtests.observe_publication(&current).await.unwrap() {
        PublicationObservation::Published(result) if status == "COMPLETED" => {
            let fingerprint = result.fingerprint();
            assert_eq!(current.completion_fingerprints(), Some((fingerprint, fingerprint, fingerprint)));
            let members = ["causal_evidence", "close_curve", "economic_result", "execution_facts"];
            assert_eq!(result.member_count(), members.len());
            for member in members {
                assert!(result.content(member).is_some());
            }
        }
        PublicationObservation::ConfirmedUnpublished(proof) if status == "CANCELLED" => {
            assert_eq!(proof.run_state(), status);
            assert_eq!(proof.active_attempts(), 0);
            assert_eq!(current.completion_fingerprints(), None);
            assert!(current.cancel_requested_at().is_some());
        }
        other => panic!("unexpected publication for {status}: {other:?}"),
    }
}

pub(crate) async fn request_and_replay_cancel(
    writer: &SharedAuthority,
    run: &VerifiedRun,
    context: &Context<'_>,
    command: CommandId,
    at: OnlyUtcDateTime,
) -> Receipt {
    let request = CancelRequest::new(command.clone(), run.run_id()).unwrap();
    let mut held = writer.lock().await;
    let mut backtests = Backtests::new(held.as_mut().unwrap(), run.namespace());
    let receipt = backtests.request_cancel(&request, context, at).await.unwrap();
    assert_eq!(receipt.admission().id(), &command);
    assert_eq!(receipt.admission().kind(), CommandKind::CancelBacktestRun);
    assert_eq!(receipt.outcome().kind(), OutcomeKind::BacktestRun);
    assert_eq!(receipt.outcome().id(), run.run_id());
    assert_eq!(receipt.accepted_at(), at);
    assert_eq!(backtests.request_cancel(&request, context, at).await.unwrap(), receipt);
    receipt
}

/// The caller commits queued cancellation with the original Human Command first.
pub(crate) async fn queued_cancel(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    assert_eq!(run.state(), RunState::Cancelled);
    assert!(!run.was_started());
    assert_eq!(run.completion_fingerprints(), None);
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(connection, facts, writer.clone(), sources, physical, configuration, clock).unwrap();
    wait_for_idle(service.subscribe()).await;
    service.drain().await.unwrap();
    assert!(attempts(&writer, &run).await.is_empty());
    assert_terminal(&writer, &run, "CANCELLED").await;
}

/// Real pause occurs after original claim+opaque restore. The blocking barrier
/// lets shutdown win deterministically while the physical owners remain retained.
pub(crate) async fn shutdown_pause(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: &VerifiedRun,
    expected_attempts: usize,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "before_produce");
    let paused = gate(run.run_id(), "pause_requested");
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        configuration.clone(),
        clock,
    )
    .unwrap();
    barrier.entered().await;
    assert_eq!(writer_row(&writer, run.run_id()).await.0, "RUNNING");
    let wake = service.wake();
    wake.stop();
    assert!(!wake.notify());
    let mut drain = Box::pin(service.drain());
    tokio::select! {biased;result=&mut drain=>panic!("shutdown dropped a live blocking owner: {result:?}"),_ = tokio::task::yield_now()=>{}}
    drop(drain);
    paused.entered().await;
    drop(barrier);
    service.drain().await.unwrap();
    let current = writer_row(&writer, run.run_id()).await;
    assert_eq!(current, ("RUNNING".into(), None, None, None));
    let mut held = writer.lock().await;
    let client = held.as_mut().unwrap().client_mut().await.unwrap();
    let rows = client.query(
        "SELECT state, failure_code, failure_detail FROM backtest_run_attempt \
         WHERE run_id=$1::text::uuid ORDER BY attempt_number",
        &[&run.run_id()],
    ).await.unwrap();
    assert_eq!(rows.len(), expected_attempts);
    let (active, previous) = rows.split_last().unwrap();
    assert!(previous.iter().all(|row| row.get::<_, &str>(0) == "EXPIRED"));
    assert_eq!(active.get::<_, &str>(0), "ACTIVE");
    assert!(active.get::<_, Option<String>>(1).is_none());
    assert!(active.get::<_, Option<String>>(2).is_none());
    let absent = Backtests::new(held.as_mut().unwrap(), run.namespace()).observe_publication(run).await.unwrap();
    let PublicationObservation::ConfirmedUnpublished(proof) = absent else {
        panic!("paused Run must be unpublished: {absent:?}");
    };
    assert_eq!(proof.run_state(), "RUNNING");
    assert_eq!(proof.attempts(), i32::try_from(expected_attempts).unwrap());
    assert_eq!(proof.active_attempts(), 1);
    drop(held);
    assert!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"]
            != true,
        "pause never releases an unfinished original work"
    );
}

/// A new original readonly session is supplied by Infrastructure after restart;
/// this function neither reconnects nor changes the immutable Run/READY identity.
pub(crate) async fn resume_expired(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let before = attempts(&writer, &run).await;
    assert_eq!(before.len(), 1);
    assert_eq!((before[0].1, before[0].3.as_str()), (1, "ACTIVE"));
    expire_original(run.run_id()).await;
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        configuration,
        clock,
    )
    .unwrap();
    wait_for_idle(service.subscribe()).await;
    service.drain().await.unwrap();
    assert_terminal(&writer, &run, "COMPLETED").await;
    assert_recomputed(&before, &attempts(&writer, &run).await);
}

fn assert_recomputed(before: &[(String, i32, i64, String)], after: &[(String, i32, i64, String)]) {
    assert_eq!(after.len(), 2);
    assert_eq!((&after[0].0, after[0].1, after[0].2), (&before[0].0, before[0].1, before[0].2));
    assert_eq!(after[0].3, "EXPIRED");
    assert_eq!((after[1].1, after[1].3.as_str()), (2, "SUCCEEDED"));
    assert_ne!(after[1].0, after[0].0);
    assert!(after[1].2 > after[0].2);
}

pub(crate) async fn expiry_before_finalization(
    [original_connection, recovery_connection]: [ResearchConnection; 2],
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: &VerifiedRun,
    following: &VerifiedRun,
    after_publication: bool,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    use crate::bootstrap::workstation_startup::test_job_fact_reader;

    let finalization = gate(run.run_id(), "before_first_finalization");
    let facts = test_job_fact_reader(&original_connection).await.unwrap();
    let mut original_worker = Service::start(
        original_connection, facts, writer.clone(), sources.clone(), physical.clone(), configuration.clone(), clock,
    ).unwrap();
    finalization.entered().await;
    let original = attempts(&writer, run).await;
    assert_eq!(original.len(), 1);
    assert_eq!((original[0].1, original[0].3.as_str()), (1, "ACTIVE"));
    assert!(attempts(&writer, following).await.is_empty());
    expire_original(run.run_id()).await;

    let loaded = gate(run.run_id(), "before_produce");
    let published = gate(run.run_id(), "after_publish");
    let facts = test_job_fact_reader(&recovery_connection).await.unwrap();
    let mut recovery_worker = Service::start(
        recovery_connection, facts, writer.clone(), sources, physical, configuration, clock,
    ).unwrap();
    loaded.entered().await;
    let claimed = attempts(&writer, run).await;
    assert_eq!(claimed.len(), 2);
    assert_eq!(claimed[0], (original[0].0.clone(), 1, original[0].2, "EXPIRED".into()));
    assert_eq!((claimed[1].1, claimed[1].3.as_str()), (2, "ACTIVE"));
    assert!(claimed[1].2 > claimed[0].2);
    assert_eq!(writer_row(&writer, run.run_id()).await, ("RUNNING".into(), None, None, None));
    {
        let mut held = writer.lock().await;
        let observation = Backtests::new(held.as_mut().unwrap(), run.namespace())
            .observe_publication(run).await.unwrap();
        let PublicationObservation::ConfirmedUnpublished(proof) = observation else {
            panic!("the recovered Run must remain unpublished before execution: {observation:?}");
        };
        assert_eq!((proof.attempts(), proof.active_attempts()), (2, 1));
    }

    if after_publication {
        loaded.release();
        published.entered().await;
        assert_terminal(&writer, run, "COMPLETED").await;
    }
    let before_late_publication = writer_row(&writer, run.run_id()).await;
    let (report, result) = tokio::sync::oneshot::channel();
    assert!(FIRST_PUBLICATIONS.get_or_init(Default::default).lock().unwrap()
        .insert(run.run_id().to_owned(), report).is_none());
    drop(finalization);
    let result = tokio::time::timeout(std::time::Duration::from_secs(45), result)
        .await.expect("original Worker did not reach publication").unwrap();
    assert_eq!(result, Err(PublicationError::OwnershipLost));
    assert_eq!(writer_row(&writer, run.run_id()).await, before_late_publication);
    if !after_publication {
        assert_eq!(attempts(&writer, run).await, claimed);
        let mut held = writer.lock().await;
        let observation = Backtests::new(held.as_mut().unwrap(), run.namespace())
            .observe_publication(run).await.unwrap();
        let PublicationObservation::ConfirmedUnpublished(proof) = observation else {
            panic!("the stale Worker must leave the Run unpublished: {observation:?}");
        };
        assert_eq!((proof.attempts(), proof.active_attempts()), (2, 1));
        drop(held);
        loaded.release();
        published.entered().await;
    }
    drop(published);
    wait_for_idle(recovery_worker.subscribe()).await;
    recovery_worker.drain().await.unwrap();
    wait_for_idle(original_worker.subscribe()).await;
    original_worker.drain().await.unwrap();
    assert_terminal(&writer, following, "COMPLETED").await;
    assert_terminal(&writer, run, "COMPLETED").await;
    assert_recomputed(&original, &attempts(&writer, run).await);
}

/// Heartbeat/cancellation is explicitly woken while the actual blocking job is
/// retained. The caller owns the same accepted Human source context.
pub(crate) async fn cancel_running(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    context: &Context<'_>,
    cancel: CommandId,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "after_first_step");
    let cancelled = gate(run.run_id(), "cancel_observed");
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        configuration,
        clock,
    )
    .unwrap();
    barrier.entered().await;
    let (renewed, before_lease) = {
        let mut held = writer.lock().await;
        let client = held.as_mut().unwrap().client_mut().await.unwrap();
        let row = client.query_one(
            "SELECT lease_expires_at FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE'",
            &[&run.run_id()],
        ).await.unwrap();
        (gate(run.run_id(), "heartbeat_committed"), row.get::<_, std::time::SystemTime>(0))
    };
    assert!(service.wake().notify());
    renewed.entered().await;
    {
        let mut held = writer.lock().await;
        let client = held.as_mut().unwrap().client_mut().await.unwrap();
        let row = client.query_one(
            "SELECT lease_expires_at>$2 AND lease_expires_at>clock_timestamp() FROM backtest_run_attempt WHERE run_id=$1::text::uuid AND state='ACTIVE'",
            &[&run.run_id(), &before_lease],
        ).await.unwrap();
        assert!(row.get::<_, bool>(0), "heartbeat must extend the active Attempt lease");
    }
    let before = attempts(&writer, &run).await;
    assert_eq!(before.len(), 1);
    assert_eq!((before[0].1, before[0].3.as_str()), (1, "ACTIVE"));
    request_and_replay_cancel(&writer, &run, context, cancel, clock().unwrap()).await;
    assert!(service.wake().notify());
    cancelled.entered().await;
    assert_eq!(writer_row(&writer, run.run_id()).await, ("CANCEL_REQUESTED".into(), None, None, None));
    assert_eq!(attempts(&writer, &run).await, before);
    drop(barrier);
    wait_for_idle(service.subscribe()).await;
    service.drain().await.unwrap();
    assert_terminal(&writer, &run, "CANCELLED").await;
    let mut expected = before;
    expected[0].3 = "CANCELLED".into();
    assert_eq!(attempts(&writer, &run).await, expected);
}

pub(crate) async fn wait_at_phase(run: &str, phase: &'static str) {
    let gate = GATES.get_or_init(Default::default).lock().unwrap()
        .get(&(run.into(), phase)).cloned();
    if let Some(gate) = gate {
        tokio::task::spawn_blocking(move || gate.hit()).await.unwrap();
    }
}

pub(crate) async fn release_committed_guard(client: &tokio_postgres::Client, run: &str) {
    let gate = GATES.get_or_init(Default::default).lock().unwrap()
        .get(&(run.into(), "release_committed_guard")).cloned();
    if let Some(gate) = gate {
        let row = client.query_one("SELECT pg_catalog.pg_advisory_unlock(1329199301,5)", &[]).await.unwrap();
        assert!(row.get::<_, bool>(0));
        gate.entered.store(true, Ordering::Release);
        gate.changed.notify_waiters();
    }
}

async fn stop_after_unknown_commit(service: &mut Service, writer: &SharedAuthority) {
    let mut observed = service.subscribe();
    tokio::time::timeout(std::time::Duration::from_secs(15), async {
        while observed.changed().await.is_ok() {}
    }).await.expect("worker must stop scanning after an unknown COMMIT");
    assert_eq!(service.status(), Status::Uncertain("BACKTEST_PUBLICATION_OUTCOME_UNKNOWN"));
    assert!(!service.wake().notify());
    service.drain().await.unwrap();
    {
        let mut held = writer.lock().await;
        let original = held.as_mut().unwrap();
        assert!(matches!(
            original.control_roles(),
            Err(crate::persistence::authority_session::AuthorityError::Lost)
        ));
        assert!(original.client_mut().await.is_err());
    }

    let mut inspector = fact_connection::Connection::operator().await.unwrap();
    let tx = inspector.client.transaction().await.unwrap();
    crate::persistence::postgres::bounds(&tx).await.unwrap();
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    tx.rollback().await.unwrap();
}

async fn open_node_authority() -> AuthoritySession {
    let mut config = fact_connection::Connection::controlled_config().unwrap();
    config.user("onlyalpha_node_test");
    config.options("-c search_path=pg_catalog,public,pg_temp");
    let (client, driver) = config.connect(tokio_postgres::NoTls).await.unwrap();
    AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap()
}

pub(crate) async fn resolve_unknown_commits(
    node: crate::bootstrap::workstation_startup::FaultedBacktestOwner<'_>,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: &VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
    context: &Context<'_>,
    cancel: CommandId,
) {
    use crate::{
        bootstrap::workstation_startup::{publication_fault::Mode, test_job_fact_reader},
        persistence::job_publication::{PublicationError, PublicationRepository, RunLocator},
    };
    let key = RunLocator::new(crate::application::job_contract::JobKind::Backtest, run.run_id()).unwrap();
    let mut observer = fact_connection::Connection::publisher().await.unwrap();
    let mut repository = PublicationRepository::new(&mut observer.client, run.namespace(), run.owner()).await.unwrap();
    let barrier = gate(run.run_id(), "before_finalization");
    let (connection, writer, mut fault) = node
        .open(run.namespace(), Mode::PauseBeforeCommit)
        .await
        .unwrap();
    let facts = test_job_fact_reader(&connection).await.unwrap();
    let mut service = Service::start(connection, facts, writer.clone(), sources.clone(), physical.clone(), configuration.clone(), clock).unwrap();
    barrier.entered().await;
    let before = attempts(&writer, run).await;
    assert_eq!(before.len(), 1);
    assert_eq!((before[0].1, before[0].3.as_str()), (1, "ACTIVE"));
    let PublicationObservation::ConfirmedUnpublished(original) = repository.observe(&key).await.unwrap() else {
        panic!("first Attempt must still own an unpublished Run");
    };
    let immutable = original.binding().fingerprint().to_owned();
    let commit = gate(run.run_id(), "before_publication_commit");
    drop(barrier);
    commit.entered().await;
    fault.arm();
    drop(commit);
    fault.entered().await;
    assert!(matches!(repository.observe(&key).await.unwrap(), PublicationObservation::Unresolved));
    assert_eq!(repository.read(&key).await.unwrap_err(), PublicationError::MissingEvidence);
    let inspector = fact_connection::Connection::operator().await.unwrap();
    let visible: i64 = inspector.client.query_one(
        "SELECT count(*) FROM public.job_result_member WHERE job_kind='BACKTEST' AND run_id=$1::text::uuid",
        &[&run.run_id()],
    ).await.unwrap().get(0);
    assert_eq!(visible, 0);
    fault.disconnect();
    stop_after_unknown_commit(&mut service, &writer).await;
    let PublicationObservation::ConfirmedUnpublished(rolled_back) = repository.observe(&key).await.unwrap() else {
        panic!("disconnected original transaction must resolve to confirmed absence");
    };
    assert_eq!(rolled_back.binding().fingerprint(), immutable);
    assert_eq!((rolled_back.run_state(), rolled_back.attempts(), rolled_back.active_attempts()), ("RUNNING", 1, 1));

    let barrier = gate(run.run_id(), "before_finalization");
    let (connection, writer, mut fault) = node
        .open(run.namespace(), Mode::DropCommitReply)
        .await
        .unwrap();
    assert_eq!(attempts(&writer, run).await, before);
    expire_original(run.run_id()).await;
    let facts = test_job_fact_reader(&connection).await.unwrap();
    let mut service = Service::start(connection, facts, writer.clone(), sources, physical, configuration, clock).unwrap();
    barrier.entered().await;
    let recomputed = attempts(&writer, run).await;
    assert_eq!(recomputed.len(), 2);
    assert_eq!(recomputed[1].3, "ACTIVE");
    let run_state = "SELECT state, revision, cancel_requested_at, finished_at, result_fingerprint \
                     FROM public.backtest_run WHERE run_id=$1::text::uuid";
    let original_run = inspector.client.query_one(run_state, &[&run.run_id()]).await.unwrap();
    assert_eq!(original_run.get::<_, &str>(0), "RUNNING");
    let original_revision: i64 = original_run.get(1);
    let receipt = request_and_replay_cancel(&writer, run, context, cancel.clone(), clock().unwrap()).await;
    let cancelled = inspector.client.query_one(run_state, &[&run.run_id()]).await.unwrap();
    let cancelled_at: std::time::SystemTime = cancelled.get(2);
    assert_eq!(cancelled.get::<_, &str>(0), "CANCEL_REQUESTED");
    assert_eq!(cancelled.get::<_, i64>(1), original_revision + 1);
    assert_eq!(attempts(&writer, run).await, recomputed);
    let commit = gate(run.run_id(), "before_publication_commit");
    drop(barrier);
    commit.entered().await;
    fault.arm();
    drop(commit);
    fault.entered().await;
    stop_after_unknown_commit(&mut service, &writer).await;
    let mut recovery = open_node_authority().await;
    let PublicationObservation::Published(published) = PublicationRepository::observe_guarded(
        &mut recovery, run.namespace(), run.owner(), &key,
    ).await.unwrap() else {
        panic!("server COMMIT acknowledgement must resolve to the original publication");
    };
    let reopened_receipt = crate::persistence::postgres::Commands::new(
        recovery.client_mut().await.unwrap(),
    ).load_verified_receipt(&cancel).await.unwrap();
    assert_eq!(reopened_receipt, Some(receipt));
    recovery.close().await.unwrap();
    assert_eq!(published.binding().fingerprint(), immutable);
    assert_eq!(published.member_count(), 4);
    let completed = inspector.client.query_one(run_state, &[&run.run_id()]).await.unwrap();
    assert_eq!(completed.get::<_, &str>(0), "COMPLETED");
    assert_eq!(completed.get::<_, i64>(1), original_revision + 2);
    assert_eq!(completed.get::<_, std::time::SystemTime>(2), cancelled_at);
    assert!(completed.get::<_, std::time::SystemTime>(3) >= cancelled_at);
    assert_eq!(completed.get::<_, &str>(4), published.fingerprint());
    let final_attempts = inspector.client.query(
        "SELECT attempt_id::text, attempt_number, fencing_token, state FROM public.backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",
        &[&run.run_id()],
    ).await.unwrap().iter().map(|row| (row.get(0), row.get(1), row.get(2), row.get(3))).collect::<Vec<_>>();
    assert_recomputed(&before, &final_attempts);
    let mut won = recomputed;
    won[1].3 = "SUCCEEDED".into();
    assert_eq!(final_attempts, won);
}

/// The harness runs this in its existing isolated owner process, then observes
/// exit86/original DB lease with the canonical driver-drain barrier.
pub(crate) async fn crash_after_publication(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) -> ! {
    let barrier = gate(run.run_id(), "after_publish");
    let release = gate(run.run_id(), "release_committed_guard");
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let _service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources,
        physical,
        configuration,
        clock,
    )
    .unwrap();
    release.entered().await;
    barrier.entered().await;
    assert!(matches!(
        writer.lock().await.as_ref().unwrap().control_roles(),
        Err(crate::persistence::authority_session::AuthorityError::Lost)
    ));
    use crate::persistence::job_publication::{PublicationRepository, RunLocator};
    let mut observer = open_node_authority().await;
    let key = RunLocator::new(
        crate::application::job_contract::JobKind::Backtest, run.run_id(),
    ).unwrap();
    let PublicationObservation::Published(published) = PublicationRepository::observe_guarded(
        &mut observer, run.namespace(), run.owner(), &key,
    ).await.unwrap() else {
        panic!("confirmed publication must survive original guard loss");
    };
    observer.close().await.unwrap();
    assert_eq!(published.member_count(), 4);
    println!("BACKTEST_PUBLICATION_CONFIRMED_WITHOUT_ORIGINAL_GUARD {}", run.run_id());
    std::io::Write::flush(&mut std::io::stdout()).unwrap();
    std::process::exit(86)
}

/// A cold worker must leave the already committed result and winning Attempt intact.
pub(crate) async fn recover_published(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    assert_terminal(&writer, &run, "COMPLETED").await;
    let before = attempts(&writer, &run).await;
    assert_eq!(before.len(), 1);
    assert_eq!((before[0].1, before[0].3.as_str()), (1, "SUCCEEDED"));
    let no_producer = gate(run.run_id(), "execute_frozen");
    no_producer.release();
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(connection, facts, writer.clone(), sources, physical, configuration, clock).unwrap();
    wait_for_idle(service.subscribe()).await;
    service.drain().await.unwrap();
    assert!(!no_producer.gate.entered.load(Ordering::Acquire));
    assert_terminal(&writer, &run, "COMPLETED").await;
    assert_eq!(attempts(&writer, &run).await, before);
}

/// Read-only inspector is supplied by the canonical test harness. It carries
/// no mutation guard and is never adopted as a replacement AuthoritySession.
pub(crate) async fn lost_original_guard(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    following: &VerifiedRun,
    inspector: &mut tokio_postgres::Client,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let barrier = gate(run.run_id(), "before_produce");
    let uncertain = gate(run.run_id(), "ownership_uncertain");
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        configuration.clone(),
        clock,
    )
    .unwrap();
    barrier.entered().await;
    {
        let mut held = writer.lock().await;
        assert!(
            held.as_mut()
                .unwrap()
                .client_mut()
                .await
                .unwrap()
                .query_one("SELECT pg_advisory_unlock(1329199301,5)", &[])
                .await
                .unwrap()
                .get::<_, bool>(0)
        );
    }
    assert!(service.wake().notify());
    uncertain.entered().await;
    assert!(
        !service.task.as_ref().unwrap().is_finished(),
        "the actual job and cleanup owner remain retained before the blocking gate is released"
    );
    let mut observations = service.subscribe();
    drop(barrier);
    tokio::time::timeout(std::time::Duration::from_secs(15), async {
        while observations.changed().await.is_ok() {}
    })
    .await
    .expect("worker must leave its scan after joining the original work");
    assert!(matches!(service.status(), Status::Uncertain(_)));
    assert!(!service.wake().notify());
    service.drain().await.unwrap();
    let row=inspector.query_one("SELECT state,evidence_fingerprint,result_fingerprint,determinism_fingerprint FROM backtest_run WHERE run_id=$1::text::uuid",&[&run.run_id()]).await.unwrap();
    assert_eq!(row.get::<_, &str>(0), "RUNNING");
    for index in 1..4 {
        assert!(row.get::<_, Option<String>>(index).is_none());
    }
    let attempts = inspector
        .query(
            "SELECT state,failure_code FROM backtest_run_attempt WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await
        .unwrap();
    assert_eq!(attempts.len(), 1);
    assert_eq!(attempts[0].get::<_, &str>(0), "ACTIVE");
    assert!(attempts[0].get::<_, Option<String>>(1).is_none());
    let following_state = inspector.query_one(
        "SELECT state, NOT EXISTS (SELECT 1 FROM backtest_run_attempt WHERE run_id=backtest_run.run_id) FROM backtest_run WHERE run_id=$1::text::uuid",
        &[&following.run_id()],
    ).await.unwrap();
    assert_eq!(following_state.get::<_, &str>(0), "QUEUED");
    assert!(following_state.get::<_, bool>(1));
    assert!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"]
            != true,
        "uncertain original outcome cannot release work"
    );
}

#[tokio::test]
async fn registry_contention_does_not_fail_the_terminal_cleanup_scan() {
    let parent = std::env::temp_dir()
        .canonicalize()
        .unwrap()
        .join(uuid4().unwrap());
    std::fs::create_dir(&parent).unwrap();
    let configuration = Configuration {
        research_root: parent.join("research"),
        runtime_root: parent.join("runtime"),
        algorithms_root: parent.join("algorithms"),
        native_version: env!("CARGO_PKG_VERSION").into(),
    };
    let exclusive = Registry::initialize_fresh(&configuration.runtime_root).unwrap();
    assert_eq!(
        Registry::unreleased_work_bindings(&configuration.runtime_root),
        Err("RESEARCH_RUNTIME_UNAVAILABLE")
    );
    assert_eq!(
        Registry::try_unreleased_work_bindings(&configuration.runtime_root),
        Ok(None)
    );
    let wake = Wake(Arc::new(Admission {
        state: AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, _) = watch::channel(Status::Idle);
    let writer = Arc::new(tokio::sync::Mutex::new(None));
    let namespace = SemanticStoreId::new(&uuid4().unwrap()).unwrap();
    let clock = || panic!("empty cleanup must not release or create work");
    // Hold the exact writer guard across the real cleanup scan, then release
    // that guard explicitly. Neither scan is ordered by a timer.
    let blocked = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    drop(exclusive);
    assert_eq!(
        Registry::try_unreleased_work_bindings(&configuration.runtime_root),
        Ok(Some(Vec::new()))
    );
    let released = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    use std::os::unix::fs::PermissionsExt;
    let lock = configuration
        .runtime_root
        .join(".generation-authority.lock");
    std::fs::set_permissions(&lock, std::fs::Permissions::from_mode(0o644)).unwrap();
    let corrupt = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    std::fs::remove_file(lock).unwrap();
    let missing = cleanup_terminal(
        &mut None,
        &writer,
        &configuration,
        &wake,
        &status,
        &clock,
        &namespace,
    )
    .await;
    std::fs::remove_dir_all(&parent).unwrap();
    assert_eq!(corrupt, Err("RESEARCH_RUNTIME_PROOF_INVALID"));
    assert_eq!(missing, Err("RESEARCH_RUNTIME_UNAVAILABLE"));
    assert_eq!(released, Ok(()));
    assert_eq!(blocked, Ok(()));
}

#[test]
fn terminal_release_error_distinguishes_unknown_write_from_storage_failure() {
    for status in [Status::Idle, Status::Running("run".into()), Status::Uncertain(CLEANUP_PENDING)] {
        assert_eq!(
            status.after_error("RUNTIME_GENERATION_OUTCOME_UNKNOWN"),
            Status::Uncertain("RUNTIME_GENERATION_OUTCOME_UNKNOWN")
        );
        assert_eq!(
            status.after_error("RESEARCH_RUNTIME_UNAVAILABLE"),
            Status::Unavailable("RESEARCH_RUNTIME_UNAVAILABLE")
        );
    }
    let unknown_heartbeat = Status::Uncertain(UNAVAILABLE);
    assert_eq!(unknown_heartbeat.after_error(UNAVAILABLE), unknown_heartbeat);
}

#[tokio::test]
async fn stopped_admission_never_polls_a_new_restore_or_revives_on_wake() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    wake.stop();
    assert!(!wake.notify());
    let entered = AtomicBool::new(false);
    assert!(
        handoff(&wake, async {
            entered.store(true, Ordering::Release);
            Ok(())
        })
        .await
        .is_none()
    );
    assert!(!entered.load(Ordering::Acquire));
}

#[tokio::test(start_paused = true)]
async fn stopped_cleanup_retries_after_its_stop_notification_was_already_consumed() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    wake.stop();
    wake.0.changed.notified().await;
    assert!(!wake.notify());
    let mut retry = tokio::time::interval_at(
        tokio::time::Instant::now() + std::time::Duration::from_secs(5),
        std::time::Duration::from_secs(5),
    );
    retry.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    let mut pending = Box::pin(wait_cleanup(&wake, &mut retry));
    tokio::select! {biased;_=&mut pending=>panic!("no cleanup retry was requested yet"),_=std::future::ready(())=>{}}
    tokio::time::advance(std::time::Duration::from_secs(5)).await;
    tokio::select! {biased;_=&mut pending=>{},_=std::future::ready(())=>panic!("stopped cleanup lost its only future retry")}
}

/// The external hold is a real archived Runtime owning reader, never a fake
/// busy callback. Releasing it sends no HTTP wake or new work permission.
pub(crate) async fn cleanup_busy_then_stop(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    let external = crate::persistence::research_runtime::RuntimeEvidenceHold::open(
        &configuration.runtime_root,
        run.run_id(),
        run.resolution()["runtime_work_binding"]["reason"]
            .as_str()
            .unwrap(),
        run.runtime_generation_fingerprint(),
    )
    .unwrap();
    let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&connection)
        .await
        .unwrap();
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        configuration.clone(),
        clock,
    )
    .unwrap();
    let mut observed = service.subscribe();
    loop {
        let current = observed.borrow().clone();
        match current {
            Status::Uncertain("BACKTEST_RUNTIME_CLEANUP_PENDING") => break,
            Status::Unavailable(code) => panic!("{code}"),
            _ => {}
        }
        observed.changed().await.unwrap();
    }
    assert_terminal(&writer, &run, "COMPLETED").await;
    external.verify().unwrap();
    service.wake().stop();
    assert!(!service.wake().notify());
    let mut drain = Box::pin(service.drain());
    tokio::select! {biased;result=&mut drain=>panic!("external actual read cut is still held: {result:?}"),_=std::future::ready(())=>{}}
    drop(drain);
    drop(external);
    // Await the actual service/Registry completion. The separate paused-time
    // unit proves its retry trigger; elapsed time never proves release here.
    service.drain().await.unwrap();
    assert_eq!(
        Registry::inspect_work(
            &configuration.runtime_root,
            run.run_id(),
            run.runtime_generation_fingerprint(),
            run.resolution()["runtime_work_binding"]["reason"]
                .as_str()
                .unwrap()
        )
        .unwrap()["closed"],
        true
    );
    let mut held = writer.lock().await;
    let rows = held
        .as_mut()
        .unwrap()
        .client_mut()
        .await
        .unwrap()
        .query(
            "SELECT state FROM backtest_run_attempt WHERE run_id=$1::text::uuid",
            &[&run.run_id()],
        )
        .await
        .unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].get::<_, &str>(0), "SUCCEEDED");
}

// No test calls stop/drain before checking admission. Waiting for the real
// task's final Sender to drop is the deterministic task-exit barrier.
#[tokio::test]
async fn known_task_error_closes_wake_before_any_drain_request() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, mut observed) = watch::channel(Status::Starting);
    let exit = TaskExit {
        wake: wake.clone(),
        status: status.clone(),
    };
    let task = tokio::spawn(async move {
        let _exit = exit;
        status.send_replace(Status::Unavailable("BACKTEST_SERVICE_UNAVAILABLE"));
        Err::<(), &'static str>("BACKTEST_SERVICE_UNAVAILABLE")
    });
    while observed.changed().await.is_ok() {}
    assert_eq!(task.await.unwrap(), Err("BACKTEST_SERVICE_UNAVAILABLE"));
    assert_eq!(
        *observed.borrow(),
        Status::Unavailable("BACKTEST_SERVICE_UNAVAILABLE")
    );
    assert!(
        !wake.notify(),
        "an exited task must refuse new work without a Host shutdown request"
    );
    assert!(!wake.begin(), "an exited task cannot admit another restore");
}

#[tokio::test]
async fn task_panic_closes_wake_and_reports_unknown_without_proving_drain() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, observed) = watch::channel(Status::Running(
        "12345678-1234-4234-8234-123456789abc".into(),
    ));
    let exit = TaskExit {
        wake: wake.clone(),
        status,
    };
    let task = tokio::spawn(async move {
        let _exit = exit;
        panic!("deterministic task panic");
        #[allow(unreachable_code)]
        Ok(())
    });
    let mut service = Service {
        wake: wake.clone(),
        status: observed,
        task: Some(task),
        drained: None,
    };
    let mut observed = service.subscribe();
    while observed.changed().await.is_ok() {}
    assert!(
        !wake.notify(),
        "panic must stop admission before any caller asks to drain"
    );
    assert_eq!(
        service.status(),
        Status::Uncertain("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
    assert_eq!(
        service.drained, None,
        "a dead task is not positive child/connection drain evidence"
    );
    assert_eq!(
        service.drain().await,
        Err("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
}

#[test]
fn unpolled_task_future_already_owns_its_exit_guard() {
    let wake = Wake(Arc::new(Admission {
        state: std::sync::atomic::AtomicU8::new(0),
        changed: Notify::new(),
    }));
    let (status, observed) = watch::channel(Status::Starting);
    let exit = TaskExit {
        wake: wake.clone(),
        status,
    };
    let unpolled = async move {
        let _exit = exit;
        std::future::pending::<()>().await;
    };
    drop(unpolled);
    assert!(
        !wake.notify(),
        "task ownership starts when its future is constructed"
    );
    assert_eq!(
        *observed.borrow(),
        Status::Uncertain("BACKTEST_SERVICE_OUTCOME_UNKNOWN")
    );
}

/// The formal scheduler must publish the actual finite result without opening
/// the retired Backtest result/journal owner. The original READY remains real.
pub(crate) async fn finite_publication(
    connection: ResearchConnection,
    writer: SharedAuthority,
    sources: SourceSessions,
    physical: Arc<crate::persistence::market_data::ClickHouse>,
    configuration: Configuration,
    run: VerifiedRun,
    clock: fn() -> std::result::Result<
        OnlyUtcDateTime,
        crate::application::research_admission::PreparationError,
    >,
) {
    use crate::bootstrap::workstation_startup::test_job_fact_reader;
    use crate::persistence::{
        backtest_run::pending_native_run_ids,
        job_publication::{PublicationRepository, RunLocator},
    };

    {
        let mut held = writer.lock().await;
        let client = held.as_mut().unwrap().client_mut().await.unwrap();
        assert!(pending_native_run_ids(client, run.namespace()).await.unwrap()
            .iter().any(|id| id == run.run_id()));
    }
    let mut publication_facts = test_job_fact_reader(&connection).await.unwrap();
    let facts = test_job_fact_reader(&connection).await.unwrap();
    let economic_publication = gate(run.run_id(), "economic_publication");
    let retired_store = configuration.runtime_root.with_file_name("backtest");
    assert!(!retired_store.exists());
    let mut service = Service::start(
        connection,
        facts,
        writer.clone(),
        sources,
        physical,
        configuration,
        clock,
    )
    .unwrap();
    let mut observed = service.subscribe();
    let outcome = tokio::time::timeout(Duration::from_secs(30), async {
        let mut running = false;
        loop {
            match observed.borrow_and_update().clone() {
                Status::Running(id) if id == run.run_id() => running = true,
                Status::Idle if running => return Ok::<_, &'static str>(()),
                Status::Uncertain(code) | Status::Unavailable(code) => return Err(code),
                Status::Stopped => return Err("BACKTEST_STOPPED_BEFORE_PUBLICATION"),
                _ => {}
            }
            observed
                .changed()
                .await
                .map_err(|_| "BACKTEST_OBSERVER_CLOSED")?;
        }
    })
    .await;
    let drained = service.drain().await;
    outcome
        .expect("original Backtest scheduler budget")
        .expect("finite PG publication");
    drained.unwrap();
    assert!(economic_publication.gate.entered.load(Ordering::Acquire));
    assert!(
        !retired_store.exists(),
        "finite worker must not recreate the obsolete result/journal store"
    );
    let mut held = writer.lock().await;
    let original = held.as_mut().unwrap();
    original.verify().await.unwrap();
    let key = RunLocator::new(crate::application::job_contract::JobKind::Backtest, run.run_id())
        .unwrap();
    let result = PublicationRepository::new(
        publication_facts.client_mut().await.unwrap(),
        run.namespace(),
        run.owner(),
    )
    .await
    .unwrap()
    .read_backtest(&key, original.client_mut().await.unwrap())
    .await
    .unwrap();
    assert_eq!(result.member_count(), 4);
    publication_facts.close().await.unwrap();
    let client = original.client_mut().await.unwrap();
    assert!(!pending_native_run_ids(client, run.namespace()).await.unwrap()
        .iter().any(|id| id == run.run_id()));
    let rows = client.query(
        "SELECT state,attempt_number FROM public.backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",
        &[&run.run_id()],
    ).await.unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].get::<_, String>(0), "SUCCEEDED");
    assert_eq!(rows[0].get::<_, i32>(1), 1);
    drop(held);
    assert_terminal(&writer, &run, "COMPLETED").await;
}
