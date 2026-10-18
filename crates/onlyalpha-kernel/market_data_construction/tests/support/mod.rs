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
    OnlyTimestamp::from_datetime(
        format!("2026-01-05T01:{:02}:00Z", 30 + minute)
            .parse::<OnlyUtcDateTime>()
            .unwrap(),
    )
}
pub fn kind(instrument: &str, window: u32) -> OnlyBarType {
    OnlyBarType::from_record(&json!({"schema_version":2,"instrument_id":instrument.parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>().unwrap().to_record(),"semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":window,"stride_minutes":window,"alignment":"UTC"},"price_type":"LAST","adjustment_policy":"RAW"}})).unwrap()
}
pub fn bar(instrument: &str, window: u32, end: u32) -> Arc<OnlyBar> {
    let price = |value: &str| json!({"schema_version":1,"value":value,"precision":2});
    let time = |minute| format!("2026-01-05T01:{:02}:00Z", 30 + minute);
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
pub fn time_executor(
    missing: OnlyMissingPolicy,
    incomplete: OnlyIncompletePolicy,
) -> OnlyTimeBarExecutor {
    let e = edge(1, 3);
    let recipe = OnlyConstructionRecipe::derived(
        e.target().semantic().clone(),
        OnlyConstructionSemantic::Bar(kind(A, 1).semantic().clone()),
        "TIME_BAR",
        1u32.into(),
        missing,
        incomplete,
    )
    .unwrap();
    OnlyTimeBarExecutor::new(
        OnlyConstructionEdge::new(e.source().clone(), e.target().clone(), recipe).unwrap(),
        calendar(),
    )
    .unwrap()
}
pub fn fact(end: u32) -> OnlyConstructionFact {
    OnlyConstructionFact::Bar(bar(A, 1, end))
}
