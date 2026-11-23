use crate::{
    Error, Inputs, MarketInput, NextOpenPolicy, OpeningInput, boundary, err, fields, hash,
    next_open::{NextOpenModel, context, signal_at_close},
    sha,
    trading::{BarOperation, bar_request},
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    fee::{OnlyOrderFeeEstimate, OnlyOrderFeePolicyBinding, OnlyOrderFundingPlan},
    numeric::{OnlyDecimal, only_divide, only_quantize, only_subtract},
    value::OnlyPrice,
};
use serde_json::{Value, json};

/// Checks retained finite model events, close curve and baseline against frozen
/// inputs and the already verified Strategy and Execution owner projections.
#[allow(clippy::too_many_arguments)]
pub fn verify_finite_backtest(
    inputs: &Inputs,
    settings: &Value,
    policy: &dyn NextOpenPolicy,
    raw_signals: &[Value],
    facts: &[&Value],
    curve: &[&Value],
    economic_result: &Value,
    equity_points: &[Value],
    analytical_baseline: &Value,
) -> Result<(), Error> {
    let configuration = &settings["execution"];
    let mut profiles = configuration["profiles"]
        .as_object()
        .ok_or_else(|| err("FINITE_PROFILE"))?
        .iter();
    let (cluster, profile) = profiles.next().ok_or_else(|| err("FINITE_PROFILE"))?;
    if settings["schema_version"] != 2 || profiles.next().is_some() {
        return Err(err("FINITE_PROFILE"));
    }
    let rows = inputs.records();
    let first = rows.first().ok_or_else(|| err("FINITE_INPUTS"))?;
    let initial = economic_result["run"]["initial_time"]["unix_nanos"]
        .as_i64()
        .filter(|ns| *ns >= 0)
        .ok_or_else(|| err("FINITE_INITIAL_TIME"))?;
    let initial = onlyalpha_clock::BigInt::from(initial);
    let model = NextOpenModel::new(settings, policy.binding(), initial.clone(), cluster)?;
    if rows.len() != raw_signals.len() {
        return Err(err("FINITE_SIGNAL_COUNT"));
    }
    let mut transcript = Transcript {
        facts,
        fact_index: 0,
        execution: array(&economic_result["facts"])?,
        execution_index: 0,
        configuration,
        working: None,
    };
    let mut equity = EquityCursor::new(
        equity_points,
        array(&economic_result["account_equity_timeline"])?,
    )?;
    let binding = json!({"policy":settings,"program":{"scope":{"cluster":cluster},"revision":{"strategy_fingerprint":profile["revision"]}},"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
    let mut pending = Value::Null;
    let mut held = false;
    let mut sample = None;
    let mut close_rows = curve.iter().copied();
    for (input, raw_signal) in rows.iter().zip(raw_signals) {
        let opening = input.opening();
        let start = opening.event_ns();
        let end = input.event_ns();
        if input.source() != first.source()
            || configuration["instruments"][0]["id"] != input.bar().instrument_id().to_string()
            || start < initial
            || end > model.end
        {
            return Err(err("FINITE_INPUT_BINDING"));
        }
        held = verify_opening(&model, policy, &opening, &pending, held, &mut transcript)?;
        if held {
            verify_mark(input, &binding, &mut equity, &mut transcript)?;
        }
        let in_sample = start >= model.start && start < model.end;
        let close = if in_sample {
            signal_at_close(input, raw_signal, held)
        } else {
            json!({"status":"WARMUP"})
        };
        pending = close["signal"].clone();
        if *transcript.next("BAR")?
            != json!({"input_identity":input.identity(),"source_sequence":input.sequence(),"raw_signal":raw_signal,"policy":close})
        {
            return Err(err("FINITE_BAR"));
        }
        if in_sample {
            let prefix = transcript.execution_index;
            let point = equity.at(prefix)?;
            let expected = json!({"bar_start_ns":start.to_string(),"bar_end_ns":end.to_string(),"execution_prefix":prefix,"nav":point["nav"],"high_water_mark":point["high_water_mark"],"drawdown":point["drawdown"],"account_sequence":point["account_sequence"]});
            if close_rows.next() != Some(&expected) {
                return Err(err("FINITE_CLOSE_CURVE"));
            }
            sample = Some((sample.map_or(input, |(first, _)| first), input));
        }
    }
    let signal = if pending.is_null() {
        Value::Null
    } else {
        json!({"status":"CANCELLED","reason":"INPUT_EXHAUSTED","signal":pending})
    };
    if *transcript.next("END")?
        != json!({"schema_version":1,"signal":signal,"cancelled_orders":[],"holdings":"RETAINED_AT_LAST_CLOSE"})
        || transcript.fact_index != facts.len()
        || transcript.execution_index != transcript.execution.len()
        || close_rows.next().is_some()
    {
        return Err(err("FINITE_END"));
    }
    let (first, last) = sample.ok_or_else(|| err("FINITE_SAMPLE_WINDOW"))?;
    verify_baseline(&model, first, last, analytical_baseline)
}

struct Transcript<'a> {
    facts: &'a [&'a Value],
    fact_index: usize,
    execution: &'a [Value],
    execution_index: usize,
    configuration: &'a Value,
    working: Option<onlyalpha_execution::WorkingState>,
}

impl<'a> Transcript<'a> {
    fn next(&mut self, family: &str) -> Result<&'a Value, Error> {
        let row = *self
            .facts
            .get(self.fact_index)
            .ok_or_else(|| err("FINITE_EVENT_MISSING"))?;
        fields(row, &["schema_version", "sequence", "family", "body"])?;
        self.fact_index += 1;
        if row["schema_version"] != 1
            || row["sequence"] != self.fact_index
            || row["family"] != family
        {
            return Err(err("FINITE_EVENT_ORDER"));
        }
        Ok(&row["body"])
    }

    fn execution_prefix(&mut self) -> Result<&mut onlyalpha_execution::WorkingState, Error> {
        if self.working.is_none() {
            self.working = Some(onlyalpha_execution::WorkingState::new(self.configuration.clone())?);
        }
        let working = self.working.as_mut().expect("initialized above");
        let applied = working.sequence() as usize;
        for fact in &self.execution[applied..self.execution_index] {
            working.apply(&fact["input"])?;
        }
        Ok(working)
    }

    fn peek_execution(&self) -> Result<&'a Value, Error> {
        self.execution
            .get(self.execution_index)
            .map(|row| &row["input"])
            .ok_or_else(|| err("FINITE_EXECUTION_MISSING"))
    }

    fn consume_execution(&mut self, expected: &Value) -> Result<(), Error> {
        let body = self.next("EXECUTION")?;
        let fact = self
            .execution
            .get(self.execution_index)
            .ok_or_else(|| err("FINITE_EXECUTION_MISSING"))?;
        self.execution_index += 1;
        if *fact
            != json!({"sequence":self.execution_index,"transaction":format!("ETX-{}",hash(expected)),"input":expected})
            || *body
                != json!({"schema_version":1,"sequence":self.execution_index,"transaction":fact["transaction"],"input":expected})
        {
            return Err(err("FINITE_EXECUTION_RELATION"));
        }
        Ok(())
    }
}

struct EquityCursor<'a> {
    points: &'a [Value],
    timeline: &'a [Value],
    index: usize,
}

impl<'a> EquityCursor<'a> {
    fn new(points: &'a [Value], timeline: &'a [Value]) -> Result<Self, Error> {
        if points.len() != timeline.len()
            || points.first().and_then(|v| v["execution_prefix"].as_u64()) != Some(0)
        {
            return Err(err("FINITE_EQUITY_POINTS"));
        }
        for (index, point) in points.iter().enumerate() {
            fields(
                point,
                &[
                    "execution_prefix",
                    "account_sequence",
                    "nav",
                    "high_water_mark",
                    "drawdown",
                ],
            )?;
            let prefix = point["execution_prefix"]
                .as_u64()
                .ok_or_else(|| err("FINITE_EQUITY_PREFIX"))?;
            if point["account_sequence"] != index
                || !point["nav"].is_string()
                || !point["high_water_mark"].is_string()
                || (!point["drawdown"].is_null() && !point["drawdown"].is_string())
                || (index > 0
                    && points[index - 1]["execution_prefix"]
                        .as_u64()
                        .is_none_or(|p| p > prefix))
            {
                return Err(err("FINITE_EQUITY_POINTS"));
            }
        }
        Ok(Self {
            points,
            timeline,
            index: 0,
        })
    }

    fn at(&mut self, prefix: usize) -> Result<&'a Value, Error> {
        let prefix = prefix as u64;
        while self
            .points
            .get(self.index + 1)
            .and_then(|point| point["execution_prefix"].as_u64())
            .is_some_and(|n| n <= prefix)
        {
            self.index += 1;
        }
        let point = &self.points[self.index];
        if point["execution_prefix"]
            .as_u64()
            .is_none_or(|n| n > prefix)
        {
            return Err(err("FINITE_EQUITY_PREFIX"));
        }
        Ok(point)
    }

    fn account_entry(&self, point: &Value) -> Result<&'a Value, Error> {
        self.timeline
            .get(self.index)
            .filter(|row| row["account_sequence"] == point["account_sequence"])
            .ok_or_else(|| err("FINITE_ACCOUNT_SNAPSHOT"))
    }
}

fn verify_opening(
    model: &NextOpenModel,
    policy: &dyn NextOpenPolicy,
    opening: &OpeningInput,
    pending: &Value,
    held: bool,
    transcript: &mut Transcript<'_>,
) -> Result<bool, Error> {
    if pending.is_null() {
        if *transcript.next("OPEN")? != json!({"status":"NO_PENDING"}) {
            return Err(err("FINITE_OPEN"));
        }
        return Ok(held);
    }
    let (price, ctx) = model.opening_terms(opening, pending)?;
    let cause = text(&ctx["cause"])?;
    let identity = opening.identity();
    let request = model.order_request(opening, pending, cause)?;
    let start = transcript.fact_index;
    let output = transcript.facts[start..]
        .iter()
        .take(5)
        .find(|row| row["family"] != "EXECUTION" && row["family"] == "OPEN")
        .map(|row| &row["body"])
        .ok_or_else(|| err("FINITE_OPEN_MISSING"))?;
    let admission = &output["admission"];
    let mut expected = json!({"schema_version":1,"signal":pending,"opening":opening.record(),"execution_price":price.to_record(),"admission":admission});
    verify_admission(model, &price, &request, &ctx, admission)?;
    let result = match text(&output["status"])? {
        "REJECTED" => {
            let reason = text(&output["reason"])?;
            let at = ctx["time"].as_u64().expect("derived");
            let working = transcript.execution_prefix()?;
            let preview = working.fee_order_preview(&model.cluster, &request, at)?;
            let resolved = policy.admission(&preview, &price, &ctx)?;
            if resolved != *admission {
                return Err(err("FINITE_OPEN_REJECTION"));
            }
            let proved = if resolved["accepted"] == false {
                Some(text(&resolved["reason"])?)
            } else {
                let order = text(&preview["order_id"]["value"])?;
                let payload = model.admit_payload(&request, order, cause, &price, &resolved);
                let command = model.request(working.sequence() + 1, &identity, &ctx, "ADMIT", payload);
                let verdict = working.apply(&command).map(drop);
                model.admission_rejection(verdict, &pending["side"], &resolved, || working.state())?
            };
            if proved != Some(reason) {
                return Err(err("FINITE_OPEN_REJECTION"));
            }
            expected["status"] = json!("REJECTED");
            expected["reason"] = json!(reason);
            held
        }
        "FILLED" if admission["accepted"] == true => {
            let order = text(&output["order"])?;
            let trade = format!("MODEL-TRADE-{cause}");
            let fill = &output["economic_evidence"];
            verify_fill(model, &price, admission, fill)?;
            let payload = model.admit_payload(&request, order, cause, &price, admission);
            let mut fill_context = ctx.clone();
            fill_context["trade"] = json!(trade);
            let fill_payload = model.fill_payload(
                opening,
                &price,
                &fill_context,
                &payload,
                fill,
                transcript.execution_index as u64 + 4,
            )?;
            for (op, payload) in [
                ("ADMIT", payload),
                (
                    "SUBMISSION",
                    json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),
                ),
                (
                    "ACCEPT",
                    json!({"schema_version":1,"order":order,"venue_order":format!("MODEL-ORDER-{cause}")}),
                ),
                ("FILL", fill_payload),
            ] {
                let expected = model.request(
                    transcript.execution_index as u64 + 1,
                    &identity,
                    &ctx,
                    op,
                    payload,
                );
                transcript.consume_execution(&expected)?;
            }
            expected["status"] = json!("FILLED");
            expected["order"] = json!(order);
            expected["trade"] = json!(trade);
            expected["economic_evidence"] = fill.clone();
            pending["side"] == "BUY"
        }
        _ => return Err(err("FINITE_OPEN_STATUS")),
    };
    if *transcript.next("OPEN")? != expected {
        return Err(err("FINITE_OPEN"));
    }
    Ok(result)
}

fn verify_admission(
    model: &NextOpenModel,
    price: &OnlyPrice,
    request: &Value,
    ctx: &Value,
    admission: &Value,
) -> Result<(), Error> {
    let market = &admission["market_provenance"];
    let accepted = admission["accepted"]
        .as_bool()
        .ok_or_else(|| err("FINITE_ADMISSION"))?;
    let verdict = if accepted {
        "MODEL_ACCEPT"
    } else {
        "MODEL_REJECT"
    };
    if admission["schema_version"] != 1
        || market["kind"] != "MODEL_RULE_DECISION"
        || market["verdict"] != verdict
        || market["reference_policy"] != "MODEL_NEXT_OPEN"
        || market["venue_acceptance_proven"] != false
        || market
            .get("reference_price")
            .is_some_and(|value| *value != price.to_record())
        || market
            .get("cause")
            .is_some_and(|value| *value != ctx["cause"])
        || market
            .get("time")
            .is_some_and(|value| *value != ctx["time"])
    {
        return Err(err("FINITE_ADMISSION"));
    }
    if !accepted {
        let reason = text(&admission["reason"])?;
        if market.get("reason").is_some_and(|value| *value != reason) {
            return Err(err("FINITE_ADMISSION"));
        }
        return Ok(());
    }
    model.verify_settlement_policy(admission)?;
    let contract = &admission["contract"];
    fields(contract, &["binding", "estimate", "funding"])?;
    let binding = boundary(OnlyOrderFeePolicyBinding::from_record(&contract["binding"]))?;
    let estimate = boundary(OnlyOrderFeeEstimate::from_record(&contract["estimate"]))?;
    let funding = boundary(OnlyOrderFundingPlan::from_record(&contract["funding"]))?;
    let budget = amount(&admission["fee_budget"])?;
    model.verify_notional(price, &admission["notional"])?;
    if binding.to_record() != contract["binding"]
        || estimate.to_record() != contract["estimate"]
        || funding.to_record() != contract["funding"]
        || budget.is_negative()
        || contract["binding"]["instrument_id"] != request["instrument_id"]
        || contract["binding"]["bound_at"]["unix_nanos"] != ctx["time"]
    {
        return Err(err("FINITE_ADMISSION_CONTRACT"));
    }
    Ok(())
}

fn verify_fill(
    model: &NextOpenModel,
    price: &OnlyPrice,
    admission: &Value,
    fill: &Value,
) -> Result<(), Error> {
    if fill["schema_version"] != 1
        || amount(&fill["charge_target"])?.is_negative()
        || amount(&fill["rebate_target"])?.is_negative()
        || fill["gross_notional"] != admission["notional"]
    {
        return Err(err("FINITE_FILL_EVIDENCE"));
    }
    model.verify_notional(price, &fill["gross_notional"])
}

fn verify_mark(
    input: &MarketInput,
    binding: &Value,
    equity: &mut EquityCursor<'_>,
    transcript: &mut Transcript<'_>,
) -> Result<(), Error> {
    let retained = transcript.peek_execution()?;
    let position = text(&retained["payload"]["position_evidence"])?;
    sha(position)?;
    let index = transcript.execution_index;
    let before = equity.at(index)?;
    let before_index = equity.index;
    let economic_version = &equity.account_entry(before)?["snapshot"]["economic_version"];
    if !economic_version.is_u64() {
        return Err(err("FINITE_VALUATION_VERSION"));
    }
    let n = index + 1;
    let identity = input.identity();
    let bar = input.bar().to_record();
    let ctx = context(&identity, input.event_ns(), &bar["trading_day"])?;
    let time = ctx["time"]
        .as_u64()
        .ok_or_else(|| err("FINITE_VALUATION_TIME"))?;
    let mark = json!({"schema_version":1,"instrument":input.bar().instrument_id().to_string(),"mark":bar["close"]["value"],"source_ref":format!("BAR-{identity}"),"family":"CLOSED_BAR","version":n,"time":time,"as_of_sequence":n});
    let payload = json!({"schema_version":1,"valuation":format!("VALUATION-{identity}"),"version":n,"position_evidence":position,"economic_version":economic_version,"marks":[mark]});
    let expected = bar_request(
        binding,
        input,
        time,
        index,
        BarOperation {
            kind: "VALUATION",
            payload,
            cause: &identity,
        },
        ctx["day_index"].clone(),
    );
    transcript.consume_execution(&expected)?;
    let after = equity.at(n)?;
    let entry = equity.account_entry(after)?;
    let snapshot = &entry["snapshot"];
    if equity.index != before_index + 1
        || after["execution_prefix"] != n
        || entry["source"] != "VALUATION"
        || entry["provenance"]["upstream_cause"] != hash(&expected)
        || snapshot["valuation_version"] != n
        || snapshot["economic_version"] != *economic_version
        || snapshot["position_evidence"] != position
    {
        return Err(err("FINITE_VALUATION_ACCOUNT_RELATION"));
    }
    Ok(())
}

fn verify_baseline(
    model: &NextOpenModel,
    first: &MarketInput,
    last: &MarketInput,
    baseline: &Value,
) -> Result<(), Error> {
    let quote = &baseline["entry_fee_quote"];
    let mut expected = model.retained_baseline(first, last, quote)?;
    if baseline.get("net_pnl").is_some() || baseline.get("return_since_start").is_some() {
        let initial = amount(&expected["initial_equity"])?;
        let final_equity = amount(&expected["final_equity"])?;
        let net = boundary(only_subtract(&final_equity, &initial))?;
        let rate = boundary(only_divide(&net, &initial))?;
        let quantum = boundary("0.00000001".parse())?;
        expected["net_pnl"] = json!(net.to_string());
        expected["return_since_start"] =
            json!(boundary(only_quantize(&rate, &quantum))?.to_string());
    }
    if *baseline != expected {
        return Err(err("FINITE_BASELINE"));
    }
    Ok(())
}

fn array(value: &Value) -> Result<&[Value], Error> {
    value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| err("FINITE_ARRAY"))
}

fn text(value: &Value) -> Result<&str, Error> {
    value
        .as_str()
        .filter(|text| !text.is_empty())
        .ok_or_else(|| err("FINITE_TEXT"))
}

fn amount(value: &Value) -> Result<OnlyDecimal, Error> {
    let text = text(value)?;
    let (significand, exponent) = text.split_once('E').unwrap_or((text, "0"));
    if text.len() > 64
        || significand
            .trim_start_matches('-')
            .bytes()
            .any(|byte| !byte.is_ascii_digit() && byte != b'.')
        || !exponent
            .parse::<i64>()
            .is_ok_and(|n| (-64..64).contains(&n))
    {
        return Err(err("FINITE_AMOUNT"));
    }
    let amount: OnlyDecimal = boundary(text.parse())?;
    if significand != text && amount.to_string() != text {
        return Err(err("FINITE_AMOUNT"));
    }
    Ok(amount)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finite_amount_accepts_exact_fee_records_at_eight_decimal_places() {
        for fixed in ["0.00000000", "0.00000001", "0.00300000"] {
            let value: OnlyDecimal = fixed.parse().unwrap();
            assert_eq!(amount(&json!(value.to_string())).unwrap(), value);
            assert_eq!(amount(&json!(fixed)).unwrap(), value);
        }
        assert_eq!(
            "0.00000000".parse::<OnlyDecimal>().unwrap().to_string(),
            "0E-8"
        );
    }

    #[test]
    fn finite_amount_rejects_noncanonical_or_unbounded_exponents() {
        for text in ["0e-8", "0E-08", "0E-999999999", "1E+999999999", "1_0"] {
            assert!(amount(&json!(text)).is_err(), "{text}");
        }
    }
}
