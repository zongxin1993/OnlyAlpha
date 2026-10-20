use crate::{Manager, model::*};
use bigdecimal::Zero;
use num_bigint::BigInt;
use onlyalpha_domain::time::OnlyTimestamp;
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// Account-derived immutable performance. It is not a trading permission.
/// ```compile_fail
/// use onlyalpha_account::Performance;
/// let forged = Performance { value: serde_json::json!({}) };
/// ```
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Performance {
    value: Value,
}
impl Performance {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
}
// Exact rational rounding: BigDecimal's default division precision is not a semantic input.
fn ratio(n: &Decimal, d: &Decimal) -> Option<String> {
    if d <= &Decimal::zero() {
        return None;
    }
    let (mut a, sa) = n.as_bigint_and_exponent();
    let (mut b, sb) = d.as_bigint_and_exponent();
    let shift = 8 + sb - sa;
    let exponent = u32::try_from(shift.unsigned_abs()).expect("bounded monetary scale");
    let power = BigInt::from(10).pow(exponent);
    if shift >= 0 {
        a *= power;
    } else {
        b *= power;
    }
    let negative = a < BigInt::zero();
    if negative {
        a = -a;
    }
    let mut q = &a / &b;
    let twice = (&a % &b) * 2;
    if twice > b || (twice == b && &q % 2 != BigInt::zero()) {
        q += 1;
    }
    if negative {
        q = -q;
    }
    Some(Decimal::new(q, 8).to_plain_string())
}
impl Manager {
    /// Rebuild the whole Account path from its owning journal. Genesis time is explicit.
    pub fn performance(&self, initial_time: &OnlyTimestamp) -> Result<Performance, Error> {
        let mut candidate = Self::new(self.config.clone())?;
        let initial = analytical(&candidate.snapshot()["equity"])?;
        let mut points = Vec::new();
        let mut external = Decimal::zero();
        let mut occurred = false;
        let mut peak = initial.clone();
        let mut maximum: Option<Decimal> = None;
        let mut current = None;
        let mut flags = BTreeSet::<String>::new();
        let genesis = json!({"configuration":hash(&self.config),"time":initial_time.unix_nanos().to_string()});
        let mut source = json!({"kind":"ACCOUNT_CREATED","command":Value::Null,"cause":hash(&genesis),"source_time":serde_json::from_str::<Value>(&initial_time.unix_nanos().to_string())?});
        for index in 0..=self.state.journal.len() {
            if index > 0 {
                let command = &self.state.journal[index - 1];
                if time(&command["time"])? < *initial_time.unix_nanos() {
                    return Err(err("PERFORMANCE_GENESIS_AFTER_SOURCE"));
                }
                let before = candidate.state.cash.clone();
                let outcome = candidate.apply_inner(command)?;
                if candidate.state.journal.len() != index {
                    return Err(err("PERFORMANCE_HISTORY_CONFLICT"));
                }
                if outcome.status == Status::Duplicate {
                    continue;
                }
                if command["op"] == "CASH_CHANGE" && outcome.status == Status::Applied {
                    external += &candidate.state.cash - before;
                    occurred = true;
                }
                source = json!({"kind":command["op"],"command":command["command_id"],"cause":hash(command),"upstream_cause":command["cause"],"source_time":command["time"],"outcome":format!("{:?}",outcome.status)});
            }
            let snapshot = candidate.snapshot();
            let equity = analytical(&snapshot["equity"])?;
            peak = peak.max(equity.clone());
            current = ratio(&(&equity - &peak), &peak);
            if let Some(ref raw) = current {
                let drawdown = analytical(&json!(raw))?;
                maximum = Some(maximum.map_or(drawdown.clone(), |m| m.min(drawdown)));
            } else {
                flags.insert("NON_POSITIVE_HIGH_WATER_MARK".into());
            }
            for flag in &candidate.state.flags {
                flags.insert(flag.clone());
            }
            let time = if index == 0 {
                source["source_time"].clone()
            } else {
                snapshot["time"].clone()
            };
            points.push(json!({"sequence":points.len(),"account_sequence":snapshot["sequence"],"time":time,"source":source["kind"],"source_time":source["source_time"],"cause":source["cause"],"provenance":source,"external_cash_flow":formatted(&external,self.precision),"external_cash_flow_occurred":occurred,"snapshot":snapshot}));
        }
        if candidate.checkpoint()? != self.checkpoint()? {
            return Err(err("PERFORMANCE_HISTORY_HEAD"));
        }
        let final_snapshot = candidate.snapshot();
        let final_equity = analytical(&final_snapshot["equity"])?;
        if initial <= Decimal::zero() {
            flags.insert("ZERO_INITIAL_EQUITY".into());
        }
        let return_since_start = if occurred {
            flags.insert("EXTERNAL_CASH_FLOW_REQUIRES_TWR".into());
            None
        } else {
            ratio(&(&final_equity - &initial), &initial)
        };
        let summary = json!({"authority":"ACCOUNT","initial_equity":formatted(&initial,self.precision),"final_equity":formatted(&final_equity,self.precision),"realized_pnl":final_snapshot["realized_pnl"],"unrealized_pnl":final_snapshot["unrealized_pnl"],"fees":final_snapshot["fees"],"net_pnl":formatted(&(&final_equity-&initial-&external),self.precision),"external_cash_flow":formatted(&external,self.precision),"external_cash_flow_occurred":occurred,"return_since_start":return_since_start,"high_water_mark":formatted(&peak,self.precision),"current_drawdown":current,"maximum_drawdown":maximum.map(|v|formatted(&v,8)),"drawdown_basis":"ACCOUNT_EQUITY","valuation_count":points.len(),"quality_flags":flags});
        let mut value = json!({"schema_version":1,"semantic_version":"ACCOUNT_PERFORMANCE@1","scope":self.config,"initial_time":genesis["time"],"account_checkpoint":self.checkpoint()?.1,"timeline":points,"summary":summary});
        value["id"] = json!(format!("AP-{}", hash(&value)));
        Ok(Performance { value })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_ratio_half_even_and_large_coefficients() {
        for (n, d, expected) in [
            ("1", "200000000", "0.00000000"),
            ("3", "200000000", "0.00000002"),
            ("-3", "200000000", "-0.00000002"),
            ("-1", "200000000", "0.00000000"),
            ("1", "12", "0.08333333"),
        ] {
            assert_eq!(
                ratio(
                    &analytical(&json!(n)).unwrap(),
                    &analytical(&json!(d)).unwrap()
                ),
                Some(expected.into())
            );
        }
        let n = format!("{}1", "1".repeat(300));
        let d = format!("{}0", "1".repeat(300));
        assert_eq!(
            ratio(
                &analytical(&json!(n)).unwrap(),
                &analytical(&json!(d)).unwrap()
            ),
            Some("1.00000000".into())
        );
        let scale = BigInt::from(10).pow(300);
        let denominator: BigInt = &scale * 3;
        let numerator: BigInt = &denominator + BigInt::from(15) * BigInt::from(10).pow(291) + 1;
        assert_eq!(
            ratio(
                &analytical(&json!(numerator.to_string())).unwrap(),
                &analytical(&json!(denominator.to_string())).unwrap()
            ),
            Some("1.00000001".into())
        );
        assert_eq!(ratio(&Decimal::zero(), &Decimal::zero()), None);
    }
}
