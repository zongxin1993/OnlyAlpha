use super::*;
use crate::application::source_access::{Permission, Selection, Session};
use crate::persistence::market_data::{Scope, Storage};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::OnlyInstrumentId,
    instrument::OnlyInstrument,
    market::{OnlyBar, OnlyBarSemantic, OnlyBarType, OnlyBarTypeInput},
    time::OnlyTimestamp,
};
use onlyalpha_integration_contract::source::HistoryRequest;
use onlyalpha_market_data_construction::*;
use serde_json::json;
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
pub struct SendFence {
    session: Session,
    selection: Selection,
    permission: Permission,
    implementation: Option<String>,
    resource: Option<Arc<dyn onlyalpha_integration_contract::source::Resource>>,
    calendar: Arc<onlyalpha_domain::calendar::OnlyTradingCalendar>,
    stream: Option<super::stream::StreamFence>,
    preview: Option<super::stream::PreviewFence>,
    temporary: Option<super::temporary_state::TemporaryFence>,
}
impl SendFence {
    pub fn check(&self) -> Result<()> {
        self.session
            .require_selection(&self.selection, self.permission)?;
        if let Some(stream) = &self.stream {
            stream.check()?;
        }
        if let Some(preview) = &self.preview {
            preview.check()?;
        }
        if let Some(temporary) = &self.temporary {
            temporary.check()?;
        }
        Ok(())
    }
    /// Calendar of this original issuance occurrence, never a caller projection.
    pub fn calendar(&self) -> Result<&onlyalpha_domain::calendar::OnlyTradingCalendar> {
        self.check()?;
        if self.permission != Permission::ClosedHistory {
            return Err(Error::Forbidden);
        }
        Ok(&self.calendar)
    }
    pub fn source_session(&self) -> Session {
        self.session.clone()
    }
    pub fn selection(&self) -> &Selection {
        &self.selection
    }
    pub(super) fn same_source(&self, r: &Resolved, subject: &Session) -> Result<()> {
        self.check()?;
        if self.selection != r.selection
            || self.implementation.as_deref() != Some(r.implementation.as_str())
            || self.session.subject_id()? != subject.subject_id()?
        {
            return Err(Error::Selection);
        }
        Ok(())
    }
    pub fn permission(&self) -> Permission {
        self.permission
    }
}
pub struct BatchFence {
    session: Session,
    selections: Vec<(Selection, Permission)>,
}
impl BatchFence {
    pub fn check(&self) -> Result<()> {
        self.session.check_active()?;
        for (selection, permission) in &self.selections {
            self.session.require_selection(selection, *permission)?;
        }
        Ok(())
    }
    pub fn source_session(&self) -> Session {
        self.session.clone()
    }
}
pub struct AuthorizedBatch {
    payload: Value,
    fence: BatchFence,
}
impl AuthorizedBatch {
    pub(super) fn new(
        payload: Value,
        session: &Session,
        selections: Vec<(Selection, Permission)>,
    ) -> Result<Self> {
        let fence = BatchFence {
            session: session.clone(),
            selections,
        };
        fence.check()?;
        Ok(Self { payload, fence })
    }
    pub fn into_parts(self) -> Result<(Value, BatchFence)> {
        self.fence.check()?;
        Ok((self.payload, self.fence))
    }
}
pub struct Authorized<T> {
    payload: T,
    fence: SendFence,
}
impl<T> Authorized<T> {
    pub(super) fn history(
        payload: T,
        session: &Session,
        c: &super::HistoryContext,
    ) -> Result<Self> {
        session.require_selection(&c.selection, Permission::ClosedHistory)?;
        Ok(Self {
            payload,
            fence: SendFence {
                session: session.clone(),
                selection: c.selection.clone(),
                permission: Permission::ClosedHistory,
                implementation: c.implementation.clone(),
                resource: c.resource.clone(),
                calendar: Arc::clone(&c.calendar),
                stream: None,
                preview: None,
                temporary: None,
            },
        })
    }

    pub(super) fn new(
        payload: T,
        session: &Session,
        resolved: &Resolved,
        permission: Permission,
    ) -> Result<Self> {
        session.require_selection(&resolved.selection, permission)?;
        Ok(Self {
            payload,
            fence: SendFence {
                session: session.clone(),
                selection: resolved.selection.clone(),
                permission,
                implementation: Some(resolved.implementation.clone()),
                resource: Some(Arc::clone(&resolved.resource)),
                calendar: Arc::new(resolved.resource.calendar().clone()),
                stream: None,
                preview: None,
                temporary: None,
            },
        })
    }
    pub(super) fn with_stream(mut self, stream: super::stream::StreamFence) -> Self {
        self.fence.stream = Some(stream);
        self
    }
    pub(super) fn with_temporary(
        mut self,
        temporary: super::temporary_state::TemporaryFence,
    ) -> Self {
        self.fence.temporary = Some(temporary);
        self
    }
    pub(super) fn with_preview(mut self, preview: super::stream::PreviewFence) -> Self {
        self.fence.preview = Some(preview);
        self
    }
    pub(super) fn for_resource(self, r: &Resolved, permission: Permission) -> Result<(T, Session)> {
        self.fence.check()?;
        if self
            .fence
            .resource
            .as_ref()
            .is_none_or(|resource| !Arc::ptr_eq(resource, &r.resource))
            || self.fence.selection != r.selection
            || self.fence.implementation.as_deref() != Some(r.implementation.as_str())
            || self.fence.permission != permission
        {
            return Err(Error::Selection);
        }
        Ok((self.payload, self.fence.session))
    }
    pub fn parts(&self) -> Result<(&T, &SendFence)> {
        self.fence.check()?;
        Ok((&self.payload, &self.fence))
    }
    pub fn into_parts(self) -> Result<(T, SendFence)> {
        self.fence.check()?;
        Ok((self.payload, self.fence))
    }
}
#[derive(Clone)]
pub struct WindowRequest {
    pub instrument_id: String,
    pub semantic: OnlyBarSemantic,
    pub before_ns: Option<i64>,
    pub bar_count: usize,
    pub clock_ns: i64,
}
pub struct InstrumentQuery {
    pub query: String,
    pub asset_class: Option<String>,
    pub instrument_types: Vec<String>,
    pub instrument_ids: Vec<String>,
    pub limit: usize,
}
struct Cache {
    at: Instant,
    rows: Vec<OnlyInstrument>,
}
impl Cache {
    fn current_at(&self, now: Instant) -> bool {
        now.checked_duration_since(self.at)
            .is_some_and(|age| age < Duration::from_secs(60))
    }
}
#[cfg(test)]
#[path = "temporary_reference_tests.rs"]
mod temporary_reference_tests;
pub struct Application {
    pub(super) stream_slots: Arc<tokio::sync::Semaphore>,
    pub(super) slots: tokio::sync::Semaphore,
    cache: Mutex<BTreeMap<String, Cache>>,
    pub(super) temporary: Arc<Mutex<super::temporary::TemporaryBook>>,
}
impl Default for Application {
    fn default() -> Self {
        Self {
            stream_slots: Arc::new(tokio::sync::Semaphore::new(8)),
            slots: tokio::sync::Semaphore::new(4),
            cache: Mutex::new(BTreeMap::new()),
            temporary: Arc::new(Mutex::new(super::temporary::TemporaryBook::default())),
        }
    }
}
pub(super) fn selection(r: &Resolved) -> Value {
    selection_value(&r.selection)
}
pub(super) fn selection_value(s: &Selection) -> Value {
    json!({"integration_id":s.reference().integration_id(),"integration_revision_fingerprint":s.reference().revision(),"type_id":s.reference().expected_type_id(),"source_id":s.source_id(),"environment":s.environment()})
}
pub(super) fn instrument_row(i: &OnlyInstrument, market: &str) -> Value {
    let s = i.specification();
    json!({"instrument_id":s.instrument_id().to_string(),"display_symbol":s.raw_symbol().value(),"venue":s.venue().value(),"market":market,"asset_class":s.asset_class().as_str(),"instrument_type":s.instrument_type().as_str(),"status":s.status().as_str(),"market_data_capabilities":["HISTORICAL_BARS","LIVE_BARS"]})
}
pub(super) fn plan(
    r: &Resolved,
    instrument: &str,
    target: &OnlyBarSemantic,
) -> Result<OnlyConstructionResolutionPlan> {
    let id: OnlyInstrumentId = instrument.parse().map_err(|_| Error::Invalid)?;
    if id.venue().value() != r.identity().venue {
        return Err(Error::Selection);
    }
    let c = OnlyConstructionResolutionContext::new(
        &r.identity().source_id,
        id,
        r.selection.reference().revision(),
        &fp(&r.resource.calendar().to_record())?,
    )
    .map_err(|_| Error::Invalid)?;
    let plan = OnlyConstructionResolutionPlan::resolve(
        target.clone(),
        r.resource.capabilities(),
        c,
        OnlyConstructionRequirement::PreferExactNative,
    )
    .map_err(|_| Error::Selection)?;
    if !plan.recipe().is_native() && plan.recipe().algorithm() != Some(("TIME_BAR", &1u32.into())) {
        return Err(Error::Selection);
    }
    Ok(plan)
}
pub(super) fn semantic(minutes: u16) -> Result<OnlyBarSemantic> {
    OnlyBarSemantic::from_record(&json!({"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":minutes,"stride_minutes":minutes,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"})).map_err(|_|Error::Invalid)
}
pub(super) fn scope(
    r: &Resolved,
    instrument: &str,
    start: i64,
    end: i64,
    p: &OnlyConstructionResolutionPlan,
) -> Result<Scope> {
    if !p.recipe().is_native() {
        return Err(Error::Invalid);
    }
    let bt = bar_type(instrument, p.target())?;
    let construction = OnlyConstructionIdentity::new(p.clone(), &r.data_version, None, None, None)
        .map_err(|_| Error::Invalid)?;
    Scope::from_record(&json!({"source_id":r.identity().source_id,"market":r.identity().market,"instrument_id":instrument,"data_kind":"BAR","start_ns":start,"end_ns":end,"data_version":r.data_version,"bar_type":fp(&bt.to_record())?,"first_sequence":null,"last_sequence":null,"bar_construction":construction.to_record()})).map_err(Into::into)
}
pub(super) fn bar_type(instrument: &str, s: &OnlyBarSemantic) -> Result<OnlyBarType> {
    OnlyBarType::new(OnlyBarTypeInput {
        instrument_id: instrument.parse().map_err(|_| Error::Invalid)?,
        semantic: s.clone(),
    })
    .map_err(|_| Error::Invalid)
}
pub(super) fn bar_row(b: &OnlyBar) -> Result<Value> {
    let r = b.to_record();
    Ok(
        json!({"bar_start_ns":ns(*b.bar_start())?.to_string(),"bar_end_ns":ns(*b.bar_end())?.to_string(),"open":r["open"]["value"],"high":r["high"]["value"],"low":r["low"]["value"],"close":r["close"]["value"],"volume":r["volume"]["value"],"closed":b.is_closed()}),
    )
}
pub(super) fn derived_with_calendar(
    calendar: &onlyalpha_domain::calendar::OnlyTradingCalendar,
    p: &OnlyConstructionResolutionPlan,
    instrument: &str,
    bars: Vec<OnlyBar>,
) -> Result<Vec<OnlyBar>> {
    if p.recipe().is_native() {
        return Ok(bars);
    }
    let edge = OnlyConstructionEdge::new(
        OnlyConstructionInput::Bar(bar_type(instrument, &semantic(1)?)?),
        bar_type(instrument, p.target())?,
        p.recipe().clone(),
    )
    .map_err(|_| Error::Invalid)?;
    let mut executor =
        OnlyTimeBarExecutor::new(edge, Arc::new(calendar.clone())).map_err(|_| Error::Invalid)?;
    let mut out = vec![];
    for bar in bars {
        let init = OnlyTimestamp::from_datetime(*bar.ts_event());
        out.extend(
            executor
                .process(&OnlyConstructionFact::Bar(Arc::new(bar)), &init)
                .map_err(|_| Error::Corrupt)?
                .into_iter()
                .map(|v| (*v).clone()),
        );
    }
    Ok(out)
}
impl Application {
    pub async fn instruments(
        &self,
        r: &Resolved,
        session: &Session,
        query: &InstrumentQuery,
        deadline: Instant,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        validate_instrument_query(query)?;
        if let [instrument] = query.instrument_ids.as_slice()
            && query.query.trim().is_empty()
            && query.asset_class.is_none()
            && query.instrument_types.is_empty()
        {
            let row = self
                .read_reference(r, session, instrument, deadline)
                .await?;
            let rows = row
                .iter()
                .map(|i| instrument_row(i, &r.identity().market))
                .collect::<Vec<_>>();
            return Authorized::new(
                json!({"schema_version":1,"source_selection":selection(r),"instruments":rows}),
                session,
                r,
                Permission::ClosedHistory,
            );
        }
        let value = self
            .discover(r, session, query, deadline)
            .await?
            .into_parts()?
            .0;
        Authorized::new(
            json!({"schema_version":1,"source_selection":value["source_selection"],"instruments":value["instruments"]}),
            session,
            r,
            Permission::ClosedHistory,
        )
    }
    async fn discover(
        &self,
        r: &Resolved,
        session: &Session,
        query: &InstrumentQuery,
        deadline: Instant,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        validate_instrument_query(query)?;
        for text in &query.instrument_ids {
            let id: OnlyInstrumentId = text.parse().map_err(|_| Error::Invalid)?;
            if id.venue().value() != r.identity().venue {
                return Err(Error::Selection);
            }
        }
        let end = deadline.min(Instant::now() + Duration::from_secs(8));
        let key = format!("{}:{}", r.binding.fingerprint(), r.artifact);
        let cached = {
            let cache = self.cache.lock().map_err(|_| Error::Unavailable)?;
            cache
                .get(&key)
                .filter(|c| c.current_at(Instant::now()))
                .map(|c| c.rows.clone())
        };
        let rows = if let Some(rows) = cached {
            rows
        } else {
            let _slot = tokio::time::timeout_at(end.into(), self.slots.acquire())
                .await
                .map_err(|_| Error::Source(SourceError::Timeout))?
                .map_err(|_| Error::Unavailable)?;
            session.require_selection(&r.selection, Permission::ClosedHistory)?;
            let rows =
                tokio::time::timeout_at(end.into(), r.resource.instruments(&[], budget(end)?))
                    .await
                    .map_err(|_| Error::Source(SourceError::Timeout))??;
            session.require_selection(&r.selection, Permission::ClosedHistory)?;
            let mut seen = std::collections::BTreeSet::new();
            if rows.len() > 10001
                || rows.iter().any(|i| {
                    i.specification().venue().value() != r.identity().venue
                        || !seen.insert(i.specification().instrument_id().to_string())
                })
            {
                return Err(Error::Corrupt);
            }
            let mut cache = self.cache.lock().map_err(|_| Error::Unavailable)?;
            if cache.len() >= 32 && !cache.contains_key(&key) {
                let oldest = cache
                    .iter()
                    .min_by_key(|(_, c)| c.at)
                    .map(|(k, _)| k.clone())
                    .ok_or(Error::Unavailable)?;
                cache.remove(&oldest);
            }
            cache.insert(
                key,
                Cache {
                    at: Instant::now(),
                    rows: rows.clone(),
                },
            );
            rows
        };
        let q = query
            .query
            .trim_matches(|c: char| c.is_whitespace() || ('\u{001c}'..='\u{001f}').contains(&c))
            .to_uppercase();
        let asset_classes = rows
            .iter()
            .map(|i| i.specification().asset_class().as_str())
            .collect::<std::collections::BTreeSet<_>>();
        let mut matches = rows
            .iter()
            .filter(|i| {
                let s = i.specification();
                query
                    .asset_class
                    .as_deref()
                    .is_none_or(|v| v == s.asset_class().as_str())
                    && (query.instrument_types.is_empty()
                        || query
                            .instrument_types
                            .iter()
                            .any(|v| v == s.instrument_type().as_str()))
                    && (query.instrument_ids.is_empty()
                        || query
                            .instrument_ids
                            .contains(&s.instrument_id().to_string()))
                    && (q.is_empty() || s.raw_symbol().value().contains(&q))
            })
            .map(|i| instrument_row(i, &r.identity().market))
            .collect::<Vec<_>>();
        matches.sort_by_key(|v| v["instrument_id"].as_str().unwrap_or_default().to_owned());
        let truncated = matches.len() > query.limit || rows.len() > 10000;
        matches.truncate(query.limit);
        Authorized::new(
            json!({"schema_version":1,"source_selection":selection(r),"instruments":matches,"status":"COMPLETE","truncated":truncated,"asset_classes":asset_classes}),
            session,
            r,
            Permission::ClosedHistory,
        )
    }
    pub async fn search(
        &self,
        sources: &[&Resolved],
        session: &Session,
        query: &InstrumentQuery,
        deadline: Instant,
    ) -> Result<AuthorizedBatch> {
        validate_instrument_query(query)?;
        if sources.len() > 32 || query.query.trim().is_empty() || !query.instrument_ids.is_empty() {
            return Err(Error::Invalid);
        }
        let end = deadline.min(Instant::now() + Duration::from_secs(10));
        let mut results = vec![];
        let mut reports = vec![];
        let mut seen = std::collections::BTreeSet::new();
        for r in sources {
            if !seen.insert(canonical(&selection(r))?) {
                return Err(Error::Invalid);
            }
            match self.discover(r,session,query,end).await {
                Ok(value)=>{
                    let (value,fence)=value.into_parts()?;fence.check()?;
                    for instrument in value["instruments"].as_array().ok_or(Error::Corrupt)? {results.push(json!({"source_selection":selection(r),"instrument":instrument}));}
                    reports.push(json!({"source_selection":selection(r),"status":"COMPLETE","asset_classes":value["asset_classes"],"truncated":value["truncated"]}));
                },
                Err(Error::Forbidden)=>return Err(Error::Forbidden),
                Err(e)=>reports.push(json!({"source_selection":selection(r),"status":match e{Error::Source(SourceError::Timeout)=>"TIMEOUT",Error::Source(SourceError::Unsupported)=>"UNSUPPORTED",_=>"UNAVAILABLE"},"asset_classes":[],"truncated":false})),
            }
        }
        let truncated =
            results.len() > query.limit || reports.iter().any(|v| v["truncated"] == true);
        results.truncate(query.limit);
        session.check_active()?;
        AuthorizedBatch::new(
            json!({"schema_version":1,"results":results,"sources":reports,"truncated":truncated}),
            session,
            sources
                .iter()
                .map(|r| (r.selection.clone(), Permission::ClosedHistory))
                .collect(),
        )
    }
    pub async fn quotes(
        &self,
        r: &Resolved,
        session: &Session,
        ids: &[String],
        deadline: Instant,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&r.selection, Permission::RealtimePreview)?;
        if ids.is_empty()
            || ids.len() > 25
            || ids.iter().collect::<std::collections::BTreeSet<_>>().len() != ids.len()
        {
            return Err(Error::Invalid);
        }
        let mut symbols = vec![];
        for id in ids {
            let i: OnlyInstrumentId = id.parse().map_err(|_| Error::Invalid)?;
            if i.venue().value() != r.identity().venue {
                return Err(Error::Selection);
            }
            symbols.push(i.symbol().value().to_owned());
        }
        let end = deadline.min(Instant::now() + Duration::from_secs(8));
        let _slot = tokio::time::timeout_at(end.into(), self.slots.acquire())
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))?
            .map_err(|_| Error::Unavailable)?;
        session.require_selection(&r.selection, Permission::RealtimePreview)?;
        let quotes = tokio::time::timeout_at(end.into(), r.resource.quotes(&symbols, budget(end)?))
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))??;
        let mut seen = std::collections::BTreeSet::new();
        if quotes
            .iter()
            .any(|q| !ids.contains(&q.instrument_id) || !seen.insert(q.instrument_id.clone()))
        {
            return Err(Error::Corrupt);
        }
        let rows=ids.iter().map(|id|match quotes.iter().find(|q|&q.instrument_id==id){Some(q)=>json!({"instrument_id":id,"status":"AVAILABLE","last_price":q.last_price,"change_pct":q.change_pct,"change_basis":"ROLLING_24H","ts_event_ns":q.event_ns.to_string()}),None=>json!({"instrument_id":id,"status":"UNAVAILABLE","last_price":null,"change_pct":null,"change_basis":null,"ts_event_ns":null})}).collect::<Vec<_>>();
        Authorized::new(
            json!({"schema_version":1,"source_selection":selection(r),"quotes":rows,"status":"COMPLETE"}),
            session,
            r,
            Permission::RealtimePreview,
        )
    }
    pub async fn window(
        &self,
        r: &Resolved,
        session: &Session,
        store: &mut Storage<'_>,
        request: &WindowRequest,
    ) -> Result<Authorized<Value>> {
        let context = super::HistoryContext::current(r, &request.instrument_id, &request.semantic)?;
        self.history_window(&context, session, store, request).await
    }

    pub async fn latest(
        &self,
        r: &Resolved,
        session: &Session,
        store: &mut Storage<'_>,
        instrument: &str,
        target: &OnlyBarSemantic,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let p = plan(r, instrument, target)?;
        if !p.recipe().is_native() {
            return Err(Error::Invalid);
        }
        let family = scope(r, instrument, 0, 1, &p)?;
        let (_, facts) = match store.read_latest(&family).await {
            Ok(value) => value,
            Err(market_data::Error::NotFound) => {
                return Authorized::new(Value::Null, session, r, Permission::ClosedHistory);
            }
            Err(error) => return Err(error.into()),
        };
        let fact = facts
            .iter()
            .max_by_key(|f| f["ts_event_ns"].as_i64())
            .ok_or(Error::Corrupt)?;
        let bar = OnlyBar::from_record(&fact["canonical_payload"]["payload"]["value"])
            .map_err(|_| Error::Corrupt)?;
        let now = r.clock.now_ns()?;
        let stride = target
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<i64>()
            .map_err(|_| Error::Invalid)?
            .checked_mul(60_000_000_000)
            .ok_or(Error::Invalid)?;
        let end = ns(*bar.bar_end())?.min(now.div_euclid(stride) * stride);
        if end <= 0 {
            return Authorized::new(Value::Null, session, r, Permission::ClosedHistory);
        }
        let projection = self
            .window(
                r,
                session,
                store,
                &WindowRequest {
                    instrument_id: instrument.into(),
                    semantic: target.clone(),
                    before_ns: Some(end),
                    bar_count: 1,
                    clock_ns: now,
                },
            )
            .await?;
        let (value, _) = projection.into_parts()?;
        if value["coverage"]["status"] != "COMPLETE"
            || value["bars"].as_array().is_none_or(|bars| bars.len() != 1)
        {
            return Err(Error::Store(market_data::Error::Unprovable));
        }
        Authorized::new(value, session, r, Permission::ClosedHistory)
    }
    /// Reuse only a current exact catalogue descriptor, never an access proof.
    pub(super) async fn temporary_reference(
        &self,
        r: &Resolved,
        session: &Session,
        instrument: &str,
        deadline: Instant,
    ) -> Result<Authorized<OnlyInstrument>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let id: OnlyInstrumentId = instrument.parse().map_err(|_| Error::Invalid)?;
        if id.venue().value() != r.identity().venue {
            return Err(Error::Selection);
        }
        let cached = self
            .cache
            .lock()
            .map_err(|_| Error::Unavailable)?
            .get(&format!("{}:{}", r.binding.fingerprint(), r.artifact))
            .filter(|c| c.current_at(Instant::now()))
            .and_then(|c| {
                c.rows
                    .iter()
                    .find(|i| i.specification().instrument_id() == &id)
            })
            .cloned();
        if let Some(instrument) = cached {
            Authorized::new(instrument, session, r, Permission::ClosedHistory)
        } else {
            self.reference(r, session, instrument, deadline).await
        }
    }
    pub async fn reference(
        &self,
        r: &Resolved,
        session: &Session,
        instrument: &str,
        deadline: Instant,
    ) -> Result<Authorized<OnlyInstrument>> {
        let instrument = self
            .read_reference(r, session, instrument, deadline)
            .await?
            .ok_or(Error::Corrupt)?;
        Authorized::new(instrument, session, r, Permission::ClosedHistory)
    }
    async fn read_reference(
        &self,
        r: &Resolved,
        session: &Session,
        instrument: &str,
        deadline: Instant,
    ) -> Result<Option<OnlyInstrument>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let id: OnlyInstrumentId = instrument.parse().map_err(|_| Error::Invalid)?;
        if id.venue().value() != r.identity().venue {
            return Err(Error::Selection);
        }
        let symbols = vec![id.symbol().value().to_owned()];
        let end = deadline.min(Instant::now() + Duration::from_secs(8));
        let _slot = tokio::time::timeout_at(end.into(), self.slots.acquire())
            .await
            .map_err(|_| Error::Source(SourceError::Timeout))?
            .map_err(|_| Error::Unavailable)?;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let rows =
            tokio::time::timeout_at(end.into(), r.resource.instruments(&symbols, budget(end)?))
                .await
                .map_err(|_| Error::Source(SourceError::Timeout))??;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        if rows.len() > 1
            || rows
                .first()
                .is_some_and(|i| i.specification().instrument_id() != &id)
        {
            return Err(Error::Corrupt);
        }
        Ok(rows.into_iter().next())
    }
    pub(super) fn history_request(
        r: &Resolved,
        instrument: OnlyInstrument,
        scope: &Scope,
    ) -> Result<HistoryRequest> {
        let p = OnlyConstructionIdentity::from_record(&scope.to_record()["bar_construction"])
            .map_err(|_| Error::Corrupt)?;
        if p.plan().context().source() != r.identity().source_id {
            return Err(Error::Conflict);
        }
        let minutes = p
            .plan()
            .target()
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse()
            .map_err(|_| Error::Invalid)?;
        Ok(HistoryRequest {
            instrument,
            minutes,
            start_ms: scope.start_ns() / 1_000_000,
            end_ms: scope.end_ns() / 1_000_000,
        })
    }
}
pub(super) fn coalesce_gaps(gaps: &[Value], maximum: i64) -> Result<Vec<Value>> {
    let mut result: Vec<Value> = vec![];
    for gap in gaps {
        let s = gap["start_ns"].as_i64().ok_or(Error::Corrupt)?;
        let e = gap["end_ns"].as_i64().ok_or(Error::Corrupt)?;
        if s >= e || e - s > maximum {
            return Err(Error::Invalid);
        }
        if let Some(last) = result.last_mut() {
            let start = last["start_ns"].as_i64().ok_or(Error::Corrupt)?;
            if last["end_ns"].as_i64() == Some(s) && e - start <= maximum {
                last["end_ns"] = json!(e);
                continue;
            }
        }
        result.push(gap.clone());
    }
    Ok(result)
}

fn validate_instrument_query(query: &InstrumentQuery) -> Result<()> {
    if query.limit == 0
        || query.limit > 25
        || query.query.chars().count() > 128
        || query.instrument_ids.len() > 25
        || query.instrument_types.len() > 8
        || query
            .instrument_ids
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != query.instrument_ids.len()
        || query
            .instrument_types
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != query.instrument_types.len()
        || query.asset_class.as_ref().is_some_and(|v| {
            v.parse::<onlyalpha_domain::enums::OnlyAssetClass>()
                .is_err()
        })
        || query.instrument_types.iter().any(|v| {
            v.parse::<onlyalpha_domain::enums::OnlyInstrumentType>()
                .is_err()
        })
    {
        return Err(Error::Invalid);
    }
    Ok(())
}
pub(super) fn evidence_wire(value: &Value) -> Result<Value> {
    let mut value = value.clone();
    for key in ["covered_start_ns", "covered_end_ns"] {
        value[key] = value[key]
            .as_i64()
            .ok_or(Error::Corrupt)?
            .to_string()
            .into();
    }
    Ok(value)
}

pub(super) fn gap_wire(gap: &Value) -> Result<Value> {
    Ok(
        json!({"start_ns":gap["start_ns"].as_i64().ok_or(Error::Corrupt)?.to_string(),"end_ns":gap["end_ns"].as_i64().ok_or(Error::Corrupt)?.to_string()}),
    )
}

pub(super) fn native_intervals(scope: &Scope) -> Result<Vec<(i64, i64)>> {
    let identity = onlyalpha_market_data_construction::OnlyConstructionIdentity::from_record(
        &scope.to_record()["bar_construction"],
    )
    .map_err(|_| Error::Corrupt)?;
    let stride = identity
        .plan()
        .target()
        .stride_minutes()
        .map_err(|_| Error::Corrupt)?
        .to_string()
        .parse::<i64>()
        .map_err(|_| Error::Corrupt)?
        .checked_mul(60_000_000_000)
        .ok_or(Error::Invalid)?;
    onlyalpha_market_data_construction::only_construction_expected_ends(
        identity.plan().target(),
        scope.start_ns().into(),
        scope.end_ns().into(),
        identity.plan().grid_origin().clone(),
        10080,
    )
    .map_err(|_| Error::Invalid)?
    .into_iter()
    .map(|end| {
        let end = end.to_string().parse::<i64>().map_err(|_| Error::Invalid)?;
        Ok((end.checked_sub(stride).ok_or(Error::Invalid)?, end))
    })
    .collect()
}
