#![allow(dead_code)]
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarType},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use onlyalpha_market_data_state::*;
use serde_json::{Value, json};
use std::sync::Arc;
pub const A: &str = "600000.XSHG";
pub const B: &str = "BTCUSD.TEST";
pub fn scope(engine: &str, runtime: &str) -> OnlyMarketDataStateScope {
    OnlyMarketDataStateScope::new(engine.parse().unwrap(), runtime.parse().unwrap())
}
pub fn state(limit: usize) -> OnlyMarketDataState {
    OnlyMarketDataState::new(
        scope("engine", "runtime"),
        OnlyMarketDataStateConfig {
            history_limit: limit,
        },
    )
    .unwrap()
}
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
pub fn apply(
    s: &mut OnlyMarketDataState,
    bars: &[Arc<OnlyBar>],
    primary: &OnlyBarType,
    end: u32,
) -> OnlyMarketDataSnapshot {
    s.apply_closed(bars, primary, stamp(end), vec![]).unwrap()
}
