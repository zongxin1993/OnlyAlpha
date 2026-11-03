//! A declared deterministic whole-fill model. Strategy and economic state remain with their owners.
use crate::{Candidate, Error, MarketInput, OpeningInput, boundary, err, fields, hash};
use onlyalpha_clock::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::OnlyOrderRequest,
    numeric::{OnlyDecimal, only_add, only_multiply},
    time::OnlyTradingDay,
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};

/// Pure, exactly bound model-rule and Fee-owner adapter. It grants no venue or LIVE authority.
/// Implementations must derive their outputs from these explicit inputs and immutable binding.
pub trait NextOpenPolicy {
    fn binding(&self) -> Value;
    fn admission(
        &self,
        order: &Value,
        reference: &OnlyPrice,
        context: &Value,
    ) -> Result<Value, Error>;
    fn fill(
        &self,
        order: &Value,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error>;
}

/// Both consumers use the same native algorithm. The read-only consumer only
/// compares original Ready inputs and reads their retained owning projections.
pub(crate) trait NativeExecution {
    fn configuration(&self) -> &Value;
    fn state(&self) -> Result<Value, Error>;
    fn position_order_view(&self) -> Result<Value, Error>;
    fn checkpoint(&self) -> Result<Value, Error>;
    fn sequence(&self) -> usize;
    fn order(&self, cluster: &str, order: &str) -> Result<Value, Error>;
    fn fee_order_preview(&self, cluster: &str, request: &Value, at: u64) -> Result<Value, Error>;
    fn apply(&mut self, input: &Value) -> Result<(), Error>;
}
impl NativeExecution for Candidate {
    fn configuration(&self) -> &Value {
        self.configuration()
    }
    fn state(&self) -> Result<Value, Error> {
        self.state()
    }
    fn position_order_view(&self) -> Result<Value, Error> {
        self.position_order_view()
    }
    fn checkpoint(&self) -> Result<Value, Error> {
        self.checkpoint()
    }
    fn sequence(&self) -> usize {
        self.records().len()
    }
    fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        self.order(cluster, order)
    }
    fn fee_order_preview(&self, cluster: &str, request: &Value, at: u64) -> Result<Value, Error> {
        self.fee_order_preview(cluster, request, at)
    }
    fn apply(&mut self, input: &Value) -> Result<(), Error> {
        self.apply(input)
    }
}

pub(crate) struct NativeReplay {
    configuration: Value,
    policy_settings: Value,
    calendar: Value,
    cluster: String,
    revision: Value,
    binding: Value,
    resolver: Box<dyn NextOpenPolicy>,
    pending: Value,
    last: Value,
    finished: bool,
    start: BigInt,
    end: BigInt,
    quantity: OnlyQuantity,
    buy_multiplier: OnlyDecimal,
    sell_multiplier: OnlyDecimal,
}
fn decimal(v: &Value) -> Result<OnlyDecimal, Error> {
    let text = v
        .as_str()
        .filter(|s| {
            !s.is_empty() && s.len() <= 36 && s.bytes().all(|c| c.is_ascii_digit() || c == b'.')
        })
        .ok_or_else(|| err("POLICY_DECIMAL"))?;
    let value: OnlyDecimal = boundary(text.parse())?;
    if value.fractional_precision() > 18 || value.is_negative() {
        return Err(err("POLICY_DECIMAL"));
    }
    Ok(value)
}
fn instant(v: &Value) -> Result<BigInt, Error> {
    let s = v
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 32)
        .ok_or_else(|| err("POLICY_TIME"))?;
    let n: BigInt = boundary(s.parse())?;
    if n.to_string() != s || n < BigInt::from(0) {
        return Err(err("POLICY_TIME"));
    }
    Ok(n)
}
pub(crate) fn context(identity: &str, time: BigInt, day: &Value) -> Result<Value, Error> {
    let d = boundary(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":day}),
    ))?
    .value();
    let origin = boundary(OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":"0001-01-01"}),
    ))?
    .value();
    let ordinal =
        u64::try_from(boundary(d.since(origin))?.get_days()).map_err(|_| err("TRADING_DAY"))? + 1;
    let nanos = boundary(time.to_string().parse::<u64>())?;
    Ok(
        json!({"schema_version":1,"time":nanos,"day_index":ordinal,"trading_day":day,"cause":identity}),
    )
}
impl NativeReplay {
    pub(crate) fn new(
        settings: &Value,
        resolver: Box<dyn NextOpenPolicy>,
        initial_ns: BigInt,
        cluster: &str,
    ) -> Result<Self, Error> {
        let p = &settings["policy"];
        fields(
            p,
            &[
                "schema_version",
                "kind",
                "quantity",
                "buy_multiplier",
                "sell_multiplier",
                "start_ns",
                "end_ns",
            ],
        )?;
        let configuration = settings["execution"].clone();
        let revision = configuration["profiles"][cluster]["revision"].clone();
        let binding = resolver.binding();
        if p["schema_version"] != 1
            || p["kind"] != "NEXT_OPEN_LONG_ONLY_V1"
            || configuration["runtime_kind"] != "BACKTEST"
            || revision.is_null()
            || binding["schema_version"] != 1
            || binding["configuration"] != hash(&configuration)
            || binding["reference_policy"] != "MODEL_NEXT_OPEN"
            || binding["kind"].as_str().is_none_or(str::is_empty)
        {
            return Err(err("NEXT_OPEN_BINDING"));
        }
        let quantity = boundary(OnlyQuantity::from_record(&p["quantity"]))?;
        if quantity.to_record() != p["quantity"]
            || quantity.value().is_zero()
            || json!(quantity.precision()) != configuration["instruments"][0]["quantity_precision"]
        {
            return Err(err("NEXT_OPEN_QUANTITY"));
        }
        let one: OnlyDecimal = boundary("1".parse())?;
        let buy_multiplier = decimal(&p["buy_multiplier"])?;
        let sell_multiplier = decimal(&p["sell_multiplier"])?;
        if buy_multiplier < one || sell_multiplier > one || sell_multiplier.is_zero() {
            return Err(err("NEXT_OPEN_SLIPPAGE"));
        }
        let start = instant(&p["start_ns"])?;
        let end = instant(&p["end_ns"])?;
        if start < initial_ns || end <= start {
            return Err(err("NEXT_OPEN_WINDOW"));
        }
        Ok(Self {
            configuration,
            policy_settings: p.clone(),
            calendar: settings["calendar"].clone(),
            cluster: cluster.into(),
            revision,
            binding,
            resolver,
            pending: Value::Null,
            last: Value::Null,
            finished: false,
            start,
            end,
            quantity,
            buy_multiplier,
            sell_multiplier,
        })
    }
    fn execution_model(&self) -> Value {
        // The native driver emits exactly one full-quantity FILL per admitted
        // model Order. Canonical Execution/Settlement independently enforce it.
        json!({"schema_version":1,"kind":"GUARANTEED_WHOLE_FILL","runtime_kind":"BACKTEST","maximum_fill_count":1,"configuration_fingerprint":hash(&self.configuration),"policy_fingerprint":hash(&self.binding)})
    }
    pub(crate) fn binding(&self) -> Value {
        let mut value = self.binding.clone();
        value["execution_model"] = self.execution_model();
        value
    }
    pub(crate) fn capture(&self) -> Value {
        json!({"schema_version":2,"binding":hash(&json!([self.binding,self.policy_settings])),"execution_model":self.execution_model(),"pending":self.pending,"last":self.last,"finished":self.finished})
    }
    /// Read-only validation of this owner's retained checkpoint profile. No
    /// resolver, SDK factory, admission or Fill operation is invoked.
    pub(crate) fn read_quiescent(
        settings: &Value,
        native_policy: &Value,
        checkpoint: &Value,
    ) -> Result<bool, Error> {
        fields(
            checkpoint,
            &[
                "schema_version",
                "binding",
                "execution_model",
                "pending",
                "last",
                "finished",
            ],
        )?;
        let mut binding = native_policy.clone();
        let model = binding
            .as_object_mut()
            .ok_or_else(|| err("NEXT_OPEN_BINDING"))?
            .remove("execution_model")
            .ok_or_else(|| err("NEXT_OPEN_BINDING"))?;
        let expected = json!({"schema_version":1,"kind":"GUARANTEED_WHOLE_FILL","runtime_kind":"BACKTEST","maximum_fill_count":1,"configuration_fingerprint":hash(&settings["execution"]),"policy_fingerprint":hash(&binding)});
        if checkpoint["schema_version"] != 2
            || model != expected
            || checkpoint["execution_model"] != model
            || binding["schema_version"] != 1
            || binding["configuration"] != hash(&settings["execution"])
            || binding["reference_policy"] != "MODEL_NEXT_OPEN"
            || checkpoint["binding"] != hash(&json!([binding, settings["policy"]]))
            || !checkpoint["finished"].is_boolean()
            || (!checkpoint["pending"].is_null() && !checkpoint["pending"].is_object())
            || (!checkpoint["last"].is_null() && !checkpoint["last"].is_object())
            || (checkpoint["finished"] == true && !checkpoint["pending"].is_null())
        {
            return Err(err("NEXT_OPEN_CHECKPOINT"));
        }
        Ok(checkpoint["finished"] == true && checkpoint["pending"].is_null())
    }
    pub(crate) fn restore(&mut self, v: &Value) -> Result<(), Error> {
        fields(
            v,
            &[
                "schema_version",
                "binding",
                "execution_model",
                "pending",
                "last",
                "finished",
            ],
        )?;
        if v["schema_version"] != 2
            || v["execution_model"] != self.execution_model()
            || v["binding"] != self.capture()["binding"]
            || !v["finished"].is_boolean()
            || (!v["pending"].is_null() && !v["pending"].is_object())
            || (!v["last"].is_null() && !v["last"].is_object())
            || (v["finished"] == true && !v["pending"].is_null())
        {
            return Err(err("NEXT_OPEN_CHECKPOINT"));
        }
        self.pending = v["pending"].clone();
        self.last = v["last"].clone();
        self.finished = v["finished"].as_bool().expect("checked");
        Ok(())
    }
    /// Integrity hashes cannot replace the Strategy owner's actual accepted outcome.
    pub(crate) fn validate_cut(&self, source: &str, outcome: Option<&Value>) -> Result<(), Error> {
        if self.pending.is_null() {
            return Ok(());
        }
        let p = &self.pending;
        fields(
            p,
            &[
                "schema_version",
                "side",
                "decision",
                "decision_identity",
                "source",
                "source_sequence",
                "signal_input",
                "signal_time",
            ],
        )?;
        let owner = outcome.ok_or_else(|| err("PENDING_STRATEGY_OUTCOME_REQUIRED"))?;
        let side = p["side"].as_str().ok_or_else(|| err("PENDING_SIDE"))?;
        let role = match side {
            "BUY" => "entry",
            "SELL" => "exit",
            _ => return Err(err("PENDING_SIDE")),
        };
        for field in ["decision_identity", "source", "signal_input"] {
            crate::sha(p[field].as_str().ok_or_else(|| err("PENDING_IDENTITY"))?)?;
        }
        p["source_sequence"]
            .as_u64()
            .filter(|n| *n > 0 && *n <= 65536)
            .ok_or_else(|| err("PENDING_SEQUENCE"))?;
        let signal_time = instant(&p["signal_time"])?;
        fields(&self.last, &["identity", "context"])?;
        let last_context = &self.last["context"];
        let last_time = last_context["time"]
            .as_u64()
            .ok_or_else(|| err("PENDING_TIME"))?;
        let expected_context = context(
            p["signal_input"].as_str().expect("validated"),
            BigInt::from(last_time),
            &last_context["trading_day"],
        )?;
        if p["schema_version"] != 1
            || p["source"] != source
            || owner["status"] != "READY"
            || owner["decision"] != p["decision"]
            || owner["event_ns"] != p["signal_time"]
            || p["decision_identity"] != hash(&p["decision"])
            || p["decision"]["eligibility"] != true
            || p["decision"][role] != true
            || signal_time <= self.start
            || signal_time > self.end
            || signal_time != BigInt::from(last_time)
            || self.last["identity"] != p["signal_input"]
            || *last_context != expected_context
        {
            return Err(err("PENDING_STRATEGY_CUT"));
        }
        Ok(())
    }
    pub(crate) fn is_genesis(&self) -> bool {
        self.pending.is_null() && self.last.is_null() && !self.finished
    }
    pub(crate) fn validate_execution(&self, c: &impl NativeExecution) -> Result<(), Error> {
        if c.configuration() != &self.configuration {
            return Err(err("PENDING_EXECUTION_CONFIG"));
        }
        let (active, held) = self.book(c)?;
        if !self.pending.is_null() {
            let side = self.pending["side"]
                .as_str()
                .ok_or_else(|| err("PENDING_SIDE"))?;
            if active
                || (side == "BUY" && !held.is_zero())
                || (side == "SELL" && held.is_zero())
                || !matches!(side, "BUY" | "SELL")
            {
                return Err(err("PENDING_EXECUTION_CUT"));
            }
        }
        Ok(())
    }
    fn book(&self, c: &impl NativeExecution) -> Result<(bool, OnlyDecimal), Error> {
        let state = c.position_order_view()?;
        let relations = state["orders"]
            .as_object()
            .ok_or_else(|| err("ORDER_PROOF"))?;
        if state["schema_version"] != 2 {
            return Err(err("ORDER_PROOF"));
        }
        for relation in relations.values() {
            if relation["cluster"] != self.cluster {
                return Err(err("ORDER_SCOPE"));
            }
        }
        let active = state["active_order_ids"]
            .as_array()
            .ok_or_else(|| err("ORDER_PROOF"))?;
        let mut seen = std::collections::BTreeSet::new();
        for id in active {
            let id = id.as_str().ok_or_else(|| err("ORDER_PROOF"))?;
            if !relations.contains_key(id) || !seen.insert(id) {
                return Err(err("ORDER_PROOF"));
            }
        }
        let active = !active.is_empty();
        let mut quantity: OnlyDecimal = boundary("0".parse())?;
        for allocation in state["position_allocations"]
            .as_array()
            .ok_or_else(|| err("POSITION_PROOF"))?
        {
            if allocation["cluster"] != self.cluster
                || allocation["instrument"] != self.configuration["instruments"][0]["id"]
            {
                return Err(err("POSITION_SCOPE"));
            }
            quantity = boundary(only_add(
                &quantity,
                &decimal(&allocation["snapshot"]["quantity"])?,
            ))?;
        }
        if !quantity.is_zero() && &quantity != self.quantity.value() {
            return Err(err("POLICY_POSITION_SHAPE"));
        }
        Ok((active, quantity))
    }
    pub(crate) fn closed(
        &mut self,
        input: &MarketInput,
        processing: &Value,
        c: &impl NativeExecution,
    ) -> Result<Value, Error> {
        if self.finished || input.event_ns() > self.end {
            return Err(err("POLICY_SAMPLE_BOUND"));
        }
        let raw = input.bar().to_record();
        self.last = json!({"identity":input.identity(),"context":context(&input.identity(),input.event_ns(),&raw["trading_day"])?});
        if input.opening().event_ns() < self.start {
            return Ok(json!({"status":"WARMUP"}));
        }
        if !self.pending.is_null() {
            return Ok(json!({"status":"WAITING_OPEN","signal":self.pending}));
        }
        let decisions = processing["decisions"]
            .as_array()
            .filter(|v| v.len() <= 1)
            .ok_or_else(|| err("DECISION_BOUND"))?;
        let Some(outcome) = decisions.first() else {
            return Ok(json!({"status":"NO_DECISION"}));
        };
        if outcome["status"] != "READY" || outcome["decision"]["eligibility"] != true {
            return Ok(json!({"status":"INELIGIBLE"}));
        }
        let (active, quantity) = self.book(c)?;
        if active {
            return Ok(json!({"status":"ORDER_PENDING"}));
        }
        let d = &outcome["decision"];
        let side = if quantity.is_zero() && d["entry"] == true {
            "BUY"
        } else if !quantity.is_zero() && d["exit"] == true {
            "SELL"
        } else {
            return Ok(json!({"status":"NO_SIGNAL"}));
        };
        self.pending = json!({"schema_version":1,"side":side,"decision":d,"decision_identity":hash(d),"source":input.source(),"source_sequence":input.sequence(),"signal_input":input.identity(),"signal_time":input.event_ns().to_string()});
        Ok(json!({"status":"PENDING","signal":self.pending}))
    }
    fn request(
        &self,
        c: &impl NativeExecution,
        identity: &str,
        ctx: &Value,
        op: &str,
        payload: Value,
    ) -> Value {
        let e = &self.configuration;
        let n = c.sequence() as u64 + 1;
        let id = format!(
            "REPLAY-{}",
            hash(
                &json!({"market":identity,"cause":ctx["cause"],"sequence":n,"op":op,"payload":payload,"policy":self.binding})
            )
        );
        json!({"schema_version":1,"engine":e["engine"],"runtime":e["runtime"],"account":e["account"],"gateway":e["gateway"],"generation":e["generation"],"runtime_kind":"BACKTEST","cluster":self.cluster,"revision":self.revision,"input_id":id,"source_ref":format!("CAUSE-{}",hash(&json!([identity,ctx["cause"],n,op]))),"time":ctx["time"],"runtime_sequence":n,"trading_day":ctx["trading_day"],"day_index":ctx["day_index"],"op":op,"payload":payload})
    }
    pub(crate) fn opening(
        &mut self,
        input: &OpeningInput,
        c: &mut impl NativeExecution,
    ) -> Result<Value, Error> {
        if self.finished {
            return Err(err("POLICY_FINISHED"));
        }
        if self.pending.is_null() {
            return Ok(json!({"status":"NO_PENDING"}));
        }
        if input.event_ns() < self.start || input.event_ns() >= self.end {
            return Err(err("POLICY_SAMPLE_BOUND"));
        }
        let signal = self.pending.clone();
        if signal["source"] != input.source()
            || signal["source_sequence"]
                .as_u64()
                .and_then(|n| n.checked_add(1))
                != Some(input.sequence())
            || instant(&signal["signal_time"])? > input.event_ns()
        {
            return Err(err("NEXT_OPEN_CAUSALITY"));
        }
        let side = signal["side"].as_str().ok_or_else(|| err("SIGNAL_SIDE"))?;
        let (active, held) = self.book(c)?;
        if active || (side == "BUY" && !held.is_zero()) || (side == "SELL" && held.is_zero()) {
            return Err(err("SIGNAL_POSITION_CONFLICT"));
        }
        let multiplier = match side {
            "BUY" => &self.buy_multiplier,
            "SELL" => &self.sell_multiplier,
            _ => return Err(err("SIGNAL_SIDE")),
        };
        let exact = boundary(only_multiply(input.price().value(), multiplier))?;
        let precision =
            u8::try_from(exact.fractional_precision().max(0)).map_err(|_| err("FILL_PRECISION"))?;
        let price = boundary(OnlyPrice::new(exact, precision))?;
        let identity = input.identity();
        let cause = hash(&json!([signal, input.record(), self.binding]));
        let ctx = context(&cause, input.event_ns(), &input.record()["trading_day"])?;
        let request = json!({"schema_version":1,"request_id":{"schema_version":1,"value":format!("NEXT-{}",cause)},"instrument_id":input.instrument_id().to_record(),"side":side,"order_type":"MARKET","quantity":self.quantity.to_record(),"time_in_force":"GTC","account_id":null,"offset":if side=="BUY"{"NONE"}else{"CLOSE"},"price":null,"stop_price":null,"expire_time":null,"tags":[],"metadata":{"replay_policy":hash(&self.binding),"signal":signal["decision_identity"]},"execution_intent":{"schema_version":2,"side":side,"position_side":"LONG","position_effect":if side=="BUY"{"OPEN"}else{"CLOSE"},"position_mode":"NETTING","close_scope":"ANY","exposure_constraint":"NONE"}});
        let request = boundary(OnlyOrderRequest::from_record(&request))?.to_record();
        let at = ctx["time"].as_u64().expect("derived");
        let preview = c.fee_order_preview(&self.cluster, &request, at)?;
        let admission = self.resolver.admission(&preview, &price, &ctx)?;
        if admission["schema_version"] != 1
            || !admission["accepted"].is_boolean()
            || admission["market_provenance"]["kind"] != "MODEL_RULE_DECISION"
            || admission["market_provenance"]["reference_policy"] != "MODEL_NEXT_OPEN"
            || admission["market_provenance"]["venue_acceptance_proven"] != false
        {
            return Err(err("MODEL_ADMISSION_PROOF"));
        }
        let mut output = json!({"schema_version":1,"signal":signal,"opening":input.record(),"execution_price":price.to_record(),"admission":admission});
        if admission["accepted"] == false {
            if admission["market_provenance"]["verdict"] != "MODEL_REJECT"
                || admission["reason"].as_str().is_none_or(str::is_empty)
            {
                return Err(err("MODEL_REJECTION_PROOF"));
            }
            self.pending = Value::Null;
            output["status"] = json!("REJECTED");
            output["reason"] = admission["reason"].clone();
            return Ok(output);
        }
        if admission["market_provenance"]["verdict"] != "MODEL_ACCEPT" {
            return Err(err("MODEL_ADMISSION_PROOF"));
        }
        let order = preview["order_id"]["value"]
            .as_str()
            .ok_or_else(|| err("ORDER"))?
            .to_owned();
        let collateral =
            json!({"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null});
        let model = self.execution_model();
        let fill_contract = json!({"schema_version":1,"kind":"BACKTEST_WHOLE_FILL","maximum_fill_count":1,"model_fingerprint":hash(&model),"model":model,"fee_estimate_assumptions_fingerprint":admission["contract"]["estimate"]["assumptions_fingerprint"]});
        let payload = json!({"schema_version":2,"request":request,"fee_contract":admission["contract"],"fee_budget":admission["fee_budget"],"settlement_fill_contract":fill_contract,"market":{"schema_version":1,"verdict":"ACCEPT","source_ref":format!("MODEL-MARKET-{cause}"),"request_digest":hash(&request),"reference_price":price.to_record(),"notional":admission["notional"],"rounding":"HALF_EVEN"},"order":order,"collateral":collateral});
        let command = self.request(c, &identity, &ctx, "ADMIT", payload);
        match c.apply(&command) {
            Ok(()) => (),
            Err(e) if e.0 == "EXECUTION_RISK_DENIED" => {
                let before = c.state()?;
                let principal =
                    decimal(&admission["contract"]["funding"]["principal_reservation"]["amount"])?;
                let fee = decimal(&admission["fee_budget"])?;
                let required = boundary(only_add(&principal, &fee))?;
                let available = decimal(&before["account"]["snapshot"]["trade_available"])?;
                let ledger_available =
                    decimal(&before["ledger"]["ledgers"][&self.cluster]["snapshot"]["available"])?;
                output["status"] = json!("REJECTED");
                output["reason"] = json!(if side == "BUY"
                    && (available < required || ledger_available < required)
                {
                    "INSUFFICIENT_FUNDS"
                } else {
                    "RISK_DENIED"
                });
                self.pending = Value::Null;
                return Ok(output);
            }
            Err(e) => return Err(e),
        }
        c.apply(&self.request(
            c,
            &identity,
            &ctx,
            "SUBMISSION",
            json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),
        ))?;
        let venue_order = format!("MODEL-ORDER-{cause}");
        c.apply(&self.request(
            c,
            &identity,
            &ctx,
            "ACCEPT",
            json!({"schema_version":1,"order":order,"venue_order":venue_order}),
        ))?;
        let trade = format!("MODEL-TRADE-{cause}");
        let snapshot = c.order(&self.cluster, &order)?;
        let mut fill_context = ctx.clone();
        fill_context["trade"] = json!(trade);
        let evidence = self
            .resolver
            .fill(&snapshot, &price, &self.quantity, &fill_context)?;
        let n = c.sequence() as u64 + 1;
        let scope = json!({"schema_version":1,"engine":self.configuration["engine"],"runtime":self.configuration["runtime"],"account":self.configuration["account"],"gateway":self.configuration["gateway"],"generation":self.configuration["generation"],"runtime_kind":"BACKTEST","cluster":self.cluster,"revision":self.revision,"instrument":input.instrument_id().to_string(),"request":request["request_id"]["value"]});
        let mut fee = json!({"schema_version":1,"instruction":format!("MODEL-FEE-{cause}"),"source_ref":format!("MODEL-FEE-{cause}"),"policy":snapshot["fee_policy_binding"]["fingerprint"],"order":order,"trade":trade,"currency":self.configuration["currency"],"charge_target":evidence["charge_target"],"rebate_target":evidence["rebate_target"]});
        let mut settlement = json!({"schema_version":1,"instruction":format!("MODEL-SET-{cause}"),"source_ref":format!("MODEL-SET-{cause}"),"order":order,"trade":trade,"currency":self.configuration["currency"],"model":"CASH_SETTLEMENT","calendar":self.calendar,"policy":evidence["settlement_policy"],"gross_notional":evidence["gross_notional"],"rounding":"HALF_EVEN"});
        let mut valuation = json!({"schema_version":1,"source_ref":format!("MODEL-VAL-{cause}"),"currency":self.configuration["currency"],"mark":input.price().value().to_string()});
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
        let payload = json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":format!("MODEL-VENUE-{cause}"),"venue_order":venue_order,"quantity":self.quantity.value().to_string(),"price":price.value().to_string(),"price_precision":price.precision(),"fees":fee,"settlement":settlement,"valuation":valuation,"collateral":collateral});
        c.apply(&self.request(c, &identity, &ctx, "FILL", payload))?;
        self.pending = Value::Null;
        output["status"] = json!("FILLED");
        output["order"] = json!(order);
        output["trade"] = json!(trade);
        output["economic_evidence"] = evidence;
        Ok(output)
    }
    pub(crate) fn end_input(&mut self, c: &mut impl NativeExecution) -> Result<Value, Error> {
        self.stop_input(c, "INPUT_EXHAUSTED")
    }
    pub(crate) fn cancel_input(&mut self, c: &mut impl NativeExecution) -> Result<Value, Error> {
        self.stop_input(c, "USER_CANCELLED")
    }
    fn stop_input(&mut self, c: &mut impl NativeExecution, reason: &str) -> Result<Value, Error> {
        if self.finished {
            return Err(err("POLICY_FINISHED"));
        }
        let mut cancelled = vec![];
        let state = c.state()?;
        for (id, _) in state["execution"]["orders"]
            .as_object()
            .ok_or_else(|| err("ORDER_PROOF"))?
        {
            let order = c.order(&self.cluster, id)?;
            if matches!(
                order["status"].as_str(),
                Some("FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED")
            ) {
                continue;
            }
            if order["metadata"]["replay_policy"] != hash(&self.binding) || self.last.is_null() {
                return Err(err("END_ORDER_SCOPE"));
            }
            let identity = self.last["identity"]
                .as_str()
                .ok_or_else(|| err("END_SOURCE"))?;
            let ctx = &self.last["context"];
            if order["status"] != "PENDING_CANCEL" {
                let (request_id, message) = if reason == "INPUT_EXHAUSTED" {
                    (
                        format!("END-CANCEL-{}", hash(&json!([id, self.binding]))),
                        "finite model input exhausted",
                    )
                } else {
                    (
                        format!("USER-CANCEL-{}", hash(&json!([id, self.binding, reason]))),
                        "user cancelled finite model input",
                    )
                };
                c.apply(&self.request(
                    c,
                    identity,
                    ctx,
                    "CANCEL",
                    json!({"schema_version":1,"order":id,"request_id":request_id,"reason":message}),
                ))?;
            }
            c.apply(&self.request(c,identity,ctx,"TERMINAL",json!({"schema_version":1,"order":id,"outcome":"CANCELLED","collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}})))?;
            cancelled.push(json!(id));
        }
        let signal = if self.pending.is_null() {
            Value::Null
        } else {
            json!({"status":"CANCELLED","reason":reason,"signal":self.pending})
        };
        self.pending = Value::Null;
        self.finished = true;
        let mut output = json!({"schema_version":1,"signal":signal,"cancelled_orders":cancelled,"holdings":"RETAINED_AT_LAST_CLOSE"});
        if reason == "USER_CANCELLED" {
            output["reason"] = json!(reason);
            output["holdings"] = json!("RETAINED_AT_LAST_OBSERVED_MARK");
        }
        Ok(output)
    }
    pub(crate) fn quiescent(&self) -> Result<bool, Error> {
        Ok(self.finished && self.pending.is_null())
    }
}
