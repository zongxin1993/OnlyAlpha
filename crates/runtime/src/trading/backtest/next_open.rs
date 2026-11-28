//! A declared deterministic whole-fill model. Strategy and economic state remain with their owners.
use super::{Error, MarketInput, OpeningInput, boundary, err, fields, hash};
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
    fn analytical_entry_quote(
        &self,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error>;
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
    fn position_order_view(&self) -> Result<Value, Error>;
    fn sequence(&self) -> usize;
}
pub(crate) struct NextOpenModel {
    configuration: Value,
    calendar: Value,
    pub(crate) cluster: String,
    revision: Value,
    binding: Value,
    pub(crate) start: BigInt,
    pub(crate) end: BigInt,
    pub(crate) quantity: OnlyQuantity,
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
impl NextOpenModel {
    pub(crate) fn new(
        settings: &Value,
        binding: Value,
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
        if p["schema_version"] != 1
            || p["kind"] != "NEXT_OPEN_LONG_ONLY_V1"
            || configuration["runtime_kind"] != "BACKTEST"
            || revision.is_null()
            || binding["schema_version"] != 1
            || binding["configuration"] != hash(&configuration)
            || binding["reference_policy"] != "MODEL_NEXT_OPEN"
            || binding["kind"].as_str().is_none_or(str::is_empty)
            || !binding["settlement_policy"].is_object()
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
            calendar: settings["calendar"].clone(),
            cluster: cluster.into(),
            revision,
            binding,
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
    pub(crate) fn verify_settlement_policy(&self, evidence: &Value) -> Result<(), Error> {
        if evidence["settlement_policy"] != self.binding["settlement_policy"] {
            return Err(err("MODEL_SETTLEMENT_POLICY"));
        }
        Ok(())
    }

    pub(crate) fn verify_notional(&self, price: &OnlyPrice, value: &Value) -> Result<(), Error> {
        use onlyalpha_domain::{
            numeric::only_quantize,
            value::{OnlyCurrency, OnlyMoney},
        };
        let currency = boundary(OnlyCurrency::from_record(&self.configuration["currency"]))?;
        let exact = boundary(only_multiply(price.value(), self.quantity.value()))?;
        let quantum = boundary(format!("1e-{}", currency.precision()).parse())?;
        let expected = boundary(OnlyMoney::new(
            boundary(only_quantize(&exact, &quantum))?,
            currency,
        ))?;
        let money = boundary(OnlyMoney::from_record(value))?;
        if money.to_record() != *value || money != expected {
            return Err(err("MODEL_NOTIONAL"));
        }
        Ok(())
    }

    pub(crate) fn baseline_entry(&self, first: &MarketInput) -> Result<(OnlyPrice, Value), Error> {
        let opening = first.opening();
        let price = self.execution_price(&opening, "BUY")?;
        let cause = hash(
            &json!({"kind":"ANALYTICAL_ESTIMATE","input":opening.identity(),"policy":self.binding}),
        );
        let context = context(&cause, opening.event_ns(), &opening.record()["trading_day"])?;
        Ok((price, context))
    }

    pub(crate) fn retained_baseline(
        &self,
        first: &MarketInput,
        last: &MarketInput,
        quote: &Value,
    ) -> Result<Value, Error> {
        let (price, context) = self.baseline_entry(first)?;
        self.baseline_from_quote(first, last, &price, &context, quote)
    }

    fn baseline_from_quote(
        &self,
        first: &MarketInput,
        last: &MarketInput,
        price: &OnlyPrice,
        context: &Value,
        quote: &Value,
    ) -> Result<Value, Error> {
        use onlyalpha_domain::{
            numeric::{only_quantize, only_subtract},
            value::{OnlyCurrency, OnlyMoney},
        };
        if quote["schema_version"] != 1
            || quote["kind"] != "ANALYTICAL_ESTIMATE"
            || quote["reference_policy"] != "MODEL_NEXT_OPEN"
            || quote["venue_acceptance_proven"] != false
            || quote["policy_fingerprint"] != hash(&self.binding)
            || quote["execution_price"] != price.to_record()
            || quote["quantity"] != self.quantity.to_record()
            || quote["context"] != *context
        {
            return Err(err("BASELINE_QUOTE"));
        }
        let currency = boundary(OnlyCurrency::from_record(&self.configuration["currency"]))?;
        let money = |v: &Value| -> Result<OnlyDecimal, Error> {
            let value = boundary(OnlyMoney::from_record(v))?;
            if value.to_record() != *v || value.currency() != &currency {
                return Err(err("BASELINE_CURRENCY"));
            }
            Ok(value.amount().clone())
        };
        let initial = decimal(&self.configuration["initial_cash"])?;
        let gross = money(&quote["gross_notional"])?;
        let charges = money(&quote["charges"])?;
        let rebates = money(&quote["rebates"])?;
        let quantum: OnlyDecimal = boundary(format!("1e-{}", currency.precision()).parse())?;
        let entry_notional = boundary(only_multiply(price.value(), self.quantity.value()))?;
        if gross != boundary(only_quantize(&entry_notional, &quantum))?
            || charges.is_negative()
            || rebates.is_negative()
        {
            return Err(err("BASELINE_QUOTE_AMOUNT"));
        }
        let cash = boundary(only_add(
            &boundary(only_subtract(
                &boundary(only_subtract(&initial, &gross))?,
                &charges,
            ))?,
            &rebates,
        ))?;
        let marked = boundary(only_multiply(
            last.bar().close().value(),
            self.quantity.value(),
        ))?;
        let equity = boundary(only_add(
            &cash,
            &boundary(only_quantize(&marked, &quantum))?,
        ))?;
        let equity = boundary(OnlyMoney::new(equity, currency))?.to_record()["amount"].clone();
        Ok(
            json!({"kind":"ANALYTICAL_ESTIMATE","entry_at_ns":first.opening().event_ns().to_string(),"valuation_at_ns":last.event_ns().to_string(),"entry_price":price.to_record(),"quantity":self.quantity.to_record(),"entry_fee_quote":quote,"initial_equity":self.configuration["initial_cash"],"final_equity":equity}),
        )
    }
    fn execution_price(&self, input: &OpeningInput, side: &str) -> Result<OnlyPrice, Error> {
        let multiplier = match side {
            "BUY" => &self.buy_multiplier,
            "SELL" => &self.sell_multiplier,
            _ => return Err(err("SIGNAL_SIDE")),
        };
        let exact = boundary(only_multiply(input.price().value(), multiplier))?;
        let precision =
            u8::try_from(exact.fractional_precision().max(0)).map_err(|_| err("FILL_PRECISION"))?;
        boundary(OnlyPrice::new(exact, precision))
    }

    pub(crate) fn opening_terms(
        &self,
        input: &OpeningInput,
        signal: &Value,
    ) -> Result<(OnlyPrice, Value), Error> {
        if input.event_ns() < self.start || input.event_ns() >= self.end {
            return Err(err("POLICY_SAMPLE_BOUND"));
        }
        if signal["source"] != input.source()
            || signal["source_sequence"]
                .as_u64()
                .and_then(|n| n.checked_add(1))
                != Some(input.sequence())
            || instant(&signal["signal_time"])? > input.event_ns()
        {
            return Err(err("NEXT_OPEN_CAUSALITY"));
        }
        let price = self.execution_price(
            input,
            signal["side"].as_str().ok_or_else(|| err("SIGNAL_SIDE"))?,
        )?;
        let cause = hash(&json!([signal, input.record(), self.binding]));
        let ctx = context(&cause, input.event_ns(), &input.record()["trading_day"])?;
        Ok((price, ctx))
    }

    pub(crate) fn order_request(
        &self,
        input: &OpeningInput,
        signal: &Value,
        cause: &str,
    ) -> Result<Value, Error> {
        let side = &signal["side"];
        let request = json!({"schema_version":1,"request_id":{"schema_version":1,"value":format!("NEXT-{cause}")},"instrument_id":input.instrument_id().to_record(),"side":side,"order_type":"MARKET","quantity":self.quantity.to_record(),"time_in_force":"GTC","account_id":{"schema_version":1,"value":self.configuration["account"]},"offset":if side=="BUY"{"NONE"}else{"CLOSE"},"price":null,"stop_price":null,"expire_time":null,"tags":[],"metadata":{"replay_policy":hash(&self.binding),"signal":signal["decision_identity"]},"execution_intent":{"schema_version":2,"side":side,"position_side":"LONG","position_effect":if side=="BUY"{"OPEN"}else{"CLOSE"},"position_mode":"NETTING","close_scope":"ANY","exposure_constraint":"NONE"}});
        Ok(boundary(OnlyOrderRequest::from_record(&request))?.to_record())
    }

    pub(crate) fn request(
        &self,
        n: u64,
        identity: &str,
        ctx: &Value,
        op: &str,
        payload: Value,
    ) -> Value {
        let e = &self.configuration;
        let id = format!(
            "REPLAY-{}",
            hash(
                &json!({"market":identity,"cause":ctx["cause"],"sequence":n,"op":op,"payload":payload,"policy":self.binding})
            )
        );
        json!({"schema_version":1,"engine":e["engine"],"runtime":e["runtime"],"account":e["account"],"gateway":e["gateway"],"generation":e["generation"],"runtime_kind":"BACKTEST","cluster":self.cluster,"revision":self.revision,"input_id":id,"source_ref":format!("CAUSE-{}",hash(&json!([identity,ctx["cause"],n,op]))),"time":ctx["time"],"runtime_sequence":n,"trading_day":ctx["trading_day"],"day_index":ctx["day_index"],"op":op,"payload":payload})
    }

    pub(crate) fn admit_payload(
        &self,
        request: &Value,
        order: &str,
        cause: &str,
        price: &OnlyPrice,
        admission: &Value,
    ) -> Value {
        let model = self.execution_model();
        let fill_contract = json!({"schema_version":1,"kind":"BACKTEST_WHOLE_FILL","maximum_fill_count":1,"model_fingerprint":hash(&model),"model":model,"fee_estimate_assumptions_fingerprint":admission["contract"]["estimate"]["assumptions_fingerprint"]});
        json!({"schema_version":2,"request":request,"fee_contract":admission["contract"],"fee_budget":admission["fee_budget"],"settlement_fill_contract":fill_contract,"market":{"schema_version":1,"verdict":"ACCEPT","source_ref":format!("MODEL-MARKET-{cause}"),"request_digest":hash(request),"reference_price":price.to_record(),"notional":admission["notional"],"rounding":"HALF_EVEN"},"order":order,"collateral":no_collateral()})
    }

    pub(crate) fn admission_rejection(
        &self,
        result: Result<(), Error>,
        side: &Value,
        admission: &Value,
        state: impl FnOnce() -> Result<Value, Error>,
    ) -> Result<Option<&'static str>, Error> {
        match result {
            Ok(()) => Ok(None),
            Err(error) if error.0 == "EXECUTION_ACCOUNT_CAPACITY_DENIED" => {
                Ok(Some("ACCOUNT_JOURNAL_BOUND"))
            }
            Err(error) if error.0 == "EXECUTION_RISK_DENIED" => {
                let before = state()?;
                let principal =
                    decimal(&admission["contract"]["funding"]["principal_reservation"]["amount"])?;
                let fee = decimal(&admission["fee_budget"])?;
                let required = boundary(only_add(&principal, &fee))?;
                let available = decimal(&before["account"]["snapshot"]["trade_available"])?;
                let ledger_available =
                    decimal(&before["ledger"]["ledgers"][&self.cluster]["snapshot"]["available"])?;
                Ok(Some(
                    if side == "BUY" && (available < required || ledger_available < required) {
                        "INSUFFICIENT_FUNDS"
                    } else {
                        "RISK_DENIED"
                    },
                ))
            }
            Err(error) => Err(error),
        }
    }

    pub(crate) fn fill_payload(
        &self,
        input: &OpeningInput,
        price: &OnlyPrice,
        fill_context: &Value,
        admitted: &Value,
        evidence: &Value,
        n: u64,
        fill: &Value,
    ) -> Result<Value, Error> {
        self.verify_settlement_policy(evidence)?;
        let cause = fill_context["cause"]
            .as_str()
            .ok_or_else(|| err("FILL_CAUSE"))?;
        let trade = &fill_context["trade"];
        let order = &admitted["order"];
        let request = &admitted["request"];
        let scope = json!({"schema_version":1,"engine":self.configuration["engine"],"runtime":self.configuration["runtime"],"account":self.configuration["account"],"gateway":self.configuration["gateway"],"generation":self.configuration["generation"],"runtime_kind":"BACKTEST","cluster":self.cluster,"revision":self.revision,"instrument":input.instrument_id().to_string(),"request":request["request_id"]["value"]});
        let mut fee = json!({"schema_version":1,"instruction":format!("MODEL-FEE-{cause}"),"source_ref":format!("MODEL-FEE-{cause}"),"policy":admitted["fee_contract"]["binding"]["fingerprint"],"order":order,"trade":trade,"currency":self.configuration["currency"],"charge_target":evidence["charge_target"],"rebate_target":evidence["rebate_target"]});
        let mut settlement = json!({"schema_version":1,"instruction":format!("MODEL-SET-{cause}"),"source_ref":format!("MODEL-SET-{cause}"),"order":order,"trade":trade,"currency":self.configuration["currency"],"model":"CASH_SETTLEMENT","calendar":self.calendar,"policy":self.binding["settlement_policy"],"gross_notional":evidence["gross_notional"],"rounding":"HALF_EVEN"});
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
        Ok(
            json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":fill["venue_trade_id"]["value"],"venue_order":fill["venue_order_id"]["value"],"quantity":self.quantity.value().to_string(),"price":price.value().to_string(),"price_precision":price.precision(),"fees":fee,"settlement":settlement,"valuation":valuation,"collateral":no_collateral()}),
        )
    }
}

fn no_collateral() -> Value {
    json!({"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null})
}

pub(crate) fn signal_at_close(input: &MarketInput, outcome: &Value, held: bool) -> Value {
    if outcome["status"] != "READY" || outcome["decision"]["eligibility"] != true {
        return json!({"status":"INELIGIBLE"});
    }
    let decision = &outcome["decision"];
    let side = if !held && decision["entry"] == true {
        "BUY"
    } else if held && decision["exit"] == true {
        "SELL"
    } else {
        return json!({"status":"NO_SIGNAL"});
    };
    let signal = json!({"schema_version":1,"side":side,"decision":decision,"decision_identity":hash(decision),"source":input.source(),"source_sequence":input.sequence(),"signal_input":input.identity(),"signal_time":input.event_ns().to_string()});
    json!({"status":"PENDING","signal":signal})
}
