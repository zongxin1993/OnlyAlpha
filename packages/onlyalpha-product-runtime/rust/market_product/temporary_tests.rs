//! Real Application boundary, controlled Provider input, and no store capability.
use super::*;
use crate::{
    integration_configuration::{IntegrationId, RuntimeBinding, RuntimeBindingRecord},
    source_access::{Authority, Grant, Permission, Reference, Selection},
};
use onlyalpha_domain::{calendar::OnlyTradingCalendar, instrument::OnlyInstrument};
use onlyalpha_integration_contract::{Category, IntegrationTypeId, source::*};
use onlyalpha_market_data_construction::OnlyConstructionCapability;
use std::sync::atomic::{AtomicUsize, Ordering};
const MINUTE: i64 = 60_000_000_000;
struct FixedClock;
impl Clock for FixedClock {
    fn now_ns(&self) -> std::result::Result<i64, SourceError> {
        Ok((20 * 1440 + 20) * MINUTE)
    }
}
#[derive(Clone, Copy)]
pub(in crate::market_product) enum TemporaryFault {
    OpenConflict,
    StreamConflict,
    ReferenceUnavailableAfterDiscovery,
    ExactReferenceRequiresSymbol,
    EmptyReference,
}
struct Feed {
    fault: Option<TemporaryFault>,
    calendar: OnlyTradingCalendar,
    capabilities: Vec<OnlyConstructionCapability>,
    identity: MarketIdentity,
    calls: Arc<AtomicUsize>,
    available_from: Option<i64>,
}
impl Resource for Feed {
    fn identity(&self) -> &MarketIdentity {
        &self.identity
    }
    fn calendar(&self) -> &OnlyTradingCalendar {
        &self.calendar
    }
    fn capabilities(&self) -> &[OnlyConstructionCapability] {
        &self.capabilities
    }
    fn resume_max_bars(&self) -> u16 {
        120
    }
    fn instruments<'a>(
        &'a self,
        symbols: &'a [String],
        _: Budget,
    ) -> FutureResult<'a, Vec<OnlyInstrument>> {
        Box::pin(async move {
            if matches!(
                self.fault,
                Some(TemporaryFault::ExactReferenceRequiresSymbol)
            ) {
                self.calls.fetch_add(1, Ordering::SeqCst);
                if symbols != ["TEST".to_owned()] {
                    return Err(SourceError::Unavailable);
                }
            }
            if matches!(self.fault, Some(TemporaryFault::EmptyReference)) {
                return Ok(vec![]);
            }
            if matches!(
                self.fault,
                Some(TemporaryFault::ReferenceUnavailableAfterDiscovery)
            ) && self.calls.fetch_add(1, Ordering::SeqCst) != 0
            {
                return Err(SourceError::Unavailable);
            }
            let mut row: Value =
                include_str!("../../../../test-data/domain/instrument-records-v2.jsonl")
                    .lines()
                    .map(|s| serde_json::from_str::<Value>(s).unwrap())
                    .find(|v| v["id"] == "OnlyCryptoSpot")
                    .unwrap()["record"]
                    .clone();
            row["instrument_id"] = "TEST.TEST"
                .parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>()
                .unwrap()
                .to_record();
            row["raw_symbol"] = json!({"schema_version":1,"value":"TEST"});
            Ok(vec![OnlyInstrument::from_record(&row).unwrap()])
        })
    }
    fn quotes<'a>(&'a self, _: &'a [String], _: Budget) -> FutureResult<'a, Vec<Quote>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn history<'a>(
        &'a self,
        _: &'a HistoryRequest,
        _: Budget,
        _: &'a mut dyn Recorder,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async { panic!("temporary queries cannot enter durable capture") })
    }
    fn stream<'a>(
        &'a self,
        _: HistoryRequest,
        _: Option<i64>,
        _: Budget,
    ) -> FutureResult<'a, Box<dyn Stream>> {
        Box::pin(async { panic!("temporary history cannot open a durable stream") })
    }
    fn probe<'a>(&'a self, _: &'a str, _: Budget) -> FutureResult<'a, Value> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn temporary_stream<'a>(
        &'a self,
        request: HistoryRequest,
        checkpoint: OnlyBar,
        _: Budget,
    ) -> FutureResult<'a, Box<dyn TemporaryStream>> {
        Box::pin(async move {
            assert_eq!(request.minutes, 1);
            if matches!(self.fault, Some(TemporaryFault::OpenConflict)) {
                return Err(SourceError::Conflict);
            }
            if matches!(self.fault, Some(TemporaryFault::StreamConflict)) {
                return Ok(Box::new(TemporaryFeed {
                    events: std::collections::VecDeque::from([StreamEvent::Lost(
                        SourceError::Conflict,
                    )]),
                    calls: Arc::clone(&self.calls),
                }) as Box<dyn TemporaryStream>);
            }
            let first = ns(*checkpoint.bar_end()).unwrap() / MINUTE;
            if 20 * 1440 + 20 - first > 120 {
                return Err(SourceError::RefreshRequired);
            }
            let mut events = std::collections::VecDeque::from([StreamEvent::Recovering]);
            for index in first..20 * 1440 + 20 {
                events.push_back(StreamEvent::Closed(
                    super::tests::bar(index, "10.00"),
                    index,
                    Some(IngressTiming {
                        provider_event_ns: (index + 1) * MINUTE + 1,
                        ingress_received_ns: (index + 1) * MINUTE + 2,
                    }),
                ));
            }
            events.push_back(StreamEvent::Ready);
            let mut preview = super::tests::bar(20 * 1440 + 20, "10.00").to_record();
            preview["is_closed"] = json!(false);
            events.push_back(StreamEvent::Preview(
                OnlyBar::from_record(&preview).unwrap(),
                20 * 1440 + 20,
                None,
            ));
            Ok(Box::new(TemporaryFeed {
                events,
                calls: Arc::clone(&self.calls),
            }) as Box<dyn TemporaryStream>)
        })
    }
    fn temporary_history<'a>(
        &'a self,
        request: &'a HistoryRequest,
        _: Budget,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async move {
            assert_eq!(request.minutes, 1);
            let first = request.start_ms / 60_000;
            let last = request.end_ms / 60_000;
            assert!((1..=1000).contains(&(last - first)));
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok((first..last)
                .filter(|index| self.available_from.is_none_or(|start| *index >= start))
                .map(|index| super::tests::bar(index, "10.00"))
                .collect())
        })
    }
}
fn source() -> (Authority, Session, Resolved, Arc<AtomicUsize>) {
    source_from(None, None)
}
pub(in crate::market_product) fn source_from(
    available_from: Option<i64>,
    fault: Option<TemporaryFault>,
) -> (Authority, Session, Resolved, Arc<AtomicUsize>) {
    let calendar=OnlyTradingCalendar::from_record(&json!({"schema_version":1,"calendar_id":{"schema_version":1,"value":"TEST-24X7"},"venue_id":{"schema_version":1,"value":"TEST"},"timezone":{"schema_version":1,"name":"UTC"},"sessions":[{"schema_version":1,"name":"continuous","opens_at":"00:00:00","closes_at":"00:00:00","session_type":"CONTINUOUS","belongs_to_trading_day_offset":0,"allows_orders":true,"allows_market_data":true}],"holidays":[],"weekend_days":[],"session_profile_id":null,"special_schedules":[],"calendar_version":1,"effective_from":null,"effective_to":null})).unwrap();
    let reference = Reference::new(
        "00000000-0000-4000-8000-000000000003",
        &"a".repeat(64),
        Some("test.source"),
    )
    .unwrap();
    let selection = Selection::new(reference, "test-feed", "TEST").unwrap();
    let token = "a".repeat(64);
    let authority = Authority::new(
        "human",
        &hash(token.as_bytes()),
        vec![
            Grant::new(
                selection.clone(),
                vec![Permission::ClosedHistory, Permission::RealtimePreview],
            )
            .unwrap(),
        ],
    )
    .unwrap();
    let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let capabilities = vec![
        OnlyConstructionCapability::new(
            queries::semantic(1).unwrap(),
            true,
            true,
            &fp(&calendar.to_record()).unwrap(),
            Some(0.into()),
        )
        .unwrap(),
    ];
    let feed = Feed {
        fault,
        calendar,
        capabilities,
        identity: MarketIdentity {
            provider: "test.provider".into(),
            venue: "TEST".into(),
            market: "TEST_MARKET".into(),
            environment: "TEST".into(),
            source_id: "test-feed".into(),
        },
        calls: Arc::clone(&calls),
        available_from,
    };
    let binding = RuntimeBinding::new(RuntimeBindingRecord {
        integration_id: IntegrationId::new("00000000-0000-4000-8000-000000000003").unwrap(),
        revision_fingerprint: "a".repeat(64),
        type_id: IntegrationTypeId::new("test.source").unwrap(),
        category: Category::DataSource,
        type_descriptor_fingerprint: "b".repeat(64),
        runtime_configuration_fingerprint: "c".repeat(64),
        runtime_generation_fingerprint: None,
    })
    .unwrap();
    let resolved = Resolved {
        selection,
        binding,
        resource: Arc::new(feed),
        artifact: "d".repeat(64),
        implementation: "e".repeat(64),
        data_version: "test@1".into(),
        probe_contract: "f".repeat(64),
        probe_configuration: None,
        probe_symbol: "TEST".into(),
        clock: Arc::new(FixedClock),
    };
    (authority, session, resolved, calls)
}
#[tokio::test(flavor = "current_thread")]
async fn temporary_application_prepares_native_and_seven_minute_windows_without_storage() {
    for minutes in [1, 7] {
        let (authority, session, resolved, calls) = source();
        let app = Application::default();
        let request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(minutes).unwrap(),
            before_ns: None,
            bar_count: 2000,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let mut last = Value::Null;
        for step in 0..20 {
            let (value, fence) = app
                .temporary_window(
                    &resolved,
                    &session,
                    &request,
                    "00000000-0000-4000-8000-000000000001",
                    Instant::now() + std::time::Duration::from_secs(10),
                )
                .await
                .unwrap()
                .into_parts()
                .unwrap();
            fence.check().unwrap();
            assert_eq!(value["source_kind"], "TEMPORARY_MARKET_DATA");
            assert!(
                value["bars"].as_array().unwrap().len()
                    > last["bars"].as_array().map_or(0, Vec::len)
            );
            last = value;
            if step == 0 {
                assert_eq!(last["coverage"]["status"], "PARTIAL");
            }
            if last["coverage"]["status"] == "COMPLETE" {
                break;
            }
        }
        assert_eq!(last["coverage"]["status"], "COMPLETE");
        assert_eq!(last["bars"].as_array().unwrap().len(), 2000);
        let fetched = calls.load(Ordering::SeqCst);
        let cached = app
            .temporary_window(
                &resolved,
                &session,
                &request,
                "00000000-0000-4000-8000-000000000002",
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        assert_eq!(cached["window_fingerprint"], last["window_fingerprint"]);
        assert_eq!(calls.load(Ordering::SeqCst), fetched);
        authority.withdraw();
        assert!(matches!(
            app.temporary_window(
                &resolved,
                &session,
                &request,
                "00000000-0000-4000-8000-000000000001",
                Instant::now() + std::time::Duration::from_secs(10)
            )
            .await,
            Err(Error::Forbidden)
        ));
    }
}
#[tokio::test(flavor = "current_thread")]
async fn sparse_temporary_history_keeps_complete_bars_and_reports_unfilled_inputs() {
    for minutes in [1, 7] {
        let (_authority, session, resolved, _) = source_from(Some(20 * 1440 - 1200), None);
        let app = Application::default();
        let request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(minutes).unwrap(),
            before_ns: None,
            bar_count: 2000,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let mut last_count = 0;
        let mut last = Value::Null;
        for _ in 0..4 {
            last = app
                .temporary_window(
                    &resolved,
                    &session,
                    &request,
                    "00000000-0000-4000-8000-000000000001",
                    Instant::now() + std::time::Duration::from_secs(10),
                )
                .await
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            let count = last["bars"].as_array().unwrap().len();
            if count == last_count {
                break;
            }
            last_count = count;
        }
        assert_eq!(last["coverage"]["status"], "PARTIAL");
        let count = last["bars"].as_array().unwrap().len();
        assert!(count > 0 && count < 2000);
        if minutes == 1 {
            assert_eq!(count, 1200);
        }
        assert_eq!(
            last["coverage"]["gaps"].as_array().unwrap().len(),
            2000 - count
        );
    }
}
#[tokio::test(flavor = "current_thread")]
async fn cached_temporary_input_keeps_exact_scope_and_actual_native_frontier_without_io() {
    for minutes in [1, 7] {
        let (_authority, session, resolved, calls) = source();
        let app = Application::default();
        let request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(minutes).unwrap(),
            before_ns: Some((19 * 1440 + 14) * MINUTE),
            bar_count: 2,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let page = "00000000-0000-4000-8000-000000000001";
        let loaded = app
            .temporary_window(
                &resolved,
                &session,
                &request,
                page,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        let expected = loaded["window_fingerprint"].as_str().unwrap();
        let prepared = app
            .cached_temporary_input(
                &resolved,
                &session,
                &request,
                page,
                expected,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap();
        assert_eq!(
            prepared.checkpoint.bar_type().semantic(),
            &queries::semantic(1).unwrap()
        );
        assert_eq!(
            ns(*prepared.checkpoint.bar_end()).unwrap(),
            request.before_ns.unwrap()
        );
        assert_eq!(
            prepared.window.parts().unwrap().0["window_fingerprint"],
            expected
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(matches!(
            app.cached_temporary_input(
                &resolved,
                &session,
                &request,
                page,
                &"f".repeat(64),
                Instant::now() + std::time::Duration::from_secs(10)
            )
            .await,
            Err(Error::Conflict)
        ));
        prepared.entry.lock().await.state.invalidate().unwrap();
        assert!(prepared.window.parts().is_err());
        let refreshed = app
            .temporary_window(
                &resolved,
                &session,
                &request,
                page,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        assert_eq!(refreshed["window_fingerprint"], expected);
        assert!(
            prepared.window.parts().is_err(),
            "equal content cannot reauthorize the original input occurrence"
        );
    }
}

// A second page may evict memory, but cannot turn ordinary cache eviction
// into a conflicting Provider fact or withdraw a previously fenced snapshot.
#[tokio::test(flavor = "current_thread")]
async fn another_pages_deep_history_eviction_requires_refresh_not_provenance_conflict() {
    let (_authority, session, resolved, _calls) = source();
    let app = Application::default();
    let deadline = || Instant::now() + std::time::Duration::from_secs(10);
    let current = WindowRequest {
        instrument_id: "TEST.TEST".into(),
        semantic: queries::semantic(1).unwrap(),
        before_ns: Some((19 * 1440 + 14) * MINUTE),
        bar_count: 2000,
        clock_ns: 20 * 1440 * MINUTE,
    };
    let b = "00000000-0000-4000-8000-000000000002";
    let a = "00000000-0000-4000-8000-000000000001";
    let mut original = Value::Null;
    for _ in 0..2 {
        original = app
            .temporary_window(&resolved, &session, &current, b, deadline())
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        // A caller that actually observed this partial window still receives
        // INPUT_INCOMPLETE, rather than an invented eviction or complete input.
        assert!(
            app.cached_temporary_input(
                &resolved,
                &session,
                &current,
                b,
                original["window_fingerprint"].as_str().unwrap(),
                deadline()
            )
            .await
            .is_ok()
        );
    }
    assert_eq!(original["coverage"]["status"], "COMPLETE");
    let pinned = app
        .cached_temporary_input(
            &resolved,
            &session,
            &current,
            b,
            original["window_fingerprint"].as_str().unwrap(),
            deadline(),
        )
        .await
        .unwrap();
    let older = WindowRequest {
        before_ns: Some(current.before_ns.unwrap() - 4000 * MINUTE),
        ..current.clone()
    };
    for _ in 0..2 {
        app.temporary_window(&resolved, &session, &older, a, deadline())
            .await
            .unwrap()
            .parts()
            .unwrap();
    }
    let older = WindowRequest {
        before_ns: Some(current.before_ns.unwrap() - 6000 * MINUTE),
        bar_count: 240,
        ..current.clone()
    };
    app.temporary_window(&resolved, &session, &older, a, deadline())
        .await
        .unwrap()
        .parts()
        .unwrap();
    assert!(pinned.window.parts().is_ok());
    assert!(pinned.entry.lock().await.window.bars.len() <= 4000);
    let error = match app
        .cached_temporary_input(
            &resolved,
            &session,
            &current,
            b,
            original["window_fingerprint"].as_str().unwrap(),
            deadline(),
        )
        .await
    {
        Err(error) => error,
        Ok(_) => panic!("an evicted window cannot be admitted"),
    };
    assert!(
        matches!(error, Error::Source(SourceError::RefreshRequired)),
        "{}",
        error.code()
    );
    let mut refreshed = Value::Null;
    for _ in 0..2 {
        refreshed = app
            .temporary_window(&resolved, &session, &current, b, deadline())
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
    }
    assert_eq!(refreshed["coverage"]["status"], "COMPLETE");
    assert_eq!(
        refreshed["window_fingerprint"],
        original["window_fingerprint"]
    );
    assert!(
        app.cached_temporary_input(
            &resolved,
            &session,
            &current,
            b,
            refreshed["window_fingerprint"].as_str().unwrap(),
            deadline()
        )
        .await
        .is_ok()
    );
    assert!(pinned.window.parts().is_ok());
}

#[tokio::test(flavor = "current_thread")]
async fn live_indicator_prefix_survives_history_retention_without_another_provider_fetch() {
    async fn next_closed(stream: &mut super::super::TemporaryProductStream) -> i64 {
        for _ in 0..4 {
            let value = stream
                .next()
                .await
                .unwrap()
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            if value["event"] == "BAR_CLOSED" {
                return value["bar"]["bar_end_ns"]
                    .as_str()
                    .unwrap()
                    .parse()
                    .unwrap();
            }
        }
        panic!("the controlled stream must emit the next canonical close");
    }
    for (minutes, adjacent) in [(1, false), (7, false), (1, true), (7, true)] {
        let (_authority, session, resolved, calls) = source();
        let resolved = Arc::new(resolved);
        let app = Application::default();
        let page = "00000000-0000-4000-8000-000000000001";
        let deadline = || Instant::now() + std::time::Duration::from_secs(10);
        let mut current = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(minutes).unwrap(),
            before_ns: None,
            bar_count: 2000,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let mut loaded = Value::Null;
        for _ in 0..20 {
            loaded = app
                .temporary_window(&resolved, &session, &current, page, deadline())
                .await
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            if loaded["coverage"]["status"] == "COMPLETE" {
                break;
            }
        }
        assert_eq!(loaded["coverage"]["status"], "COMPLETE");
        current.before_ns = Some(loaded["resolved_end_ns"].as_str().unwrap().parse().unwrap());
        let mut stream = app
            .open_temporary_stream(
                Arc::clone(&resolved),
                &session,
                super::super::TemporaryStreamRequest {
                    stream_id: "00000000-0000-4000-8000-000000000002".into(),
                    page_id: page.into(),
                    window: current.clone(),
                    expected_window_fingerprint: loaded["window_fingerprint"]
                        .as_str()
                        .unwrap()
                        .into(),
                    deadline: deadline(),
                },
            )
            .await
            .unwrap();
        next_closed(&mut stream).await;
        // Adjacent older windows must complete while the live prefix shares
        // the same retention limit. The second page crosses the 4000-bar cap.
        let mut older = WindowRequest {
            before_ns: Some(if adjacent {
                current.before_ns.unwrap() - i64::from(minutes) * MINUTE
            } else {
                10 * 1440 * MINUTE
            }),
            ..current.clone()
        };
        for _ in 0..if adjacent { 2 } else { 1 } {
            let before = calls.load(Ordering::SeqCst);
            let mut historical = Value::Null;
            for _ in 0..20 {
                historical = app
                    .temporary_window(&resolved, &session, &older, page, deadline())
                    .await
                    .unwrap()
                    .into_parts()
                    .unwrap()
                    .0;
                if historical["coverage"]["status"] == "COMPLETE" {
                    break;
                }
            }
            assert_eq!(historical["coverage"]["status"], "COMPLETE");
            // Canonical 7m leaves a daily session tail. Provider fetches
            // cannot bridge it, so bound batches per planned contiguous run.
            let plan = crate::market_data::plan_bar_window(
                &older.semantic,
                older.before_ns,
                older.clock_ns,
                2000,
                2000,
            )
            .unwrap();
            let outputs_per_batch = 1000 / usize::from(minutes);
            let max_batches: usize = plan
                .provider_intervals
                .iter()
                .map(|(start, end)| {
                    usize::try_from((end - start) / (i64::from(minutes) * MINUTE))
                        .unwrap()
                        .div_ceil(outputs_per_batch)
                })
                .sum();
            assert!(calls.load(Ordering::SeqCst) - before <= max_batches);
            older.before_ns = Some(
                historical["resolved_start_ns"]
                    .as_str()
                    .unwrap()
                    .parse()
                    .unwrap(),
            );
        }
        current.before_ns = Some(next_closed(&mut stream).await);
        current.clock_ns = (20 * 1440 + 20) * MINUTE;
        let before = calls.load(Ordering::SeqCst);
        let current_window = app
            .temporary_window(&resolved, &session, &current, page, deadline())
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        assert_eq!(current_window["coverage"]["status"], "COMPLETE");
        assert_eq!(
            calls.load(Ordering::SeqCst),
            before,
            "a live closed prefix cannot be evicted by historical browsing"
        );
        for (_, entry) in app.temporary.lock().unwrap().windows.values() {
            assert!(entry.try_lock().unwrap().window.bars.len() <= 4000);
        }
        stream.close().await.unwrap();
    }
}

struct TemporaryFeed {
    events: std::collections::VecDeque<StreamEvent>,
    calls: Arc<AtomicUsize>,
}
impl TemporaryStream for TemporaryFeed {
    fn next<'a>(&'a mut self) -> FutureResult<'a, StreamEvent> {
        Box::pin(async move {
            match self.events.pop_front() {
                Some(event) => Ok(event),
                None => std::future::pending().await,
            }
        })
    }
    fn close<'a>(&'a mut self) -> FutureResult<'a, ()> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
    }
}
#[tokio::test(flavor = "current_thread")]
async fn temporary_product_stream_constructs_closed_bars_separates_preview_and_always_closes() {
    for minutes in [1, 7] {
        let (authority, session, resolved, calls) = source();
        let resolved = Arc::new(resolved);
        let app = Application::default();
        let page = "00000000-0000-4000-8000-000000000001";
        let mut request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(minutes).unwrap(),
            before_ns: None,
            bar_count: 2000,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let mut loaded = Value::Null;
        for _ in 0..20 {
            loaded = app
                .temporary_window(
                    &resolved,
                    &session,
                    &request,
                    page,
                    Instant::now() + std::time::Duration::from_secs(10),
                )
                .await
                .unwrap()
                .into_parts()
                .unwrap()
                .0;
            if loaded["coverage"]["status"] == "COMPLETE" {
                break;
            }
        }
        assert_eq!(loaded["coverage"]["status"], "COMPLETE");
        request.before_ns = Some(loaded["resolved_end_ns"].as_str().unwrap().parse().unwrap());
        let mut stream = app
            .open_temporary_stream(
                Arc::clone(&resolved),
                &session,
                super::super::TemporaryStreamRequest {
                    stream_id: "00000000-0000-4000-8000-000000000002".into(),
                    page_id: page.into(),
                    window: request,
                    expected_window_fingerprint: loaded["window_fingerprint"]
                        .as_str()
                        .unwrap()
                        .into(),
                    deadline: Instant::now() + std::time::Duration::from_secs(10),
                },
            )
            .await
            .unwrap();
        let first = stream
            .next()
            .await
            .unwrap()
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        assert_eq!(first["event"], "SUBSCRIBED");
        assert_eq!(first["source_kind"], "TEMPORARY_MARKET_DATA");
        let mut closed = 0;
        let mut ready = false;
        let mut last = None;
        for _ in 0..30 {
            let event = stream.next().await.unwrap().unwrap();
            let value = event.parts().unwrap().0;
            match value["event"].as_str().unwrap() {
                "BAR_CLOSED" => {
                    closed += 1;
                    assert_eq!(value["bar"]["closed"], true);
                    if minutes == 1 {
                        assert_eq!(
                            value["timing"]["stream_id"],
                            "00000000-0000-4000-8000-000000000002"
                        );
                    } else {
                        assert!(value["timing"].is_null());
                    }
                }
                "STATE" => {
                    if value["state"] == "READY" {
                        ready = true;
                    }
                }
                "BAR_PREVIEW" => {
                    assert!(ready);
                    assert_eq!(value["bar"]["closed"], false);
                    last = Some(event);
                    break;
                }
                other => panic!("unexpected {other}"),
            }
        }
        assert_eq!(closed, if minutes == 1 { 20 } else { 2 });
        assert!(last.is_some());
        let fetched = calls.load(Ordering::SeqCst);
        authority.withdraw();
        assert!(last.unwrap().parts().is_err());
        stream.close().await.unwrap();
        assert_eq!(calls.load(Ordering::SeqCst), fetched + 1);
    }
}
#[tokio::test(flavor = "current_thread")]
async fn temporary_next_cancellation_while_cache_is_locked_does_not_lose_a_source_bar() {
    use std::{
        future::Future,
        task::{Context, Waker},
    };
    let (_authority, session, resolved, _) = source();
    let resolved = Arc::new(resolved);
    let app = Application::default();
    let page = "00000000-0000-4000-8000-000000000001";
    let request = WindowRequest {
        instrument_id: "TEST.TEST".into(),
        semantic: queries::semantic(1).unwrap(),
        before_ns: Some(20 * 1440 * MINUTE),
        bar_count: 2,
        clock_ns: 20 * 1440 * MINUTE,
    };
    let loaded = app
        .temporary_window(
            &resolved,
            &session,
            &request,
            page,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    let expected = loaded["window_fingerprint"].as_str().unwrap();
    let input = app
        .cached_temporary_input(
            &resolved,
            &session,
            &request,
            page,
            expected,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap();
    let mut stream = app
        .open_temporary_stream(
            Arc::clone(&resolved),
            &session,
            super::super::TemporaryStreamRequest {
                stream_id: "00000000-0000-4000-8000-000000000002".into(),
                page_id: page.into(),
                window: request,
                expected_window_fingerprint: expected.into(),
                deadline: Instant::now() + std::time::Duration::from_secs(10),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        stream.next().await.unwrap().unwrap().parts().unwrap().0["event"],
        "SUBSCRIBED"
    );
    assert_eq!(
        stream.next().await.unwrap().unwrap().parts().unwrap().0["state"],
        "RECOVERING"
    );
    let guard = input.entry.lock().await;
    let mut pending = Box::pin(stream.next());
    assert!(
        pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    drop(pending);
    drop(guard);
    let first = stream
        .next()
        .await
        .unwrap()
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(first["event"], "BAR_CLOSED");
    assert_eq!(
        first["bar"]["bar_start_ns"],
        (20 * 1440 * MINUTE).to_string()
    );
    stream.close().await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
async fn temporary_large_gap_withdraws_old_inputs_before_full_window_refresh() {
    let (_authority, session, resolved, calls) = source();
    let resolved = Arc::new(resolved);
    let app = Application::default();
    let page = "00000000-0000-4000-8000-000000000001";
    let request = WindowRequest {
        instrument_id: "TEST.TEST".into(),
        semantic: queries::semantic(1).unwrap(),
        before_ns: Some((20 * 1440 - 101) * MINUTE),
        bar_count: 2,
        clock_ns: 20 * 1440 * MINUTE,
    };
    let loaded = app
        .temporary_window(
            &resolved,
            &session,
            &request,
            page,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    let expected = loaded["window_fingerprint"].as_str().unwrap();
    let input = app
        .cached_temporary_input(
            &resolved,
            &session,
            &request,
            page,
            expected,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap();
    assert!(matches!(
        app.open_temporary_stream(
            Arc::clone(&resolved),
            &session,
            super::super::TemporaryStreamRequest {
                stream_id: "00000000-0000-4000-8000-000000000002".into(),
                page_id: page.into(),
                window: request.clone(),
                expected_window_fingerprint: expected.into(),
                deadline: Instant::now() + std::time::Duration::from_secs(10)
            }
        )
        .await,
        Err(Error::Source(SourceError::RefreshRequired))
    ));
    assert!(
        input.window.parts().is_err(),
        "an unprovable continuity gap withdraws the original calculation input"
    );
    let fetched = calls.load(Ordering::SeqCst);
    let refreshed = app
        .temporary_window(
            &resolved,
            &session,
            &request,
            page,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(calls.load(Ordering::SeqCst), fetched + 1);
    assert_eq!(refreshed["window_fingerprint"], expected);
    assert!(
        input.window.parts().is_err(),
        "equal re-fetched content cannot reauthorize the old input occurrence"
    );
}

#[tokio::test(flavor = "current_thread")]
async fn temporary_early_provider_close_waits_for_local_time_without_losing_input_on_cancellation()
{
    use std::{
        future::Future,
        sync::atomic::AtomicI64,
        task::{Context, Waker},
    };
    struct MovingClock(AtomicI64);
    impl Clock for MovingClock {
        fn now_ns(&self) -> std::result::Result<i64, SourceError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }
    let (_authority, session, mut resolved, _) = source();
    let end = (20 * 1440 + 1) * MINUTE;
    let clock = Arc::new(MovingClock(AtomicI64::new(end - 2_000_000_000)));
    resolved.clock = clock.clone();
    let resolved = Arc::new(resolved);
    let app = Application::default();
    let page = "00000000-0000-4000-8000-000000000001";
    let request = WindowRequest {
        instrument_id: "TEST.TEST".into(),
        semantic: queries::semantic(1).unwrap(),
        before_ns: Some(20 * 1440 * MINUTE),
        bar_count: 2,
        clock_ns: 20 * 1440 * MINUTE,
    };
    let loaded = app
        .temporary_window(
            &resolved,
            &session,
            &request,
            page,
            Instant::now() + std::time::Duration::from_secs(10),
        )
        .await
        .unwrap();
    let expected = loaded.parts().unwrap().0["window_fingerprint"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut stream = app
        .open_temporary_stream(
            Arc::clone(&resolved),
            &session,
            super::super::TemporaryStreamRequest {
                stream_id: "00000000-0000-4000-8000-000000000002".into(),
                page_id: page.into(),
                window: request,
                expected_window_fingerprint: expected,
                deadline: Instant::now() + std::time::Duration::from_secs(10),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        stream.next().await.unwrap().unwrap().parts().unwrap().0["event"],
        "SUBSCRIBED"
    );
    assert_eq!(
        stream.next().await.unwrap().unwrap().parts().unwrap().0["state"],
        "RECOVERING"
    );
    let mut pending = Box::pin(stream.next());
    assert!(
        pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending(),
        "a close ahead of local time must wait without revoking valid cached history"
    );
    drop(pending);
    loaded.parts().unwrap();
    clock.0.store(end, Ordering::SeqCst);
    let event = stream
        .next()
        .await
        .unwrap()
        .unwrap()
        .into_parts()
        .unwrap()
        .0;
    assert_eq!(event["event"], "BAR_CLOSED");
    assert_eq!(event["bar"]["bar_end_ns"], end.to_string());
    loaded.parts().unwrap();
    stream.close().await.unwrap();
}

#[tokio::test(flavor = "current_thread")]
async fn temporary_provider_identity_conflict_withdraws_the_existing_input_occurrence() {
    for fault in [TemporaryFault::OpenConflict, TemporaryFault::StreamConflict] {
        let (_authority, session, resolved, _) = source_from(None, Some(fault));
        let resolved = Arc::new(resolved);
        let app = Application::default();
        let page = "00000000-0000-4000-8000-000000000001";
        let request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: queries::semantic(1).unwrap(),
            before_ns: Some(20 * 1440 * MINUTE),
            bar_count: 2,
            clock_ns: 20 * 1440 * MINUTE,
        };
        let loaded = app
            .temporary_window(
                &resolved,
                &session,
                &request,
                page,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap()
            .into_parts()
            .unwrap()
            .0;
        let expected = loaded["window_fingerprint"].as_str().unwrap();
        let input = app
            .cached_temporary_input(
                &resolved,
                &session,
                &request,
                page,
                expected,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .await
            .unwrap();
        let opened = app
            .open_temporary_stream(
                Arc::clone(&resolved),
                &session,
                super::super::TemporaryStreamRequest {
                    stream_id: "00000000-0000-4000-8000-000000000002".into(),
                    page_id: page.into(),
                    window: request,
                    expected_window_fingerprint: expected.into(),
                    deadline: Instant::now() + std::time::Duration::from_secs(10),
                },
            )
            .await;
        match fault {
            TemporaryFault::ReferenceUnavailableAfterDiscovery
            | TemporaryFault::ExactReferenceRequiresSymbol
            | TemporaryFault::EmptyReference => {
                unreachable!("this matrix contains only stream identity faults")
            }
            TemporaryFault::OpenConflict => {
                assert!(matches!(opened, Err(Error::Source(SourceError::Conflict))))
            }
            TemporaryFault::StreamConflict => {
                let mut stream = opened.unwrap();
                assert!(stream.next().await.unwrap().is_some());
                assert!(matches!(
                    stream.next().await,
                    Err(Error::Source(SourceError::Conflict))
                ));
            }
        }
        assert!(
            input.window.parts().is_err(),
            "a Provider identity contradiction cannot leave an old numeric input admitted"
        );
    }
}
