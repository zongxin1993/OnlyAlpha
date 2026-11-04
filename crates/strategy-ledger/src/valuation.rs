use crate::model::*;
use serde_json::Value;
use std::collections::BTreeSet;
impl Ledger {
    pub(crate) fn valuation(&mut self, p: &Value, precision: u8) -> Result<(), Error> {
        let version = uint(&p["version"])?;
        if uint(&p["economic_version"])? != self.economic_version
            || version <= self.valuation_version
        {
            return Err(err("LEDGER_VALUATION_BASIS"));
        }
        let mut seen = BTreeSet::new();
        for row in p["lines"].as_array().expect("normalized lines") {
            let inst = instrument(&row["instrument"])?;
            if !seen.insert(inst.clone()) {
                return Err(err("LEDGER_VALUATION_DUPLICATE_LINE"));
            }
            let line = self
                .lines
                .get_mut(&inst)
                .ok_or_else(|| err("LEDGER_VALUATION_UNKNOWN_LINE"))?;
            if uint(&row["allocation_version"])? != line.allocation.version
                || text(&row["allocation_evidence"])? != line.allocation.evidence
            {
                return Err(err("LEDGER_VALUATION_ALLOCATION_BASIS"));
            }
            let mark = positive(&row["mark"])?;
            let multiplier = positive(&row["multiplier"])?;
            if multiplier != line.multiplier {
                return Err(err("LEDGER_MULTIPLIER_CONFLICT"));
            }
            line.market = (&line.allocation.quantity * &mark * &multiplier)
                .with_scale_round(i64::from(precision), bigdecimal::RoundingMode::HalfEven);
            line.unrealized = &line.market - &line.allocation.cost;
            line.mark = mark;
        }
        if seen.len() != self.lines.len() {
            return Err(err("LEDGER_VALUATION_INCOMPLETE"));
        }
        self.valuation_version = version;
        Ok(())
    }
}
