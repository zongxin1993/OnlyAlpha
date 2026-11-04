use crate::{Manager, model::*};
use bigdecimal::Zero;
use serde_json::{Value, json};
struct Check {
    scope: u8,
    order: u64,
    id: String,
    observing: bool,
    failure: Option<(&'static str, String)>,
}
impl Manager {
    pub(crate) fn evaluate(
        &mut self,
        cluster: &str,
        payload: &Value,
        n: u64,
    ) -> Result<(Value, bool), Error> {
        let p = row(payload, &["request", "views"])?;
        let r = row(
            &p["request"],
            &[
                "request_id",
                "instrument",
                "side",
                "effect",
                "position_side",
                "position_mode",
                "order_type",
                "quantity",
                "price",
                "notional",
                "fee",
                "cash_requirement",
            ],
        )?;
        let request = id(&r["request_id"])?;
        let k = key(cluster, &request);
        if let Some(old) = self.request_inputs.get(&k) {
            if old != payload {
                return Err(err("RISK_REQUEST_ID_CONFLICT"));
            }
            return Ok((self.decisions[&k].clone(), true));
        }
        let i = instrument(&r["instrument"])?;
        let side = text(&r["side"])?;
        let position = text(&r["position_side"])?;
        if !matches!(side, "BUY" | "SELL") || !matches!(position, "LONG" | "SHORT") {
            return Err(err("RISK_SIDE_INVALID"));
        }
        let position_mode = text(&r["position_mode"])?;
        if !matches!(position_mode, "NETTING" | "HEDGING") {
            return Err(err("RISK_POSITION_MODE_INVALID"));
        }
        let quantity = dec(&r["quantity"], 18)?;
        let effect = text(&r["effect"])?;
        let increasing = effect == "OPEN"
            && ((side == "BUY" && position == "LONG") || (side == "SELL" && position == "SHORT"));
        let closing = effect == "CLOSE"
            && ((side == "SELL" && position == "LONG") || (side == "BUY" && position == "SHORT"));
        let v = row(&p["views"], &["account", "ledger", "position", "market"])?;
        let account = self
            .envelope(&v["account"], "ACCOUNT", cluster, &i, n)?
            .cloned();
        let ledger = self
            .envelope(&v["ledger"], "LEDGER", cluster, &i, n)?
            .cloned();
        let position_view = self
            .envelope(&v["position"], "POSITION", cluster, &i, n)?
            .cloned();
        let market = self
            .envelope(&v["market"], "MARKET", cluster, &i, n)?
            .cloned();
        let mut checks: Vec<Check> = vec![];
        let mut mandatory = |order, id: &str, result: Option<(&'static str, String)>| {
            checks.push(Check {
                scope: 0,
                order,
                id: id.into(),
                observing: false,
                failure: result,
            });
        };
        mandatory(10, "system.scope", None);
        mandatory(
            20,
            "system.instrument",
            if self.profiles[cluster].instruments.contains(&i) {
                None
            } else {
                Some(("REJECT", "INSTRUMENT_NOT_AUTHORIZED".into()))
            },
        );
        mandatory(
            30,
            "system.quantity",
            if quantity > Decimal::zero() {
                None
            } else {
                Some(("REJECT", "INVALID_QUANTITY".into()))
            },
        );
        let order_type = text(&r["order_type"])?;
        let price = if r["price"].is_null() {
            None
        } else {
            Some(dec(&r["price"], 18)?)
        };
        mandatory(
            40,
            "system.order_type",
            if matches!(order_type, "LIMIT" | "MARKET") {
                None
            } else {
                Some(("REJECT", "UNSUPPORTED_ORDER_TYPE".into()))
            },
        );
        mandatory(
            50,
            "system.price",
            if order_type == "LIMIT" && price.as_ref().is_none_or(|x| x <= &Decimal::zero()) {
                Some(("ERROR", "PRICE_UNAVAILABLE".into()))
            } else {
                None
            },
        );
        mandatory(
            60,
            "system.exposure",
            if increasing || closing {
                None
            } else {
                Some(("ERROR", "EXPOSURE_NOT_PROVED".into()))
            },
        );
        let notional = if r["notional"].is_null() {
            None
        } else {
            Some(dec(&r["notional"], self.precision)?)
        };
        let fee = if r["fee"].is_null() {
            None
        } else {
            Some(dec(&r["fee"], self.precision)?)
        };
        let cash_requirement = if r["cash_requirement"].is_null() {
            None
        } else {
            Some(dec(&r["cash_requirement"], self.precision)?)
        };
        mandatory(
            70,
            "system.cost",
            if notional.is_none() || (increasing && (fee.is_none() || cash_requirement.is_none())) {
                Some(("ERROR", "COST_UNAVAILABLE".into()))
            } else {
                None
            },
        );
        let killed = self.kills.contains("RUNTIME")
            || self.kills.contains("ACCOUNT")
            || self.kills.contains(&key("CLUSTER", cluster));
        mandatory(
            80,
            "system.kill_switch",
            if killed && increasing {
                Some(("REJECT", "KILL_SWITCH_ACTIVE".into()))
            } else {
                None
            },
        );
        let mut market_result = None;
        if let Some(m) = &market {
            let x = row(m, &["request_digest", "verdict", "code"])?;
            fp(&x["request_digest"])?;
            if x["request_digest"] != hash(&p["request"]) {
                return Err(err("RISK_MARKET_INTENT_RELATION"));
            }
            let verdict = text(&x["verdict"])?;
            let code = text(&x["code"])?;
            match verdict {
                "ACCEPT" => {}
                "REJECT" => market_result = Some(("REJECT", code.into())),
                "ERROR" => market_result = Some(("ERROR", code.into())),
                _ => return Err(err("RISK_MARKET_VERDICT")),
            }
        } else {
            market_result = Some(("ERROR", "MARKET_UNAVAILABLE".into()));
        }
        mandatory(90, "system.market", market_result);
        let cash_of = |v: &Option<Value>| -> Result<Option<Decimal>, Error> {
            if let Some(v) = v {
                let r = row(v, &["status", "cash"])?;
                let status = text(&r["status"])?;
                let value = dec(&r["cash"], self.precision)?;
                if status == "ACTIVE" {
                    Ok(Some(value))
                } else {
                    Ok(None)
                }
            } else {
                Ok(None)
            }
        };
        let ac = cash_of(&account)?;
        let lc = cash_of(&ledger)?;
        let ac_holds: Decimal = self.reservations.values().map(Hold::cash).sum();
        let lc_holds: Decimal = self
            .reservations
            .values()
            .filter(|h| h.cluster == cluster)
            .map(Hold::cash)
            .sum();
        let required =
            cash_requirement.clone().unwrap_or_default() + fee.clone().unwrap_or_default();
        let funds = if !increasing {
            None
        } else if let (Some(ac), Some(lc)) = (ac, lc) {
            if ac - ac_holds < required || lc - lc_holds < required {
                Some(("REJECT", "INSUFFICIENT_CASH_WITH_FEES".into()))
            } else {
                None
            }
        } else {
            Some(("ERROR", "ACCOUNT_OR_LEDGER_UNAVAILABLE".into()))
        };
        mandatory(100, "system.cash", funds);
        let pv = if let Some(p) = &position_view {
            let r = row(
                p,
                &[
                    "account_available",
                    "allocation_available",
                    "position_side",
                    "position_mode",
                ],
            )?;
            if r["position_side"] != position || r["position_mode"] != position_mode {
                return Err(err("RISK_POSITION_PROOF_RELATION"));
            }
            Some((
                dec(&r["account_available"], 18)?,
                dec(&r["allocation_available"], 18)?,
            ))
        } else {
            None
        };
        let positions = if closing {
            if let Some((ac, lc)) = pv {
                let account_held: Decimal = self
                    .reservations
                    .values()
                    .filter(|h| {
                        !h.increasing
                            && h.state == "ACTIVE"
                            && h.instrument == i
                            && h.position_side == position
                            && h.position_mode == position_mode
                    })
                    .map(Hold::remaining_quantity)
                    .sum();
                let cluster_held: Decimal = self
                    .reservations
                    .values()
                    .filter(|h| {
                        !h.increasing
                            && h.state == "ACTIVE"
                            && h.instrument == i
                            && h.position_side == position
                            && h.position_mode == position_mode
                            && h.cluster == cluster
                    })
                    .map(Hold::remaining_quantity)
                    .sum();
                if ac - account_held < quantity || lc - cluster_held < quantity {
                    Some(("REJECT", "INSUFFICIENT_POSITION".into()))
                } else {
                    None
                }
            } else {
                Some(("ERROR", "POSITION_UNAVAILABLE".into()))
            }
        } else if pv.is_none() {
            Some(("ERROR", "POSITION_UNAVAILABLE".into()))
        } else {
            None
        };
        mandatory(110, "system.position", positions);
        for rule in &self.profiles[cluster].rules {
            let holds: Vec<_> = self
                .reservations
                .values()
                .filter(|h| {
                    h.state == "ACTIVE"
                        && match rule.scope.as_str() {
                            "CLUSTER" => h.cluster == cluster,
                            "INSTRUMENT" => h.instrument == i,
                            _ => true,
                        }
                })
                .collect();
            let amount = match rule.kind.as_str() {
                "MAX_ACTIVE_ORDERS" => Decimal::from(holds.len() as u64 + 1),
                "MAX_ORDER_QUANTITY" => quantity.clone(),
                "MAX_ORDER_NOTIONAL" => notional.clone().unwrap_or_default(),
                "MAX_RESERVED_NOTIONAL" => {
                    holds
                        .iter()
                        .map(|h| h.remaining_notional())
                        .sum::<Decimal>()
                        + notional.clone().unwrap_or_default()
                }
                _ => return Err(err("RISK_RULE_KIND")),
            };
            let fail = if amount > rule.limit {
                Some(("REJECT", rule.kind.clone()))
            } else {
                None
            }; /* Risk-increasing limits must not suppress a proved close. */
            checks.push(Check {
                scope: scope(&rule.scope)?,
                order: rule.order,
                id: rule.id.clone(),
                observing: rule.observing,
                failure: if increasing { fail } else { None },
            });
        }
        checks.sort_by(|a, b| (&a.scope, &a.order, &a.id).cmp(&(&b.scope, &b.order, &b.id)));
        let mut evaluated = vec![];
        let mut observations = vec![];
        let mut outcome = "ACCEPT";
        let mut code = "OK".to_string();
        let mut failed: Option<String> = None;
        for Check {
            id,
            observing,
            failure: result,
            ..
        } in checks
        {
            evaluated.push(id.clone());
            if let Some((result, reason)) = result {
                if observing && result == "REJECT" {
                    observations.push(id);
                    continue;
                }
                outcome = result;
                code = reason;
                failed = Some(id);
                break;
            }
        }
        let decision = json!({"schema_version":1,"request":request,"cluster":cluster,"revision":self.profiles[cluster].revision,"profile_digest":hash(&self.config["clusters"][cluster]),"input_digest":hash(payload),"outcome":outcome,"rule":failed,"code":code,"evaluated":evaluated,"observations":observations,"admission_epoch":self.epoch,"runtime_sequence":n});
        self.request_inputs.insert(k.clone(), payload.clone());
        self.decisions.insert(k, decision.clone());
        self.audits.push(decision.clone());
        Ok((decision, false))
    }
}
