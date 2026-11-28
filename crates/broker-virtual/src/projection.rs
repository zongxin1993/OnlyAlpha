//! 模拟场所观察到的现金和持仓。交易许可与正式会计仍由 Runtime 决定。
use super::plan::{domain_value, err, number, quantity_record};
use bigdecimal::{BigDecimal as D, RoundingMode, Zero};
use onlyalpha_broker::{Error, Scope, Snapshot};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    errors::OnlyDomainError,
    numeric::{only_divide, only_quantize},
    value::{OnlyCurrency, OnlyMoney, OnlyPrice},
};
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn average_price(total: &D, quantity: &D, precision: u8) -> Result<OnlyPrice, OnlyDomainError> {
    let total = total.to_plain_string().parse()?;
    let quantity = quantity.to_plain_string().parse()?;
    let quantum = format!("1E-{precision}").parse()?;
    let mean = only_divide(&total, &quantity)?;
    OnlyPrice::new(only_quantize(&mean, &quantum)?, precision)
}

#[derive(Clone)]
struct Position {
    instrument: Value,
    side: String,
    quantity: D,
    held: D,
    average: Option<Value>,
    precision: i64,
}

#[derive(Clone)]
pub(crate) struct Projection {
    currency: OnlyCurrency,
    scale: i64,
    cash: D,
    held: D,
    positions: BTreeMap<(String, String), Position>,
    pub marks: BTreeMap<String, Value>,
}
impl Projection {
    pub fn new(initial: &OnlyMoney) -> Result<Self, Error> {
        let money = initial.to_record();
        let cash = number(&money["amount"])?;
        if cash < D::zero() {
            return Err(err("VIRTUAL_CASH"));
        }
        Ok(Self {
            currency: initial.currency().clone(),
            scale: i64::from(initial.currency().precision()),
            cash,
            held: D::zero(),
            positions: BTreeMap::new(),
            marks: BTreeMap::new(),
        })
    }
    fn rounded(&self, n: D) -> D {
        n.with_scale_round(self.scale, RoundingMode::HalfEven)
    }
    fn key(r: &Value) -> (String, String) {
        (
            r["instrument_id"].to_string(),
            r["execution_intent"]["position_side"]
                .as_str()
                .expect("validated")
                .into(),
        )
    }
    fn opening(r: &Value) -> bool {
        r["execution_intent"]["position_effect"] == "OPEN"
    }
    pub fn reserve(&mut self, r: &Value, price: &D, q: &D) -> Option<D> {
        let key = Self::key(r);
        if Self::opening(r) {
            if self
                .positions
                .iter()
                .any(|(k, p)| k.0 == key.0 && k.1 != key.1 && !p.quantity.is_zero())
            {
                return None;
            }
            if key.1 == "LONG" {
                let amount = self.rounded(price * q);
                if amount > &self.cash - &self.held {
                    return None;
                }
                self.held += &amount;
                return Some(amount);
            }
        } else {
            let p = self.positions.get_mut(&key)?;
            if q > &(&p.quantity - &p.held) {
                return None;
            }
            p.held += q;
        }
        Some(D::zero())
    }
    pub fn release(&mut self, r: &Value, cash: &D, remaining: &D) -> Result<(), Error> {
        self.held -= cash;
        if !Self::opening(r) {
            self.positions
                .get_mut(&Self::key(r))
                .ok_or_else(|| err("VIRTUAL_POSITION_MISSING"))?
                .held -= remaining;
        }
        Ok(())
    }
    pub fn fill(&mut self, r: &Value, q: &D, price: &Value, released: &D) -> Result<(), Error> {
        let key = Self::key(r);
        let exact = number(&price["value"])?;
        let cost = self.rounded(&exact * q);
        let p = self
            .positions
            .entry(key.clone())
            .or_insert_with(|| Position {
                instrument: r["instrument_id"].clone(),
                side: key.1.clone(),
                quantity: D::zero(),
                held: D::zero(),
                average: None,
                precision: r["quantity"]["precision"].as_i64().expect("validated"),
            });
        p.precision = p
            .precision
            .max(r["quantity"]["precision"].as_i64().expect("validated"));
        let average = p
            .average
            .as_ref()
            .map(|v| number(&v["value"]))
            .transpose()?
            .unwrap_or_default();
        if Self::opening(r) {
            let total = &average * &p.quantity
                + if key.1 == "LONG" {
                    cost.clone()
                } else {
                    &exact * q
                };
            p.quantity += q;
            let precision = price["precision"].as_u64().expect("validated") as u8;
            p.average = Some(
                average_price(&total, &p.quantity, precision)
                    .map_err(|_| err("VIRTUAL_AVERAGE_PRICE"))?
                    .to_record(),
            );
            if key.1 == "LONG" {
                self.cash -= cost;
                self.held -= released;
            }
        } else {
            p.held -= q;
            p.quantity -= q;
            if p.quantity.is_zero() {
                p.average = None;
            }
            if key.1 == "LONG" {
                self.cash += cost;
            } else {
                self.cash +=
                    ((&average - exact) * q).with_scale_round(self.scale, RoundingMode::HalfEven);
            }
        }
        Ok(())
    }
    pub fn account(
        &self,
        scope: &Scope,
        seq: u64,
        now: i64,
        balance: bool,
    ) -> Result<Snapshot, Error> {
        let money = |n: &D| -> Result<Value, Error> {
            Ok(
                OnlyMoney::new(domain_value(n, self.scale)?, self.currency.clone())
                    .map_err(|_| err("VIRTUAL_MONEY"))?
                    .to_record(),
            )
        };
        let mut payload = json!({"currency":self.currency.to_record(),"ledger_cash":money(&self.cash)?,
            "order_reserved_cash":money(&self.held)?,"trade_available_cash":money(&(&self.cash-&self.held))?});
        if !balance {
            let mut equity = self.cash.clone();
            for ((instrument, _), p) in &self.positions {
                if let Some(price) = self.marks.get(instrument).or(p.average.as_ref()) {
                    let mark = number(&price["value"])?;
                    let exposure = if p.side == "SHORT" {
                        let basis = p
                            .average
                            .as_ref()
                            .map(|v| number(&v["value"]))
                            .transpose()?
                            .unwrap_or_default();
                        basis - mark
                    } else {
                        mark
                    };
                    equity += &p.quantity * exposure;
                }
            }
            payload["equity"] = money(&self.rounded(equity))?;
        }
        Snapshot::decode(
            &json!({"scope":scope.record(),"kind":if balance{"BALANCE"}else{"ACCOUNT"},
            "source_sequence":seq,"snapshot_time":now,"payload":payload}),
        )
    }
    pub fn positions(&self, scope: &Scope, seq: u64, now: i64) -> Result<Vec<Snapshot>, Error> {
        self.positions.values().map(|p|Snapshot::decode(&json!({"scope":scope.record(),"kind":"POSITION","source_sequence":seq,
            "snapshot_time":now,"payload":{"instrument":p.instrument,"side":p.side,"quantity":quantity_record(&p.quantity,p.precision)?,
            "frozen":quantity_record(&p.held,p.precision)?,"available":quantity_record(&(&p.quantity-&p.held),p.precision)?,"average_price":p.average}}))).collect()
    }
    pub fn remaining_hold(&self, r: &Value, price: &D, remaining: &D) -> D {
        if Self::opening(r) && r["side"] == "BUY" {
            self.rounded(price * remaining)
        } else {
            D::zero()
        }
    }
}
