use crate::{Components, Prepared, model::*};
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{base::OnlyDomainModel, execution::OnlyOrderRequest};
use serde_json::{Value, json};
impl Components {
    pub fn prepare<S: crate::Store>(&self, store: &S, input: &Value) -> Result<Prepared, Error> {
        self.ready_source(store)?;
        if self.pending.is_some() {
            return Err(err("EXECUTION_PENDING"));
        }
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
        for f in ["input_id", "source_ref"] {
            id(&input[f])?;
        }
        let n = uint(&input["runtime_sequence"])?;
        if n == 0
            || n > u64::MAX / 16
            || n <= self.meta["last_runtime_sequence"].as_u64().unwrap_or(0)
        {
            return Err(err("EXECUTION_RUNTIME_SEQUENCE"));
        }
        if self.meta["inputs"].get(text(&input["input_id"])?).is_some()
            || self.meta["sources"]
                .get(text(&input["source_ref"])?)
                .is_some()
        {
            return Err(err("EXECUTION_INPUT_ALIAS"));
        }
        let before = self.payloads()?;
        let mut candidate = Self::new(self.config.clone())?;
        let checkpoint = self.checkpoint()?;
        candidate.restore(&checkpoint, &hash(&checkpoint))?;
        match text(&input["op"])? {
            "ADMIT" => candidate.admit(input)?,
            "SUBMISSION" => candidate.submission(input)?,
            "ACCEPT" => candidate.accept(input)?,
            "CANCEL" => candidate.cancel(input)?,
            "FILL" => candidate.fill(input)?,
            "SETTLEMENT_MATURITY" => candidate.settlement_maturity(input)?,
            "TERMINAL" => candidate.terminal(input)?,
            _ => return Err(err("EXECUTION_OPERATION")),
        };
        candidate.meta["inputs"][text(&input["input_id"])?] = json!(hash(input));
        candidate.meta["sources"][text(&input["source_ref"])?] = json!(hash(input));
        candidate.meta["last_runtime_sequence"] = json!(n);
        candidate.meta["transactions"][self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?
            .to_string()] = json!(format!("ETX-{}", hash(input)));
        let after = candidate.payloads()?;
        let projections:Vec<_>=before.iter().zip(after).enumerate().map(|(i,(b,a))|json!({"schema_version":1,"component":COMPONENTS[i],"before_hash":hash(b),"result_hash":hash(&a),"result":a})).collect();
        let tx = format!("ETX-{}", hash(input));
        let sequence = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?;
        Prepared::new(
            json!({"schema_version":1,"transaction_id":tx,"config_hash":hash(&self.config),"sequence":sequence,"predecessor":self.sequence,"input":input,"projections":projections,"events":[{"schema_version":1,"event_id":format!("{tx}-EVENT-1"),"transaction_id":tx,"sequence":sequence,"input":input}]}),
        )
    }
    fn command(&self, input: &Value, op: &str, payload: Value, suffix: u64) -> Value {
        json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"command_id":format!("{}-{suffix}",input["input_id"].as_str().expect("validated")),"cause":hash(input),"time":input["time"],"op":op,"payload":payload})
    }
    fn ledger_command(&self, input: &Value, op: &str, payload: Value, suffix: u64) -> Value {
        let mut c = self.command(input, op, payload, suffix);
        c.as_object_mut().expect("object").remove("gateway");
        c["cluster"] = input["cluster"].clone();
        c["runtime_sequence"] =
            json!(input["runtime_sequence"].as_u64().expect("validated") * 16 + suffix);
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
    fn order_apply(&mut self, c: &Value) -> Result<Value, Error> {
        let o = boundary(self.order.apply(c))?;
        if o.result != onlyalpha_order::ApplyResult::Applied {
            return Err(err("EXECUTION_ORDER_NOT_APPLIED"));
        }
        Ok(o.snapshot.map(|s| s.to_record()).unwrap_or(Value::Null))
    }
    fn account_apply(&mut self, c: &Value) -> Result<(), Error> {
        if boundary(self.account.apply(c))?.status != onlyalpha_account::Status::Applied {
            return Err(err("EXECUTION_ACCOUNT_NOT_APPLIED"));
        }
        Ok(())
    }
    fn ledger_apply(&mut self, c: &Value) -> Result<(), Error> {
        if boundary(self.ledger.apply(c))?.status != onlyalpha_strategy_ledger::Status::Applied {
            return Err(err("EXECUTION_LEDGER_NOT_APPLIED"));
        }
        Ok(())
    }
    fn position_apply(&mut self, c: &Value) -> Result<Value, Error> {
        let o = boundary(self.position.apply(c))?;
        if o.status != onlyalpha_position::Status::Applied {
            return Err(err("EXECUTION_POSITION_NOT_APPLIED"));
        }
        Ok(o.fact.unwrap_or(Value::Null))
    }
    fn risk_apply(&mut self, c: &Value) -> Result<Option<Value>, Error> {
        let o = boundary(self.risk.apply(c))?;
        if o.status != onlyalpha_risk::Status::Applied {
            return Err(err("EXECUTION_RISK_NOT_APPLIED"));
        }
        Ok(o.decision)
    }
    fn relation(&self, input: &Value) -> Result<Value, Error> {
        let order = id(&input["payload"]["order"])?;
        let r = self.meta["orders"]
            .get(order)
            .ok_or_else(|| err("EXECUTION_ORDER_RELATION"))?;
        if r["cluster"] != input["cluster"] || r["revision"] != input["revision"] {
            return Err(err("EXECUTION_ORDER_OWNER"));
        }
        Ok(r.clone())
    }
    fn economic_source(&mut self, family: &str, proof: &Value) -> Result<(), Error> {
        let source = id(&proof["source_ref"])?;
        if self.meta[family].get(source).is_some() {
            return Err(err("EXECUTION_ECONOMIC_SOURCE_ALIAS"));
        }
        self.meta[family][source] = json!(hash(proof));
        Ok(())
    }
    fn admit(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(
            p,
            &["request", "fee_contract", "fee_budget", "market", "order"],
        )?;
        bound_decimal_leaves(&p["request"])?;
        bound_decimal_leaves(&p["fee_contract"])?;
        let request = OnlyOrderRequest::from_record(&p["request"])?;
        if request.to_record() != p["request"] {
            return Err(err("EXECUTION_REQUEST_CANONICAL"));
        }
        let r = &p["request"];
        let side = text(&r["side"])?;
        let buy = side == "BUY";
        if buy {
            boundary(self.position.admit_new_risk())?;
        }
        let intent = &r["execution_intent"];
        if r["order_type"] != "LIMIT"
            || intent["position_side"] != "LONG"
            || intent["position_mode"] != "NETTING"
            || intent["side"] != r["side"]
            || intent["position_effect"] != if buy { "OPEN" } else { "CLOSE" }
            || !matches!(side, "BUY" | "SELL")
        {
            return Err(err("EXECUTION_UNSUPPORTED_SHAPE"));
        }
        let cluster = text(&input["cluster"])?;
        let inst = request.instrument_id().to_string();
        let price = nonnegative(&r["price"]["value"])?;
        let quantity = nonnegative(&r["quantity"]["value"])?;
        if price.is_zero() || quantity.is_zero() {
            return Err(err("EXECUTION_POSITIVE"));
        }
        let notional = &price * &quantity;
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
        if (buy && cash_requirement < dec(&json!(amount))?)
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
        if r["price"]["precision"] != spec["price_precision"]
            || r["quantity"]["precision"] != spec["quantity_precision"]
        {
            return Err(err("EXECUTION_INSTRUMENT_PRECISION"));
        }
        row(
            &p["market"],
            &[
                "verdict",
                "source_ref",
                "request_digest",
                "notional",
                "rounding",
            ],
        )?;
        id(&p["market"]["source_ref"])?;
        if p["market"]["verdict"] != "ACCEPT" || p["market"]["request_digest"] != hash(r) {
            return Err(err("EXECUTION_MARKET_ADMISSION"));
        }
        let mut settlement_owner = self.settlement_owner()?;
        boundary(settlement_owner.admit_order(json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"runtime_kind":input["runtime_kind"],"cluster":input["cluster"],"revision":input["revision"],"instrument":inst,"request":r["request_id"]["value"]}),order,side,text(&r["quantity"]["value"])?,u8::try_from(uint(&spec["quantity_precision"])?).map_err(|_|err("EXECUTION_QUANTITY_PRECISION"))?))?;
        self.meta["settlement_authority"] = settlement_owner.checkpoint();
        self.economic_source("markets", &p["market"])?;
        if boundary(self.ledger.snapshot(cluster))?["status"] == "CREATED" {
            self.ledger_apply(&self.ledger_command(
                input,
                "ACTIVATE",
                json!({"schema_version":1}),
                0,
            ))?;
        }
        let mut req = json!({"schema_version":1,"request_id":r["request_id"]["value"],"instrument":inst,"side":side,"effect":if buy{"OPEN"}else{"CLOSE"},"position_side":"LONG","position_mode":"NETTING","order_type":"LIMIT","quantity":quantity.to_plain_string(),"price":price.to_plain_string(),"notional":amount,"fee":money(&fee,self.precision)?,"cash_requirement":if buy{money(&cash_requirement,self.precision)?}else{money(&BigDecimal::zero(),self.precision)?}});
        for f in ["quantity", "price", "notional", "fee", "cash_requirement"] {
            req[f] = json!(dec(&req[f])?.normalized().to_plain_string());
        }
        let n = input["runtime_sequence"].as_u64().expect("validated") * 16;
        let envelope = |family: &str, data: Value| json!({"schema_version":1,"family":family,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"generation":input["generation"],"cluster":cluster,"instrument":inst,"revision":input["revision"],"source_ref":format!("{}-{family}",input["input_id"].as_str().expect("validated")),"version":n,"as_of_sequence":n,"source_digest":hash(&data),"data":data});
        // These owners contain only this composition's holds. Gross cash is BEFORE those same-owner holds.
        let account = self.account.snapshot();
        let ledger = boundary(self.ledger.snapshot(cluster))?;
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
        let views = json!({"schema_version":1,"account":envelope("ACCOUNT",json!({"schema_version":1,"status":account["status"],"cash":account["cash"]})),"ledger":envelope("LEDGER",json!({"schema_version":1,"status":ledger["status"],"cash":ledger["cash"]})),"position":envelope("POSITION",json!({"schema_version":1,"account_available":aq,"allocation_available":cq,"position_side":"LONG","position_mode":"NETTING"})),"market":envelope("MARKET",json!({"schema_version":1,"request_digest":hash(&req),"verdict":"ACCEPT","code":"OK"}))});
        let decision = self
            .risk_apply(&self.risk_command(
                input,
                "EVALUATE",
                json!({"schema_version":1,"request":req,"views":views}),
                1,
            ))?
            .ok_or_else(|| err("EXECUTION_RISK_DECISION"))?;
        if decision["outcome"] != "ACCEPT" {
            return Err(err("EXECUTION_RISK_DENIED"));
        }
        let created=self.order_apply(&json!({"schema_version":1,"op":"CREATE","cluster_id":cluster,"account_id":input["account"],"request":r,"cause":hash(input),"at":input["time"]}))?;
        if created["order_id"]["value"] != order {
            return Err(err("EXECUTION_ORDER_IDENTITY"));
        }
        let mut fc = self.order_local(input, "FEE", order);
        fc["contract"] = p["fee_contract"].clone();
        fc["contract"]["schema_version"] = json!(1);
        self.order_apply(&fc)?;
        let reserve = json!({"schema_version":1,"reservation":order,"order":order,"amount":money(&(&cash_requirement+&fee),self.precision)?});
        if buy {
            self.account_apply(&self.command(input, "RESERVE", reserve.clone(), 2))?;
            self.ledger_apply(&self.ledger_command(input, "RESERVE", reserve, 2))?;
        } else {
            self.position_apply(&self.command(input,"RESERVE",json!({"schema_version":1,"instrument":inst,"cluster":cluster,"order":order,"quantity":quantity.to_plain_string()}),2))?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "RESERVE",
            json!({"schema_version":1,"request_id":r["request_id"]["value"],"order":order}),
            2,
        ))?;
        self.order_apply(&self.order_local(input, "BEGIN_SUBMIT", order))?;
        if buy {
            let stage = json!({"schema_version":1,"reservation":order,"stage":"SENT_TO_BROKER"});
            self.account_apply(&self.command(input, "STAGE", stage.clone(), 3))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", stage, 3))?;
        } else {
            self.position_apply(&self.command(input,"STAGE",json!({"schema_version":1,"order":order,"cluster":cluster,"stage":"SENT_TO_BROKER"}),3))?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"SENT"}),
            3,
        ))?;
        self.meta["orders"][order] = json!({"cluster":cluster,"revision":input["revision"],"instrument":inst,"side":side,"request":r,"fee_contract":p["fee_contract"]});
        Ok(())
    }
    fn submission(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "outcome"])?;
        let r = self.relation(input)?;
        let order = text(&p["order"])?;
        let outcome = text(&p["outcome"])?;
        if !matches!(outcome, "UNKNOWN" | "DISPATCHED") {
            return Err(err("EXECUTION_SUBMISSION_OUTCOME"));
        }
        let mut c = self.order_local(input, "SUBMIT_RESULT", order);
        c["outcome"] = json!(if outcome == "DISPATCHED" {
            "KNOWN_RESULT"
        } else {
            outcome
        });
        self.order_apply(&c)?;
        if outcome == "DISPATCHED" {
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
    fn accept(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "venue_order"])?;
        let relation = self.relation(input)?;
        let order = id(&p["order"])?;
        id(&p["venue_order"])?;
        let mut c = self.external(input, "ACCEPT", order);
        c["venue_order_id"] = p["venue_order"].clone();
        self.order_apply(&c)?;
        if relation["side"] == "BUY" {
            let payload =
                json!({"schema_version":1,"reservation":order,"stage":"BROKER_ACKNOWLEDGED"});
            self.account_apply(&self.command(input, "STAGE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", payload, 0))?;
        } else {
            self.position_apply(&self.command(input,"STAGE",json!({"schema_version":1,"order":order,"cluster":input["cluster"],"stage":"BROKER_ACKNOWLEDGED"}),0))?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"ACKNOWLEDGED"}),
            0,
        ))?;
        Ok(())
    }
    fn cancel(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "request_id", "reason"])?;
        let relation = self.relation(input)?;
        let order = id(&p["order"])?;
        id(&p["request_id"])?;
        text(&p["reason"])?;
        let mut c = self.order_local(input, "CANCEL", order);
        c["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":p["request_id"]},"order_id":{"schema_version":1,"value":order},"reason":p["reason"],"metadata":{}});
        self.order_apply(&c)?;
        if relation["side"] == "BUY" {
            let payload =
                json!({"schema_version":1,"reservation":order,"stage":"CANCEL_REQUESTED"});
            self.account_apply(&self.command(input, "STAGE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "STAGE", payload, 0))?;
        } else {
            self.position_apply(&self.command(input,"RELEASE",json!({"schema_version":1,"order":order,"cluster":input["cluster"],"broker_confirmed":false}),0))?;
        }
        self.risk_apply(&self.risk_command(
            input,
            "STAGE",
            json!({"schema_version":1,"order":order,"stage":"CANCEL_PENDING"}),
            0,
        ))?;
        Ok(())
    }
    fn fill(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(
            p,
            &[
                "order",
                "trade",
                "venue_trade",
                "venue_order",
                "quantity",
                "price",
                "fees",
                "settlement",
                "valuation",
            ],
        )?;
        let relation = self.relation(input)?;
        let order = id(&p["order"])?;
        let cluster = text(&input["cluster"])?;
        let inst = text(&relation["instrument"])?;
        for f in ["trade", "venue_trade", "venue_order"] {
            id(&p[f])?;
        }
        let fee = &p["fees"];
        row(
            fee,
            &[
                "instruction",
                "source_ref",
                "policy",
                "order",
                "trade",
                "currency",
                "charge_target",
                "rebate_target",
                "scope",
                "family",
                "version",
                "as_of_sequence",
                "source_digest",
            ],
        )?;
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
        if settlement["model"] != "CASH_SETTLEMENT" {
            return Err(err("EXECUTION_SETTLEMENT_UNAVAILABLE"));
        }
        let schedule = boundary(onlyalpha_settlement::resolve_schedule(
            &settlement["calendar"],
            &settlement["policy"],
            text(&input["trading_day"])?,
        ))?;
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
        let application = boundary(fee_owner.apply_admitted_target(fee))?.record();
        let charges = money(&nonnegative(&application["charges"])?, self.precision)?;
        let rebates = money(&nonnegative(&application["rebates"])?, self.precision)?;
        self.meta["fee_authority"] = fee_owner.checkpoint();
        let before_order = boundary(self.order.get(cluster, order))?.to_record();
        let qp = before_order["quantity"]["precision"].clone();
        let pp = before_order["price"]["precision"].clone();
        let price = nonnegative(&p["price"])?;
        let qty = nonnegative(&p["quantity"])?;
        let limit = dec(&before_order["price"]["value"])?;
        let buy = relation["side"] == "BUY";
        if price.is_zero() || qty.is_zero() || (buy && price > limit) || (!buy && price < limit) {
            return Err(err("EXECUTION_LIMIT_OR_POSITIVE"));
        }
        let notional = &price * &qty;
        let notional_s = settled_money(
            settlement,
            "gross_notional",
            &notional,
            &self.config["currency"],
            self.precision,
        )?;
        let mut oc = self.external(input, "FILL", order);
        oc["fill"] = json!({"schema_version":1,"trade_id":{"schema_version":1,"value":p["trade"]},"order_id":{"schema_version":1,"value":order},"price":{"schema_version":1,"value":p["price"],"precision":pp},"quantity":{"schema_version":1,"value":p["quantity"],"precision":qp},"ts_event":{"schema_version":1,"unix_nanos":input["time"]},"ts_init":{"schema_version":1,"unix_nanos":input["time"]},"venue_trade_id":{"schema_version":1,"value":p["venue_trade"]},"venue_order_id":{"schema_version":1,"value":p["venue_order"]},"liquidity_side":"UNKNOWN","external_sequence":input["runtime_sequence"],"external_event_id":input["source_ref"],"metadata":{},"reference_price":null});
        let after_order = self.order_apply(&oc)?;
        let terminal = after_order["status"] == "FILLED";
        let before_alloc = match self.position.cluster(cluster, inst) {
            Ok(v) => Some(v),
            Err(e) if e.0 == "POSITION_ALLOCATION_NOT_FOUND" => None,
            Err(e) => return Err(Error(e.to_string())),
        };
        let before_account = self.account.snapshot();
        let fact=self.position_apply(&self.command(input,"TRADE",json!({"schema_version":1,"instrument":inst,"cluster":cluster,"order":order,"trade":p["trade"],"venue_trade":p["venue_trade"],"execution":format!("ETX-{}",hash(input)),"sequence":input["runtime_sequence"],"side":relation["side"],"position_side":"LONG","position_mode":"NETTING","price":p["price"],"quantity":p["quantity"],"fee":charges,"bucket":initial_bucket,"terminal_fill":terminal}),0))?;
        let allocation = boundary(self.position.cluster(cluster, inst))?;
        let pos = boundary(self.position.account(inst))?;
        let rd = exact(&fact["realized_pnl"])?;
        if self.meta["marks"][cluster].is_null() {
            self.meta["marks"][cluster] = json!({});
        }
        self.meta["marks"][cluster][inst] = json!(mark.normalized().to_plain_string());
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
            new_market += (&exact(&snapshot["quantity"])? * mark).with_scale_round(
                i64::from(self.precision),
                bigdecimal::RoundingMode::HalfEven,
            );
            total_cost += exact(&snapshot["cost"])?;
        }
        let old_market = dec(&before_account["market_value"])?;
        let account_market_delta = &new_market - &old_market;
        let unrealized = &new_market - total_cost;
        let ledger_before = if let Some(b) = before_alloc {
            allocation_witness(&b, self.precision)?
        } else {
            json!({"schema_version":1,"identity":null,"cycle":0,"realized_exact":money(&BigDecimal::zero(),self.precision)?,"quantity":"0","cost":money(&BigDecimal::zero(),self.precision)?,"realized":money(&BigDecimal::zero(),self.precision)?,"version":0})
        };
        let ledger_after = allocation_witness(&allocation, self.precision)?;
        self.ledger_apply(&self.ledger_command(input,"TRADE",json!({"schema_version":1,"trade":p["trade"],"execution":format!("ETX-{}",hash(input)),"venue_trade":p["venue_trade"],"order":order,"fee_instruction":fee["instruction"],"source_sequence":input["runtime_sequence"],"side":relation["side"],"instrument":inst,"notional":notional_s,"charges":charges,"rebates":rebates,"reservation":if buy{json!(order)}else{Value::Null},"terminal_fill":terminal,"before":ledger_before,"after":ledger_after,"allocation_evidence":hash(&allocation),"mark":valuation["mark"],"multiplier":"1"}),0))?;
        let mut rounding_adjustment = BigDecimal::zero();
        for cluster in self.config["profiles"]
            .as_object()
            .expect("profiles")
            .keys()
        {
            rounding_adjustment +=
                exact(&boundary(self.ledger.snapshot(cluster))?["realized_rounding_adjustment"])?;
        }
        self.account_apply(&self.command(input,"TRADE",json!({"schema_version":1,"trade":p["trade"],"execution":format!("ETX-{}",hash(input)),"venue_trade":p["venue_trade"],"order":order,"sequence":input["runtime_sequence"],"side":relation["side"],"notional":notional_s,"fee_instruction":fee["instruction"],"charges":charges,"rebates":rebates,"realized_pnl_delta":exact_record(&rd,self.precision),"position_evidence":hash(&pos),"market_value_delta":money(&account_market_delta,self.precision)?,"unrealized_pnl":exact_record(&unrealized,self.precision),"realized_rounding_adjustment":exact_record(&rounding_adjustment,self.precision),"reservation":if buy{json!(order)}else{Value::Null},"terminal_fill":terminal,"cash_withdrawable":cash_withdrawable}),0))?;
        let instruction = boundary(onlyalpha_settlement::compile(
            json!({"schema_version":1,"scope":settlement["scope"],"order":order,"trade":p["trade"],"currency":self.config["currency"],"side":relation["side"],"quantity":p["quantity"],"gross_notional":notional_s,"charges":charges,"rebates":rebates,"trading_day":input["trading_day"],"time":input["time"],"calendar":settlement["calendar"],"policy":settlement["policy"],"position":pos["id"],"position_cycle":pos["cycle"],"allocation":allocation["id"],"allocation_cycle":allocation["cycle"],"provenance":{"reference":settlement["source_ref"],"fingerprint":settlement["source_digest"],"instruction":settlement["instruction"]}}),
        ))?;
        let mut owner = self.settlement_owner()?;
        boundary(owner.register(&instruction))?;
        self.meta["settlement_authority"] = owner.checkpoint();
        self.risk_apply(&self.risk_command(input,"FILL",json!({"schema_version":1,"order":order,"trade":p["trade"],"source_ref":input["source_ref"],"quantity":p["quantity"],"notional":notional_s,"final_fill":terminal}),0))?;
        Ok(())
    }
    fn terminal(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(p, &["order", "outcome"])?;
        let relation = self.relation(input)?;
        let order = text(&p["order"])?;
        let outcome = text(&p["outcome"])?;
        if !matches!(outcome, "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED") {
            return Err(err("EXECUTION_TERMINAL_UNPROVEN"));
        }
        let mut oc = self.external(input, outcome, order);
        if outcome == "REJECTED" {
            oc["rejection"] = json!({"schema_version":1,"code":"EXTERNAL_REJECTION","message":"explicit external rejection"});
        }
        if outcome == "FAILED" {
            oc["failure"] = json!({"schema_version":1,"code":"EXTERNAL_FAILURE","message":"explicit external failure"});
        }
        self.order_apply(&oc)?;
        if relation["side"] == "BUY" {
            let payload = json!({"schema_version":1,"reservation":order,"outcome":outcome});
            self.account_apply(&self.command(input, "RELEASE", payload.clone(), 0))?;
            self.ledger_apply(&self.ledger_command(input, "RELEASE", payload, 0))?;
        } else {
            self.position_apply(&self.command(input,"RELEASE",json!({"schema_version":1,"order":order,"cluster":input["cluster"],"broker_confirmed":true}),0))?;
        }
        self.risk_apply(&self.risk_command(input,"TERMINAL",json!({"schema_version":1,"order":order,"outcome":outcome,"source_ref":input["source_ref"]}),0))?;
        Ok(())
    }
}

impl Components {
    fn settlement_owner(&self) -> Result<onlyalpha_settlement::Authority, Error> {
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
        let p = &input["payload"];
        row(p, &["instruction", "expected_version"])?;
        let mut owner = self.settlement_owner()?;
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
        let effect = boundary(owner.mature(
            id,
            text(&input["trading_day"])?,
            input["time"].clone(),
            uint(&p["expected_version"])?,
        ))?
        .record();
        let quantity = nonnegative(&effect["asset_quantity"])?;
        if !quantity.is_zero() {
            let instrument = text(&original["scope"]["instrument"])?;
            let position = boundary(self.position.account(instrument))?;
            let allocation = boundary(self.position.cluster(text(&input["cluster"])?, instrument))?;
            if position["id"] != effect["position"]
                || position["cycle"] != effect["position_cycle"]
                || allocation["id"] != effect["allocation"]
                || allocation["cycle"] != effect["allocation_cycle"]
            {
                return Err(err("EXECUTION_SETTLEMENT_LIFECYCLE"));
            }
            self.position_apply(&self.command(input,"SETTLE",json!({"schema_version":1,"instrument":instrument,"trading_day":input["trading_day"],"source":effect["id"],"buckets":[{"schema_version":1,"cluster":input["cluster"],"quantity":effect["asset_quantity"]}]}),0))?;
            let after = boundary(self.position.cluster(text(&input["cluster"])?, instrument))?;
            self.ledger_apply(&self.ledger_command(input,"SETTLEMENT",json!({"schema_version":1,"instruction":effect["id"],"instrument":instrument,"before":allocation_witness(&allocation,self.precision)?,"after":allocation_witness(&after,self.precision)?,"before_evidence":hash(&allocation),"allocation_evidence":hash(&after)}),0))?;
        }
        if !nonnegative(&effect["cash_amount"])?.is_zero() {
            self.account_apply(&self.command(input,"SETTLE",json!({"schema_version":1,"instruction":effect["id"],"source_trade":effect["trade"],"amount":effect["cash_amount"]}),0))?;
        }
        self.meta["settlement_authority"] = owner.checkpoint();
        Ok(())
    }
}

fn allocation_witness(a: &Value, p: u8) -> Result<Value, Error> {
    Ok(
        json!({"schema_version":1,"identity":a["id"],"cycle":a["cycle"],"realized_exact":exact_record(&exact(&a["realized_exact"])?,p),"quantity":a["quantity"],"cost":exact_record(&exact(&a["cost"])?,p),"realized":exact_record(&exact(&a["realized_pnl"])?,p),"version":a["version"]}),
    )
}
