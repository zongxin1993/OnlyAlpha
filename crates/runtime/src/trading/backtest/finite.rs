use super::{
    Error, ExecutionBinding, Inputs, MarketInput, NextOpenPolicy, OpeningInput, boundary, err,
    fields, hash,
    next_open::{NextOpenModel, context, signal_at_close},
    sha,
    trading::{BarOperation, bar_request},
};
use crate::RunBinding;
use onlyalpha_broker::{
    AppendIntent, Broker, BrokerCommand, Fact, Journal, Operation, Record, Scope,
};
use onlyalpha_broker_virtual::{CompletedMemoryVenue, SourceTrace};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    fee::{OnlyOrderFeeEstimate, OnlyOrderFeePolicyBinding, OnlyOrderFundingPlan},
    numeric::{OnlyDecimal, only_divide, only_quantize, only_subtract},
    value::OnlyPrice,
};
use onlyalpha_execution::{WorkingState, WorkingStep};
use serde_json::{Value, json};

/// 依据冻结行情、策略原始输出、场所原件和经济所有者重放，核验完整回测。
#[allow(clippy::too_many_arguments)]
pub fn verify_finite_backtest(
    inputs: &Inputs,
    execution_binding: &ExecutionBinding,
    policy: &dyn NextOpenPolicy,
    program_record: &Value,
    raw_signals: &[Value],
    signal_receipts: &[Value],
    signal_checkpoint: &Value,
    facts: &[&Value],
    curve: &[&Value],
    economic_result: &Value,
    equity_points: &[Value],
    analytical_baseline: &Value,
    venue: &CompletedMemoryVenue,
    run: &RunBinding,
) -> Result<(), Error> {
    let frozen = execution_binding.record();
    let settings = &frozen["policy_settings"];
    let configuration = &settings["execution"];
    if run.record()["execution"] != execution_binding.fingerprint()
        || run.record()["configuration"] != hash(configuration)
        || run.record()["input_pin"] != inputs.fingerprint()
        || frozen["resolver"] != policy.binding()
        || frozen["configuration"] != *configuration
    {
        return Err(err("FINITE_RUN_BINDING"));
    }
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
    if frozen["initial_ns"] != initial.to_string() || frozen["cluster"] != cluster.as_str() {
        return Err(err("FINITE_RUN_BINDING"));
    }
    let model = NextOpenModel::new(settings, policy.binding(), initial.into(), cluster)?;
    let final_ns = i64::try_from(&model.end).map_err(|_| err("FINITE_END_TIME"))?;
    if rows.len() != raw_signals.len() {
        return Err(err("FINITE_SIGNAL_COUNT"));
    }
    let program = boundary(onlyalpha_strategy::Program::from_record(program_record))?;
    if run.record()["signal_program"] != program.fingerprint()
        || configuration["generation"] != program.generation()
        || configuration["engine"] != program.scope().engine.value()
        || configuration["runtime"] != program.scope().runtime.value()
        || cluster.as_str() != program.scope().cluster.value()
        || profile["revision"] != program.revision().fingerprint()
        || program.revision().universe() != std::slice::from_ref(first.bar().instrument_id())
        || first.source() != program.source()
    {
        return Err(err("FINITE_PROGRAM_BINDING"));
    }
    boundary(program.verify_finite_completion(
        rows.iter().map(MarketInput::bar),
        raw_signals,
        signal_receipts,
        signal_checkpoint,
    ))?;
    let mut transcript = Transcript {
        facts,
        fact_index: 0,
        execution: array(&economic_result["facts"])?,
        execution_index: 0,
        working: WorkingState::for_run(configuration.clone(), run.fingerprint())?,
        venue: VenueCursor::new(venue, text(&frozen["venue"]["source"])?)?,
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
            || start < initial.into()
            || end > model.end
        {
            return Err(err("FINITE_INPUT_BINDING"));
        }
        transcript.venue.market(&json!({"kind":"OPEN","sequence":input.sequence(),"bar_start":opening.record()["time"]["unix_nanos"],"instrument":opening.instrument_id().to_record(),"open":opening.price().to_record()}))?;
        held = verify_opening(&model, policy, &opening, &pending, held, &mut transcript)?;
        transcript.venue.market(&json!({"kind":"BAR_REFERENCE","sequence":input.sequence(),"content":onlyalpha_broker::digest(&input.bar().to_record())}))?;
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
    transcript.venue.finish(final_ns)?;
    let execution_inputs: Vec<_> = transcript
        .execution
        .iter()
        .map(|f| f["input"].clone())
        .collect();
    let replay = transcript
        .working
        .finish(&execution_inputs, run.record(), initial, final_ns)?;
    if replay.result() != economic_result || replay.equity_points() != equity_points {
        return Err(err("FINITE_ECONOMIC_REPLAY"));
    }
    let (first, last) = sample.ok_or_else(|| err("FINITE_SAMPLE_WINDOW"))?;
    verify_baseline(&model, policy, first, last, analytical_baseline)
}

struct Transcript<'a> {
    facts: &'a [&'a Value],
    fact_index: usize,
    execution: &'a [Value],
    execution_index: usize,
    working: WorkingState,
    venue: VenueCursor<'a>,
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

    fn peek_execution(&self) -> Result<&'a Value, Error> {
        self.execution
            .get(self.execution_index)
            .map(|row| &row["input"])
            .ok_or_else(|| err("FINITE_EXECUTION_MISSING"))
    }

    fn consume_execution(&mut self, expected: &Value) -> Result<WorkingStep, Error> {
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
        if let Some(record) = expected.get("broker_record") {
            let fact = boundary(Fact::decode(record))?;
            let observed = boundary(self.venue.broker.observed(fact.identity()))?;
            let evidence = self.working.check_cash_observation(expected, &observed)?;
            self.working.apply_verified(expected, evidence)
        } else {
            self.working.apply(expected)
        }
    }
}

struct CompletedJournal<'a>(&'a [Record]);

impl Journal for CompletedJournal<'_> {
    fn records(&self) -> Result<Vec<Record>, onlyalpha_broker::Error> {
        Ok(self.0.to_vec())
    }

    fn append(&mut self, _: &AppendIntent) -> Result<(), onlyalpha_broker::Error> {
        Err(onlyalpha_broker::Error::new(
            "FINITE_COMPLETED_JOURNAL_READ_ONLY",
        ))
    }
}

/// 两个游标只消费完成场所持有的原件。每个开盘必须在本行收盘前完成派发、观察和确认。
struct VenueCursor<'a> {
    broker: Broker,
    source: std::slice::Iter<'a, SourceTrace>,
    protocol: std::slice::Iter<'a, Record>,
}

impl<'a> VenueCursor<'a> {
    fn new(venue: &'a CompletedMemoryVenue, genesis: &str) -> Result<Self, Error> {
        let trace = venue.source_trace();
        if trace
            .first()
            .is_none_or(|s| s.record()["previous"] != genesis)
            || trace
                .last()
                .is_none_or(|s| s.fingerprint() != venue.source_fingerprint())
        {
            return Err(err("FINITE_VENUE_BINDING"));
        }
        let records = venue.protocol_records();
        let scope = boundary(Scope::decode(&venue.protocol()["scope"]))?;
        let broker = boundary(Broker::recover(scope, &CompletedJournal(records), 65536))?;
        Ok(Self {
            broker,
            source: trace.iter(),
            protocol: records.iter(),
        })
    }

    fn step(&mut self) -> Result<Value, Error> {
        self.source
            .next()
            .map(SourceTrace::record)
            .ok_or_else(|| err("FINITE_SOURCE_MISSING"))
    }

    fn market(&mut self, action: &Value) -> Result<(), Error> {
        let step = self.step()?;
        if step["action"] != *action || !array(&step["born"])?.is_empty() {
            return Err(err("FINITE_SOURCE_MARKET"));
        }
        Ok(())
    }

    fn protocol_record(&mut self, kind: &str) -> Result<Value, Error> {
        let record = self
            .protocol
            .next()
            .ok_or_else(|| err("FINITE_PROTOCOL_MISSING"))?
            .record();
        if record["event"]["kind"] != kind {
            return Err(err("FINITE_PROTOCOL_ORDER"));
        }
        Ok(record)
    }

    fn dispatch(&mut self, admitted: &WorkingStep, client: &Value) -> Result<[Fact; 2], Error> {
        let step = self.step()?;
        let intent = self.protocol_record("INTENT")?;
        let dispatch = self.protocol_record("DISPATCHED")?;
        let result = self.protocol_record("RESULT")?;
        let input = admitted.input();
        let command = boundary(BrokerCommand::decode(&step["action"]["command"]))?;
        let scope = command.scope().record();
        let ready = &intent["event"]["intent"];
        if command.operation() != Operation::Submit
            || step["action"]["kind"] != "COMMAND"
            || step["action"]["ready"] != true
            || step["dispatch"]["record"] != dispatch
            || step["dispatch"]["admitted_at"] != input["time"]
            || step["dispatch"]["outcome"] != "RECEIVED"
            || dispatch["event"]["command_id"] != command.id()
            || result["event"]
                != json!({"kind":"RESULT","command_id":command.id(),"result":"RECEIVED"})
            || ready["command"] != command.record()
            || ready["transaction"] != format!("ETX-{}", hash(input))
            || ready["payload_hash"] != admitted.payload_fingerprint()
            || command.record()["request"] != input["payload"]["request"]
            || input["payload"]["order"] != command.order()
            || client != command.client()
            || [
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
            ]
            .iter()
            .any(|k| scope[*k] != input[*k])
        {
            return Err(err("FINITE_DISPATCH_RELATION"));
        }
        let [accepted, trade] = array(&step["born"])? else {
            return Err(err("FINITE_VENUE_BIRTH"));
        };
        let facts = [
            boundary(Fact::decode(&accepted["fact"]))?,
            boundary(Fact::decode(&trade["fact"]))?,
        ];
        for (fact, kind) in facts.iter().zip(["ACCEPTED", "TRADE"]) {
            let raw = fact.record();
            if raw["kind"] != kind
                || raw["scope"] != scope
                || raw["payload"]["order"] != command.order()
                || raw["ts_event"] != input["time"]
            {
                return Err(err("FINITE_VENUE_BIRTH"));
            }
            let ingress = self.protocol_record("INGRESS")?;
            let observed = self.step()?;
            if ingress["event"]["facts"] != json!([raw])
                || observed["action"]
                    != json!({"kind":"PUBLISHED","identity":fact.identity(),"content":fact.fingerprint()})
                || observed["protocol"]
                    != onlyalpha_broker::digest(&json!([ingress["hash"], Value::Null]))
                || !array(&observed["born"])?.is_empty()
            {
                return Err(err("FINITE_VENUE_OBSERVATION"));
            }
        }
        Ok(facts)
    }

    fn acknowledge(&mut self, original: &Fact, applied: &WorkingStep) -> Result<(), Error> {
        let ack = self.protocol_record("ACK")?;
        verify_receipt(&ack["event"]["receipt"], original, applied)
    }

    fn finish(mut self, end: i64) -> Result<(), Error> {
        self.market(&json!({"kind":"CLOCK","at":end}))?;
        if self.source.next().is_some() || self.protocol.next().is_some() {
            return Err(err("FINITE_VENUE_TRAILING_EVIDENCE"));
        }
        Ok(())
    }
}

fn verify_receipt(receipt: &Value, original: &Fact, applied: &WorkingStep) -> Result<(), Error> {
    if receipt
        != &json!({"scope":original.scope().record(),"identity":original.identity(),"fingerprint":original.fingerprint(),"transaction":format!("ETX-{}",hash(applied.input())),"payload_hash":applied.payload_fingerprint(),"status":"APPLIED"})
    {
        return Err(err("FINITE_APPLICATION_RECEIPT"));
    }
    Ok(())
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
    let at = ctx["time"]
        .as_u64()
        .ok_or_else(|| err("FINITE_OPEN_TIME"))?;
    let preview = transcript
        .working
        .fee_order_preview(&model.cluster, &request, at)?;
    let resolved = policy.admission(&preview, &price, &ctx)?;
    if resolved != *admission {
        return Err(err("FINITE_ADMISSION"));
    }
    let result = match text(&output["status"])? {
        "REJECTED" => {
            let reason = text(&output["reason"])?;
            let working = &mut transcript.working;
            let proved = if resolved["accepted"] == false {
                Some(text(&resolved["reason"])?)
            } else {
                let order = text(&preview["order_id"]["value"])?;
                let payload = model.admit_payload(&request, order, cause, &price, &resolved);
                let command =
                    model.request(working.sequence() + 1, &identity, &ctx, "ADMIT", payload);
                let verdict = working.apply(&command).map(drop);
                model
                    .admission_rejection(verdict, &pending["side"], &resolved, || working.state())?
            };
            if proved != Some(reason) {
                return Err(err("FINITE_OPEN_REJECTION"));
            }
            expected["status"] = json!("REJECTED");
            expected["reason"] = json!(reason);
            held
        }
        "FILLED" if admission["accepted"] == true => {
            let order = text(&preview["order_id"]["value"])?;
            let payload = model.admit_payload(&request, order, cause, &price, admission);
            let admit = model.request(
                transcript.working.sequence() + 1,
                &identity,
                &ctx,
                "ADMIT",
                payload,
            );
            let admitted = transcript.consume_execution(&admit)?;
            let original_order = transcript.working.order(&model.cluster, order)?;
            let [accept, trade] = transcript
                .venue
                .dispatch(&admitted, &original_order["client_order_id"]["value"])?;
            let accepted = accept.record();
            let traded = trade.record();
            let raw_fill = &traded["payload"]["fill"];
            verify_observed_fill(&accepted, raw_fill, &request, opening, &price, &ctx)?;
            let submission = model.request(
                transcript.working.sequence() + 1,
                &identity,
                &ctx,
                "SUBMISSION",
                json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),
            );
            transcript.consume_execution(&submission)?;
            let mut acknowledge = model.request(transcript.working.sequence() + 1, &identity, &ctx, "ACCEPT", json!({"schema_version":1,"order":order,"venue_order":accepted["payload"]["venue"]}));
            acknowledge["broker_record"] = accepted.clone();
            let applied = transcript.consume_execution(&acknowledge)?;
            transcript.venue.acknowledge(&accept, &applied)?;

            let snapshot = transcript.working.order(&model.cluster, order)?;
            let mut fill_context = ctx.clone();
            fill_context["trade"] = raw_fill["trade_id"]["value"].clone();
            let evidence = policy.fill(&snapshot, &price, &model.quantity, &fill_context)?;
            verify_fill(model, &price, admission, &evidence)?;
            let n = transcript.working.sequence() + 1;
            let fill_payload = model.fill_payload(
                opening,
                &price,
                &fill_context,
                &admit["payload"],
                &evidence,
                n,
                raw_fill,
            )?;
            let mut fill = model.request(n, &identity, &ctx, "FILL", fill_payload);
            fill["broker_record"] = traded.clone();
            let applied = transcript.consume_execution(&fill)?;
            transcript.venue.acknowledge(&trade, &applied)?;
            expected["status"] = json!("FILLED");
            expected["order"] = json!(order);
            expected["trade"] = fill_context["trade"].clone();
            expected["economic_evidence"] = evidence;
            expected["venue_facts"] = json!([accepted, traded]);
            pending["side"] == "BUY"
        }
        _ => return Err(err("FINITE_OPEN_STATUS")),
    };
    if *transcript.next("OPEN")? != expected {
        return Err(err("FINITE_OPEN"));
    }
    Ok(result)
}

fn verify_observed_fill(
    accepted: &Value,
    fill: &Value,
    request: &Value,
    opening: &OpeningInput,
    price: &OnlyPrice,
    ctx: &Value,
) -> Result<(), Error> {
    if fill["venue_order_id"]["value"] != accepted["payload"]["venue"]
        || fill["order_id"]["value"] != accepted["payload"]["order"]
        || fill["quantity"] != request["quantity"]
        || fill["price"] != price.to_record()
        || fill["reference_price"] != opening.price().to_record()
        || fill["ts_event"]["unix_nanos"] != ctx["time"]
    {
        return Err(err("FINITE_VENUE_FILL_RELATION"));
    }
    Ok(())
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
    policy: &dyn NextOpenPolicy,
    first: &MarketInput,
    last: &MarketInput,
    baseline: &Value,
) -> Result<(), Error> {
    let (price, ctx) = model.baseline_entry(first)?;
    let quote = policy.analytical_entry_quote(&price, &model.quantity, &ctx)?;
    let mut expected = model.retained_baseline(first, last, &quote)?;
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
#[path = "../../tests/finite_verification.rs"]
mod verification_tests;

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
