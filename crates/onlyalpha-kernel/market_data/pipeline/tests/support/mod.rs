#![allow(dead_code)]
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarType},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_market_data_construction::*;
use serde_json::{Value, json};
use std::sync::Arc;
pub const A: &str = "600000.XSHG";
pub fn stamp(minute: u32) -> OnlyTimestamp {
    let base =
        OnlyTimestamp::from_datetime("2026-01-05T01:30:00Z".parse::<OnlyUtcDateTime>().unwrap());
    OnlyTimestamp::from_unix_nanos(
        base.unix_nanos() + num_bigint::BigInt::from(minute) * 60_000_000_000i64,
    )
}
pub fn kind(instrument: &str, window: u32) -> OnlyBarType {
    OnlyBarType::from_record(&json!({"schema_version":2,"instrument_id":instrument.parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>().unwrap().to_record(),"semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":window,"stride_minutes":window,"alignment":"UTC"},"price_type":"LAST","adjustment_policy":"RAW"}})).unwrap()
}
pub fn bar(instrument: &str, window: u32, end: u32) -> Arc<OnlyBar> {
    let price = |value: &str| json!({"schema_version":1,"value":value,"precision":2});
    let time = |minute| stamp(minute).to_datetime_exact().unwrap().to_string();
    Arc::new(OnlyBar::from_record(&json!({"schema_version":1,"bar_type":kind(instrument,window).to_record(),"open":price("10.00"),"high":price("10.10"),"low":price("9.90"),"close":price("10.05"),"volume":{"schema_version":1,"value":"100","precision":0},"quote_volume":null,"turnover":null,"trade_count":1,"open_interest":null,"bar_start":time(end-window),"bar_end":time(end),"ts_event":time(end),"ts_init":time(end),"is_closed":true,"revision":0,"adjustment_type":"RAW","trading_day":"2026-01-05","session_type":"CONTINUOUS"})).unwrap())
}
pub fn altered(bar: &OnlyBar, field: &str, value: Value) -> Arc<OnlyBar> {
    let mut row = bar.to_record();
    row[field] = value;
    Arc::new(OnlyBar::from_record(&row).unwrap())
}

pub fn edge(source: u32, target: u32) -> OnlyConstructionEdge {
    let s = kind(A, source);
    let t = kind(A, target);
    let recipe = OnlyConstructionRecipe::derived(
        t.semantic().clone(),
        OnlyConstructionSemantic::Bar(s.semantic().clone()),
        "TIME_BAR",
        1u32.into(),
        OnlyMissingPolicy::Reject,
        OnlyIncompletePolicy::Drop,
    )
    .unwrap();
    OnlyConstructionEdge::new(OnlyConstructionInput::Bar(s), t, recipe).unwrap()
}
pub fn graph() -> OnlyConstructionGraph {
    OnlyConstructionGraph::new(
        vec![OnlyConstructionInput::Bar(kind(A, 1))],
        vec![edge(1, 3), edge(3, 9)],
    )
    .unwrap()
}

pub fn calendar() -> std::sync::Arc<onlyalpha_domain::calendar::OnlyTradingCalendar> {
    use onlyalpha_domain::{calendar::*, enums::OnlySessionType, time::OnlyTimeZone};
    let session = |name: &str, open: &str, close: &str| {
        OnlyTradingSession::new(OnlyTradingSessionInput {
            name: name.into(),
            opens_at: open.parse().unwrap(),
            closes_at: close.parse().unwrap(),
            session_type: OnlySessionType::Continuous,
            belongs_to_trading_day_offset: 0,
            allows_orders: true,
            allows_market_data: true,
        })
        .unwrap()
    };
    std::sync::Arc::new(
        OnlyTradingCalendar::new(OnlyTradingCalendarInput {
            calendar_id: "cal".parse().unwrap(),
            venue_id: "XSHG".parse().unwrap(),
            timezone: OnlyTimeZone::new("Asia/Shanghai").unwrap(),
            sessions: vec![
                session("morning", "09:30:00", "11:30:00"),
                session("afternoon", "13:00:00", "15:00:00"),
            ],
            holidays: vec![],
            weekend_days: vec![5, 6],
            session_profile_id: None,
            special_schedules: vec![],
            calendar_version: 1.into(),
            effective_from: None,
            effective_to: None,
        })
        .unwrap(),
    )
}

use onlyalpha_calculation::{
    CalculationSnapshot, CalculationState, ExecutionBinding, StateOutcome,
};
use onlyalpha_market_data_delivery::*;
use onlyalpha_market_data_pipeline::*;
use onlyalpha_market_data_state::*;
use std::{collections::BTreeMap, sync::Mutex};
pub fn owner() -> OnlyMarketDataStateScope {
    OnlyMarketDataStateScope::new("engine".parse().unwrap(), "runtime".parse().unwrap())
}
pub fn source() -> String {
    "c".repeat(64)
}
pub fn slot(cluster: &str, window: u32, required: bool) -> CalculationSlot {
    let id =
        calculation_scope(&owner(), &cluster.parse().unwrap(), &format!("sma{window}")).unwrap();
    let mut digests = std::array::from_fn(|_| "a".repeat(64));
    digests[5] = digest(
        &json!({"schema_version":1,"bar_type":kind(A,window).to_record(),"source_fingerprint":source()}),
    );
    CalculationSlot {
        local: format!("sma{window}"),
        cluster: cluster.parse().unwrap(),
        binding: ExecutionBinding::new(digests, &id).unwrap(),
        source: source(),
        bar_type: kind(A, window),
        required,
        dependencies: vec![],
    }
}
pub fn program(slots: Vec<CalculationSlot>) -> PipelineProgram {
    let g = OnlyConstructionGraph::new(
        vec![OnlyConstructionInput::Bar(kind(A, 1))],
        vec![edge(1, 3)],
    )
    .unwrap();
    let src = SourceProgram::new(
        &source(),
        calendar(),
        Arc::new(OnlyConstructionRegistry::default()),
        &"e".repeat(64),
        g.clone(),
    )
    .unwrap();
    let clusters = [("a", 1), ("b", 3)]
        .into_iter()
        .map(|(id, p)| ClusterProgram {
            cluster: id.parse().unwrap(),
            subscription: OnlyBarSubscription::new(
                &format!("sub-{id}"),
                vec![kind(A, 1), kind(A, 3)],
                g.clone(),
                Some(kind(A, p)),
                OnlyBarFreshness::LatestClosed,
            )
            .unwrap(),
        })
        .collect();
    PipelineProgram::new(
        owner(),
        &"a".repeat(64),
        4,
        vec![src],
        clusters,
        slots,
        &"f".repeat(64),
    )
    .unwrap()
}
pub fn input(end: u32) -> PipelineInput {
    PipelineInput {
        source: source(),
        sequence: end as u64,
        fact: OnlyConstructionFact::Bar(bar(A, 1, end)),
        logical_init: stamp(end),
        quality: vec![],
    }
}
#[derive(Clone, Default)]
pub struct Fault {
    pub scope: String,
    pub mode: String,
}
pub struct Port {
    pub slots: Vec<CalculationSlot>,
    pub states: BTreeMap<String, CalculationState>,
    pub fault: Arc<Mutex<Fault>>,
}
impl Port {
    pub fn new(slots: Vec<CalculationSlot>) -> Self {
        Self {
            states: slots
                .iter()
                .map(|s| {
                    (
                        s.binding.scope().to_owned(),
                        CalculationState::new(s.binding.clone()),
                    )
                })
                .collect(),
            slots,
            fault: Arc::new(Mutex::new(Fault::default())),
        }
    }
}
impl CalculationPort for Port {
    fn registrations(&self) -> Vec<CalculationSlot> {
        self.slots.clone()
    }
    fn snapshot(&mut self, s: &str) -> Result<CalculationSnapshot, CalculationFailure> {
        Ok(self.states[s].snapshot())
    }
    fn update(&mut self, s: &str, bars: &[Arc<OnlyBar>]) -> Result<(), CalculationFailure> {
        let state = self.states.get_mut(s).unwrap();
        let fault = self.fault.lock().unwrap();
        if fault.scope == s {
            match fault.mode.as_str() {
                "unknown" => return Err(CalculationFailure::Unknown),
                "malformed" => return Ok(()),
                "known" => {
                    state
                        .fail(StateOutcome::Failed, "CONTROLLED_FAILURE")
                        .unwrap();
                    return Err(CalculationFailure::Known);
                }
                _ => (),
            }
        }
        let b = &bars[0];
        let t = OnlyTimestamp::from_datetime(*b.bar_end())
            .unix_nanos()
            .to_string();
        let d = digest(&b.to_record());
        let batch = state.prepare(&[&t], &d).unwrap();
        let mut cursor = state.cursor().capture();
        let n = cursor["samples"].as_u64().unwrap() + 1;
        cursor["revision"] = json!(n);
        cursor["samples"] = json!(n);
        cursor["last_event_ns"] = json!(t);
        // Controlled readiness producer; financial arithmetic is tested through the real worker.
        let window = self
            .slots
            .iter()
            .find(|r| r.binding.scope() == s)
            .unwrap()
            .local
            .clone();
        let threshold = if window == "sma1" { 3 } else { 2 };
        state.commit(&batch,&json!({"cursor":cursor,"input_digest":d,"outputs":{"value":{"type":"DECIMAL","value":"10.05"}},"ready":n>=threshold,"quality_flags":[]})).unwrap();
        Ok(())
    }
    fn capture(&mut self) -> Result<Value, CalculationFailure> {
        Ok(json!(
            self.states
                .iter()
                .map(|(s, v)| json!([s, v.capture()]))
                .collect::<Vec<_>>()
        ))
    }
    fn restore_candidate(&self, v: &Value) -> Result<Self, CalculationFailure> {
        let mut fresh = Self::new(self.slots.clone());
        let rows = v.as_array().ok_or(CalculationFailure::Known)?;
        if rows.len() != fresh.states.len() {
            return Err(CalculationFailure::Known);
        }
        for r in rows {
            let p = r
                .as_array()
                .filter(|p| p.len() == 2)
                .ok_or(CalculationFailure::Known)?;
            let s = p[0].as_str().ok_or(CalculationFailure::Known)?;
            fresh
                .states
                .get_mut(s)
                .ok_or(CalculationFailure::Known)?
                .restore(&p[1])
                .map_err(|_| CalculationFailure::Known)?;
        }
        Ok(fresh)
    }
}
#[derive(Clone, Default)]
pub struct Recorder {
    pub calls: Arc<Mutex<Vec<Value>>>,
    pub fail: Arc<Mutex<String>>,
}
impl PreparationConsumer for Recorder {
    fn artifact(&self) -> &str {
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    }
    fn consume(
        &mut self,
        id: &str,
        plan: &OnlyBarDeliveryPlan,
        values: &BTreeMap<String, CalculationSnapshot>,
    ) -> ConsumerOutcome {
        self.calls.lock().unwrap().push(json!({"id":id,"cluster":plan.cluster_id().value(),"event":plan.snapshot().ts_event().unix_nanos().to_string(),"calculations":values.len()}));
        let fail = self.fail.lock().unwrap().clone();
        if fail == plan.cluster_id().value() {
            ConsumerOutcome::Failed
        } else if fail == format!("panic:{}", plan.cluster_id().value()) {
            panic!("controlled consumer panic")
        } else {
            ConsumerOutcome::Accepted
        }
    }
}
pub fn pipeline() -> MarketDataPipeline<Port, Recorder> {
    let slots = vec![slot("a", 1, true), slot("b", 3, true)];
    MarketDataPipeline::new(
        program(slots.clone()),
        Port::new(slots),
        Recorder::default(),
    )
    .unwrap()
}
pub fn restore<C: CalculationPort, D: PreparationConsumer>(
    p: &mut MarketDataPipeline<C, D>,
    v: &Value,
) -> PipelineResult<()> {
    p.restore_checkpoint(v.to_string().as_bytes(), &digest(v))
}
