use crate::{Components, Prepared, model::*};
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{base::OnlyDomainModel, execution::OnlyOrderRequest, value::OnlyPrice};
use serde_json::{Value, json};
use std::sync::Arc;

pub(crate) fn checked_admission_request(record: &Value) -> Result<OnlyOrderRequest, Error> {
    bound_decimal_leaves(record)?;
    let request = OnlyOrderRequest::from_record(record)?;
    if request.to_record() != *record {
        return Err(err("EXECUTION_REQUEST_CANONICAL"));
    }
    Ok(request)
}

pub(crate) fn validate_admission_intent(request: &Value, side: &str) -> Result<(), Error> {
    let intent = &request["execution_intent"];
    if !matches!(request["order_type"].as_str(), Some("MARKET" | "LIMIT"))
        || intent["position_side"] != "LONG"
        || intent["position_mode"] != "NETTING"
        || intent["side"] != side
        || intent["position_effect"] != if side == "BUY" { "OPEN" } else { "CLOSE" }
        || !matches!(side, "BUY" | "SELL")
    {
        return Err(err("EXECUTION_UNSUPPORTED_SHAPE"));
    }
    Ok(())
}

pub(crate) fn admission_quantity_precision(spec: &Value, request: &Value) -> Result<u8, Error> {
    if (request["order_type"] != "MARKET"
        && request["price"]["precision"] != spec["price_precision"])
        || request["quantity"]["precision"] != spec["quantity_precision"]
    {
        return Err(err("EXECUTION_INSTRUMENT_PRECISION"));
    }
    u8::try_from(uint(&spec["quantity_precision"])?)
        .map_err(|_| err("EXECUTION_QUANTITY_PRECISION"))
}

pub(crate) fn validate_fill_price(
    order: &Value,
    price: &BigDecimal,
    quantity: &BigDecimal,
) -> Result<(), Error> {
    if price <= &0 || quantity <= &0 {
        return Err(err("EXECUTION_LIMIT_OR_POSITIVE"));
    }
    if order["order_type"] != "MARKET" {
        let limit = dec(&order["price"]["value"])?;
        if (order["side"] == "BUY" && price > &limit) || (order["side"] == "SELL" && price < &limit)
        {
            return Err(err("EXECUTION_LIMIT_OR_POSITIVE"));
        }
    }
    Ok(())
}

fn external_rejection(broker_record: &Value) -> Value {
    let reason = broker_record["payload"]["reason"]
        .as_str()
        .unwrap_or("explicit external rejection");
    json!({"schema_version":1,"code":"EXTERNAL_REJECTION","message":reason})
}

/// 单次只读验证中的准入复算基线；不授予 Store、Ready、运行或提交资格。
/// 调用方仍须逐次证明 checkpoint 来自本次验证的确切原始前缀。
/// 完整 checkpoint 改变时冷恢复；每个输入从独立候选执行，不保留拒绝结果。
#[derive(Default)]
pub struct AdmissionPreview {
    baseline: Option<(Value, Components)>,
    #[cfg(test)]
    restores: usize,
}
impl AdmissionPreview {
    /// 检查本次确切 checkpoint 和输入；返回 Some 仅表示重新推导出的业务拒绝。
    /// None 不证明缺失的原始 ADMIT 事实存在；错误仍按原准入/恢复契约传播。
    pub fn check(
        &mut self,
        configuration: &Value,
        checkpoint: &Value,
        input: &Value,
    ) -> Result<Option<Error>, Error> {
        if self.baseline.as_ref().is_some_and(|(original, baseline)| {
            original != checkpoint || baseline.configuration() != configuration
        }) {
            // 来源内容或配置变化，即使新输入 scope 无效也不保留旧基线。
            self.baseline = None;
        }
        if input["op"] != "ADMIT" || checkpoint["config"] != *configuration {
            return Err(err("EXECUTION_ADMISSION_PREVIEW_SCOPE"));
        }
        for field in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
        ] {
            if input[field] != configuration[field] {
                return Err(err("EXECUTION_ADMISSION_PREVIEW_SCOPE"));
            }
        }
        let cluster = text(&input["cluster"])?;
        if input["revision"] != configuration["profiles"][cluster]["revision"]
            || input["revision"].is_null()
        {
            return Err(err("EXECUTION_ADMISSION_PREVIEW_SCOPE"));
        }
        if self.baseline.is_none() {
            let mut baseline = Components::new(configuration.clone())?;
            baseline.restore(checkpoint, &hash(checkpoint))?;
            self.baseline = Some((checkpoint.clone(), baseline));
            #[cfg(test)]
            {
                self.restores += 1;
            }
        }
        let mut candidate = self
            .baseline
            .as_ref()
            .expect("restored exact checkpoint")
            .1
            .clone_data();
        if candidate.pending.is_some() {
            return Err(err("EXECUTION_PENDING"));
        }
        candidate.validate_planning_input(input)?;
        candidate.invalidate_payloads();
        match candidate.apply_operation(input) {
            Ok(()) => Ok(None),
            Err(error)
                if matches!(
                    error.0.as_str(),
                    "EXECUTION_RISK_DENIED" | "EXECUTION_ACCOUNT_CAPACITY_DENIED"
                ) =>
            {
                Ok(Some(error))
            }
            Err(error) => Err(error),
        }
    }
}

impl Components {
    pub(crate) fn validate_planning_input(&self, input: &Value) -> Result<u64, Error> {
        row(
            input,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
                "cluster",
                "revision",
                "input_id",
                "time",
                "runtime_sequence",
                "trading_day",
                "day_index",
                "source_ref",
                "op",
                "payload",
            ],
        )?;
        if input.to_string().len() > 65536 {
            return Err(err("EXECUTION_INPUT_BOUND"));
        }
        for f in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
        ] {
            if input[f] != self.config[f] {
                return Err(err("EXECUTION_CONTEXT"));
            }
        }
        let cluster = id(&input["cluster"])?;
        if input["revision"] != self.config["profiles"][cluster]["revision"]
            || input["revision"].is_null()
        {
            return Err(err("EXECUTION_REVISION"));
        }
        let input_id = input_id(input)?;
        id(&input["source_ref"])?;
        let n = uint(&input["runtime_sequence"])?;
        if n == 0
            || n > u64::MAX / 64
            || n <= self.meta["last_runtime_sequence"].as_u64().unwrap_or(0)
        {
            return Err(err("EXECUTION_RUNTIME_SEQUENCE"));
        }
        if self.meta["inputs"].get(input_id).is_some()
            || self.meta["sources"]
                .get(text(&input["source_ref"])?)
                .is_some()
        {
            return Err(err("EXECUTION_INPUT_ALIAS"));
        }
        Ok(n)
    }
    pub fn prepare<S: crate::Store>(&self, store: &S, input: &Value) -> Result<Prepared, Error> {
        self.require_original_evidence(input)?;
        self.prepare_input(store, input)
    }
    pub(crate) fn require_original_evidence(&self, input: &Value) -> Result<(), Error> {
        if self.config["schema_version"] == 3
            && matches!(
                input["op"].as_str(),
                Some("ACCEPT" | "FILL" | "TERMINAL" | "MARK" | "FUNDING")
            )
        {
            return Err(err("EXECUTION_ORIGINAL_EVIDENCE_REQUIRED"));
        }
        Ok(())
    }
    pub(crate) fn prepare_input<S: crate::Store>(
        &self,
        store: &S,
        input: &Value,
    ) -> Result<Prepared, Error> {
        self.prepare_with_origin(store, input, Value::Null)
    }
    pub(crate) fn prepare_with_origin<S: crate::Store>(
        &self,
        store: &S,
        input: &Value,
        origin: Value,
    ) -> Result<Prepared, Error> {
        self.ready_source(store)?;
        if self.pending.is_some() {
            return Err(err("EXECUTION_PENDING"));
        }
        let n = self.validate_planning_input(input)?;
        let before = self.payload_hashes()?;
        let mut candidate = self.clone_data();
        candidate.invalidate_payloads();
        candidate.apply_operation(input)?;
        if !origin.is_null() {
            let p = &input["payload"];
            let econ = &mut Arc::make_mut(&mut candidate.meta)["perpetual"];
            // 首次事实固定其原件关系，重复投递维护同一个经济身份。
            let row = if input["op"] == "FUNDING" {
                &mut econ["funding"][text(&p["fact"]["fact_id"])?]
            } else {
                &mut econ["broker_facts"][text(&p["broker"]["id"])?]
            };
            if row.get("origin").is_none() {
                row["origin"] = origin;
            }
        }
        Arc::make_mut(&mut candidate.meta)["inputs"][text(&input["input_id"])?] =
            json!(hash(input));
        Arc::make_mut(&mut candidate.meta)["sources"][text(&input["source_ref"])?] =
            json!(hash(input));
        Arc::make_mut(&mut candidate.meta)["last_runtime_sequence"] = json!(n);
        Arc::make_mut(&mut candidate.meta)["transactions"][self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?
            .to_string()] = json!(format!("ETX-{}", hash(input)));
        let after = candidate.payloads()?;
        let after_hashes = candidate.payload_hashes()?;
        let projections:Vec<_>=before.iter().zip(after.iter()).enumerate().map(|(i,(b,a))|json!({"schema_version":1,"component":COMPONENTS[i],"before_hash":b,"result_hash":after_hashes[i],"result":a})).collect();
        let tx = format!("ETX-{}", hash(input));
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?;
        let mut body = json!({"schema_version":1,"transaction_id":tx,"config_hash":hash(&self.config),"sequence":sequence,"predecessor":self.sequence,"input":input,"projections":null,"events":[{"schema_version":1,"event_id":format!("{tx}-EVENT-1"),"transaction_id":tx,"sequence":sequence,"input":input}]});
        // Retain the original key position while moving the already constructed
        // Values, rather than serializing and copying every projection again.
        body["projections"] = Value::Array(projections);
        Prepared::new_with_typed_after(body, candidate)
    }
    pub(crate) fn apply_operation(&mut self, input: &Value) -> Result<(), Error> {
        if self.config["schema_version"] == 3 {
            return self.perpetual_operation(input);
        }
        match text(&input["op"])? {
            "ADMIT" => self.admit(input)?,
            "SUBMISSION" => self.submission(input)?,
            "ACCEPT" => self.accept(input)?,
            "CANCEL" => self.cancel(input)?,
            "FILL" => self.fill(input)?,
            "VALUATION" => self.valuation(input)?,
            "SETTLEMENT_MATURITY" => self.settlement_maturity(input)?,
            "TERMINAL" => self.terminal(input)?,
            _ => return Err(err("EXECUTION_OPERATION")),
        };
        Ok(())
    }
    pub(crate) fn command(&self, input: &Value, op: &str, payload: Value, suffix: u64) -> Value {
        json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"command_id":format!("{}-{suffix}",input["input_id"].as_str().expect("validated")),"cause":super::perpetual::cause(input),"time":input["time"],"op":op,"payload":payload})
    }
    pub(crate) fn ledger_command(
        &self,
        input: &Value,
        op: &str,
        payload: Value,
        suffix: u64,
    ) -> Value {
        let mut c = self.command(input, op, payload, suffix);
        c.as_object_mut().expect("object").remove("gateway");
        c["cluster"] = input["cluster"].clone();
        c["runtime_sequence"] =
            json!(input["runtime_sequence"].as_u64().expect("validated") * 64 + suffix);
        c["trading_day"] = input["trading_day"].clone();
        c["day_index"] = input["day_index"].clone();
        c
    }
    fn risk_command(&self, input: &Value, op: &str, payload: Value, suffix: u64) -> Value {
        let mut c = self.ledger_command(input, op, payload, suffix);
        for f in ["trading_day", "day_index"] {
            c.as_object_mut().expect("object").remove(f);
        }
        let cause = c
            .as_object_mut()
            .expect("object")
            .remove("cause")
            .expect("cause");
        c["causal"] = cause;
        c
    }
    fn order_local(&self, input: &Value, op: &str, order: &str) -> Value {
        json!({"schema_version":1,"op":op,"cluster_id":input["cluster"],"order_id":order,"at":input["time"]})
    }
    fn order_creation(input: &Value) -> Value {
        json!({"schema_version":1,"op":"CREATE","cluster_id":input["cluster"],"account_id":input["account"],"request":input["payload"]["request"],"cause":super::perpetual::cause(input),"at":input["time"]})
    }
    fn order_fee(&self, input: &Value, order: &str, contract: &Value) -> Value {
        let mut command = self.order_local(input, "FEE", order);
        command["contract"] = contract.clone();
        command["contract"]["schema_version"] = json!(1);
        command
    }
    pub(crate) fn create_order(&mut self, input: &Value, order: &str) -> Result<(), Error> {
        let created = self.order_apply(&Self::order_creation(input))?;
        if created["order_id"]["value"] != order {
            return Err(err("EXECUTION_ORDER_IDENTITY"));
        }
        Ok(())
    }
    pub(crate) fn bind_order_fee(
        &mut self,
        input: &Value,
        order: &str,
        contract: &Value,
    ) -> Result<(), Error> {
        self.order_apply(&self.order_fee(input, order, contract))?;
        Ok(())
    }
    pub(crate) fn begin_order_submission(
        &mut self,
        input: &Value,
        order: &str,
    ) -> Result<(), Error> {
        self.order_apply(&self.order_local(input, "BEGIN_SUBMIT", order))?;
        Ok(())
    }
    fn external(&self, input: &Value, op: &str, order: &str) -> Value {
        let mut c = self.order_local(input, op, order);
        c["runtime_id"] = input["runtime"].clone();
        c["gateway_id"] = input["gateway"].clone();
        c["generation"] = input["generation"].clone();
        c["account_id"] = input["account"].clone();
        c["event_at"] = input["time"].clone();
        c["event_id"] = input["source_ref"].clone();
        c["sequence"] = input["runtime_sequence"].clone();
        c
    }
    pub(crate) fn apply_native_order_fact(
        &mut self,
        input: &Value,
        order: &str,
        broker: &Value,
    ) -> Result<Value, Error> {
        let kind = text(&broker["kind"])?;
        let op = match kind {
            "ACCEPTED" => "ACCEPT",
            "TRADE" => "FILL",
            "REJECTED" | "EXPIRED" | "CANCELLED" => kind,
            _ => return Err(err("EXECUTION_BROKER_KIND")),
        };
        let payload = &broker["payload"];
        let mut command = self.external(input, op, order);
        command["at"] = broker["ts_init"].clone();
        command["event_at"] = broker["ts_event"].clone();
        command["event_id"] = broker["update_id"].clone();
        command["sequence"] = broker["source_sequence"].clone();
        match op {
            "ACCEPT" => command["venue_order_id"] = payload["venue"].clone(),
            "REJECTED" => command["rejection"] = external_rejection(broker),
            "FILL" => {
                let fill = &payload["fill"];
                command["event_id"] = fill["external_event_id"].clone();
                command["sequence"] = fill["external_sequence"].clone();
                command["fill"] = fill.clone();
            }
            _ => {}
        }
        self.order_apply(&command)
    }
    fn order_apply(&mut self, c: &Value) -> Result<Value, Error> {
        let o = boundary(Arc::make_mut(&mut self.order).apply(c))?;
        if o.result != onlyalpha_order::ApplyResult::Applied {
            return Err(err("EXECUTION_ORDER_NOT_APPLIED"));
        }
        Ok(o.snapshot.map(|s| s.to_record()).unwrap_or(Value::Null))
    }
    pub(crate) fn account_apply(&mut self, c: &Value) -> Result<(), Error> {
        if boundary(Arc::make_mut(&mut self.account).apply(c))?.status
            != onlyalpha_account::Status::Applied
        {
            return Err(err("EXECUTION_ACCOUNT_NOT_APPLIED"));
        }
        Ok(())
    }
    pub(crate) fn ledger_apply(&mut self, c: &Value) -> Result<(), Error> {
        if boundary(Arc::make_mut(&mut self.ledger).apply(c))?.status
            != onlyalpha_strategy_ledger::Status::Applied
        {
            return Err(err("EXECUTION_LEDGER_NOT_APPLIED"));
        }
        Ok(())
    }
    pub(crate) fn position_apply(&mut self, c: &Value) -> Result<Value, Error> {
        let o = boundary(Arc::make_mut(&mut self.position).apply(c))?;
        if o.status != onlyalpha_position::Status::Applied {
            return Err(err("EXECUTION_POSITION_NOT_APPLIED"));
        }
        Ok(o.fact.unwrap_or(Value::Null))
    }
    pub(crate) fn reserve_position(
        &mut self,
        input: &Value,
        instrument: &str,
    ) -> Result<(), Error> {
        let payload = &input["payload"];
        let quantity = nonnegative(&payload["request"]["quantity"]["value"])?;
        self.position_apply(&self.command(input,"RESERVE",json!({"schema_version":1,"instrument":instrument,"cluster":input["cluster"],"order":payload["order"],"quantity":quantity.to_plain_string()}),2))?;
        Ok(())
    }
    pub(crate) fn stage_position(
        &mut self,
        input: &Value,
        stage: &str,
        suffix: u64,
    ) -> Result<(), Error> {
        self.position_apply(&self.command(input,"STAGE",json!({"schema_version":1,"order":input["payload"]["order"],"cluster":input["cluster"],"stage":stage}),suffix))?;
        Ok(())
    }
    pub(crate) fn release_position(
        &mut self,
        input: &Value,
        broker_confirmed: bool,
    ) -> Result<(), Error> {
        self.position_apply(&self.command(input,"RELEASE",json!({"schema_version":1,"order":input["payload"]["order"],"cluster":input["cluster"],"broker_confirmed":broker_confirmed}),0))?;
        Ok(())
    }
    pub(crate) fn position_trade_command(
        &self,
        input: &Value,
        instrument: &str,
        request: &Value,
        fee: &Value,
        bucket: &str,
        terminal: bool,
    ) -> Result<Value, Error> {
        let payload = &input["payload"];
        let is_market = request["order_type"] == "MARKET";
        let mut trade = json!({"schema_version":if is_market {2} else {1},"instrument":instrument,"cluster":input["cluster"],"order":payload["order"],"trade":payload["trade"],"venue_trade":payload["venue_trade"],"execution":format!("ETX-{}",super::perpetual::cause(input)),"sequence":input["runtime_sequence"],"side":request["side"],"position_side":"LONG","position_mode":"NETTING","price":payload["price"],"quantity":payload["quantity"],"fee":fee["charges"],"bucket":bucket,"terminal_fill":terminal});
        if is_market {
            trade["price_precision"] = payload["price_precision"].clone();
        }
        if self.config["schema_version"] == 3 {
            let broker = input
                .get("broker_record")
                .unwrap_or(&payload["broker"]["record"]);
            let fill = &broker["payload"]["fill"];
            trade["schema_version"] = json!(3);
            trade["trade"] = fill["trade_id"]["value"].clone();
            trade["venue_trade"] = fill["venue_trade_id"]["value"].clone();
            trade["price"] = fill["price"]["value"].clone();
            trade["quantity"] = fill["quantity"]["value"].clone();
            trade["economic_time"] = broker["ts_event"].clone();
            trade["broker_record_digest"] = json!(hash(broker));
            trade["rebates"] = fee["rebates"].clone();
        }
        let mut command = self.command(input, "TRADE", trade, 0);
        if self.config["schema_version"] == 3 {
            command["payload"]["trade_evidence"] =
                json!(boundary(self.position.trade_input_digest(&command))?);
        }
        Ok(command)
    }
    fn risk_apply(&mut self, c: &Value) -> Result<Option<Value>, Error> {
        let o = boundary(Arc::make_mut(&mut self.risk).apply(c))?;
        if o.status != onlyalpha_risk::Status::Applied {
            return Err(err("EXECUTION_RISK_NOT_APPLIED"));
        }
        Ok(o.decision)
    }
    pub(crate) fn relation(&self, input: &Value) -> Result<Value, Error> {
        let order = id(&input["payload"]["order"])?;
        let r = self.meta["orders"]
            .get(order)
            .ok_or_else(|| err("EXECUTION_ORDER_RELATION"))?;
        if r["cluster"] != input["cluster"] || r["revision"] != input["revision"] {
            return Err(err("EXECUTION_ORDER_OWNER"));
        }
        Ok(r.clone())
    }
    fn validate_whole_fill_contract(
        &self,
        request: &Value,
        fee: &Value,
        contract: &Value,
    ) -> Result<(), Error> {
        row(
            contract,
            &[
                "kind",
                "maximum_fill_count",
                "model_fingerprint",
                "model",
                "fee_estimate_assumptions_fingerprint",
            ],
        )?;
        let model = &contract["model"];
        row(
            model,
            &[
                "kind",
                "runtime_kind",
                "maximum_fill_count",
                "configuration_fingerprint",
                "policy_fingerprint",
            ],
        )?;
        for value in [
            &contract["model_fingerprint"],
            &contract["fee_estimate_assumptions_fingerprint"],
            &model["configuration_fingerprint"],
            &model["policy_fingerprint"],
        ] {
            fp(value)?;
        }
        if self.config["runtime_kind"] != "BACKTEST"
            || request["order_type"] != "MARKET"
            || contract["kind"] != "BACKTEST_WHOLE_FILL"
            || contract["maximum_fill_count"] != 1
            || model["kind"] != "GUARANTEED_WHOLE_FILL"
            || model["runtime_kind"] != "BACKTEST"
            || model["maximum_fill_count"] != 1
            || model["configuration_fingerprint"] != hash(&self.config)
            || model["policy_fingerprint"] != request["metadata"]["replay_policy"]
            || contract["model_fingerprint"] != hash(model)
            || contract["fee_estimate_assumptions_fingerprint"]
                != fee["estimate"]["assumptions_fingerprint"]
        {
            return Err(err("EXECUTION_WHOLE_FILL_CONTRACT"));
        }
        Ok(())
    }
    fn economic_source(&mut self, family: &str, proof: &Value) -> Result<(), Error> {
        let source = id(&proof["source_ref"])?;
        if self.meta[family].get(source).is_some() {
            return Err(err("EXECUTION_ECONOMIC_SOURCE_ALIAS"));
        }
        Arc::make_mut(&mut self.meta)[family][source] = json!(hash(proof));
        Ok(())
    }
    /// Reuse the exact canonical admission against an original retained
    /// checkpoint, without a Store, transaction, Event or grant escaping. This
    /// verifies the no-ADMIT branch: Some is a proved business rejection;
    /// None means admissible input still requires its missing retained fact.
    pub fn admission_rejection(
        configuration: &Value,
        checkpoint: &Value,
        input: &Value,
    ) -> Result<Option<Error>, Error> {
        AdmissionPreview::default().check(configuration, checkpoint, input)
    }
    pub(crate) fn admit(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        let whole_fill = match p["schema_version"].as_u64() {
            Some(1) => false,
            Some(2) => true,
            _ => return Err(err("EXECUTION_ADMISSION_SCHEMA")),
        };
        let mut fields = vec![
            "request",
            "fee_contract",
            "fee_budget",
            "market",
            "order",
            "collateral",
        ];
        if whole_fill {
            fields.push("settlement_fill_contract");
        }
        let mut shape = p.clone();
        shape["schema_version"] = json!(1);
        row(&shape, &fields)?;
        bound_decimal_leaves(&p["fee_contract"])?;
        let r = &p["request"];
        let request = checked_admission_request(r)?;
        let side = text(&r["side"])?;
        let buy = side == "BUY";
        if buy {
            boundary(self.position.admit_new_risk())?;
        }
        validate_admission_intent(r, side)?;
        let is_market = r["order_type"] == "MARKET";
        let cluster = text(&input["cluster"])?;
        let inst = request.instrument_id().to_string();
        let mut market_fields = vec![
            "verdict",
            "source_ref",
            "request_digest",
            "notional",
            "rounding",
        ];
        if is_market {
            market_fields.push("reference_price");
        }
        row(&p["market"], &market_fields)?;
        let reference = if is_market {
            let reference = &p["market"]["reference_price"];
            bound_decimal_leaves(reference)?;
            if OnlyPrice::from_record(reference)?.to_record() != *reference {
                return Err(err("EXECUTION_REFERENCE_CANONICAL"));
            }
            reference
        } else {
            &r["price"]
        };
        let price = nonnegative(&reference["value"])?;
        let quantity = nonnegative(&r["quantity"]["value"])?;
        if price.is_zero() || quantity.is_zero() {
            return Err(err("EXECUTION_POSITIVE"));
        }
        let notional = &price * &quantity * self.contract_multiplier()?;
        let amount = settled_money(
            &p["market"],
            "notional",
            &notional,
            &self.config["currency"],
            self.precision,
        )?;
        let fee = nonnegative(&p["fee_budget"])?;
        money(&fee, self.precision)?;
        let order = id(&p["order"])?;
        let contract = p["fee_contract"]
            .as_object()
            .filter(|c| {
                c.len() == 3
                    && ["binding", "estimate", "funding"]
                        .iter()
                        .all(|k| c.contains_key(*k))
            })
            .ok_or_else(|| err("EXECUTION_FEE_CONTRACT_FIELDS"))?;
        let binding = &contract["binding"];
        let funding = &contract["funding"];
        for currency in [
            &binding["charge_currency"],
            &contract["estimate"]["reservation_charge"]["currency"],
            &funding["principal_reservation"]["currency"],
            &funding["fee_reservation"]["currency"],
            &funding["total_reservation"]["currency"],
        ] {
            if *currency != self.config["currency"] {
                return Err(err("EXECUTION_FEE_CURRENCY"));
            }
        }
        let cash_requirement = nonnegative(&funding["principal_reservation"]["amount"])?;
        if (buy && self.config["schema_version"] != 3 && cash_requirement < dec(&json!(amount))?)
            || fee < nonnegative(&funding["fee_reservation"]["amount"])?
            || fee < nonnegative(&contract["estimate"]["reservation_charge"]["amount"])?
        {
            return Err(err("EXECUTION_FUNDING_ENVELOPE"));
        }
        let spec = self.config["instruments"]
            .as_array()
            .expect("validated config")
            .iter()
            .find(|i| i["id"] == inst)
            .ok_or_else(|| err("EXECUTION_INSTRUMENT"))?;
        let quantity_precision = admission_quantity_precision(spec, r)?;
        id(&p["market"]["source_ref"])?;
        if p["market"]["verdict"] != "ACCEPT" || p["market"]["request_digest"] != hash(r) {
            return Err(err("EXECUTION_MARKET_ADMISSION"));
        }
        let mut settlement_owner = self.settlement_owner()?;
        self.admit_settlement_order(&mut settlement_owner, input, &inst, quantity_precision)?;
        let market_source = id(&p["market"]["source_ref"])?;
        if self.meta["markets"].get(market_source).is_some() {
            return Err(err("EXECUTION_ECONOMIC_SOURCE_ALIAS"));
        }
        // Only the first activation needs a prospective Ledger owner; an active
        // Ledger is read directly. No Account/Position/Order/history fork.
        let mut activated = None;
        if boundary(self.ledger.snapshot(cluster))?["status"] == "CREATED" {
            let mut ledger = self.ledger.as_ref().clone();
            if boundary(ledger.apply(&self.ledger_command(
                input,
                "ACTIVATE",
                json!({"schema_version":1}),
                0,
            )))?
            .status
                != onlyalpha_strategy_ledger::Status::Applied
            {
                return Err(err("EXECUTION_LEDGER_NOT_APPLIED"));
            }
            activated = Some(ledger);
        }
        let risk_cash = if self.config["schema_version"] == 3 {
            nonnegative(&p["collateral"]["instruction"]["amount"])?
        } else {
            cash_requirement.clone()
        };
        let mut req = json!({"schema_version":1,"request_id":r["request_id"]["value"],"instrument":inst,"side":side,"effect":if buy{"OPEN"}else{"CLOSE"},"position_side":"LONG","position_mode":"NETTING","order_type":r["order_type"],"quantity":quantity.to_plain_string(),"price":if is_market{Value::Null}else{json!(price.to_plain_string())},"notional":amount,"fee":money(&fee,self.precision)?,"cash_requirement":if buy{money(&risk_cash,self.precision)?}else{money(&BigDecimal::zero(),self.precision)?}});
        for f in ["quantity", "price", "notional", "fee", "cash_requirement"] {
            if !req[f].is_null() {
                req[f] = json!(dec(&req[f])?.normalized().to_plain_string());
            }
        }
        let n = input["runtime_sequence"].as_u64().expect("validated") * 64;
        let envelope = |family: &str, data: Value| json!({"schema_version":1,"family":family,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"generation":input["generation"],"cluster":cluster,"instrument":inst,"revision":input["revision"],"source_ref":format!("{}-{family}",input["input_id"].as_str().expect("validated")),"version":n,"as_of_sequence":n,"source_digest":hash(&data),"data":data});
        // These owners contain only this composition's holds. Gross cash is BEFORE those same-owner holds.
        let account = self.account.snapshot();
        let ledger = boundary(
            activated
                .as_ref()
                .unwrap_or(self.ledger.as_ref())
                .snapshot(cluster),
        )?;
        let (aq, cq) = if buy {
            ("0".to_owned(), "0".to_owned())
        } else {
            let a = boundary(self.position.account(&inst))?;
            let c = boundary(self.position.cluster(cluster, &inst))?;
            let state = self.position.state();
            let reservations = state["reservations"]
                .as_array()
                .ok_or_else(|| err("EXECUTION_RESERVATIONS"))?;
            let mut aa = dec(&a["available"])?;
            let mut ca = dec(&c["available"])?;
            for h in reservations {
                if h["instrument"] == inst {
                    let remaining = dec(&h["remaining"])?;
                    aa += &remaining;
                    if h["cluster"] == cluster {
                        ca += remaining;
                    }
                }
            }
            (aa.to_plain_string(), ca.to_plain_string())
        };
        let cash_field = if self.config["schema_version"] == 3 {
            "equity"
        } else {
            "cash"
        };
        let views = json!({"schema_version":1,"account":envelope("ACCOUNT",json!({"schema_version":1,"status":account["status"],"cash":account[cash_field]})),"ledger":envelope("LEDGER",json!({"schema_version":1,"status":ledger["status"],"cash":ledger[cash_field]})),"position":envelope("POSITION",json!({"schema_version":1,"account_available":aq,"allocation_available":cq,"position_side":"LONG","position_mode":"NETTING"})),"market":envelope("MARKET",json!({"schema_version":1,"request_digest":hash(&req),"verdict":"ACCEPT","code":"OK"}))});
        let mut risk = self.risk.as_ref().clone();
        let evaluated = boundary(risk.apply(&self.risk_command(
            input,
            "EVALUATE",
            json!({"schema_version":1,"request":req,"views":views}),
            1,
        )))?;
        if evaluated.status != onlyalpha_risk::Status::Applied {
            return Err(err("EXECUTION_RISK_NOT_APPLIED"));
        }
        let decision = evaluated
            .decision
            .ok_or_else(|| err("EXECUTION_RISK_DECISION"))?;
        if decision["outcome"] != "ACCEPT" {
            return Err(err("EXECUTION_RISK_DENIED"));
        }
        let reserve = json!({"schema_version":1,"reservation":order,"order":order,"amount":money(&(&cash_requirement+&fee),self.precision)?});
        if buy
            && let Err(error) = self.account.check_new_reservation_capacity(&self.command(
                input,
                "RESERVE",
                reserve.clone(),
                2,
            ))
        {
            if error.0 != "ACCOUNT_JOURNAL_BOUND" {
                return Err(Error(error.0));
            }
            // Preserve the old failure order: a malformed proposed Order/fee
            // contract is an error even when Account has no admission capacity.
            let mut order_owner = self.order.as_ref().clone();
            let created = boundary(order_owner.apply(&Self::order_creation(input)))?;
            if created.result != onlyalpha_order::ApplyResult::Applied
                || created.snapshot.as_ref().map(|s| s.order_id().value()) != Some(order)
            {
                return Err(err("EXECUTION_ORDER_IDENTITY"));
            }
            let fee = self.order_fee(input, order, &p["fee_contract"]);
            if boundary(order_owner.apply(&fee))?.result != onlyalpha_order::ApplyResult::Applied {
                return Err(err("EXECUTION_ORDER_NOT_APPLIED"));
            }
            return Err(err("EXECUTION_ACCOUNT_CAPACITY_DENIED"));
        }
        // Both ordinary rejections are settled before any owning mutation.
        Arc::make_mut(&mut self.meta)["settlement_authority"] = settlement_owner.checkpoint();
        self.economic_source("markets", &p["market"])?;
        if let Some(ledger) = activated {
            self.ledger = Arc::new(ledger);
        }
        self.risk = Arc::new(risk);
        self.create_order(input, order)?;
        self.bind_order_fee(input, order, &p["fee_contract"])?;

        if buy {
            // Only this actual new-risk RESERVE can produce the distinct
            // Execution rejection. Source/restore/codec errors retain their codes.
            // A capacity error after the exact preflight is unexpected and
            // poisons unpublished work; it is never a normal rollback result.
            self.account_apply(&self.command(input, "RESERVE", reserve.clone(), 2))?;
            self.ledger_apply(&self.ledger_command(input, "RESERVE", reserve, 2))?;
        } else {
            self.reserve_position(input, &inst)?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "RESERVE",
            json!({"schema_version":1,"request_id":r["request_id"]["value"],"order":order}),
            2,
        ))?;
        self.begin_order_submission(input, order)?;
        if buy {
            let stage = json!({"schema_version":1,"reservation":order,"stage":"SENT_TO_BROKER"});
            self.account_apply(&self.command(input, "STAGE", stage.clone(), 3))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", stage, 3))?;
        } else {
            self.stage_position(input, "SENT_TO_BROKER", 3)?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"SENT"}),
            3,
        ))?;
        let mut relation = json!({"cluster":cluster,"revision":input["revision"],"instrument":inst,"side":side,"request":r,"fee_contract":p["fee_contract"]});
        if whole_fill {
            relation["settlement_fill_contract"] = p["settlement_fill_contract"].clone();
        }
        Arc::make_mut(&mut self.meta)["orders"][order] = relation;
        self.admit_collateral(input)?;
        Ok(())
    }
    pub(crate) fn apply_order_submission(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "outcome"])?;
        let order = text(&p["order"])?;
        let mut c = self.order_local(input, "SUBMIT_RESULT", order);
        c["outcome"] = json!(match text(&p["outcome"])? {
            "DISPATCHED" => "KNOWN_RESULT",
            "UNKNOWN" => "UNKNOWN",
            _ => return Err(err("EXECUTION_SUBMISSION_OUTCOME")),
        });
        self.order_apply(&c)?;
        Ok(())
    }
    pub(crate) fn submission(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "outcome"])?;
        let r = self.relation(input)?;
        let order = text(&p["order"])?;
        self.apply_order_submission(input)?;
        if p["outcome"] == "DISPATCHED" {
            return Ok(());
        }
        let stage = "SUBMIT_UNKNOWN";
        if r["side"] == "BUY" {
            let payload = json!({"schema_version":1,"reservation":order,"stage":stage});
            self.account_apply(&self.command(input, "STAGE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", payload, 0))?;
        } else {
            let _ = boundary(self.position.reservation(order))?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"UNKNOWN"}),
            0,
        ))?;
        Ok(())
    }
    pub(crate) fn apply_spot_order_accept(
        &mut self,
        input: &Value,
        order: &str,
    ) -> Result<(), Error> {
        let payload = &input["payload"];
        row(payload, &["order", "venue_order"])?;
        let venue_order = id(&payload["venue_order"])?;
        let mut command = self.external(input, "ACCEPT", order);
        command["venue_order_id"] = json!(venue_order);
        self.order_apply(&command)?;
        Ok(())
    }
    pub(crate) fn accept(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "venue_order"])?;
        let relation = self.relation(input)?;
        let order = id(&p["order"])?;
        if let Some(broker) = input.get("broker_record") {
            id(&p["venue_order"])?;
            self.apply_native_order_fact(input, order, broker)?;
        } else {
            self.apply_spot_order_accept(input, order)?;
        }
        if relation["side"] == "BUY" {
            let payload =
                json!({"schema_version":1,"reservation":order,"stage":"BROKER_ACKNOWLEDGED"});
            self.account_apply(&self.command(input, "STAGE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", payload, 0))?;
        } else {
            self.stage_position(input, "BROKER_ACKNOWLEDGED", 0)?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"ACKNOWLEDGED"}),
            0,
        ))?;
        Ok(())
    }
    pub(crate) fn apply_order_cancel(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "request_id", "reason"])?;
        let order = id(&p["order"])?;
        id(&p["request_id"])?;
        text(&p["reason"])?;
        let mut c = self.order_local(input, "CANCEL", order);
        c["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":p["request_id"]},"order_id":{"schema_version":1,"value":order},"reason":p["reason"],"metadata":{}});
        self.order_apply(&c)?;
        Ok(())
    }
    pub(crate) fn cancel(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "request_id", "reason"])?;
        let relation = self.relation(input)?;
        let order = id(&p["order"])?;
        self.apply_order_cancel(input)?;
        if relation["side"] == "BUY" {
            let payload =
                json!({"schema_version":1,"reservation":order,"stage":"CANCEL_REQUESTED"});
            self.account_apply(&self.command(input, "STAGE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", payload, 0))?;
        } else {
            self.release_position(input, false)?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"CANCEL_PENDING"}),
            0,
        ))?;
        Ok(())
    }
    pub(crate) fn apply_spot_order_fill(
        &mut self,
        input: &Value,
        order: &str,
    ) -> Result<Value, Error> {
        let p = &input["payload"];
        let before = boundary(self.order.get(text(&input["cluster"])?, order))?.to_record();
        let precision = if before["order_type"] == "MARKET" {
            &p["price_precision"]
        } else {
            &before["price"]["precision"]
        };
        let mut command = self.external(input, "FILL", order);
        command["fill"] = json!({"schema_version":1,"trade_id":{"schema_version":1,"value":p["trade"]},"order_id":{"schema_version":1,"value":order},"price":{"schema_version":1,"value":p["price"],"precision":precision},"quantity":{"schema_version":1,"value":p["quantity"],"precision":before["quantity"]["precision"]},"ts_event":{"schema_version":1,"unix_nanos":input["time"]},"ts_init":{"schema_version":1,"unix_nanos":input["time"]},"venue_trade_id":{"schema_version":1,"value":p["venue_trade"]},"venue_order_id":{"schema_version":1,"value":p["venue_order"]},"liquidity_side":"UNKNOWN","external_sequence":input["runtime_sequence"],"external_event_id":input["source_ref"],"metadata":{},"reference_price":null});
        self.order_apply(&command)
    }
    pub(crate) fn fill(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        let relation = self.relation(input)?;
        let is_market = relation["request"]["order_type"] == "MARKET";
        let mut fields = vec![
            "order",
            "trade",
            "venue_trade",
            "venue_order",
            "quantity",
            "price",
            "fees",
            "settlement",
            "valuation",
            "collateral",
        ];
        if is_market {
            fields.push("price_precision");
        }
        row(p, &fields)?;
        let order = id(&p["order"])?;
        if let Some(contract) = relation.get("settlement_fill_contract") {
            self.validate_whole_fill_contract(
                &relation["request"],
                &relation["fee_contract"],
                contract,
            )?;
            if self.meta["settlement_authority"]["orders"][order]["fill_contract"] != *contract
                || nonnegative(&p["quantity"])?
                    != nonnegative(&relation["request"]["quantity"]["value"])?
                || self.meta["settlement_authority"]["instructions"]
                    .as_object()
                    .ok_or_else(|| err("EXECUTION_SETTLEMENT_STATE"))?
                    .values()
                    .any(|v| v["instruction"]["input"]["order"] == order)
            {
                return Err(err("EXECUTION_WHOLE_FILL_QUANTITY_OR_COUNT"));
            }
        }
        let cluster = text(&input["cluster"])?;
        let inst = text(&relation["instrument"])?;
        for f in ["trade", "venue_trade", "venue_order"] {
            id(&p[f])?;
        }
        let fee = &p["fees"];
        let perpetual = self.config["schema_version"] == 3;
        let mut fee_fields = vec![
            "instruction",
            "source_ref",
            "policy",
            "order",
            "trade",
            "currency",
            "scope",
            "family",
            "version",
            "as_of_sequence",
            "source_digest",
        ];
        if perpetual {
            fee_fields.push("assessment_fingerprint");
            if fee["assessment_fingerprint"] != onlyalpha_fee::digest(&input["fee_assessment"]) {
                return Err(err("EXECUTION_FEE_ASSESSMENT_SOURCE"));
            }
        } else {
            fee_fields.extend(["charge_target", "rebate_target"]);
        }
        row(fee, &fee_fields)?;
        let settlement = &p["settlement"];
        row(
            settlement,
            &[
                "instruction",
                "source_ref",
                "order",
                "trade",
                "currency",
                "model",
                "calendar",
                "policy",
                "gross_notional",
                "rounding",
                "scope",
                "family",
                "version",
                "as_of_sequence",
                "source_digest",
            ],
        )?;
        let valuation = &p["valuation"];
        row(
            valuation,
            &[
                "source_ref",
                "currency",
                "mark",
                "scope",
                "family",
                "version",
                "as_of_sequence",
                "source_digest",
            ],
        )?;
        let expected_scope = json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"runtime_kind":input["runtime_kind"],"cluster":input["cluster"],"revision":input["revision"],"instrument":inst,"request":relation["request"]["request_id"]["value"]});
        for (proof, family) in [
            (fee, "ORDER_FEE_ACCRUAL"),
            (settlement, "SETTLEMENT"),
            (valuation, "VALUATION"),
        ] {
            if proof["scope"] != expected_scope
                || proof["family"] != family
                || proof["currency"] != self.config["currency"]
                || proof["as_of_sequence"] != input["runtime_sequence"]
                || uint(&proof["version"])? == 0
            {
                return Err(err("EXECUTION_SOURCE_SCOPE_OR_WATERMARK"));
            }
            id(&proof["source_ref"])?;
            let mut data = proof.clone();
            let expected = data
                .as_object_mut()
                .expect("row")
                .remove("source_digest")
                .expect("row");
            if expected != hash(&data) {
                return Err(err("EXECUTION_SOURCE_DIGEST"));
            }
        }
        if fee["policy"] != relation["fee_contract"]["binding"]["fingerprint"] {
            return Err(err("EXECUTION_FEE_BINDING_CONFLICT"));
        }
        self.economic_source("valuations", valuation)?;
        let mark = nonnegative(&valuation["mark"])?;
        if mark.is_zero() {
            return Err(err("EXECUTION_MARK_REQUIRED"));
        }
        for proof in [fee, settlement] {
            for f in ["instruction", "source_ref"] {
                id(&proof[f])?;
            }
            if proof["order"] != p["order"]
                || proof["trade"] != p["trade"]
                || proof["currency"] != self.config["currency"]
            {
                return Err(err("EXECUTION_ECONOMIC_PROOF_SCOPE"));
            }
        }
        if settlement["model"]
            != if perpetual {
                "LINEAR_PERPETUAL_OPEN"
            } else {
                "CASH_SETTLEMENT"
            }
        {
            return Err(err("EXECUTION_SETTLEMENT_UNAVAILABLE"));
        }
        let schedule = if perpetual {
            json!({"asset_booked":input["trading_day"],"cash_booked":input["trading_day"],"cash_trade_available":input["trading_day"],"asset_trade_available":input["trading_day"],"cash_withdrawable":input["trading_day"]})
        } else {
            boundary(onlyalpha_settlement::resolve_schedule(
                &settlement["calendar"],
                &settlement["policy"],
                text(&input["trading_day"])?,
            ))?
        };
        // These existing cash consumers book immediately. Other shapes need explicit owning support.
        if ["asset_booked", "cash_booked", "cash_trade_available"]
            .iter()
            .any(|k| schedule[k] != input["trading_day"])
        {
            return Err(err("EXECUTION_SETTLEMENT_ECONOMIC_SHAPE_UNSUPPORTED"));
        }
        let initial_bucket = if relation["side"] == "BUY"
            && schedule["asset_trade_available"] != input["trading_day"]
        {
            "UNSETTLED"
        } else {
            "SETTLED"
        };
        let cash_withdrawable = schedule["cash_withdrawable"] == input["trading_day"];
        fp(&fee["policy"])?;
        let mut fee_owner = boundary(onlyalpha_fee::Manager::new(
            json!({"engine":self.config["engine"],"runtime":self.config["runtime"],"account":self.config["account"],"gateway":self.config["gateway"],"runtime_kind":self.config["runtime_kind"],"generation":self.config["generation"]}),
            4096,
        ))?;
        boundary(fee_owner.restore(
            &self.meta["fee_authority"],
            &onlyalpha_fee::digest(&self.meta["fee_authority"]),
        ))?;
        let application = if perpetual {
            let a = crate::perpetual_fees::decode_assessment(&input["fee_assessment"])?;
            boundary(fee_owner.apply(&a))?
        } else {
            boundary(fee_owner.apply_admitted_target(fee))?
        }
        .record();
        if application["id"] != fee["instruction"] {
            return Err(err("EXECUTION_FEE_APPLICATION"));
        }
        let charges = money(&nonnegative(&application["charges"])?, self.precision)?;
        let rebates = money(&nonnegative(&application["rebates"])?, self.precision)?;
        Arc::make_mut(&mut self.meta)["fee_authority"] = fee_owner.checkpoint();
        let price = nonnegative(&p["price"])?;
        let qty = nonnegative(&p["quantity"])?;
        let buy = relation["side"] == "BUY";
        validate_fill_price(&relation["request"], &price, &qty)?;
        let multiplier = self.contract_multiplier()?;
        let notional = &price * &qty * &multiplier;
        let notional_s = settled_money(
            settlement,
            "gross_notional",
            &notional,
            &self.config["currency"],
            self.precision,
        )?;
        let after_order = if perpetual {
            self.apply_native_order_fact(input, order, &input["broker_record"])?
        } else {
            self.apply_spot_order_fill(input, order)?
        };
        let terminal = after_order["status"] == "FILLED";
        let before_alloc = match self.position.cluster(cluster, inst) {
            Ok(v) => Some(v),
            Err(e) if e.0 == "POSITION_ALLOCATION_NOT_FOUND" => None,
            Err(e) => return Err(Error(e.to_string())),
        };
        let before_account = self.account.snapshot();
        let position_command = self.position_trade_command(
            input,
            inst,
            &relation["request"],
            &json!({"charges":charges,"rebates":rebates}),
            initial_bucket,
            terminal,
        )?;
        let fact = self.position_apply(&position_command)?;
        let original_trade = if perpetual {
            Some(boundary(self.position.trade_evidence(text(&p["trade"])?))?)
        } else {
            None
        };
        let allocation = boundary(self.position.cluster(cluster, inst))?;
        let pos = boundary(self.position.account(inst))?;
        let rd = exact(&fact["realized_pnl"])?;
        if self.meta["marks"][cluster].is_null() {
            Arc::make_mut(&mut self.meta)["marks"][cluster] = json!({});
        }
        Arc::make_mut(&mut self.meta)["marks"][cluster][inst] =
            json!(mark.normalized().to_plain_string());
        let position_state = self.position.state();
        let mut new_market = BigDecimal::zero();
        let mut total_cost = BigDecimal::zero();
        for book in position_state["allocations"]
            .as_array()
            .ok_or_else(|| err("EXECUTION_POSITION_VIEW"))?
        {
            let instrument = text(&book["instrument"])?;
            let snapshot = &book["snapshot"];
            let owner = text(&book["cluster"])?;
            let mark = exact(&self.meta["marks"][owner][instrument])?;
            let gross = exact(&snapshot["quantity"])? * mark * &multiplier;
            new_market += if perpetual {
                gross
            } else {
                gross.with_scale_round(
                    i64::from(self.precision),
                    bigdecimal::RoundingMode::HalfEven,
                )
            };
            total_cost += exact(&snapshot["cost"])? * &multiplier;
        }
        let old_market = dec(&before_account["market_value"])?;
        let unrealized = &new_market - total_cost;
        let account_market_delta = if perpetual {
            unrealized.with_scale_round(
                i64::from(self.precision),
                bigdecimal::RoundingMode::HalfEven,
            )
        } else {
            new_market
        } - old_market;
        let ledger_before = allocation_before(before_alloc.as_ref(), self.precision)?;
        let ledger_after = allocation_witness(&allocation, self.precision)?;
        let ledger_trade = self.ledger_command(input,"TRADE",json!({"schema_version":1,"trade":p["trade"],"execution":format!("ETX-{}",super::perpetual::cause(input)),"venue_trade":p["venue_trade"],"order":order,"fee_instruction":fee["instruction"],"source_sequence":input["runtime_sequence"],"side":relation["side"],"instrument":inst,"notional":notional_s,"charges":charges,"rebates":rebates,"reservation":if buy{json!(order)}else{Value::Null},"terminal_fill":terminal,"before":ledger_before,"after":ledger_after,"allocation_evidence":hash(&allocation),"mark":valuation["mark"],"multiplier":multiplier.normalized().to_plain_string()}),0);
        if let Some(original) = &original_trade {
            if boundary(
                Arc::make_mut(&mut self.ledger).apply_position_trade(&ledger_trade, original),
            )?
            .status
                != onlyalpha_strategy_ledger::Status::Applied
            {
                return Err(err("EXECUTION_LEDGER_NOT_APPLIED"));
            }
        } else {
            self.ledger_apply(&ledger_trade)?;
        }
        let mut rounding_adjustment = BigDecimal::zero();
        for cluster in self.config["profiles"]
            .as_object()
            .expect("profiles")
            .keys()
        {
            rounding_adjustment +=
                exact(&boundary(self.ledger.snapshot(cluster))?["realized_rounding_adjustment"])?;
        }
        let account_trade = self.command(input,"TRADE",json!({"schema_version":1,"trade":p["trade"],"execution":format!("ETX-{}",super::perpetual::cause(input)),"venue_trade":p["venue_trade"],"order":order,"sequence":input["runtime_sequence"],"side":relation["side"],"notional":notional_s,"fee_instruction":fee["instruction"],"charges":charges,"rebates":rebates,"realized_pnl_delta":exact_record(&rd,self.precision),"position_evidence":hash(&pos),"market_value_delta":money(&account_market_delta,self.precision)?,"unrealized_pnl":exact_record(&unrealized,self.precision),"realized_rounding_adjustment":exact_record(&rounding_adjustment,self.precision),"reservation":if buy{json!(order)}else{Value::Null},"terminal_fill":terminal,"cash_withdrawable":cash_withdrawable}),0);
        if let Some(original) = &original_trade {
            if boundary(
                Arc::make_mut(&mut self.account).apply_position_trade(&account_trade, original),
            )?
            .status
                != onlyalpha_account::Status::Applied
            {
                return Err(err("EXECUTION_ACCOUNT_NOT_APPLIED"));
            }
        } else {
            self.account_apply(&account_trade)?;
        }
        let instruction = self.settlement_instruction(
            input,
            &position_command["payload"],
            &json!({"notional":notional_s,"rebates":rebates}),
            &pos,
            &allocation,
        )?;
        let mut owner = self.settlement_owner()?;
        boundary(owner.register(&instruction))?;
        Arc::make_mut(&mut self.meta)["settlement_authority"] = owner.checkpoint();
        self.risk_apply(&self.risk_command(input,"FILL",json!({"schema_version":1,"order":order,"trade":p["trade"],"source_ref":input["source_ref"],"quantity":p["quantity"],"notional":notional_s,"final_fill":terminal}),0))?;
        self.fill_collateral(input)?;
        Ok(())
    }
    pub(crate) fn apply_order_terminal(&mut self, input: &Value, order: &str) -> Result<(), Error> {
        let outcome = text(&input["payload"]["outcome"])?;
        if !matches!(outcome, "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED") {
            return Err(err("EXECUTION_TERMINAL_UNPROVEN"));
        }
        if let Some(broker) = input.get("broker_record") {
            self.apply_native_order_fact(input, order, broker)?;
            return Ok(());
        }
        let mut command = self.external(input, outcome, order);
        if outcome == "REJECTED" {
            command["rejection"] = external_rejection(&Value::Null);
        }
        if outcome == "FAILED" {
            command["failure"] = json!({"schema_version":1,"code":"EXTERNAL_FAILURE","message":"explicit external failure"});
        }
        self.order_apply(&command)?;
        Ok(())
    }
    pub(crate) fn terminal(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "outcome", "collateral"])?;
        let relation = self.relation(input)?;
        let order = text(&p["order"])?;
        let outcome = text(&p["outcome"])?;
        self.apply_order_terminal(input, order)?;
        if relation["side"] == "BUY" {
            let payload = json!({"schema_version":1,"reservation":order,"outcome":outcome});
            self.account_apply(&self.command(input, "RELEASE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "RELEASE", payload, 0))?;
        } else {
            self.release_position(input, true)?;
        }
        self.risk_apply(&self.risk_command(input,"TERMINAL",json!({"schema_version":1,"order":order,"outcome":outcome,"source_ref":input["source_ref"]}),0))?;
        self.terminal_collateral(input)?;
        Ok(())
    }
}

impl Components {
    pub(crate) fn admit_settlement_order(
        &self,
        owner: &mut onlyalpha_settlement::Authority,
        input: &Value,
        instrument: &str,
        precision: u8,
    ) -> Result<(), Error> {
        let payload = &input["payload"];
        let request = &payload["request"];
        let scope = json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"runtime_kind":input["runtime_kind"],"cluster":input["cluster"],"revision":input["revision"],"instrument":instrument,"request":request["request_id"]["value"]});
        let order = id(&payload["order"])?;
        let side = text(&request["side"])?;
        let quantity = text(&request["quantity"]["value"])?;
        match payload["schema_version"].as_u64() {
            Some(1) => boundary(owner.admit_order(scope, order, side, quantity, precision)),
            Some(2) => {
                let contract = &payload["settlement_fill_contract"];
                self.validate_whole_fill_contract(request, &payload["fee_contract"], contract)?;
                boundary(
                    owner.admit_whole_fill_order(scope, order, side, quantity, precision, contract),
                )
            }
            _ => Err(err("EXECUTION_ADMISSION_SCHEMA")),
        }
    }
    pub(crate) fn settlement_instruction(
        &self,
        input: &Value,
        trade: &Value,
        economics: &Value,
        position: &Value,
        allocation: &Value,
    ) -> Result<onlyalpha_settlement::Instruction, Error> {
        let settlement = &input["payload"]["settlement"];
        boundary(onlyalpha_settlement::compile(
            json!({"schema_version":if self.config["schema_version"] == 3 {2}else{1},"scope":settlement["scope"],"order":trade["order"],"trade":trade["trade"],"currency":self.config["currency"],"side":trade["side"],"quantity":trade["quantity"],"gross_notional":economics["notional"],"charges":trade["fee"],"rebates":economics["rebates"],"trading_day":input["trading_day"],"time":input["time"],"calendar":settlement["calendar"],"policy":settlement["policy"],"position":position["id"],"position_cycle":position["cycle"],"allocation":allocation["id"],"allocation_cycle":allocation["cycle"],"provenance":{"reference":settlement["source_ref"],"fingerprint":settlement["source_digest"],"instruction":settlement["instruction"]}}),
        ))
    }
    pub(crate) fn settlement_owner(&self) -> Result<onlyalpha_settlement::Authority, Error> {
        let mut owner = boundary(onlyalpha_settlement::Authority::new(
            crate::components::settlement_config(&self.config),
            512,
        ))?;
        boundary(owner.restore(
            &self.meta["settlement_authority"],
            &onlyalpha_settlement::digest(&self.meta["settlement_authority"]),
        ))?;
        Ok(owner)
    }
    fn settlement_maturity(&mut self, input: &Value) -> Result<(), Error> {
        let mut owner = self.settlement_owner()?;
        let (effect, instrument) = Self::settlement_effect(&mut owner, input)?;
        if let Some(payload) = self.settle_position(input, &effect, &instrument)? {
            self.ledger_apply(&self.ledger_command(input, "SETTLEMENT", payload, 0))?;
        }
        if !nonnegative(&effect["cash_amount"])?.is_zero() {
            self.account_apply(&self.command(input,"SETTLE",json!({"schema_version":1,"instruction":effect["id"],"source_trade":effect["trade"],"amount":effect["cash_amount"]}),0))?;
        }
        Arc::make_mut(&mut self.meta)["settlement_authority"] = owner.checkpoint();
        Ok(())
    }
    pub(crate) fn settlement_effect(
        owner: &mut onlyalpha_settlement::Authority,
        input: &Value,
    ) -> Result<(Value, String), Error> {
        let p = &input["payload"];
        row(p, &["instruction", "expected_version"])?;
        let id = text(&p["instruction"])?;
        let before = boundary(owner.snapshot(id))?;
        if before["version"] != p["expected_version"] {
            return Err(err("EXECUTION_SETTLEMENT_PRECONDITION"));
        }
        let original = &before["instruction"]["input"];
        if original["scope"]["cluster"] != input["cluster"]
            || original["scope"]["revision"] != input["revision"]
        {
            return Err(err("EXECUTION_SETTLEMENT_SCOPE"));
        }
        let instrument = text(&original["scope"]["instrument"])?.to_owned();
        let effect = boundary(owner.mature(
            id,
            text(&input["trading_day"])?,
            input["time"].clone(),
            uint(&p["expected_version"])?,
        ))?
        .record();
        Ok((effect, instrument))
    }
    pub(crate) fn settle_position(
        &mut self,
        input: &Value,
        effect: &Value,
        instrument: &str,
    ) -> Result<Option<Value>, Error> {
        if nonnegative(&effect["asset_quantity"])?.is_zero() {
            return Ok(None);
        }
        let cluster = text(&input["cluster"])?;
        let position = boundary(self.position.account(instrument))?;
        let allocation = boundary(self.position.cluster(cluster, instrument))?;
        if position["id"] != effect["position"]
            || position["cycle"] != effect["position_cycle"]
            || allocation["id"] != effect["allocation"]
            || allocation["cycle"] != effect["allocation_cycle"]
        {
            return Err(err("EXECUTION_SETTLEMENT_LIFECYCLE"));
        }
        self.position_apply(&self.command(input,"SETTLE",json!({"schema_version":1,"instrument":instrument,"trading_day":input["trading_day"],"source":effect["id"],"buckets":[{"schema_version":1,"cluster":cluster,"quantity":effect["asset_quantity"]}]}),0))?;
        let after = boundary(self.position.cluster(cluster, instrument))?;
        Ok(Some(
            json!({"schema_version":1,"instruction":effect["id"],"instrument":instrument,"before":allocation_witness(&allocation,self.precision)?,"after":allocation_witness(&after,self.precision)?,"before_evidence":hash(&allocation),"allocation_evidence":hash(&after)}),
        ))
    }
}

pub(crate) fn allocation_before(allocation: Option<&Value>, precision: u8) -> Result<Value, Error> {
    if let Some(allocation) = allocation {
        return allocation_witness(allocation, precision);
    }
    let zero = money(&BigDecimal::zero(), precision)?;
    Ok(
        json!({"schema_version":1,"identity":null,"cycle":0,"realized_exact":zero,"quantity":"0","cost":zero,"realized":zero,"version":0}),
    )
}

pub(crate) fn allocation_witness(a: &Value, p: u8) -> Result<Value, Error> {
    Ok(
        json!({"schema_version":1,"identity":a["id"],"cycle":a["cycle"],"realized_exact":exact_record(&exact(&a["realized_exact"])?,p),"quantity":a["quantity"],"cost":exact_record(&exact(&a["cost"])?,p),"realized":exact_record(&exact(&a["realized_pnl"])?,p),"version":a["version"]}),
    )
}

#[cfg(test)]
#[path = "tests/admission_preview_tests.rs"]
mod admission_preview_tests;
