//! Source-derived mark valuation. Position remains the only cost/quantity owner.
use crate::{Manager, model::*};
use bigdecimal::{RoundingMode, Zero};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// Only a live Position owner or complete canonical replay can produce this value.
/// The source checkpoint is evidence, not external producer authentication.
/// ```compile_fail
/// use onlyalpha_position::ValuationEffect;
/// let forged = ValuationEffect { input: serde_json::json!({}), result: serde_json::json!({"market_value":"999.00"}) };
/// ```
pub struct ValuationEffect {
    input: Value,
    result: Value,
}
impl ValuationEffect {
    pub fn record(&self) -> Value {
        self.result.clone()
    }
    pub fn replay_input(&self) -> Value {
        self.input.clone()
    }
    pub fn rederive(proof: &Value) -> Result<Self, Error> {
        row(proof, &["position", "intent"])?;
        let cp = &proof["position"];
        let mut owner = Manager::new(cp["config"].clone())?;
        let bytes = serde_json::to_vec(cp)?;
        owner.restore(&bytes, &digest(&bytes))?;
        owner.value(&proof["intent"])
    }
}
impl Manager {
    pub fn value(&self, intent: &Value) -> Result<ValuationEffect, Error> {
        row(
            intent,
            &[
                "valuation",
                "version",
                "economic_version",
                "position_evidence",
                "time",
                "marks",
            ],
        )?;
        id(&intent["valuation"])?;
        uint(&intent["economic_version"])?;
        if uint(&intent["version"])? == 0 {
            return Err(err("POSITION_VALUATION_VERSION"));
        }
        let at = time(&intent["time"])?;
        let (bytes, evidence) = self.checkpoint()?;
        if intent["position_evidence"] != evidence {
            return Err(err("POSITION_VALUATION_SOURCE"));
        }
        if !self.state.journal.is_empty() && at < self.state.now {
            return Err(err("POSITION_VALUATION_TIME"));
        }
        let rows = intent["marks"]
            .as_array()
            .filter(|a| a.len() <= 32)
            .ok_or_else(|| err("POSITION_VALUATION_MARKS"))?;
        let mut marks = BTreeMap::new();
        for m in rows {
            row(
                m,
                &[
                    "instrument",
                    "mark",
                    "source_ref",
                    "family",
                    "version",
                    "time",
                    "as_of_sequence",
                ],
            )?;
            let i = id(&m["instrument"])?;
            let spec = self.spec(&i)?;
            spec.price(&m["mark"])?;
            id(&m["source_ref"])?;
            if m["family"] != "CLOSED_BAR"
                || uint(&m["version"])? == 0
                || uint(&m["as_of_sequence"])? == 0
                || time(&m["time"])? > at
            {
                return Err(err("POSITION_VALUATION_MARK_PROOF"));
            }
            if marks.insert(i, m).is_some() {
                return Err(err("POSITION_VALUATION_DUPLICATE_MARK"));
            }
        }
        if marks.len() != self.state.accounts.len()
            || self.state.accounts.keys().any(|i| !marks.contains_key(i))
        {
            return Err(err("POSITION_VALUATION_INCOMPLETE"));
        }
        let mut market = Decimal::zero();
        let mut cost = Decimal::zero();
        for (i, b) in &self.state.accounts {
            let m = marks[i];
            // A mark older than a consumed economic fact cannot certify its valuation.
            if time(&m["time"])? < b.updated {
                return Err(err("POSITION_VALUATION_STALE_MARK"));
            }
            let spec = &self.instruments[i];
            let mv = (&b.qty * decimal(&m["mark"])? * &spec.multiplier)
                .with_scale_round(i64::from(self.currency.precision()), RoundingMode::HalfEven);
            let c = &b.cost * &spec.multiplier;
            market += &mv;
            cost += &c;
        }
        let mut replay = Self::new(self.config.clone())?;
        let mut trades = serde_json::Map::new();
        for command in &self.state.journal {
            let outcome = replay.apply(command)?;
            if command["op"] == "TRADE" && outcome.status == crate::Status::Applied {
                let p = &command["payload"];
                let fact = outcome
                    .fact
                    .ok_or_else(|| err("POSITION_VALUATION_TRADE_FACT"))?;
                trades.insert(id(&p["trade"])?,json!({"position_evidence":hash(&fact["details"]["account"]),"cause":command["cause"],"time":command["time"],"order":p["order"],"execution":p["execution"],"venue_trade":p["venue_trade"],"sequence":p["sequence"]}));
            }
        }
        let result = json!({"schema_version":1,"scope":self.config,"configuration":hash(&self.config),"trades":trades,"intent":intent,"market_value":rounded(&market,self.currency.precision()),"unrealized_pnl":(&market-&cost).normalized().to_plain_string()});
        Ok(ValuationEffect {
            input: json!({"schema_version":1,"position":serde_json::from_slice::<Value>(&bytes)?,"intent":intent}),
            result,
        })
    }
}
