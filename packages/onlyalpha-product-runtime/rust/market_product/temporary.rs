//! Bounded volatile display windows. No durable-store capability is accepted here.
use super::*;
use crate::source_access::Session;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarSemantic},
};
use serde_json::json;
use std::collections::BTreeMap;
use std::{sync::Arc, time::Instant};

#[derive(Default)]
pub(super) struct TemporaryBook {
    pages: BTreeMap<String, (Instant, Vec<(String, Instant)>)>,
    windows: BTreeMap<String, (Session, Arc<tokio::sync::Mutex<TemporaryEntry>>)>,
    wake: Arc<tokio::sync::Notify>,
    subscriptions: BTreeMap<
        String,
        (
            String,
            std::sync::Weak<super::temporary_state::TemporarySubscription>,
        ),
    >,
}
pub(super) struct TemporaryEntry {
    pub(super) window: MemoryWindow,
    pub(super) instrument: Option<onlyalpha_domain::instrument::OnlyInstrument>,
    pub(super) state: Arc<super::temporary_state::TemporaryState>,
    pub(super) checkpoints: BTreeMap<i64, OnlyBar>,
}
impl TemporaryBook {
    pub(super) fn subscribe(
        &mut self,
        page: &str,
        entry: &Arc<tokio::sync::Mutex<TemporaryEntry>>,
        active: &Arc<super::temporary_state::TemporarySubscription>,
    ) -> Result<()> {
        let key = self
            .pages
            .get(page)
            .and_then(|(_, recent)| recent.first())
            .map(|(key, _)| key.clone())
            .ok_or(Error::Source(SourceError::RefreshRequired))?;
        if !self
            .windows
            .get(&key)
            .is_some_and(|(_, current)| Arc::ptr_eq(current, entry))
        {
            return Err(Error::Source(SourceError::RefreshRequired));
        }
        if let Some((_, previous)) = self.subscriptions.remove(page)
            && let Some(previous) = previous.upgrade()
        {
            previous.cancel();
        }
        self.subscriptions
            .insert(page.into(), (key, Arc::downgrade(active)));
        self.wake.notify_one();
        Ok(())
    }
    pub(super) fn unsubscribe(
        &mut self,
        page: &str,
        active: &Arc<super::temporary_state::TemporarySubscription>,
        now: Instant,
    ) {
        active.cancel();
        if self.subscriptions.get(page).is_some_and(|(_, current)| {
            current
                .upgrade()
                .is_some_and(|current| Arc::ptr_eq(&current, active))
        }) {
            self.subscriptions.remove(page);
            if let Some((at, _)) = self.pages.get_mut(page) {
                *at = now;
            }
            self.wake.notify_one();
        }
    }

    pub(super) fn expire(&mut self, now: Instant) -> Option<Instant> {
        let live =
            |at: Instant| now.saturating_duration_since(at) < std::time::Duration::from_secs(300);
        self.subscriptions
            .retain(|_, (_, active)| active.upgrade().is_some_and(|active| active.is_active()));
        self.pages
            .retain(|page, (at, _)| self.subscriptions.contains_key(page) || live(*at));
        for (_, recent) in self.pages.values_mut() {
            let active = recent.first().map(|(k, _)| k.clone());
            recent.retain(|(k, at)| Some(k) == active.as_ref() || live(*at));
        }
        self.prune_windows();
        self.pages
            .iter()
            .flat_map(|(page, (at, recent))| {
                let page_expiry = (!self.subscriptions.contains_key(page)).then_some(*at);
                page_expiry
                    .into_iter()
                    .chain(recent.iter().skip(1).map(|(_, at)| *at))
            })
            .map(|at| at + std::time::Duration::from_secs(300))
            .min()
    }

    fn entry(
        &mut self,
        page: &str,
        key: &str,
        session: &Session,
        now: Instant,
    ) -> Result<Arc<tokio::sync::Mutex<TemporaryEntry>>> {
        session.check_active()?;
        if self
            .subscriptions
            .get(page)
            .is_some_and(|(current, _)| current != key)
            && let Some((_, active)) = self.subscriptions.remove(page)
            && let Some(active) = active.upgrade()
        {
            active.cancel();
            if let Some((at, _)) = self.pages.get_mut(page) {
                *at = now;
            }
        }
        self.expire(now);
        if !self.pages.contains_key(page) && self.pages.len() >= 8 {
            return Err(Error::Busy);
        }
        let (touched, recent) = self.pages.entry(page.into()).or_insert((now, vec![]));
        *touched = now;
        if recent.first().is_some_and(|(k, _)| k != key)
            && let Some((_, at)) = recent.first_mut()
        {
            *at = now;
        }
        recent.retain(|(k, _)| k != key);
        recent.insert(0, (key.into(), now));
        recent.truncate(3);
        self.prune_windows();
        let (_, entry) = self.windows.entry(key.into()).or_insert_with(|| {
            (
                session.clone(),
                Arc::new(tokio::sync::Mutex::new(TemporaryEntry {
                    window: MemoryWindow::default(),
                    instrument: None,
                    state: Arc::new(super::temporary_state::TemporaryState::default()),
                    checkpoints: BTreeMap::new(),
                })),
            )
        });
        self.wake.notify_one();
        Ok(Arc::clone(entry))
    }
    fn prune_windows(&mut self) {
        let retained = self
            .pages
            .values()
            .flat_map(|(_, r)| r.iter().map(|(k, _)| k.clone()))
            .collect::<std::collections::BTreeSet<_>>();
        self.windows
            .retain(|k, (s, _)| retained.contains(k) && s.check_active().is_ok());
    }
}
fn context_key(
    r: &Resolved,
    session: &Session,
    plan: &onlyalpha_market_data_construction::OnlyConstructionResolutionPlan,
) -> Result<String> {
    fp(
        &json!({"subject":session.subject_id()?,"selection":queries::selection(r),
        "binding":r.binding.fingerprint(),"implementation":r.implementation,"artifact":r.artifact,"data_version":r.data_version,
        "plan":plan.fingerprint()}),
    )
}

fn next_batch(
    intervals: &[(i64, i64)],
    window: &MemoryWindow,
    base_stride: i64,
) -> Result<Option<(i64, i64)>> {
    if base_stride <= 0 {
        return Err(Error::Invalid);
    }
    let mut selected: Option<(i64, i64)> = None;
    for &(start, end) in intervals.iter().rev() {
        if window.bars.contains_key(&(start, end)) {
            if selected.is_some() {
                break;
            }
            continue;
        }
        selected = match selected {
            None if (end - start) / base_stride <= 1000 => Some((start, end)),
            Some((right, last)) if end == right && (last - start) / base_stride <= 1000 => {
                Some((start, last))
            }
            _ => break,
        };
    }
    Ok(selected)
}

#[derive(Default)]
pub(super) struct MemoryWindow {
    pub(super) bars: BTreeMap<(i64, i64), OnlyBar>,
    // Retention hint from an admitted stream, never a continuity/access proof.
    pub(super) live_frontier: Option<i64>,
}
impl MemoryWindow {
    pub(super) fn merge(
        &mut self,
        bars: Vec<OnlyBar>,
        instrument: &str,
        semantic: &OnlyBarSemantic,
        clock: i64,
        anchor: i64,
    ) -> Result<()> {
        let mut next = self.bars.clone();
        for bar in bars {
            let start = ns(*bar.bar_start())?;
            let end = ns(*bar.bar_end())?;
            if !*bar.is_closed()
                || end > clock
                || bar.instrument_id().to_string() != instrument
                || bar.bar_type().semantic() != semantic
            {
                return Err(Error::Selection);
            }
            let key = (start, end);
            if let Some(old) = next.get(&key) {
                let content = |b: &OnlyBar| {
                    let mut v = b.to_record();
                    v.as_object_mut().expect("bar record").remove("ts_init");
                    v
                };
                if content(old) != content(&bar) {
                    return Err(Error::Conflict);
                }
            } else {
                next.insert(key, bar);
            }
        }
        if next.len() > 4000 {
            let mut retained = next
                .keys()
                .rev()
                .filter(|(_, end)| self.live_frontier.is_some_and(|at| *end <= at))
                .take(2000)
                .copied()
                .collect::<std::collections::BTreeSet<_>>();
            let mut keys = next.keys().copied().collect::<Vec<_>>();
            keys.sort_by_key(|(_, end)| {
                (
                    self.live_frontier.is_some() && *end > anchor,
                    (i128::from(*end) - i128::from(anchor)).abs(),
                )
            });
            for key in keys {
                if retained.len() == 4000 {
                    break;
                }
                retained.insert(key);
            }
            next.retain(|key, _| retained.contains(key));
        }
        self.bars = next;
        Ok(())
    }
}

fn projection(
    selection: &crate::source_access::Selection,
    plan: &onlyalpha_market_data_construction::OnlyConstructionResolutionPlan,
    request: &WindowRequest,
    window: &MemoryWindow,
) -> Result<Value> {
    if request.semantic != *plan.target()
        || request.instrument_id != plan.context().instrument().to_string()
    {
        return Err(Error::Selection);
    }
    let requested = crate::market_data::plan_bar_window(
        &request.semantic,
        request.before_ns,
        request.clock_ns.div_euclid(60_000_000_000) * 60_000_000_000,
        request.bar_count,
        2000,
    )?;
    let start = requested.intervals.first().ok_or(Error::Invalid)?.0;
    let end = requested.intervals.last().ok_or(Error::Invalid)?.1;
    let mut bars = vec![];
    let mut gaps = vec![];
    for &(start, end) in &requested.intervals {
        if let Some(bar) = window.bars.get(&(start, end)) {
            bars.push(queries::bar_row(bar)?);
        } else {
            gaps.push(json!({"start_ns":start.to_string(),"end_ns":end.to_string()}));
        }
    }
    let source = queries::selection_value(selection);
    let fingerprint = fp(
        &json!({"domain":"ONLYALPHA_TEMPORARY_WINDOW_V1","source_selection":source,
        "instrument_id":request.instrument_id,"bar_semantic":request.semantic.to_record(),
        "resolution_plan_fingerprint":plan.fingerprint(),"start_ns":start,"end_ns":end,"bars":bars}),
    )?;
    Ok(
        json!({"schema_version":1,"source_kind":"TEMPORARY_MARKET_DATA","authority":"DISPLAY_ONLY",
        "publication_status":"NOT_A_RESEARCH_RESULT","source_selection":source,
        "instrument_id":request.instrument_id,"bar_semantic":request.semantic.to_record(),
        "anchor_kind":if request.before_ns.is_some(){"BEFORE_TIME"}else{"LATEST_CLOSED"},
        "requested_before_ns":request.before_ns.map(|n|n.to_string()),"requested_bar_count":request.bar_count,
        "resolved_start_ns":start.to_string(),"resolved_end_ns":end.to_string(),
        "coverage":{"status":if gaps.is_empty(){"COMPLETE"}else{"PARTIAL"},"expected_bar_count":request.bar_count,
            "actual_bar_count":bars.len(),"gaps":gaps},"bars":bars,"window_fingerprint":fingerprint,
        "calendar_fingerprint":plan.context().calendar_fingerprint(),"resolution_plan_fingerprint":plan.fingerprint(),
        "resolution_mode":if plan.recipe().is_native(){"PROVIDER_NATIVE"}else{"DERIVED"}}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    const MINUTE: i64 = 60_000_000_000;
    #[test]
    fn volatile_projection_reports_gaps_without_fabricating_seals_or_research_evidence() {
        use crate::source_access::{Reference, Selection};
        use onlyalpha_market_data_construction::*;
        let semantic = queries::semantic(1).unwrap();
        let reference =
            Reference::new("test-source", &"a".repeat(64), Some("test.source")).unwrap();
        let selection = Selection::new(reference, "test-feed", "TEST").unwrap();
        let calendar = "b".repeat(64);
        let context = OnlyConstructionResolutionContext::new(
            "test-feed",
            "TEST.TEST".parse().unwrap(),
            &"a".repeat(64),
            &calendar,
        )
        .unwrap();
        let capability = OnlyConstructionCapability::new(
            semantic.clone(),
            true,
            true,
            &calendar,
            Some(0.into()),
        )
        .unwrap();
        let plan = OnlyConstructionResolutionPlan::resolve(
            semantic.clone(),
            &[capability],
            context,
            OnlyConstructionRequirement::PreferExactNative,
        )
        .unwrap();
        let request = WindowRequest {
            instrument_id: "TEST.TEST".into(),
            semantic: semantic.clone(),
            before_ns: Some(3 * MINUTE),
            bar_count: 2,
            clock_ns: 10 * MINUTE,
        };
        let mut window = MemoryWindow::default();
        window
            .merge(
                vec![bar(2, "10.00")],
                "TEST.TEST",
                &semantic,
                10 * MINUTE,
                3 * MINUTE,
            )
            .unwrap();
        let partial = projection(&selection, &plan, &request, &window).unwrap();
        assert_eq!(partial["source_kind"], "TEMPORARY_MARKET_DATA");
        assert_eq!(partial["authority"], "DISPLAY_ONLY");
        assert_eq!(partial["coverage"]["status"], "PARTIAL");
        assert_eq!(partial["coverage"]["actual_bar_count"], 1);
        assert_eq!(partial["coverage"]["gaps"].as_array().unwrap().len(), 1);
        for forbidden in [
            "revision_evidence",
            "seal_id",
            "history_projection_fingerprint",
            "research_result_id",
        ] {
            assert!(partial.get(forbidden).is_none(), "{forbidden}");
        }
        window
            .merge(
                vec![bar(1, "10.00")],
                "TEST.TEST",
                &semantic,
                10 * MINUTE,
                3 * MINUTE,
            )
            .unwrap();
        let complete = projection(&selection, &plan, &request, &window).unwrap();
        assert_eq!(complete["coverage"]["status"], "COMPLETE");
        assert_eq!(complete["bars"].as_array().unwrap().len(), 2);
        assert_ne!(
            partial["window_fingerprint"],
            complete["window_fingerprint"]
        );
    }
    #[test]
    fn volatile_cache_is_shared_bounded_expires_and_never_reuses_a_withdrawn_session() {
        use crate::source_access::Authority;
        use std::time::Duration;
        let token = "a".repeat(64);
        let authority = Authority::new("human", &hash(token.as_bytes()), vec![]).unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        let now = Instant::now();
        let mut book = TemporaryBook::default();
        let first = book.entry("page1", "A", &session, now).unwrap();
        assert!(Arc::ptr_eq(
            &first,
            &book.entry("page2", "A", &session, now).unwrap()
        ));
        book.entry("page1", "B", &session, now).unwrap();
        book.entry("page1", "C", &session, now).unwrap();
        book.entry("page1", "D", &session, now).unwrap();
        // A is still owned by page2, even after page1's fourth context.
        assert!(Arc::ptr_eq(
            &first,
            &book.entry("page2", "A", &session, now).unwrap()
        ));
        let expired = book
            .entry("page1", "A", &session, now + Duration::from_secs(301))
            .unwrap();
        assert!(!Arc::ptr_eq(&first, &expired));
        authority.withdraw();
        assert!(matches!(
            book.entry("page1", "A", &session, now),
            Err(Error::Forbidden)
        ));
    }
    #[test]
    fn volatile_cache_prunes_the_fourth_context_without_reusing_its_pinned_entry() {
        use crate::source_access::Authority;
        let token = "a".repeat(64);
        let authority = Authority::new("human", &hash(token.as_bytes()), vec![]).unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        let now = Instant::now();
        let mut book = TemporaryBook::default();
        let first = book.entry("page", "A", &session, now).unwrap();
        for key in ["B", "C", "D"] {
            book.entry("page", key, &session, now).unwrap();
        }
        assert_eq!(
            book.pages["page"]
                .1
                .iter()
                .map(|(key, _)| key.as_str())
                .collect::<Vec<_>>(),
            ["D", "C", "B"]
        );
        assert_eq!(
            book.windows.keys().map(String::as_str).collect::<Vec<_>>(),
            ["B", "C", "D"]
        );
        let replacement = book.entry("page", "A", &session, now).unwrap();
        assert!(!Arc::ptr_eq(&first, &replacement));
    }
    #[test]
    fn volatile_cache_rejects_a_ninth_page_and_recovers_capacity_at_expiry() {
        use crate::source_access::Authority;
        use std::time::Duration;
        let token = "a".repeat(64);
        let authority = Authority::new("human", &hash(token.as_bytes()), vec![]).unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        let now = Instant::now();
        let mut book = TemporaryBook::default();
        let first = book.entry("page0", "A", &session, now).unwrap();
        let active = Arc::new(super::super::temporary_state::TemporarySubscription::default());
        book.subscribe("page0", &first, &active).unwrap();
        for index in 1..8 {
            book.entry(
                &format!("page{index}"),
                &format!("key{index}"),
                &session,
                now,
            )
            .unwrap();
        }
        assert!(matches!(
            book.entry("page8", "new", &session, now),
            Err(Error::Busy)
        ));
        assert!(matches!(
            book.entry("page8", "new", &session, now + Duration::from_secs(299)),
            Err(Error::Busy)
        ));
        assert_eq!(book.pages.len(), 8);
        assert_eq!(book.windows.len(), 8);
        book.entry("page8", "new", &session, now + Duration::from_secs(300))
            .unwrap();
        assert_eq!(book.pages.len(), 2);
        assert_eq!(book.windows.len(), 2);
        assert!(active.is_active());
        assert!(Arc::ptr_eq(&first, &book.windows["A"].1));
    }
    #[test]
    fn volatile_cache_expires_without_a_followup_query() {
        use crate::source_access::Authority;
        let token = "a".repeat(64);
        let authority = Authority::new("human", &hash(token.as_bytes()), vec![]).unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        let now = Instant::now();
        let mut book = TemporaryBook::default();
        book.entry("page1", "A", &session, now).unwrap();
        assert_eq!(
            book.expire(now),
            Some(now + std::time::Duration::from_secs(300))
        );
        assert_eq!(book.expire(now + std::time::Duration::from_secs(300)), None);
        assert!(book.windows.is_empty());
        assert!(book.pages.is_empty());
    }
    #[test]
    fn volatile_subscription_pins_only_current_context_and_ttl_begins_when_it_leaves() {
        use crate::source_access::Authority;
        let token = "a".repeat(64);
        let authority = Authority::new("human", &hash(token.as_bytes()), vec![]).unwrap();
        let session = authority.authenticate(&format!("Bearer {token}")).unwrap();
        let now = Instant::now();
        let later = now + std::time::Duration::from_secs(301);
        let mut book = TemporaryBook::default();
        let original = book.entry("page1", "A", &session, now).unwrap();
        let active = Arc::new(super::super::temporary_state::TemporarySubscription::default());
        book.subscribe("page1", &original, &active).unwrap();
        assert_eq!(book.expire(later), None);
        assert!(Arc::ptr_eq(&original, &book.windows["A"].1));
        book.entry("page1", "B", &session, later).unwrap();
        assert!(
            book.windows.contains_key("A"),
            "the departed context starts its own five-minute retention"
        );
        assert!(
            !active.is_active(),
            "leaving the context cancels its Provider subscription"
        );
        // A late close of the departed subscription must not retouch page B.
        book.unsubscribe(
            "page1",
            &active,
            later + std::time::Duration::from_secs(100),
        );
        assert_eq!(
            book.expire(later + std::time::Duration::from_secs(300)),
            None
        );
        assert!(book.windows.is_empty());
        let current = book.entry("page2", "C", &session, now).unwrap();
        let active = Arc::new(super::super::temporary_state::TemporarySubscription::default());
        book.subscribe("page2", &current, &active).unwrap();
        book.unsubscribe("page2", &active, later);
        assert_eq!(
            book.expire(later),
            Some(later + std::time::Duration::from_secs(300))
        );
        assert!(book.windows.contains_key("C"));
        book.expire(later + std::time::Duration::from_secs(300));
        assert!(book.windows.is_empty());
    }
    #[test]
    fn volatile_fetch_starts_with_recent_complete_windows_and_bounds_base_inputs() {
        let plan = crate::market_data::plan_bar_window(
            &queries::semantic(7).unwrap(),
            None,
            20 * 1440 * MINUTE,
            2000,
            2000,
        )
        .unwrap();
        let (start, end) = next_batch(&plan.intervals, &MemoryWindow::default(), MINUTE)
            .unwrap()
            .unwrap();
        assert_eq!(end, plan.intervals.last().unwrap().1);
        assert!(plan.intervals.iter().any(|(s, _)| *s == start));
        assert!((end - start) / MINUTE <= 1000);
        assert_eq!(start / (1440 * MINUTE), (end - 1) / (1440 * MINUTE));
        let mut complete = MemoryWindow::default();
        complete
            .merge(
                (0..3).map(|i| bar(i, "10.00")).collect(),
                "TEST.TEST",
                &queries::semantic(1).unwrap(),
                10 * MINUTE,
                3 * MINUTE,
            )
            .unwrap();
        assert_eq!(
            next_batch(
                &[(0, MINUTE), (MINUTE, 2 * MINUTE), (2 * MINUTE, 3 * MINUTE)],
                &complete,
                MINUTE
            )
            .unwrap(),
            None
        );
    }
    pub(super) fn bar(index: i64, close: &str) -> OnlyBar {
        let start = time(index * MINUTE).unwrap();
        let end = time((index + 1) * MINUTE).unwrap();
        let price = |v: &str| json!({"schema_version":1,"value":v,"precision":2});
        let quantity = json!({"schema_version":1,"value":"1.00","precision":2});
        OnlyBar::from_record(&json!({"schema_version":1,
            "bar_type":queries::bar_type("TEST.TEST", &queries::semantic(1).unwrap()).unwrap().to_record(),
            "open":price("10.00"),"high":price("12.00"),"low":price("9.00"),"close":price(close),
            "volume":quantity,"quote_volume":null,"turnover":null,"trade_count":1,"open_interest":null,
            "bar_start":start.to_string(),"bar_end":end.to_string(),"ts_event":end.to_string(),"ts_init":end.to_string(),
            "is_closed":true,"revision":0,"adjustment_type":"RAW","trading_day":start.date().to_string(),"session_type":"CONTINUOUS"})).unwrap()
    }
    #[test]
    fn volatile_window_accepts_reordered_duplicates_and_rejects_conflicts_atomically() {
        let mut window = MemoryWindow::default();
        let semantic = queries::semantic(1).unwrap();
        window
            .merge(
                vec![bar(2, "11.00"), bar(1, "10.00"), bar(2, "11.00")],
                "TEST.TEST",
                &semantic,
                10 * MINUTE,
                3 * MINUTE,
            )
            .unwrap();
        assert_eq!(
            window.bars.keys().copied().collect::<Vec<_>>(),
            vec![(MINUTE, 2 * MINUTE), (2 * MINUTE, 3 * MINUTE)]
        );
        assert_eq!(
            window.merge(
                vec![bar(3, "11.00"), bar(2, "10.00")],
                "TEST.TEST",
                &semantic,
                10 * MINUTE,
                4 * MINUTE
            ),
            Err(Error::Conflict)
        );
        assert_eq!(window.bars.len(), 2);
    }
    #[test]
    fn volatile_window_rejects_wrong_instrument_semantic_and_future_or_preview_rows() {
        for case in 0..4 {
            let mut window = MemoryWindow::default();
            let mut value = bar(1, "10.00").to_record();
            let (instrument, semantic, clock) = match case {
                0 => ("OTHER.TEST", queries::semantic(1).unwrap(), 10 * MINUTE),
                1 => ("TEST.TEST", queries::semantic(3).unwrap(), 10 * MINUTE),
                2 => ("TEST.TEST", queries::semantic(1).unwrap(), MINUTE),
                _ => {
                    value["is_closed"] = json!(false);
                    ("TEST.TEST", queries::semantic(1).unwrap(), 10 * MINUTE)
                }
            };
            assert!(
                window
                    .merge(
                        vec![OnlyBar::from_record(&value).unwrap()],
                        instrument,
                        &semantic,
                        clock,
                        2 * MINUTE
                    )
                    .is_err()
            );
            assert!(window.bars.is_empty());
        }
    }
    #[test]
    fn volatile_history_retention_stays_bounded_around_the_requested_window() {
        let mut window = MemoryWindow::default();
        window
            .merge(
                (0..4100).map(|i| bar(i, "10.00")).collect(),
                "TEST.TEST",
                &queries::semantic(1).unwrap(),
                5000 * MINUTE,
                4100 * MINUTE,
            )
            .unwrap();
        assert_eq!(window.bars.len(), 4000);
        assert_eq!(window.bars.first_key_value().unwrap().0.0, 100 * MINUTE);
        window
            .merge(
                vec![bar(0, "10.00")],
                "TEST.TEST",
                &queries::semantic(1).unwrap(),
                5000 * MINUTE,
                MINUTE,
            )
            .unwrap();
        assert_eq!(window.bars.len(), 4000);
        assert!(window.bars.contains_key(&(0, MINUTE)));
    }
}

impl Application {
    /// One bounded Provider page toward a volatile display window. No Storage,
    /// WAL or mutation admission crosses this boundary.
    pub async fn temporary_window(
        &self,
        r: &Resolved,
        session: &Session,
        request: &WindowRequest,
        page: &str,
        deadline: Instant,
    ) -> Result<Authorized<Value>> {
        use crate::source_access::Permission;
        use onlyalpha_integration_contract::source::HistoryRequest;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        if !crate::command::uuid4(page) {
            return Err(Error::Invalid);
        }
        budget(deadline)?;
        let plan = queries::plan(r, &request.instrument_id, &request.semantic)?;
        let requested = crate::market_data::plan_bar_window(
            &request.semantic,
            request.before_ns,
            request.clock_ns.div_euclid(60_000_000_000) * 60_000_000_000,
            request.bar_count,
            2000,
        )?;
        let key = context_key(r, session, &plan)?;
        let entry = self
            .temporary
            .lock()
            .map_err(|_| Error::Unavailable)?
            .entry(page, &key, session, Instant::now())?;
        let mut entry = tokio::time::timeout_at(deadline.into(), entry.lock())
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))?;
        if entry.state.fence().check().is_err() {
            entry.window = MemoryWindow::default();
            entry.checkpoints.clear();
            entry.state.reset()?;
        }
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let base = if plan.recipe().is_native() {
            request.semantic.clone()
        } else {
            queries::semantic(1)?
        };
        let minutes = base
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<u16>()
            .map_err(|_| Error::Invalid)?;
        let stride = i64::from(minutes) * 60_000_000_000;
        if let Some((start, end)) = next_batch(&requested.intervals, &entry.window, stride)? {
            if entry.instrument.is_none() {
                let (instrument, fence) = self
                    .temporary_reference(r, session, &request.instrument_id, deadline)
                    .await?
                    .into_parts()?;
                fence.check()?;
                entry.instrument = Some(instrument);
            }
            let input = HistoryRequest {
                instrument: entry.instrument.as_ref().ok_or(Error::Unavailable)?.clone(),
                minutes,
                start_ms: start / 1_000_000,
                end_ms: end / 1_000_000,
            };
            let _slot = tokio::time::timeout_at(deadline.into(), self.slots.acquire())
                .await
                .map_err(|_| Error::Source(SourceError::Timeout))?
                .map_err(|_| Error::Unavailable)?;
            session.require_selection(&r.selection, Permission::ClosedHistory)?;
            let bars = tokio::time::timeout_at(
                deadline.into(),
                r.resource.temporary_history(&input, budget(deadline)?),
            )
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))??;
            session.require_selection(&r.selection, Permission::ClosedHistory)?;
            if bars.len()>1000 || bars.iter().any(|bar| {
                let s=ns(*bar.bar_start()).ok();let e=ns(*bar.bar_end()).ok();
                !matches!((s,e),(Some(s),Some(e)) if s>=start && e<=end && e-s==stride && (s-start)%stride==0)
            }) {
                entry.state.invalidate()?;
                return Err(Error::Corrupt);
            }
            let mut inputs = MemoryWindow::default();
            if let Err(error) =
                inputs.merge(bars, &request.instrument_id, &base, request.clock_ns, end)
            {
                entry.state.invalidate()?;
                return Err(error);
            }
            let mut outputs = vec![];
            let mut checkpoints = vec![];
            for &(s, e) in requested
                .intervals
                .iter()
                .filter(|(s, e)| *s >= start && *e <= end)
            {
                let rows = inputs
                    .bars
                    .range((s, i64::MIN)..(e, i64::MIN))
                    .map(|(_, bar)| bar.clone())
                    .collect::<Vec<_>>();
                if rows.len() != usize::try_from((e - s) / stride).map_err(|_| Error::Invalid)? {
                    continue;
                }
                // This frontier belongs to this exact construction invocation,
                // not a join against another Source's equal timestamp.
                let checkpoint = rows.last().ok_or(Error::Corrupt)?.clone();
                let mut constructed = queries::derived_with_calendar(
                    r.resource.calendar(),
                    &plan,
                    &request.instrument_id,
                    rows,
                )?;
                if constructed.len() != 1 {
                    entry.state.invalidate()?;
                    return Err(Error::Corrupt);
                }
                let bar = constructed.remove(0);
                if ns(*bar.bar_start())? != s || ns(*bar.bar_end())? != e {
                    entry.state.invalidate()?;
                    return Err(Error::Corrupt);
                }
                outputs.push(bar);
                if !plan.recipe().is_native() {
                    checkpoints.push((e, checkpoint));
                }
            }
            let anchor = requested.intervals.last().ok_or(Error::Invalid)?.1;
            if let Err(error) = entry.window.merge(
                outputs,
                &request.instrument_id,
                &request.semantic,
                request.clock_ns,
                anchor,
            ) {
                entry.state.invalidate()?;
                return Err(error);
            }
            entry.checkpoints.extend(checkpoints);
            let retained = entry
                .window
                .bars
                .keys()
                .map(|(_, end)| *end)
                .collect::<std::collections::BTreeSet<_>>();
            entry.checkpoints.retain(|end, _| retained.contains(end));
        }
        let value = projection(&r.selection, &plan, request, &entry.window)?;
        budget(deadline)?;
        Ok(
            Authorized::new(value, session, r, Permission::ClosedHistory)?
                .with_temporary(entry.state.fence()),
        )
    }
}
#[cfg(test)]
#[path = "temporary_tests.rs"]
pub(super) mod application_tests;

pub(super) struct TemporaryInput {
    pub(super) window: Authorized<Value>,
    pub(super) checkpoint: OnlyBar,
    pub(super) instrument: onlyalpha_domain::instrument::OnlyInstrument,
    pub(super) plan: onlyalpha_market_data_construction::OnlyConstructionResolutionPlan,
    pub(super) entry: Arc<tokio::sync::Mutex<TemporaryEntry>>,
}
impl Application {
    pub(super) async fn cached_temporary_input(
        &self,
        r: &Resolved,
        session: &Session,
        request: &WindowRequest,
        page: &str,
        expected: &str,
        deadline: Instant,
    ) -> Result<TemporaryInput> {
        use crate::source_access::Permission;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        if request.before_ns.is_none()
            || !crate::command::uuid4(page)
            || !crate::is_sha256_hex(expected)
        {
            return Err(Error::Invalid);
        }
        budget(deadline)?;
        let plan = queries::plan(r, &request.instrument_id, &request.semantic)?;
        let key = context_key(r, session, &plan)?;
        let owned = {
            let mut book = self.temporary.lock().map_err(|_| Error::Unavailable)?;
            if !book
                .windows
                .get(&key)
                .is_some_and(|(issuer, _)| issuer.check_active().is_ok())
            {
                return Err(Error::Source(SourceError::RefreshRequired));
            }
            book.entry(page, &key, session, Instant::now())?
        };
        let entry = tokio::time::timeout_at(deadline.into(), owned.lock())
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))?;
        entry.state.fence().check()?;
        let value = projection(&r.selection, &plan, request, &entry.window)?;
        if value["window_fingerprint"] != expected {
            // A different page can evict these observations within the same
            // bounded context. Missing cache rows are not conflicting facts.
            if value["coverage"]["status"] != "COMPLETE" {
                return Err(Error::Source(SourceError::RefreshRequired));
            }
            return Err(Error::Conflict);
        }
        let requested = crate::market_data::plan_bar_window(
            &request.semantic,
            request.before_ns,
            request.clock_ns.div_euclid(60_000_000_000) * 60_000_000_000,
            request.bar_count,
            2000,
        )?;
        let last = requested
            .intervals
            .iter()
            .rev()
            .find_map(|interval| entry.window.bars.get(interval))
            .ok_or(Error::Source(SourceError::RefreshRequired))?;
        let checkpoint = if plan.recipe().is_native() {
            last.clone()
        } else {
            entry
                .checkpoints
                .get(&ns(*last.bar_end())?)
                .ok_or(Error::Corrupt)?
                .clone()
        };
        if checkpoint.bar_end() != last.bar_end()
            || checkpoint.instrument_id() != last.instrument_id()
        {
            return Err(Error::Corrupt);
        }
        let instrument = entry.instrument.as_ref().ok_or(Error::Corrupt)?.clone();
        let window = Authorized::new(value, session, r, Permission::ClosedHistory)?
            .with_temporary(entry.state.fence());
        budget(deadline)?;
        drop(entry);
        Ok(TemporaryInput {
            window,
            checkpoint,
            instrument,
            plan,
            entry: owned,
        })
    }
}

impl Application {
    /// Polled by the existing Host lifecycle. No detached background task and no
    /// follow-up market query is required to release expired price values.
    pub async fn expire_temporary(&self) -> Result<()> {
        let wake = Arc::clone(&self.temporary.lock().map_err(|_| Error::Unavailable)?.wake);
        loop {
            let next = self
                .temporary
                .lock()
                .map_err(|_| Error::Unavailable)?
                .expire(Instant::now());
            match next {
                Some(next) => tokio::select! {
                    _=tokio::time::sleep_until(next.into())=>{self.temporary.lock().map_err(|_|Error::Unavailable)?.expire(Instant::now());return Ok(());},
                    _=wake.notified()=>{},
                },
                None => wake.notified().await,
            }
        }
    }
}

impl Application {
    /// Chart receives a retained, fenced snapshot only; this path has no Source
    /// acquisition or durable-store fallback when the input is unavailable.
    pub(crate) async fn temporary_chart_window(
        &self,
        r: &Resolved,
        session: &Session,
        request: &WindowRequest,
        page: &str,
        expected: &str,
        deadline: Instant,
    ) -> Result<Authorized<Value>> {
        Ok(self
            .cached_temporary_input(r, session, request, page, expected, deadline)
            .await?
            .window)
    }
}
