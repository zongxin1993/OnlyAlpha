//! Consume compiled collateral instructions within the existing owning transaction.
use crate::{Components, components::settlement_config, model::*};
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};

fn declaration(input: &Value) -> Result<&Value, Error> {
    let value = &input["payload"]["collateral"];
    row(value, &["kind", "instruction", "close_allocation"])?;
    if value["kind"] == "NONE" {
        if !value["instruction"].is_null() || !value["close_allocation"].is_null() {
            return Err(err("EXECUTION_COLLATERAL_DECLARATION"));
        }
    } else if value["kind"] != "MARGIN" {
        return Err(err("EXECUTION_COLLATERAL_DECLARATION"));
    }
    Ok(value)
}
impl Components {
    fn margin_owner(&self) -> Result<onlyalpha_margin::Manager, Error> {
        let mut owner = boundary(onlyalpha_margin::Manager::new(
            settlement_config(&self.config),
            512,
        ))?;
        boundary(owner.restore(
            &self.meta["margin_authority"],
            &onlyalpha_margin::digest(&self.meta["margin_authority"]),
        ))?;
        Ok(owner)
    }
    fn margin_trade(&self, trade: &str) -> Result<Value, Error> {
        let rows = self.meta["settlement_authority"]["instructions"]
            .as_object()
            .ok_or_else(|| err("EXECUTION_MARGIN_TRADE_PROOF"))?;
        let matches: Vec<_> = rows
            .values()
            .filter(|s| s["instruction"]["input"]["trade"] == trade)
            .collect();
        if matches.len() != 1 {
            return Err(err("EXECUTION_MARGIN_TRADE_PROOF"));
        }
        Ok(matches[0]["instruction"]["input"].clone())
    }
    fn compiled_margin(&self, input: &Value, command: &Value, action: &str) -> Result<(), Error> {
        if command["action"] != action
            || command["source_order"] != input["payload"]["order"]
            || command["source_ref"] != input["source_ref"]
            || command["time"] != input["time"]
            || command["position_side"] != "LONG"
        {
            return Err(err("EXECUTION_MARGIN_SOURCE"));
        }
        let mut body = command.clone();
        body.as_object_mut()
            .ok_or_else(|| err("EXECUTION_MARGIN_SOURCE"))?
            .remove("source_fingerprint");
        if command["source_fingerprint"] != hash(&body) {
            return Err(err("EXECUTION_MARGIN_SOURCE_DIGEST"));
        }
        let relation = self.relation(input)?;
        let scope = json!({"schema_version":1,"engine":input["engine"],"runtime":input["runtime"],"account":input["account"],"gateway":input["gateway"],"generation":input["generation"],"runtime_kind":input["runtime_kind"],"cluster":input["cluster"],"revision":input["revision"],"instrument":relation["instrument"],"request":relation["request"]["request_id"]["value"]});
        if command["scope"] != scope {
            return Err(err("EXECUTION_MARGIN_SCOPE"));
        }
        Ok(())
    }
    fn consume_margin(
        &mut self,
        input: &Value,
        owner: &mut onlyalpha_margin::Manager,
        command: &Value,
    ) -> Result<(), Error> {
        if command["action"] != "RESERVE"
            && boundary(owner.snapshot(text(&command["reservation"])?))?["version"]
                != command["expected_version"]
        {
            return Err(err("EXECUTION_MARGIN_VERSION"));
        }
        let effect = boundary(owner.apply(command))?;
        let record = effect.record();
        let mut projection = self.command(input, "MARGIN", Value::Null, 0);
        projection["command_id"] = json!(format!(
            "MACMD-{}",
            hash(&json!([input["input_id"], record["id"]]))
        ));
        if boundary(self.account.apply_margin(&projection, &effect))?.status
            != onlyalpha_account::Status::Applied
        {
            return Err(err("EXECUTION_ACCOUNT_NOT_APPLIED"));
        }
        self.meta["margin_authority"] = owner.checkpoint();
        Ok(())
    }
    pub(crate) fn admit_collateral(&mut self, input: &Value) -> Result<(), Error> {
        let decl = declaration(input)?;
        if decl["kind"] == "NONE" {
            return self.margin_capital(input);
        }
        if !decl["close_allocation"].is_null() {
            return Err(err("EXECUTION_MARGIN_ADMISSION_SHAPE"));
        }
        let command = &decl["instruction"];
        self.compiled_margin(input, command, "RESERVE")?;
        let relation = self.relation(input)?;
        let request = &relation["request"];
        if relation["side"] != "BUY"
            || nonnegative(&command["quantity"])? != nonnegative(&request["quantity"]["value"])?
            || command["quantity_precision"] != request["quantity"]["precision"]
        {
            return Err(err("EXECUTION_MARGIN_ADMISSION_QUANTITY"));
        }
        let mut owner = self.margin_owner()?;
        // This native Position consumer has one LONG/NETTING allocation. Separate margin
        // modes cannot silently share that allocation; the library itself supports both.
        for old in owner.snapshots() {
            if same_scope(&old, input, &relation)
                && (nonnegative(&old["unfilled"])? > BigDecimal::zero()
                    || nonnegative(&old["open"])? > BigDecimal::zero()
                    || nonnegative(&old["reserved"])? > BigDecimal::zero())
                && (old["mode"] != command["mode"] || old["isolation"] != command["isolation"])
            {
                return Err(err("EXECUTION_MARGIN_POSITION_MODE"));
            }
        }
        self.consume_margin(input, &mut owner, command)?;
        self.margin_capital(input)
    }
    fn margin_capital(&self, input: &Value) -> Result<(), Error> {
        let relation = self.relation(input)?;
        if relation["side"] != "BUY" {
            return Ok(());
        }
        let mut held = BigDecimal::zero();
        for state in self.margin_owner()?.snapshots() {
            if state["scope"]["cluster"] == input["cluster"]
                && state["scope"]["revision"] == input["revision"]
            {
                held += nonnegative(&state["reserved"])? + nonnegative(&state["occupied"])?;
            }
        }
        if held
            > nonnegative(&boundary(self.ledger.snapshot(text(&input["cluster"])?))?["available"])?
        {
            return Err(err("EXECUTION_MARGIN_CLUSTER_CAPITAL"));
        }
        Ok(())
    }
    pub(crate) fn fill_collateral(&mut self, input: &Value) -> Result<(), Error> {
        let decl = declaration(input)?;
        let relation = self.relation(input)?;
        let mut owner = self.margin_owner()?;
        let order = text(&input["payload"]["order"])?;
        let trade = self.margin_trade(text(&input["payload"]["trade"])?)?;
        if trade["order"] != order {
            return Err(err("EXECUTION_MARGIN_TRADE_ORDER"));
        }
        if relation["side"] == "BUY" {
            let reservations: Vec<_> = owner
                .snapshots()
                .into_iter()
                .filter(|s| s["order"] == order)
                .collect();
            if reservations.is_empty() {
                return if decl["kind"] == "NONE" {
                    Ok(())
                } else {
                    Err(err("EXECUTION_MARGIN_NOT_ADMITTED"))
                };
            }
            if reservations.len() != 1
                || decl["kind"] != "MARGIN"
                || !decl["close_allocation"].is_null()
            {
                return Err(err("EXECUTION_MARGIN_FILL_PROOF"));
            }
            let command = &decl["instruction"];
            self.compiled_margin(input, command, "OCCUPY")?;
            if command["reservation"] != reservations[0]["id"]
                || command["source_trade"] != trade["trade"]
                || command["scope"] != trade["scope"]
                || nonnegative(&command["quantity"])? != nonnegative(&trade["quantity"])?
            {
                return Err(err("EXECUTION_MARGIN_FILL_RELATION"));
            }
            self.consume_margin(input, &mut owner, command)?;
            let snapshot = boundary(self.order.get(text(&input["cluster"])?, order))?.to_record();
            if snapshot["status"] == "FILLED" {
                let state = boundary(owner.snapshot(text(&command["reservation"])?))?;
                let release = self.derived_margin(
                    input,
                    &state,
                    "RELEASE_RESERVED",
                    state["unfilled"].clone(),
                    state["reserved"].clone(),
                    json!("0.00"),
                );
                self.consume_margin(input, &mut owner, &release)?;
            }
            return Ok(());
        }
        let mut eligible = vec![];
        for state in owner.snapshots() {
            if same_scope(&state, input, &relation)
                && nonnegative(&state["open"])? > BigDecimal::zero()
                && self.margin_position_matches(&owner, &state, &trade)?
            {
                eligible.push(state);
            }
        }
        if eligible.is_empty() {
            return if decl["kind"] == "NONE" {
                Ok(())
            } else {
                Err(err("EXECUTION_MARGIN_CLOSE_PROOF"))
            };
        }
        if decl["kind"] != "MARGIN" || !decl["instruction"].is_null() {
            return Err(err("EXECUTION_MARGIN_CLOSE_PROOF"));
        }
        let allocation = &decl["close_allocation"];
        row(
            allocation,
            &["policy", "mode", "isolation", "position_side"],
        )?;
        if allocation["policy"] != "RESERVATION_ID_ASCENDING"
            || allocation["position_side"] != "LONG"
            || eligible.iter().any(|s| {
                s["mode"] != allocation["mode"] || s["isolation"] != allocation["isolation"]
            })
        {
            return Err(err("EXECUTION_MARGIN_CLOSE_ALLOCATION"));
        }
        let mut remaining = nonnegative(&trade["quantity"])?;
        for state in eligible {
            if remaining == BigDecimal::zero() {
                break;
            }
            let quantity = remaining.clone().min(nonnegative(&state["open"])?);
            let spelling = quantity.normalized().to_plain_string();
            let quote = boundary(owner.release_quote(text(&state["id"])?, &spelling))?;
            let command = self.derived_margin(
                input,
                &state,
                "RELEASE_OCCUPIED",
                json!(spelling),
                quote["amount"].clone(),
                quote["maintenance"].clone(),
            );
            self.consume_margin(input, &mut owner, &command)?;
            remaining -= quantity;
        }
        Ok(())
    }
    fn margin_position_matches(
        &self,
        owner: &onlyalpha_margin::Manager,
        state: &Value,
        closing: &Value,
    ) -> Result<bool, Error> {
        let cp = owner.checkpoint();
        let records = cp["records"]
            .as_array()
            .ok_or_else(|| err("EXECUTION_MARGIN_HISTORY"))?;
        let mut found = false;
        let mut matches = true;
        for record in records {
            let command = &record["command"];
            if command["reservation"] != state["id"] {
                continue;
            }
            if command["action"] == "OCCUPY" {
                found = true;
                let opening = self.margin_trade(text(&command["source_trade"])?)?;
                if opening["order"] != state["order"] || opening["scope"] != state["scope"] {
                    return Err(err("EXECUTION_MARGIN_OPENING_RELATION"));
                }
                for k in [
                    "position",
                    "position_cycle",
                    "allocation",
                    "allocation_cycle",
                ] {
                    if opening[k] != closing[k] {
                        matches = false;
                    }
                }
            }
            if record["result"]["after"]["open"] == "0" {
                found = false;
                matches = true;
            }
        }
        if !found {
            return Err(err("EXECUTION_MARGIN_OPENING_PROOF_MISSING"));
        }
        Ok(matches)
    }
    pub(crate) fn terminal_collateral(&mut self, input: &Value) -> Result<(), Error> {
        let decl = declaration(input)?;
        let mut owner = self.margin_owner()?;
        let order = text(&input["payload"]["order"])?;
        let reservations: Vec<_> = owner
            .snapshots()
            .into_iter()
            .filter(|s| s["order"] == order)
            .collect();
        if reservations.is_empty() {
            return if decl["kind"] == "NONE" {
                Ok(())
            } else {
                Err(err("EXECUTION_MARGIN_NOT_ADMITTED"))
            };
        }
        if reservations.len() != 1
            || decl["kind"] != "MARGIN"
            || !decl["instruction"].is_null()
            || !decl["close_allocation"].is_null()
        {
            return Err(err("EXECUTION_MARGIN_TERMINAL_PROOF"));
        }
        let state = &reservations[0];
        let order_state = boundary(self.order.get(text(&input["cluster"])?, order))?.to_record();
        if !matches!(
            text(&order_state["status"])?,
            "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED"
        ) || nonnegative(&state["open"])? + nonnegative(&state["closed"])?
            != nonnegative(&order_state["filled_quantity"]["value"])?
        {
            return Err(err("EXECUTION_MARGIN_TERMINAL_RELATION"));
        }
        let command = self.derived_margin(
            input,
            state,
            "RELEASE_RESERVED",
            state["unfilled"].clone(),
            state["reserved"].clone(),
            json!("0.00"),
        );
        self.consume_margin(input, &mut owner, &command)
    }
    fn derived_margin(
        &self,
        input: &Value,
        state: &Value,
        action: &str,
        quantity: Value,
        amount: Value,
        maintenance: Value,
    ) -> Value {
        let mut c = json!({"schema_version":1,"id":format!("MINST-{}",hash(&json!([input["input_id"],state["id"],action]))),"scope":state["scope"],"reservation":state["id"],"source_order":input["payload"]["order"],"source_trade":if action=="RELEASE_OCCUPIED"{input["payload"]["trade"].clone()}else{Value::Null},"source_ref":format!("MSRC-{}",hash(&json!([input["source_ref"],state["id"],action]))),"mode":state["mode"],"isolation":state["isolation"],"position_side":state["position_side"],"action":action,"quantity":quantity,"quantity_precision":state["quantity_precision"],"amount":amount,"maintenance":maintenance,"time":input["time"],"expected_version":state["version"],"before_hash":hash(state)});
        c["source_fingerprint"] = json!(hash(&c));
        c
    }
}
fn same_scope(state: &Value, input: &Value, relation: &Value) -> bool {
    state["scope"]["cluster"] == input["cluster"]
        && state["scope"]["revision"] == input["revision"]
        && state["scope"]["instrument"] == relation["instrument"]
}
