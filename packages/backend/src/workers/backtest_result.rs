//! Read-only projection of the actual native replay and canonical economic owners.
//! No Run admission, publication seal, fabricated Trade or parallel position book.
use super::backtest::PreparedNextOpen;
use onlyalpha_backtest::{Error, Participants, RunLoop};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    numeric::{OnlyDecimal, only_add, only_divide, only_multiply, only_quantize, only_subtract},
    time::{OnlyTimestamp, OnlyTradingDay},
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, Error>;
fn bad(reason: &str) -> Error {
    Error(format!("BACKTEST_OBSERVATION_{reason}"))
}
fn boundary<T, E: std::fmt::Display>(v: std::result::Result<T, E>) -> Result<T> {
    v.map_err(|e| bad(&e.to_string()))
}
fn number(v: &Value) -> Result<OnlyDecimal> {
    boundary(v.as_str().ok_or_else(|| bad("DECIMAL"))?.parse())
}
fn integer(v: &Value) -> Result<u64> {
    v.as_u64().ok_or_else(|| bad("INTEGER"))
}
fn fingerprint(v: &Value) -> String {
    onlyalpha_calculation_bridge::fingerprint(v.to_string().as_bytes())
}
fn instant(bar: &onlyalpha_domain::market::OnlyBar, start: bool) -> Result<u64> {
    boundary(
        OnlyTimestamp::from_datetime(if start {
            *bar.bar_start()
        } else {
            *bar.bar_end()
        })
        .to_unix_nanos()
        .to_string()
        .parse(),
    )
}
struct Point {
    prefix: u64,
    nav: OnlyDecimal,
    peak: OnlyDecimal,
    drawdown: Option<OnlyDecimal>,
    sequence: Value,
}
/// Only a real terminal RunLoop can produce this value. It carries observations,
/// never an execution grant or the Product's opaque CompletionProof.
pub struct ObservedBacktest {
    record: Value,
    result: Value,
    proof: Value,
    trace: Value,
    preparation: Value,
}
impl ObservedBacktest {
    pub fn observe<P: Participants>(prepared: &PreparedNextOpen, run: &RunLoop<P>) -> Result<Self> {
        Self::project(
            prepared,
            run.result()?,
            run.encoded_trace()?,
            run.state()?,
            |visit| run.for_each_step(visit),
        )
    }
    pub fn from_terminal(
        prepared: &PreparedNextOpen,
        snapshot: &onlyalpha_backtest::TerminalSnapshot,
    ) -> Result<Self> {
        snapshot.verify_cut()?;
        let observed = Self::project(
            prepared,
            snapshot.proof().clone(),
            snapshot.trace().clone(),
            snapshot.state().clone(),
            |visit| snapshot.for_each_step(visit),
        )?;
        snapshot.verify_cut()?;
        Ok(observed)
    }
    fn project(
        prepared: &PreparedNextOpen,
        proof: Value,
        trace: Value,
        state: Value,
        visit: impl FnOnce(&mut dyn FnMut(&Value, bool) -> Result<()>) -> Result<()>,
    ) -> Result<Self> {
        let result = proof["execution_result"].clone();
        let preparation = prepared.record();
        let settings = &preparation["settings"];
        let expected_native =
            fingerprint(&json!([preparation["policy_binding"], settings["policy"]]));
        if trace["binding"]["input_pin"] != prepared.inputs().fingerprint()
            || trace["inputs"] != prepared.inputs().record()
            || trace["binding"]["configuration"] != fingerprint(prepared.configuration())
            || trace["binding"]["initial_state"]["participants"]["schema_version"] != 2
            || trace["binding"]["initial_state"]["participants"]["native"]["binding"]
                != expected_native
            || result["scope"] != *prepared.configuration()
            || proof["processed_prefix_verified"] != true
            || result["manifest"]["input_pin"] != prepared.inputs().fingerprint()
        {
            return Err(bad("PREPARATION_BINDING"));
        }
        let facts = result["facts"].as_array().ok_or_else(|| bad("FACTS"))?;
        let mut causes = BTreeMap::new();
        for (index, fact) in facts.iter().enumerate() {
            if integer(&fact["sequence"])? != index as u64 + 1
                || causes
                    .insert(fingerprint(&fact["input"]), index as u64 + 1)
                    .is_some()
            {
                return Err(bad("FACT_SEQUENCE"));
            }
        }
        let summary = &result["runtime_performance"]["summary"];
        let timeline = result["account_equity_timeline"]
            .as_array()
            .filter(|v| !v.is_empty())
            .ok_or_else(|| bad("ACCOUNT_TIMELINE"))?;
        let mut peak = number(&summary["initial_equity"])?;
        let mut maximum: Option<OnlyDecimal> = None;
        let mut points = Vec::with_capacity(timeline.len());
        let mut previous_prefix = 0;
        for (index, point) in timeline.iter().enumerate() {
            let prefix = if index == 0 {
                if point["source"] != "ACCOUNT_CREATED" {
                    return Err(bad("ACCOUNT_GENESIS"));
                }
                0
            } else {
                let cause = point["provenance"]["upstream_cause"]
                    .as_str()
                    .ok_or_else(|| bad("ACCOUNT_CAUSE"))?;
                *causes.get(cause).ok_or_else(|| bad("ACCOUNT_CAUSE"))?
            };
            if prefix < previous_prefix {
                return Err(bad("ACCOUNT_PREFIX"));
            }
            previous_prefix = prefix;
            let nav = number(&point["snapshot"]["equity"])?;
            if nav > peak {
                peak = nav.clone();
            }
            let drawdown = boundary(onlyalpha_account::equity_drawdown(&nav, &peak))?;
            if let Some(value) = &drawdown
                && maximum.as_ref().is_none_or(|m| value < m)
            {
                maximum = Some(value.clone());
            }
            points.push(Point {
                prefix,
                nav,
                peak: peak.clone(),
                drawdown,
                sequence: point["account_sequence"].clone(),
            });
        }
        let owning_maximum = if summary["maximum_drawdown"].is_null() {
            None
        } else {
            Some(number(&summary["maximum_drawdown"])?)
        };
        if maximum != owning_maximum
            || points.last().ok_or_else(|| bad("ACCOUNT_TIMELINE"))?.nav
                != number(&summary["final_equity"])?
        {
            return Err(bad("ACCOUNT_SUMMARY"));
        }
        let start: u64 = boundary(
            settings["policy"]["start_ns"]
                .as_str()
                .ok_or_else(|| bad("WINDOW"))?
                .parse(),
        )?;
        let end: u64 = boundary(
            settings["policy"]["end_ns"]
                .as_str()
                .ok_or_else(|| bad("WINDOW"))?
                .parse(),
        )?;
        let mut curve = Vec::new();
        let mut closed = 0usize;
        visit(&mut |step, ready| {
            if !ready {
                return Err(bad("STEP_NOT_READY"));
            }
            if step["cause"]["kind"] != "BAR" {
                return Ok(());
            }
            let input = prepared
                .inputs()
                .records()
                .get(closed)
                .ok_or_else(|| bad("BAR_PREFIX"))?;
            closed += 1;
            if step["cause"]["processing"]["input"] != input.record() {
                return Err(bad("BAR_PREFIX"));
            }
            let bar_start = instant(input.bar(), true)?;
            if bar_start < start || bar_start >= end {
                return Ok(());
            }
            let prefix = integer(&step["execution_start"])?
                + step["inputs"]
                    .as_array()
                    .ok_or_else(|| bad("STEP_INPUTS"))?
                    .len() as u64;
            if prefix > facts.len() as u64 {
                return Err(bad("STEP_EXECUTION_PREFIX"));
            }
            let point = points
                .iter()
                .rev()
                .find(|p| p.prefix <= prefix)
                .ok_or_else(|| bad("ACCOUNT_PREFIX"))?;
            curve.push(json!({"bar_start_ns":bar_start.to_string(),"bar_end_ns":instant(input.bar(),false)?.to_string(),"execution_prefix":prefix,"nav":point.nav.to_string(),"high_water_mark":point.peak.to_string(),"drawdown":point.drawdown.as_ref().map(ToString::to_string),"account_sequence":point.sequence}));
            Ok(())
        })?;
        if integer(&trace["state"]["cursor"])? != closed as u64 {
            return Err(bad("CLOSED_PREFIX"));
        }
        let cluster = prepared.configuration()["profiles"]
            .as_object()
            .filter(|m| m.len() == 1)
            .and_then(|m| m.keys().next())
            .ok_or_else(|| bad("CLUSTER"))?;
        let mut cycles = BTreeSet::new();
        let mut remember = |snapshot: &Value| -> Result<()> {
            if snapshot["status"] == "CLOSED" {
                let id = snapshot["id"].as_str().ok_or_else(|| bad("POSITION_ID"))?;
                cycles.insert((id.to_owned(), integer(&snapshot["cycle"])?));
            }
            Ok(())
        };
        for history in state["position"]["history"]
            .as_array()
            .ok_or_else(|| bad("POSITION_HISTORY"))?
        {
            if history["owner"][0] == "CLUSTER" && history["owner"][4] == *cluster {
                remember(&history["snapshot"])?;
            }
        }
        for allocation in result["final_allocations"]
            .as_array()
            .ok_or_else(|| bad("ALLOCATIONS"))?
        {
            if allocation["cluster"] == *cluster {
                remember(&allocation["snapshot"])?;
            }
        }
        let complete = proof["status"] == "COMPLETED"
            && proof["outcome"]["status"] == "COMPLETED"
            && proof["market_exhausted"] == true
            && proof["drained"] == true;
        let baseline = if complete {
            if curve.len() as u64 != integer(&preparation["window"]["sample_bar_count"])? {
                return Err(bad("SAMPLE_COMPLETENESS"));
            }
            analytical_baseline(prepared, &preparation, start, end)?
        } else {
            Value::Null
        };
        let record = json!({"schema_version":1,"kind":"NATIVE_BTC_SPOT_NEXT_OPEN_OBSERVATION","preparation_fingerprint":boundary(crate::application::factor_content::hash(&preparation))?,"status":proof["status"],"sample_bar_count":curve.len(),"account_summary":summary,"close_curve":curve,"fill_count":result["trades"].as_array().ok_or_else(||bad("TRADES"))?.len(),"roundtrip_count":cycles.len(),"final_positions":result["final_positions"],"baseline":baseline});
        Ok(Self {
            record,
            result,
            proof,
            trace,
            preparation,
        })
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn result(&self) -> &Value {
        &self.result
    }
    pub fn proof(&self) -> &Value {
        &self.proof
    }
    pub fn trace(&self) -> &Value {
        &self.trace
    }
    pub fn preparation(&self) -> &Value {
        &self.preparation
    }
}
fn analytical_baseline(
    prepared: &PreparedNextOpen,
    preparation: &Value,
    start: u64,
    end: u64,
) -> Result<Value> {
    let mut sample = Vec::new();
    for input in prepared.inputs().records() {
        let at = instant(input.bar(), true)?;
        if at >= start && at < end {
            sample.push(input);
        }
    }
    let first = sample.first().ok_or_else(|| bad("BASELINE_INPUT"))?;
    let last = sample.last().ok_or_else(|| bad("BASELINE_INPUT"))?;
    let quantity = boundary(OnlyQuantity::from_record(
        &preparation["settings"]["policy"]["quantity"],
    ))?;
    let multiplier = number(&preparation["settings"]["policy"]["buy_multiplier"])?;
    let exact = boundary(only_multiply(first.opening().price().value(), &multiplier))?;
    let price = boundary(OnlyPrice::new(
        exact.clone(),
        u8::try_from(exact.fractional_precision().max(0)).map_err(|_| bad("BASELINE_PRICE"))?,
    ))?;
    let bar_record = first.bar().to_record();
    let day = boundary(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":bar_record["trading_day"]}),
    ))?
    .value();
    let origin = boundary(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":"0001-01-01"}),
    ))?
    .value();
    let ordinal = u64::try_from(boundary(day.since(origin))?.get_days())
        .map_err(|_| bad("BASELINE_DAY"))?
        + 1;
    let cause = fingerprint(
        &json!({"kind":"ANALYTICAL_ESTIMATE","input":first.identity(),"policy":preparation["policy_binding"]}),
    );
    let context = json!({"schema_version":1,"time":instant(first.bar(),true)?,"day_index":ordinal,"trading_day":bar_record["trading_day"],"cause":cause});
    let quote = boundary(
        prepared
            .simulation_policy()
            .analytical_entry_quote(&price, &quantity, &context),
    )?;
    let initial = number(&prepared.configuration()["initial_cash"])?;
    let gross = number(&quote["gross_notional"]["amount"])?;
    let fee = number(&quote["charges"]["amount"])?;
    let rebate = number(&quote["rebates"]["amount"])?;
    let cash = boundary(only_add(
        &boundary(only_subtract(
            &boundary(only_subtract(&initial, &gross))?,
            &fee,
        ))?,
        &rebate,
    ))?;
    let mark = boundary(only_multiply(last.bar().close().value(), quantity.value()))?;
    let quantum: OnlyDecimal = boundary(
        format!(
            "1e-{}",
            prepared.configuration()["currency"]["precision"]
                .as_u64()
                .ok_or_else(|| bad("CURRENCY"))?
        )
        .parse(),
    )?;
    let market = boundary(only_quantize(&mark, &quantum))?;
    let equity = boundary(only_add(&cash, &market))?;
    let net = boundary(only_subtract(&equity, &initial))?;
    // Fixed 10000 capital is a power of ten, so Domain division is exact here.
    let returns = boundary(only_quantize(
        &boundary(only_divide(&net, &initial))?,
        &boundary("0.00000001".parse())?,
    ))?;
    let cost = boundary(only_multiply(price.value(), quantity.value()))?;
    let unrealized = boundary(only_subtract(&mark, &cost))?;
    Ok(
        json!({"kind":"ANALYTICAL_ESTIMATE","sample_start_ns":start.to_string(),"sample_end_ns":end.to_string(),"entry_at_ns":instant(first.bar(),true)?.to_string(),"valuation_at_ns":instant(last.bar(),false)?.to_string(),"entry_price":price.to_record(),"quantity":quantity.to_record(),"entry_fee_quote":quote,"initial_equity":initial.to_string(),"final_equity":equity.to_string(),"net_pnl":net.to_string(),"unrealized_pnl":unrealized.to_string(),"return_since_start":returns.to_string()}),
    )
}
