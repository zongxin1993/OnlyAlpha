//! 正式历史日线的命令身份、原始输入、单次封存及精确读。只有 Host 持有 mutation admission。
use super::*;
use crate::application::source_access::{Permission, Selection, Session};
use crate::persistence::market_data::{
    AcquisitionAttempt, AcquisitionIntent, Scope, SealedRevision, Storage, VerifiedHistoryInput,
};
use crate::persistence::market_data_wal::Wal;
use base64::{Engine, engine::general_purpose::STANDARD};
use onlyalpha_domain::{
    base::OnlyDomainModel, calendar::OnlyTradingCalendar, time::OnlyTradingDay,
};
use onlyalpha_integration_contract::source::{
    HistoricalDayRequest, MarketIdentity, Observation, Recorder,
};
use onlyalpha_market_data_construction::{
    OnlyConstructionCapability, OnlyConstructionIdentity, OnlyConstructionResolutionContext,
    OnlyConstructionResolutionPlan,
};
use serde_json::json;
use std::sync::Arc;

pub(crate) fn request(body: &Value) -> Result<HistoricalDayRequest> {
    let instrument = body["instrument_id"]
        .as_str()
        .ok_or(Error::Invalid)?
        .parse()
        .map_err(|_| Error::Invalid)?;
    let semantic = onlyalpha_domain::market::OnlyBarSemantic::from_record(&body["bar_semantic"])
        .map_err(|_| Error::Invalid)?;
    let timestamp = |key: &str| -> Result<_> {
        let raw = body[key].as_str().ok_or(Error::Invalid)?;
        let n: i64 = raw.parse().map_err(|_| Error::Invalid)?;
        if n < 0 || raw != n.to_string() {
            return Err(Error::Invalid);
        }
        time(n)
    };
    let anchor = body
        .get("adjustment_anchor")
        .map(|v| {
            OnlyTradingDay::from_record(&json!({"schema_version":1,"value":v}))
                .map_err(|_| Error::Invalid)
        })
        .transpose()?;
    let start = timestamp("start_ns")?;
    let end = timestamp("end_ns")?;
    if end <= start {
        return Err(Error::Invalid);
    }
    Ok(HistoricalDayRequest {
        instrument,
        semantic,
        start,
        end,
        anchor,
    })
}
pub(crate) fn matches_original(
    intent: &AcquisitionIntent,
    selected: &Selection,
    identity: &MarketIdentity,
    binding: &str,
) -> Result<()> {
    let i = intent.to_record();
    let r = &i["requested_scope"];
    if i["identity_version"] != 3
        || i["integration_binding_fingerprint"] != binding
        || r["source_id"] != selected.source_id()
        || r["environment"] != selected.environment()
        || r["integration_id"] != selected.reference().integration_id()
        || r["integration_revision_fingerprint"] != selected.reference().revision()
        || r["provider"] != identity.provider
        || r["venue"] != identity.venue
        || r["market"] != identity.market
    {
        return Err(Error::Conflict);
    }
    Ok(())
}
pub(crate) fn matches_body(
    intent: &AcquisitionIntent,
    request: &HistoricalDayRequest,
) -> Result<()> {
    let i = intent.to_record();
    let r = &i["requested_scope"];
    if r["instrument_id"] != request.instrument.to_string()
        || r["bar_semantic"] != request.semantic.to_record()
        || r["start_ns"] != ns(request.start)?
        || r["end_ns"] != ns(request.end)?
        || r["adjustment_anchor"] != json!(request.anchor.map(|v| v.to_record()))
    {
        return Err(Error::Conflict);
    }
    Ok(())
}
pub(crate) fn capture_input(
    wal: &mut Wal,
    r: &Resolved,
    attempt: &AcquisitionAttempt,
    query: &Value,
    bytes: &[u8],
    segment: &str,
    at: &str,
    receive_ns: i64,
) -> Result<Value> {
    let identity = r.identity();
    let stream = fp(query)?;
    let raw_hash = hash(bytes);
    let raw_id = format!(
        "raw-event:{}",
        fp(
            &json!({"source_id":identity.source_id,"capture_session_id":attempt.id(),"stream":stream,
        "ts_receive_ns":receive_ns,"raw_sha256":raw_hash,"provider_event_id":null,"type":"HISTORICAL_INPUT"})
        )?
    );
    let frame = json!({"schema_version":1,"canonical_facts":[],"evidence":{"raw_event_id":raw_id,"source_id":identity.source_id,
        "capture_session_id":attempt.id(),"provider":identity.provider,"venue":identity.venue,"market":identity.market,"stream":stream,
        "provider_event_type":"HISTORICAL_INPUT","provider_event_id":null,
        "provider_sequence":null,"ts_event_ns":null,"ts_receive_ns":receive_ns,"payload_codec":"application/json","provider_schema":"v1",
        "payload_base64":STANDARD.encode(bytes),"raw_sha256":raw_hash,"provenance":"REST_BACKFILL","integration_binding_fingerprint":r.binding_fingerprint()}});
    wal.create_segment(segment, at)
        .map_err(|_| Error::Unknown)?;
    wal.append(&frame.to_string()).map_err(|_| Error::Unknown)?;
    let seal = wal.seal(at).map_err(|_| Error::Unknown)?;
    Ok(
        json!({"attempt_id":attempt.id(),"query_fingerprint":stream,"query_document":query,"segment_id":segment,"segment_content_hash":seal["content_hash"],
        "raw_event_id":raw_id,"raw_sha256":raw_hash}),
    )
}
/// 已安装实现按原输入规范化且已封段的唯一准备凭据。持久化只读其原文。
pub(crate) struct PreparedDay(Value);
impl PreparedDay {
    pub(crate) fn record(&self) -> &Value {
        &self.0
    }
}
pub(crate) struct DayProducer<'a> {
    pub resolved: &'a Resolved,
    pub session: &'a Session,
    pub intent: &'a AcquisitionIntent,
    pub attempt: &'a AcquisitionAttempt,
}
impl DayProducer<'_> {
    pub(crate) async fn prepare(
        self,
        original_request: &HistoricalDayRequest,
        verified: Vec<VerifiedHistoryInput>,
        wal: &mut Wal,
        segment: &str,
        observed: onlyalpha_domain::time::OnlyUtcDateTime,
        deadline: std::time::Instant,
    ) -> Result<PreparedDay> {
        let Self {
            resolved: r,
            session,
            intent,
            attempt,
        } = self;
        session.require_selection(r.selection(), Permission::ClosedHistory)?;
        matches_original(intent, r.selection(), r.identity(), r.binding_fingerprint())?;
        matches_body(intent, original_request)?;
        let i = intent.to_record();
        let request = &i["requested_scope"];
        if request["implementation_fingerprint"] != r.implementation_fingerprint()
            || request["artifact_fingerprint"] != r.artifact_fingerprint()
            || attempt.to_record()["acquisition_id"] != intent.id()
        {
            return Err(Error::Conflict);
        }
        let days = r.resource().historical_days().ok_or(Error::Corrupt)?;
        let plan = days.inputs(original_request)?;
        if plan.len() != verified.len() || plan.is_empty() {
            return Err(Error::Corrupt);
        }
        let mut inputs = Vec::with_capacity(plan.len());
        let mut observations = Vec::with_capacity(plan.len());
        for (expected, original) in plan.into_iter().zip(verified) {
            let (link, observation) = original.into_parts();
            if link["attempt_id"] != attempt.id()
                || link["query_document"] != expected
                || observation.query != expected
            {
                return Err(Error::Conflict);
            }
            inputs.push((link, observation.bytes.clone()));
            observations.push(observation);
        }
        let normalized = days
            .replay(original_request, observations, budget(deadline)?)
            .await
            .map_err(|error| match error {
                SourceError::Evidence | SourceError::Conflict => Error::HistoricalInputRejected,
                other => Error::Source(other),
            })?;
        let received = ns(observed)?;
        let at = observed.to_string();
        let at = at.as_str();
        let semantic =
            onlyalpha_domain::market::OnlyBarSemantic::from_record(&request["bar_semantic"])
                .map_err(|_| Error::Corrupt)?;
        let calendar = normalized.calendar.to_record();
        let calendar_fp = fp(&calendar)?;
        let id = request["instrument_id"].as_str().ok_or(Error::Corrupt)?;
        let context = OnlyConstructionResolutionContext::new(
            &r.identity().source_id,
            id.parse().map_err(|_| Error::Invalid)?,
            r.selection.reference().revision(),
            &calendar_fp,
        )
        .map_err(|_| Error::Invalid)?;
        let cap =
            OnlyConstructionCapability::new(semantic.clone(), true, false, &calendar_fp, None)
                .map_err(|_| Error::Invalid)?;
        let plan = OnlyConstructionResolutionPlan::resolve_historical_day(
            semantic.clone(),
            &[cap],
            context,
        )
        .map_err(|_| Error::Invalid)?;
        let security = fp(&normalized.security)?;
        let factor = normalized.factor_basis.as_ref().map(fp).transpose()?;
        let version = market_data::day_data_version(
            request,
            json!(calendar_fp),
            json!(normalized.normalized_daily_fingerprint),
            json!(security),
            json!(factor),
        )?;
        let construction =
            OnlyConstructionIdentity::new(plan, &version, Some(security), None, factor)
                .map_err(|_| Error::Corrupt)?;
        let scope = Scope::from_record(
            &json!({"source_id":r.identity().source_id,"market":r.identity().market,"instrument_id":id,"data_kind":"BAR",
            "start_ns":request["start_ns"],"end_ns":request["end_ns"],"data_version":version,"bar_type":fp(&queries::bar_type(id,&semantic)?.to_record())?,
            "first_sequence":null,"last_sequence":null,"bar_construction":construction.to_record()}),
        )?;
        if normalized.bars.is_empty() {
            return Err(Error::Source(SourceError::Gap));
        }
        let expected = market_data::day_intervals(
            &normalized.calendar,
            scope.start_ns(),
            scope.end_ns(),
            5001,
        )?;
        let actual = normalized
            .bars
            .iter()
            .map(|b| Ok((ns(*b.bar_start())?, ns(*b.bar_end())?)))
            .collect::<Result<Vec<_>>>()?;
        if actual != expected {
            return Err(Error::Source(SourceError::Gap));
        }
        let (original, bytes) = inputs
            .iter()
            .find(|(q, _)| q["query_document"] == normalized.bar_query)
            .ok_or(Error::Corrupt)?;
        let stream = fp(&normalized.bar_query)?;
        let mut recorder = WalRecorder::open(
            wal,
            r,
            session.clone(),
            scope.clone(),
            segment,
            attempt.id(),
            at,
        )?;
        recorder.record(Observation {
            identity: r.identity().clone(),
            stream: stream.clone(),
            event_type: "NORMALIZED_HISTORY_INPUT".into(),
            provider_event_id: Some(
                original["raw_event_id"]
                    .as_str()
                    .ok_or(Error::Corrupt)?
                    .into(),
            ),
            provider_sequence: None,
            event_ns: None,
            receive_ns: received,
            bytes: bytes.clone(),
            bars: normalized.bars,
        })?;
        let candidate = recorder.seal(at)?.ok_or(Error::Unknown)?;
        inputs.sort_by(|(a, _), (b, _)| {
            a["query_fingerprint"]
                .as_str()
                .cmp(&b["query_fingerprint"].as_str())
        });
        let manifest = json!({"acquisition_id":intent.id(),"attempt_id":attempt.id(),"inputs":inputs.into_iter().map(|(q,_)|q).collect::<Vec<_>>(),
            "calendar":calendar,"security":normalized.security,"factor_basis":normalized.factor_basis,"normalized_daily_fingerprint":normalized.normalized_daily_fingerprint,
            "bar_query_fingerprint":stream,"candidate_refs":[[segment,candidate["content_hash"]]]});
        Ok(PreparedDay(
            json!({"attempt_id":attempt.id(),"input_manifest":manifest,"input_fingerprint":fp(&manifest)?,"requested_scope":scope.to_record()}),
        ))
    }
}

pub(crate) async fn status(
    session: &Session,
    selection: &Selection,
    store: &mut Storage<'_>,
    intent: &AcquisitionIntent,
) -> Result<Authorized<Value>> {
    session.require_selection(selection, Permission::ClosedHistory)?;
    let i = intent.to_record();
    let r = &i["requested_scope"];
    let attempt = store.catalog().latest_attempt(intent.id()).await?;
    let mut revision = None;
    let mut count = 0;
    let mut calendar = None;
    let mut state = "PENDING";
    let mut failure = None;
    if let Some(a) = attempt {
        let record = a.to_record();
        if record["outcome"] == "FAILED" {
            if store.catalog().history_preparation(&a).await?.is_some() {
                return Err(Error::Corrupt);
            }
            state = "FAILED";
            failure = Some(record["detail"].clone());
        } else {
            state = "UNKNOWN";
            if let Some(prepared) = store.catalog().history_preparation(&a).await? {
                let m = &prepared["input_manifest"];
                store.prepared_inputs(intent, &a, m).await?;
                let scope = Scope::from_record(&prepared["requested_scope"])?;
                let c =
                    OnlyTradingCalendar::from_record(&m["calendar"]).map_err(|_| Error::Corrupt)?;
                count =
                    market_data::day_intervals(&c, scope.start_ns(), scope.end_ns(), 5001)?.len();
                calendar = Some(Arc::new(c));
                let refs = &m["candidate_refs"];
                revision = store
                    .original_day_revision(&scope, refs, record["revision_id"].as_str())
                    .await?;
                if revision.is_some() {
                    state = "COMPLETE";
                }
            } else if record["outcome"] == "COMPLETE" {
                return Err(Error::Corrupt);
            }
        }
    }
    let coverage = if let Some(rev) = &revision {
        let m = rev.manifest().to_record();
        json!({"status":"COMPLETE","manifest_id":rev.manifest().id(),"manifest_fingerprint":m["fingerprint"],"expected_bar_count":count,"actual_bar_count":count,"gaps":[],"issues":[],"planned_acquisition_ranges":[]})
    } else {
        json!({"status":"UNPROVABLE","manifest_id":null,"manifest_fingerprint":null,"expected_bar_count":count,"actual_bar_count":0,"gaps":[],"planned_acquisition_ranges":[],"issues":["HISTORICAL_DAY_EVIDENCE_UNPROVEN"]})
    };
    Authorized::original(
        json!({"schema_version":1,"acquisition_id":intent.id(),"original_request_id":r["original_request_id"],"status":state,"source_id":r["source_id"],
        "integration_binding_fingerprint":i["integration_binding_fingerprint"],"instrument_id":r["instrument_id"],"bar_semantic":r["bar_semantic"],
        "start_ns":r["start_ns"].as_i64().ok_or(Error::Corrupt)?.to_string(),"end_ns":r["end_ns"].as_i64().ok_or(Error::Corrupt)?.to_string(),"provenance":i["provenance"],
        "coverage":coverage,"revision_id":revision.as_ref().map(SealedRevision::id),"revision_fingerprint":revision.as_ref().map(|r|r.revision()["fingerprint"].clone()),
        "seal_id":revision.as_ref().map(|r|r.seal()["seal_id"].clone()),"failure_detail":failure}),
        session,
        selection,
        calendar,
    )
}

pub(crate) async fn instruments(
    session: &Session,
    selection: &Selection,
    identity: &MarketIdentity,
    store: &mut Storage<'_>,
    query: &super::InstrumentQuery,
) -> Result<super::AuthorizedBatch> {
    session.require_selection(selection, Permission::ClosedHistory)?;
    super::queries::validate_instrument_query(query)?;
    let families = store
        .catalog()
        .history_families(&identity.source_id, None, selection.reference().revision())
        .await?;
    let mut rows = std::collections::BTreeMap::new();
    for scope in families {
        let raw = scope.to_record();
        let id = raw["instrument_id"].as_str().ok_or(Error::Corrupt)?;
        if !scope.is_session_day()
            || (!query.instrument_ids.is_empty() && !query.instrument_ids.iter().any(|s| s == id))
            || !id
                .to_uppercase()
                .contains(&query.query.trim().to_uppercase())
        {
            continue;
        }
        let (revision, _) = store.read_latest(&scope).await?;
        let refs = &revision.revision()["segment_refs"];
        let (segment, _) = store
            .catalog()
            .segment(refs[0][0].as_str().ok_or(Error::Corrupt)?)
            .await?;
        let (_, _, prep) = store
            .day_preparation(
                segment.to_record()["capture_session_id"]
                    .as_str()
                    .ok_or(Error::Corrupt)?,
            )
            .await?;
        if prep["input_manifest"]["candidate_refs"] != *refs
            || prep["requested_scope"] != revision.manifest().to_record()["scope"]
        {
            return Err(Error::Conflict);
        }
        let row = &prep["input_manifest"]["security"]["display"];
        if row["instrument_id"] != id
            || row["market"] != identity.market
            || row["venue"] != identity.venue
        {
            return Err(Error::Corrupt);
        }
        if rows
            .insert(id.to_owned(), row.clone())
            .is_some_and(|old| old != *row)
        {
            return Err(Error::Conflict);
        }
    }
    let rows = rows.into_values().take(query.limit).collect::<Vec<_>>();
    super::AuthorizedBatch::new(
        json!({"schema_version":1,"source_selection":queries::selection_value(selection),"instruments":rows}),
        session,
        vec![(selection.clone(), Permission::ClosedHistory)],
    )
}

pub(crate) async fn window(
    session: &Session,
    selection: &Selection,
    identity: &MarketIdentity,
    store: &mut Storage<'_>,
    request: &super::WindowRequest,
    revision_id: Option<&str>,
) -> Result<Authorized<Value>> {
    session.require_selection(selection, Permission::ClosedHistory)?;
    if request.bar_count == 0 || request.bar_count > 2000 {
        return Err(Error::Invalid);
    }
    let matches = |scope: &Scope| {
        let raw = scope.to_record();
        let plan = &raw["bar_construction"]["plan"];
        scope.is_session_day()
            && raw["source_id"] == identity.source_id
            && raw["market"] == identity.market
            && raw["instrument_id"] == request.instrument_id
            && plan["target_semantic"] == request.semantic.to_record()
            && plan["integration_revision_fingerprint"] == selection.reference().revision()
    };
    let (revision, facts) = if let Some(id) = revision_id {
        let original = store.catalog().revision(id).await?;
        if !matches(&Scope::from_record(
            &original.manifest().to_record()["scope"],
        )?) {
            return Err(Error::Conflict);
        }
        store.read_exact(id).await?
    } else {
        let families = store
            .catalog()
            .history_families(
                &identity.source_id,
                Some(&request.instrument_id),
                selection.reference().revision(),
            )
            .await?;
        let candidates: Vec<_> = families.iter().filter(|s| matches(s)).collect();
        match candidates.as_slice() {
            [] => return Err(Error::Store(market_data::Error::NotFound)),
            [one] => store.read_latest(one).await?,
            _ => return Err(Error::Conflict),
        }
    };
    let manifest = revision.manifest().to_record();
    let scope = Scope::from_record(&manifest["scope"])?;
    let raw = scope.to_record();
    let plan = &raw["bar_construction"]["plan"];
    let refs = revision.revision()["segment_refs"].clone();
    let id = refs[0][0].as_str().ok_or(Error::Corrupt)?;
    let (segment, _) = store.catalog().segment(id).await?;
    let (_, _, prep) = store
        .day_preparation(
            segment.to_record()["capture_session_id"]
                .as_str()
                .ok_or(Error::Corrupt)?,
        )
        .await?;
    if prep["requested_scope"] != raw || prep["input_manifest"]["candidate_refs"] != refs {
        return Err(Error::Conflict);
    }
    let calendar = OnlyTradingCalendar::from_record(&prep["input_manifest"]["calendar"])
        .map_err(|_| Error::Corrupt)?;
    let end = request
        .before_ns
        .unwrap_or(request.clock_ns)
        .min(request.clock_ns);
    let all = market_data::day_intervals(&calendar, scope.start_ns(), scope.end_ns(), 5001)?;
    let intervals: Vec<_> = all
        .iter()
        .copied()
        .filter(|(_, close)| *close <= end)
        .collect();
    let included = &intervals[intervals.len().saturating_sub(request.bar_count)..];
    let start = included.first().map_or(scope.start_ns(), |v| v.0);
    let last = included.last().map_or(scope.end_ns(), |v| v.1);
    let complete = included.len() == request.bar_count;
    let mut bars = Vec::new();
    if complete {
        for fact in facts {
            let bar = onlyalpha_domain::market::OnlyBar::from_record(
                &fact["canonical_payload"]["payload"]["value"],
            )
            .map_err(|_| Error::Corrupt)?;
            if included
                .binary_search(&(ns(*bar.bar_start())?, ns(*bar.bar_end())?))
                .is_ok()
            {
                bars.push(queries::bar_row(&bar)?);
            }
        }
        if bars.len() != included.len() {
            return Err(Error::Corrupt);
        }
    }
    let selection_value = queries::selection_value(selection);
    let evidence = json!({"revision_id":revision.id(),"revision_fingerprint":revision.revision()["fingerprint"],"manifest_id":revision.manifest().id(),"manifest_fingerprint":manifest["fingerprint"],
        "seal_id":revision.seal()["seal_id"],"covered_start_ns":start,"covered_end_ns":last});
    let plan = OnlyConstructionResolutionPlan::from_record(plan).map_err(|_| Error::Corrupt)?;
    let anchor = if request.before_ns.is_some() {
        "BEFORE_TIME"
    } else {
        "LATEST_CLOSED"
    };
    let fingerprint = if complete {
        Some(fp(
            &json!({"source_selection":selection_value,"bar_semantic":request.semantic.to_record(),"resolution_plan_fingerprint":plan.fingerprint(),
        "revision_evidence":[evidence],"resolved_start_ns":start,"resolved_end_ns":last,"anchor_kind":anchor,"requested_before_ns":request.before_ns,"requested_bar_count":request.bar_count}),
        )?)
    } else {
        None
    };
    Authorized::original(
        json!({"schema_version":1,"source_selection":selection_value,"instrument_id":request.instrument_id,"display_symbol":prep["input_manifest"]["security"]["display"]["display_symbol"],
        "venue":identity.venue,"market":identity.market,"bar_semantic":request.semantic.to_record(),"closed_only":true,"anchor_kind":anchor,"requested_before_ns":request.before_ns.map(|n|n.to_string()),
        "requested_bar_count":request.bar_count,"resolved_start_ns":start.to_string(),"resolved_end_ns":last.to_string(),
        "coverage":{"status":if complete{"COMPLETE"}else{"INCOMPLETE"},"manifest_id":revision.manifest().id(),"manifest_fingerprint":manifest["fingerprint"],
        "expected_bar_count":request.bar_count,"actual_bar_count":included.len(),"issues":if complete{vec![]}else{vec!["REQUEST_EXCEEDS_SEALED_SCOPE"]},"gaps":[],"planned_acquisition_ranges":[]},
        "bars":bars,"revision_evidence":[queries::evidence_wire(&evidence)?],"history_projection_fingerprint":fingerprint,"derived_projection_fingerprint":null,"aggregation_semantics_version":null,
        "calendar_fingerprint":plan.context().calendar_fingerprint(),"resolution_mode":"PROVIDER_NATIVE","resolution_plan_fingerprint":plan.fingerprint(),"resume_after_sequence":null,"resume_plan_fingerprint":null}),
        session,
        selection,
        Some(Arc::new(calendar)),
    )
}
