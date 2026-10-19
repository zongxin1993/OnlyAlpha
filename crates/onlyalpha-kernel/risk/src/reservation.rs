use crate::{Manager, model::*};
use bigdecimal::Zero;
use serde_json::{Value, json};
impl Manager {
    pub(crate) fn reserve(&mut self, cluster: &str, v: &Value) -> Result<bool, Error> {
        let r = row(v, &["request_id", "order"])?;
        let request = id(&r["request_id"])?;
        let order = id(&r["order"])?;
        let k = key(cluster, &request);
        if let Some(existing) = self.request_orders.get(&k) {
            if existing == &order {
                let hold = self
                    .reservations
                    .get(existing)
                    .ok_or_else(|| err("RISK_ORDER_RELATION_MISSING"))?;
                if hold.cluster == cluster && hold.request == request {
                    return Ok(true);
                }
            }
            return Err(err("RISK_ORDER_REQUEST_CONFLICT"));
        }
        let d = self
            .decisions
            .get(&k)
            .ok_or_else(|| err("RISK_ACCEPTANCE_REQUIRED"))?;
        if d["outcome"] != "ACCEPT" || uint(&d["admission_epoch"])? != self.epoch {
            return Err(err("RISK_ACCEPTANCE_STALE_OR_DENIED"));
        }
        if self.reservations.contains_key(&order) {
            return Err(err("RISK_ORDER_REQUEST_CONFLICT"));
        }
        let r = &self.request_inputs[&k]["request"];
        let q = dec(&r["quantity"], 18)?;
        let n = dec(&r["notional"], self.precision)?;
        let increasing = r["effect"] == "OPEN";
        let fee = if increasing {
            dec(&r["fee"], self.precision)?
        } else {
            Decimal::zero()
        };
        let cash_requirement = if increasing {
            dec(&r["cash_requirement"], self.precision)?
        } else {
            Decimal::zero()
        };
        let hold = Hold {
            cluster: cluster.into(),
            request: request.clone(),
            instrument: instrument(&r["instrument"])?,
            side: id(&r["side"])?,
            position_side: id(&r["position_side"])?,
            position_mode: id(&r["position_mode"])?,
            increasing,
            quantity: q,
            notional: n,
            fee,
            cash_requirement,
            consumed_quantity: Decimal::zero(),
            consumed_notional: Decimal::zero(),
            released_quantity: Decimal::zero(),
            released_notional: Decimal::zero(),
            state: "ACTIVE".into(),
            sent: false,
            unknown: false,
            acknowledged: false,
            cancel_pending: false,
            terminal: None,
        };
        self.request_orders.insert(k, order.clone());
        self.reservations.insert(order, hold);
        self.advance_epoch()?;
        Ok(false)
    }
    pub(crate) fn transition(
        &mut self,
        cluster: &str,
        op: &str,
        v: &Value,
        n: u64,
    ) -> Result<bool, Error> {
        let fields: &[&str] = match op {
            "STAGE" => &["order", "stage"],
            "FILL" => &[
                "order",
                "trade",
                "source_ref",
                "quantity",
                "notional",
                "final_fill",
            ],
            "TERMINAL" => &["order", "outcome", "source_ref"],
            _ => return Err(err("RISK_OPERATION_UNKNOWN")),
        };
        let r = row(v, fields)?;
        let order = id(&r["order"])?;
        let hold = self
            .reservations
            .get(&order)
            .ok_or_else(|| err("RISK_RESERVATION_MISSING"))?;
        if hold.cluster != cluster {
            return Err(err("RISK_HOLD_OWNER_CONFLICT"));
        }
        let h = hash(&json!({"cluster":cluster,"op":op,"payload":v}));
        let mut aliases = vec![];
        if op == "FILL" {
            aliases.push(key("trade", &id(&r["trade"])?));
            aliases.push(key("fill_source", &id(&r["source_ref"])?));
        } else if op == "TERMINAL" {
            aliases.push(key("terminal_source", &id(&r["source_ref"])?));
        } else {
            aliases.push(key("stage", &json!([order, id(&r["stage"])?]).to_string()));
        }
        let existing = aliases
            .iter()
            .filter(|k| self.aliases.contains_key(*k))
            .count();
        if existing > 0 {
            if existing == aliases.len() && aliases.iter().all(|k| self.aliases[k] == h) {
                return Ok(true);
            }
            return Err(err("RISK_FACT_ID_CONFLICT"));
        }
        if hold.state != "ACTIVE" {
            return Err(err("RISK_HOLD_TERMINAL"));
        }
        let hold = self
            .reservations
            .get_mut(&order)
            .ok_or_else(|| err("RISK_RESERVATION_MISSING"))?;
        match op {
            "STAGE" => match text(&r["stage"])? {
                "SENT" => hold.sent = true,
                "UNKNOWN" => {
                    hold.sent = true;
                    hold.unknown = true;
                }
                "ACKNOWLEDGED" => {
                    hold.sent = true;
                    hold.acknowledged = true;
                    hold.unknown = false;
                }
                "CANCEL_PENDING" => {
                    hold.sent = true;
                    hold.cancel_pending = true;
                }
                _ => return Err(err("RISK_STAGE_INVALID")),
            },
            "FILL" => {
                let quantity = dec(&r["quantity"], 18)?;
                let notional = dec(&r["notional"], self.precision)?;
                let final_fill = boolean(&r["final_fill"])?;
                let remaining = hold.remaining_quantity();
                if quantity <= Decimal::zero()
                    || quantity > remaining
                    || notional > hold.remaining_notional()
                    || final_fill != (quantity == remaining)
                {
                    return Err(err("RISK_FILL_CONSERVATION_OR_TERMINAL"));
                }
                hold.sent = true;
                hold.consumed_quantity += quantity;
                hold.consumed_notional += notional;
                if final_fill {
                    hold.released_notional = hold.remaining_notional();
                    hold.state = "CONSUMED".into();
                    hold.terminal = Some("FILLED".into());
                }
                self.watermark = n;
            }
            "TERMINAL" => {
                let outcome = text(&r["outcome"])?;
                if !matches!(
                    outcome,
                    "CANCELLED" | "REJECTED" | "FAILED" | "EXPIRED" | "NOT_SENT"
                ) {
                    return Err(err("RISK_TERMINAL_OUTCOME_INVALID"));
                }
                if outcome == "NOT_SENT" && hold.sent {
                    return Err(err("RISK_SENT_NOT_ABSENCE"));
                }
                hold.released_quantity = hold.remaining_quantity();
                hold.released_notional = hold.remaining_notional();
                hold.state = "RELEASED".into();
                hold.terminal = Some(outcome.into());
                self.watermark = n;
            }
            _ => return Err(err("RISK_OPERATION_UNKNOWN")),
        }
        for k in aliases {
            self.aliases.insert(k, h.clone());
        }
        self.advance_epoch()?;
        Ok(false)
    }
}
