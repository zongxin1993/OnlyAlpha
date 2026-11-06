//! Actual native Pipeline/Strategy and canonical Execution with explicit replay profiles.
use crate::{
    Candidate, Error, MarketInput, NextOpenPolicy, OpeningInput, Participants, boundary, err,
    fields, hash,
    next_open::{NativeExecution, NativeReplay},
};
use onlyalpha_calculation_bridge::{StrategyPreparation, Worker};
use onlyalpha_clock::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel, execution::OnlyOrderRequest, numeric::OnlyDecimal, time::OnlyTimestamp,
};
use onlyalpha_market_data::{PipelineInput, construction::OnlyConstructionFact};
use onlyalpha_strategy::NodePort;
use serde_json::{Value, json};
use std::{collections::BTreeSet, sync::Arc, time::Duration};
const DEADLINE: Duration = Duration::from_secs(10);
pub struct Trading<C: NodePort> {
    preparation: StrategyPreparation<C>,
    worker: Option<Worker>,
    native: Option<NativeReplay>,
    settings: Value,
    binding: Value,
    world: Value,
    fees: Value,
    next: usize,
    now: u64,
    effects: Vec<Value>,
}
/// One canonical transport derivation for actual BAR valuation and its original
/// read-only journal consumer. Values confer no execution permission.
struct BarOperation<'a> {
    kind: &'a str,
    payload: Value,
    cause: &'a str,
}
fn bar_request(
    binding: &Value,
    input: &MarketInput,
    now: u64,
    sequence: usize,
    operation: BarOperation<'_>,
    day_index: Value,
) -> Value {
    let BarOperation {
        kind: op,
        payload,
        cause,
    } = operation;
    let config = &binding["policy"]["execution"];
    let program = &binding["program"];
    let n = sequence as u64 + 1;
    let id = format!(
        "REPLAY-{}",
        hash(
            &json!({"market":input.identity(),"cause":cause,"sequence":n,"op":op,"payload":payload,"program":binding})
        )
    );
    json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":"BACKTEST","cluster":program["scope"]["cluster"],"revision":program["revision"]["strategy_fingerprint"],"input_id":id,"source_ref":format!("CAUSE-{}",hash(&json!([input.identity(),cause,n,op]))),"time":now,"runtime_sequence":n,"trading_day":input.bar().to_record()["trading_day"],"day_index":day_index,"op":op,"payload":payload})
}
// Pure quantity predicate over the caller's complete owning Ready view. It
// supplies neither source freshness nor an execution/valuation capability.
fn native_bar_has_exposure(state: &Value) -> Result<bool, Error> {
    let accounts = state["position_accounts"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    let allocations = state["position_allocations"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    if accounts.is_empty() && !allocations.is_empty() {
        return Err(err("POSITION"));
    }
    let mut exposed = false;
    for book in accounts.iter().chain(allocations) {
        let quantity: OnlyDecimal = boundary(
            book["snapshot"]["quantity"]
                .as_str()
                .ok_or_else(|| err("POSITION"))?
                .parse(),
        )?;
        exposed |= !quantity.is_zero();
    }
    Ok(exposed)
}
pub(crate) fn valuation_input(
    binding: &Value,
    input: &MarketInput,
    now: u64,
    c: &impl NativeExecution,
    day_index: Value,
) -> Result<Option<Value>, Error> {
    let state = c.position_order_view()?;
    let positions = state["position_accounts"]
        .as_array()
        .ok_or_else(|| err("POSITION"))?;
    match binding["policy"]["schema_version"].as_u64() {
        Some(1) => {
            // The retained closed-only LIMIT driver keeps its original policy.
            if positions.is_empty() {
                return Ok(None);
            }
        }
        Some(2) => {
            if binding["opening_profile"] != json!({"schema_version":1,"kind":"OPEN_CLOSE_V1"})
                || binding["policy"]["policy"]["kind"] != "NEXT_OPEN_LONG_ONLY_V1"
            {
                return Err(err("TRADING_CONTEXT"));
            }
            // Historical closed books remain in the source. This cash driver
            // requests a further BAR price barrier only for actual exposure.
            // Validate every quantity, including all Allocations, without netting.
            if !native_bar_has_exposure(&state)? {
                return Ok(None);
            }
        }
        _ => return Err(err("TRADING_CONTEXT")),
    }
    let n = c.sequence() as u64 + 1;
    let marks=positions.iter().map(|p|{if p["instrument"]!=input.bar().instrument_id().to_string(){return Err(err("MARK_SOURCE"));}Ok(json!({"schema_version":1,"instrument":p["instrument"],"mark":input.bar().to_record()["close"]["value"],"source_ref":format!("BAR-{}",input.identity()),"family":"CLOSED_BAR","version":n,"time":now,"as_of_sequence":n}))}).collect::<Result<Vec<_>,Error>>()?;
    let payload = json!({"schema_version":1,"valuation":format!("VALUATION-{}",input.identity()),"version":n,"position_evidence":state["position_checkpoint_fingerprint"],"economic_version":state["economic_version"],"marks":marks});
    Ok(Some(bar_request(
        binding,
        input,
        now,
        c.sequence(),
        BarOperation {
            kind: "VALUATION",
            payload,
            cause: &input.identity(),
        },
        day_index,
    )))
}
impl<C: NodePort> Trading<C> {
    pub fn new(
        mut preparation: StrategyPreparation<C>,
        mut worker: Worker,
        mut settings: Value,
        initial_ns: BigInt,
    ) -> Result<Self, Error> {
        fields(
            &settings,
            &[
                "schema_version",
                "execution",
                "instrument",
                "maximum_fill_quantity",
                "requests",
            ],
        )?;
        if settings["schema_version"] != 1 {
            return Err(err("TRADING_CONTEXT"));
        }
        let now = Self::context(&mut preparation, &settings, &initial_ns)?;
        let program = preparation.strategy().program();
        if worker.binding() != (program.generation(), program.artifact()) {
            return Err(err("TRADING_CONTEXT"));
        }
        let e = settings["execution"].clone();
        let cluster = program.scope().cluster.value();
        let revision = program.revision().fingerprint();
        let pipeline = preparation.pipeline_program().to_record();
        let sources = &pipeline["sources"];
        let candidate = Candidate::new(e.clone(), vec![])?;
        let mut request_ids = BTreeSet::new();
        for v in settings["requests"]
            .as_array()
            .filter(|v| v.len() <= 16)
            .ok_or_else(|| err("POLICY_BOUND"))?
        {
            candidate.fee_order_preview(cluster, v, now)?;
            let request = boundary(OnlyOrderRequest::from_record(v))?;
            if !request_ids.insert(request.request_id().to_string())
                || request.instrument_id() != &program.revision().universe()[0]
            {
                return Err(err("POLICY_REQUEST_IDENTITY"));
            }
        }
        settings["calendar"] = sources[0]["calendar"].clone();
        let world=boundary(worker.exchange_replay(json!({"schema_version":1,"configuration":settings,"checkpoint":null,"operation":"INIT","payload":{},"now":now}),DEADLINE))?;
        world_proof(&world)?;
        let binding = json!({"schema_version":1,"configuration":hash(&e),"generation":program.generation(),"initial_ns":initial_ns.to_string(),"strategies":{cluster:revision},"sources":[program.source()],"program":program.to_record(),"pipeline":pipeline,"policy":settings});
        Ok(Self {
            preparation,
            worker: Some(worker),
            native: None,
            settings,
            binding,
            world,
            fees: json!({}),
            next: 0,
            now,
            effects: vec![],
        })
    }
    fn context(
        preparation: &mut StrategyPreparation<C>,
        settings: &Value,
        initial_ns: &BigInt,
    ) -> Result<u64, Error> {
        boundary(preparation.capture_checkpoint())?;
        let program = preparation.strategy().program();
        let e = settings["execution"].clone();
        let instrument = boundary(onlyalpha_domain::instrument::OnlyInstrument::from_record(
            &settings["instrument"],
        ))?
        .to_record();

        let cluster = program.scope().cluster.value();
        let revision = program.revision().fingerprint();
        let pipeline = preparation.pipeline_program().to_record();
        let sources = &pipeline["sources"];
        if e["runtime_kind"] != "BACKTEST"
            || e["engine"] != program.scope().engine.value()
            || e["runtime"] != program.scope().runtime.value()
            || e["generation"] != program.generation()
            || e["profiles"].as_object().is_none_or(|m| m.len() != 1)
            || e["profiles"][cluster]["revision"] != revision
            || e["instruments"].as_array().is_none_or(|v| v.len() != 1)
            || program.revision().universe().len() != 1
            || e["instruments"][0]["id"] != program.revision().universe()[0].to_string()
            || sources.as_array().is_none_or(|s| s.len() != 1)
        {
            return Err(err("TRADING_CONTEXT"));
        }
        if instrument != settings["instrument"]
            || instrument["instrument_id"] != program.revision().universe()[0].to_record()
            || instrument["price_precision"] != e["instruments"][0]["price_precision"]
            || instrument["quantity_precision"] != e["instruments"][0]["quantity_precision"]
            || instrument["settlement_currency"] != e["currency"]
            || instrument["contract_multiplier"]["value"] != e["instruments"][0]["multiplier"]
            || instrument["market_type"] != "CASH"
        {
            return Err(err("TRADING_INSTRUMENT_CONTEXT"));
        }
        let now = boundary(initial_ns.to_string().parse::<u64>())?;
        Ok(now)
    }
    /// Explicit native model profile; it never invokes the external Replay worker.
    pub fn next_open(
        mut preparation: StrategyPreparation<C>,
        mut settings: Value,
        resolver: Box<dyn NextOpenPolicy>,
        initial_ns: BigInt,
    ) -> Result<Self, Error> {
        fields(
            &settings,
            &["schema_version", "execution", "instrument", "policy"],
        )?;
        if settings["schema_version"] != 2 {
            return Err(err("TRADING_CONTEXT"));
        }
        let now = Self::context(&mut preparation, &settings, &initial_ns)?;
        let pipeline = preparation.pipeline_program().to_record();
        settings["calendar"] = pipeline["sources"][0]["calendar"].clone();
        let program = preparation.strategy().program();
        let cluster = program.scope().cluster.value();
        let revision = program.revision().fingerprint();
        let native = NativeReplay::new(&settings, resolver, initial_ns.clone(), cluster)?;
        let binding = json!({"schema_version":1,"configuration":hash(&settings["execution"]),"generation":program.generation(),"initial_ns":initial_ns.to_string(),"strategies":{cluster:revision},"sources":[program.source()],"program":program.to_record(),"pipeline":pipeline,"policy":settings,"native_policy":native.binding(),"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
        Ok(Self {
            preparation,
            worker: None,
            native: Some(native),
            settings,
            binding,
            world: Value::Null,
            fees: json!({}),
            next: 0,
            now,
            effects: vec![],
        })
    }
    fn exchange(&mut self, operation: &str, payload: Value) -> Result<Value, Error> {
        let value=self.worker.as_mut().ok_or_else(||err("EXTERNAL_PROFILE_REQUIRED"))?.exchange_replay(json!({"schema_version":1,"configuration":self.settings,"checkpoint":self.world["checkpoint"],"operation":operation,"payload":payload,"now":self.now}),DEADLINE).map_err(|error|err(&format!("EXTERNAL_{operation}_{error}")))?;
        if matches!(operation, "INIT" | "VALIDATE" | "BAR" | "SUBMIT") {
            world_proof(&value)?;
        }
        Ok(value)
    }
    fn request(
        &self,
        c: &Candidate,
        input: &MarketInput,
        op: &str,
        payload: Value,
        cause: &str,
    ) -> Result<Value, Error> {
        let day_index = if self.native.is_some() {
            crate::next_open::context(
                cause,
                input.event_ns(),
                &input.bar().to_record()["trading_day"],
            )?["day_index"]
                .clone()
        } else {
            self.world["day_index"].clone()
        };
        Ok(bar_request(
            &self.binding,
            input,
            self.now,
            c.records().len(),
            BarOperation {
                kind: op,
                payload,
                cause,
            },
            day_index,
        ))
    }

    fn apply_updates(
        &mut self,
        c: &mut Candidate,
        input: &MarketInput,
        cause: &str,
    ) -> Result<(), Error> {
        let updates = self.world["updates"]
            .as_array()
            .ok_or_else(|| err("BROKER_UPDATES"))?
            .clone();
        let cluster = self
            .preparation
            .strategy()
            .program()
            .scope()
            .cluster
            .value()
            .to_owned();
        for row in updates {
            let update = &row["update"];
            let order = update["order_id"]["value"]
                .as_str()
                .ok_or_else(|| err("BROKER_ORDER"))?;
            let config = c.configuration().clone();
            if update["runtime_id"]["value"] != config["runtime"]
                || update["account_id"]["value"] != config["account"]
                || update["gateway_id"]["value"] != config["gateway"]
                || update["ts_event"]["unix_nanos"] != self.now
            {
                return Err(err("BROKER_CONTEXT"));
            }
            let (op, payload) = match row["kind"].as_str().ok_or_else(|| err("BROKER_FAMILY"))? {
                "ACCEPT" => (
                    "ACCEPT",
                    json!({"schema_version":1,"order":order,"venue_order":update["venue_order_id"]["value"]}),
                ),
                "CANCELLED" | "REJECTED" | "EXPIRED" => (
                    "TERMINAL",
                    json!({"schema_version":1,"order":order,"outcome":row["kind"],"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
                ),
                "FILL" => {
                    let snapshot = c.order(&cluster, order)?;
                    let fill = &update["fill"];
                    if fill["order_id"]["value"] != order {
                        return Err(err("FILL_RELATION"));
                    }
                    let evidence = self.exchange(
                        "FEE",
                        json!({"order":snapshot,"fill":fill,"accrual":self.fees[order]}),
                    )?;
                    let trade = fill["trade_id"]["value"]
                        .as_str()
                        .ok_or_else(|| err("TRADE"))?;
                    let n = c.records().len() as u64 + 1;
                    let scope = json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":"BACKTEST","cluster":cluster,"revision":self.preparation.strategy().program().revision().fingerprint(),"instrument":input.bar().instrument_id().to_string(),"request":snapshot["request_id"]["value"]});
                    let reference = hash(&json!([input.identity(), row, evidence]));
                    let reference = format!("PLUGIN-{reference}");
                    let mut fee = json!({"schema_version":1,"instruction":format!("FEE-{reference}"),"source_ref":format!("FEE-{reference}"),"policy":snapshot["fee_policy_binding"]["fingerprint"],"order":order,"trade":trade,"currency":config["currency"],"charge_target":evidence["charge_target"],"rebate_target":evidence["rebate_target"]});
                    let mut settlement = json!({"schema_version":1,"instruction":format!("SET-{reference}"),"source_ref":format!("SET-{reference}"),"order":order,"trade":trade,"currency":config["currency"],"model":"CASH_SETTLEMENT","calendar":self.settings["calendar"],"policy":evidence["settlement_policy"],"gross_notional":evidence["gross_notional"],"rounding":"HALF_EVEN"});
                    let mut valuation = json!({"schema_version":1,"source_ref":format!("VAL-{reference}"),"currency":config["currency"],"mark":fill["price"]["value"]});
                    for (proof, family) in [
                        (&mut fee, "ORDER_FEE_ACCRUAL"),
                        (&mut settlement, "SETTLEMENT"),
                        (&mut valuation, "VALUATION"),
                    ] {
                        proof["scope"] = scope.clone();
                        proof["family"] = json!(family);
                        proof["version"] = json!(n);
                        proof["as_of_sequence"] = json!(n);
                        proof["source_digest"] = json!(hash(proof));
                    }
                    self.effects.push(json!({"fill":fill,"fee":evidence}));
                    self.fees[order] = evidence["accrual"].clone();
                    (
                        "FILL",
                        json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":fill["venue_trade_id"]["value"],"venue_order":fill["venue_order_id"]["value"],"quantity":fill["quantity"]["value"],"price":fill["price"]["value"],"fees":fee,"settlement":settlement,"valuation":valuation,"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
                    )
                }
                _ => return Err(err("BROKER_FAMILY")),
            };
            let normalized = self.request(c, input, op, payload, &hash(&json!([cause, row])))?;
            c.apply(&normalized)?;
        }
        Ok(())
    }
    fn validate_native_cut(&self) -> Result<(), Error> {
        if let Some(native) = &self.native {
            let strategy = self.preparation.strategy();
            let program = strategy.program();
            let outcome = strategy
                .last_outcome(&program.revision().universe()[0])
                .map(|o| o.to_record());
            native.validate_cut(program.source(), outcome.as_ref())?;
        }
        Ok(())
    }
    fn valuation(&self, c: &mut Candidate, input: &MarketInput) -> Result<(), Error> {
        let day_index = if self.native.is_some() {
            crate::next_open::context(
                &input.identity(),
                input.event_ns(),
                &input.bar().to_record()["trading_day"],
            )?["day_index"]
                .clone()
        } else {
            self.world["day_index"].clone()
        };
        if let Some(command) = valuation_input(&self.binding, input, self.now, c, day_index)? {
            c.apply(&command)?;
        }
        Ok(())
    }
}
impl<C: NodePort> Participants for Trading<C> {
    fn binding(&self) -> Value {
        self.binding.clone()
    }
    fn capture(&mut self) -> Result<Value, Error> {
        self.validate_native_cut()?;
        if let Some(native) = &self.native {
            return Ok(
                json!({"schema_version":2,"binding":hash(&self.binding),"preparation":boundary(self.preparation.capture_checkpoint())?,"native":native.capture(),"now":self.now}),
            );
        }
        Ok(
            json!({"schema_version":1,"binding":hash(&self.binding),"preparation":boundary(self.preparation.capture_checkpoint())?,"world":self.world,"fees":self.fees,"next":self.next,"now":self.now}),
        )
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        if let Some(native) = &mut self.native {
            fields(
                v,
                &["schema_version", "binding", "preparation", "native", "now"],
            )?;
            if v["schema_version"] != 2 || v["binding"] != hash(&self.binding) {
                return Err(err("TRADING_CHECKPOINT"));
            }
            let now = v["now"].as_u64().ok_or_else(|| err("NOW"))?;
            native.restore(&v["native"])?;
            boundary(self.preparation.restore_checkpoint(
                v["preparation"].to_string().as_bytes(),
                &hash(&v["preparation"]),
            ))?;
            self.now = now;
            self.validate_native_cut()?;
            return Ok(());
        }
        fields(
            v,
            &[
                "schema_version",
                "binding",
                "preparation",
                "world",
                "fees",
                "next",
                "now",
            ],
        )?;
        if v["schema_version"] != 1
            || v["binding"] != hash(&self.binding)
            || v["next"].as_u64().is_none_or(|n| {
                n > self.settings["requests"]
                    .as_array()
                    .expect("requests")
                    .len() as u64
            })
        {
            return Err(err("TRADING_CHECKPOINT"));
        }
        boundary(self.preparation.restore_checkpoint(
            v["preparation"].to_string().as_bytes(),
            &hash(&v["preparation"]),
        ))?;
        self.world = v["world"].clone();
        self.now = v["now"].as_u64().ok_or_else(|| err("NOW"))?;
        let checked = self.exchange("VALIDATE", json!({}))?;
        if checked["checkpoint"] != self.world["checkpoint"]
            || checked["open_orders"] != self.world["open_orders"]
            || checked["pending"] != self.world["pending"]
        {
            return Err(err("BROKER_CHECKPOINT"));
        }
        self.fees = v["fees"].clone();
        self.next = usize::try_from(v["next"].as_u64().ok_or_else(|| err("NEXT"))?)
            .map_err(|_| err("BOUND"))?;
        Ok(())
    }
    fn process(&mut self, input: &MarketInput, c: &mut Candidate) -> Result<Value, Error> {
        self.validate_execution(c)?;
        self.effects.clear();
        if input.source() != self.preparation.strategy().program().source() {
            return Err(err("SOURCE_BINDING"));
        }
        self.now = boundary(input.event_ns().to_string().parse())?;
        if self.native.is_none() {
            self.world = self.exchange("BAR", json!({"bar":input.bar().to_record()}))?;
            self.apply_updates(c, input, &input.identity())?;
        }
        self.valuation(c, input)?;
        let pipeline = PipelineInput {
            source: input.source().into(),
            sequence: input.sequence(),
            fact: OnlyConstructionFact::Bar(Arc::new(input.bar().clone())),
            logical_init: OnlyTimestamp::from_datetime(*input.bar().ts_init()),
            quality: vec![],
        };
        let processing = boundary(self.preparation.process(&pipeline))?;
        if let Some(native) = &mut self.native {
            let policy = native.closed(input, &processing, c)?;
            self.validate_execution(c)?;
            return Ok(json!({"schema_version":2,"preparation":processing,"policy":policy}));
        }
        let mut policy = Value::Null;
        if let Some(request) = self.settings["requests"]
            .as_array()
            .expect("requests")
            .get(self.next)
            .cloned()
        {
            let decisions = processing["decisions"]
                .as_array()
                .ok_or_else(|| err("DECISIONS"))?;
            if decisions.len() > 1 {
                return Err(err("DECISION_BOUND"));
            }
            if let Some(outcome) = decisions.first() {
                let d = &outcome["decision"];
                let signal = if request["side"] == "BUY" {
                    "entry"
                } else {
                    "exit"
                };
                if d["eligibility"] == true
                    && d[signal] == true
                    && self.world["open_orders"]
                        .as_array()
                        .is_some_and(Vec::is_empty)
                {
                    let cluster = self
                        .preparation
                        .strategy()
                        .program()
                        .scope()
                        .cluster
                        .value()
                        .to_owned();
                    let preview = c.fee_order_preview(&cluster, &request, self.now)?;
                    let admission =
                        self.exchange("ADMISSION", json!({"order":preview,"state":c.state()?}))?;
                    if admission["schema_version"] != 1 || !admission["accepted"].is_boolean() {
                        return Err(err("ADMISSION_PROOF"));
                    }
                    policy = json!({"request":request,"decision":hash(d),"admission":admission});
                    if admission["accepted"] == true {
                        let order = preview["order_id"]["value"]
                            .as_str()
                            .ok_or_else(|| err("ORDER"))?
                            .to_owned();
                        let payload = json!({"schema_version":1,"request":request,"fee_contract":admission["contract"],"fee_budget":admission["fee_budget"],"market":{"schema_version":1,"verdict":"ACCEPT","source_ref":format!("MARKET-{}",hash(&json!([input.identity(),d,admission]))),"request_digest":hash(&request),"notional":admission["notional"],"rounding":"HALF_EVEN"},"order":order,"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}});
                        let normalized = self.request(c, input, "ADMIT", payload, &hash(d))?;
                        match c.apply(&normalized) {
                            Ok(()) => {
                                self.next += 1;
                                let snapshot = c.order(&cluster, &order)?;
                                let ready = c
                                    .records()
                                    .last()
                                    .ok_or_else(|| err("ADMIT_RECORD"))?
                                    .prepared()
                                    .record();
                                let broker = json!({"schema_version":2,"gateway_request_id":{"schema_version":1,"value":format!("SUBMIT-{}",hash(&normalized))},"order_id":snapshot["order_id"],"client_order_id":snapshot["client_order_id"],"account_id":snapshot["account_id"],"instrument_id":snapshot["instrument_id"],"side":snapshot["side"],"offset":snapshot["offset"],"order_type":snapshot["order_type"],"time_in_force":snapshot["time_in_force"],"quantity":snapshot["quantity"],"price":snapshot["price"],"submitted_at":{"schema_version":1,"unix_nanos":self.now},"runtime_intent_transaction_id":ready["transaction_id"],"runtime_intent_authority_hash":hash(&ready),"execution_intent":snapshot["execution_intent"]});
                                self.world = self.exchange("SUBMIT", json!({"request":broker}))?;
                                c.apply(&self.request(c,input,"SUBMISSION",json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),&hash(d))?)?;
                                self.apply_updates(c, input, &hash(d))?;
                            }
                            Err(e) if e.0 == "EXECUTION_ACCOUNT_CAPACITY_DENIED" => {
                                policy["admission_rejection"] = json!("ACCOUNT_JOURNAL_BOUND");
                            }
                            Err(e) if e.0 == "EXECUTION_RISK_DENIED" => {
                                policy["risk_denied"] = json!(true);
                            }
                            Err(e) => return Err(e),
                        }
                    }
                }
            }
        }
        Ok(
            json!({"schema_version":1,"preparation":processing,"policy":policy,"broker":self.world,"economic_evidence":self.effects}),
        )
    }
    fn validate_initial(&self, c: &Candidate) -> Result<(), Error> {
        self.validate_execution(c)?;
        if let Some(native) = &self.native {
            let strategy = self.preparation.strategy();
            let instrument = &strategy.program().revision().universe()[0];
            if !native.is_genesis() || strategy.last_outcome(instrument).is_some() {
                return Err(err("NATIVE_INITIAL_GENESIS_REQUIRED"));
            }
        }
        Ok(())
    }
    fn validate_execution(&self, c: &Candidate) -> Result<(), Error> {
        self.validate_native_cut()?;
        if let Some(native) = &self.native {
            native.validate_execution(c)?;
        }
        Ok(())
    }
    fn opening_phase(&self) -> bool {
        self.native.is_some()
    }
    fn opening(&mut self, input: &OpeningInput, c: &mut Candidate) -> Result<Value, Error> {
        self.validate_execution(c)?;
        let program = self.preparation.strategy().program();
        if input.source() != program.source()
            || input.instrument_id() != &program.revision().universe()[0]
        {
            return Err(err("SOURCE_BINDING"));
        }
        self.now = boundary(input.event_ns().to_string().parse())?;
        self.native
            .as_mut()
            .ok_or_else(|| err("OPENING_PROFILE_REQUIRED"))?
            .opening(input, c)
    }
    fn end_input(&mut self, c: &mut Candidate) -> Result<Value, Error> {
        self.validate_execution(c)?;
        self.native
            .as_mut()
            .ok_or_else(|| err("OPENING_PROFILE_REQUIRED"))?
            .end_input(c)
    }
    fn cancel_input(&mut self, c: &mut Candidate) -> Result<Value, Error> {
        self.validate_execution(c)?;
        self.native
            .as_mut()
            .ok_or_else(|| err("OPENING_PROFILE_REQUIRED"))?
            .cancel_input(c)
    }
    fn quiescent(&self) -> Result<bool, Error> {
        if let Some(native) = &self.native {
            return native.quiescent();
        }
        let pending = self.world["pending"]
            .as_u64()
            .ok_or_else(|| err("BROKER_PENDING_PROOF"))?;
        let orders = self.world["open_orders"]
            .as_array()
            .ok_or_else(|| err("BROKER_OPEN_PROOF"))?;
        Ok(pending == 0 && orders.is_empty())
    }
}

fn world_proof(value: &Value) -> Result<(), Error> {
    fields(
        value,
        &[
            "schema_version",
            "checkpoint",
            "updates",
            "open_orders",
            "pending",
            "trading_day",
            "day_index",
        ],
    )?;
    if value["schema_version"] != 1
        || !value["checkpoint"].is_object()
        || value["updates"].as_array().is_none_or(|v| v.len() > 64)
        || value["open_orders"].as_array().is_none_or(|v| v.len() > 16)
        || value["pending"].as_u64().is_none()
    {
        return Err(err("BROKER_WORLD_PROOF"));
    }
    Ok(())
}

#[cfg(test)]
mod native_bar_valuation_tests {
    use super::*;
    fn book(quantity: Value) -> Value {
        json!({"snapshot":{"quantity":quantity}})
    }
    #[test]
    fn flat_means_every_complete_account_and_allocation_is_individually_zero() {
        let view = |accounts: Value, allocations: Value| json!({"position_accounts":accounts,"position_allocations":allocations});
        assert!(!native_bar_has_exposure(&view(json!([]), json!([]))).unwrap());
        assert!(
            !native_bar_has_exposure(&view(
                json!([book(json!("0"))]),
                json!([book(json!("0.00"))])
            ))
            .unwrap()
        );
        assert!(
            native_bar_has_exposure(&view(
                json!([book(json!("0"))]),
                json!([book(json!("1")), book(json!("-1"))])
            ))
            .unwrap(),
            "consolidated zero cannot hide offsetting Allocation exposure"
        );
        assert!(
            native_bar_has_exposure(&view(json!([book(json!("1"))]), json!([book(json!("0"))])))
                .unwrap()
        );
        assert!(native_bar_has_exposure(&view(json!([book(json!("-1"))]), json!([]))).unwrap());
        assert!(native_bar_has_exposure(&view(json!([]), json!([book(json!("1"))]))).is_err());
        for malformed in [
            Value::Null,
            json!(0),
            json!("NaN"),
            json!("invalid"),
            json!({}),
        ] {
            for state in [
                view(json!([book(malformed.clone())]), json!([])),
                view(json!([book(json!("0"))]), json!([book(malformed.clone())])),
                view(json!([book(json!("1")), book(malformed)]), json!([])),
            ] {
                assert!(
                    native_bar_has_exposure(&state).is_err(),
                    "incomplete quantity proof became a flat/nonflat verdict"
                );
            }
        }
        for malformed in [
            json!({}),
            json!({"position_accounts":[]}),
            json!({"position_accounts":[],"position_allocations":null}),
        ] {
            assert!(native_bar_has_exposure(&malformed).is_err());
        }
    }
}
