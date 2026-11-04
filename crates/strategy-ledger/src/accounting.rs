use crate::model::*;
use bigdecimal::Zero;
use serde_json::{Value, json};
impl Ledger {
    pub(crate) fn entry(
        &mut self,
        kind: &str,
        amount: Decimal,
        affects: bool,
        input: &Value,
        sequence: u64,
        p: u8,
    ) {
        self.entries.push(json!({"kind":kind,"amount":formatted(&amount,p),"affects_cash":affects,"sequence":sequence,"source":input}));
    }
    pub(crate) fn trade(&mut self, p: &Value, precision: u8, sequence: u64) -> Result<(), Error> {
        let inst = instrument(&p["instrument"])?;
        let existing = self
            .lines
            .get(&inst)
            .map(|l| l.allocation.clone())
            .unwrap_or_else(Allocation::empty);
        if p["before"] != existing.record(precision) {
            return Err(err("LEDGER_ALLOCATION_BEFORE_CONFLICT"));
        }
        let a = &p["after"];
        let quantity = decimal(&a["quantity"])?;
        let cost = analytical(&a["cost"])?;
        let realized = analytical(&a["realized"])?;
        let version = uint(&a["version"])?;
        let cycle = uint(&a["cycle"])?;
        let identity = id(&a["identity"])?.to_owned();
        let realized_exact = analytical(&a["realized_exact"])?;
        let new_cycle = cycle != existing.cycle;
        if new_cycle {
            if existing.quantity != Decimal::zero()
                || existing.cycle.checked_add(1) != Some(cycle)
                || existing.identity.as_ref() == Some(&identity)
                || version != 1
                || realized != Decimal::zero()
                || realized_exact != Decimal::zero()
            {
                return Err(err("LEDGER_ALLOCATION_CYCLE"));
            }
        } else if existing.identity.as_ref() != Some(&identity) || version <= existing.version {
            return Err(err("LEDGER_ALLOCATION_VERSION_OR_IDENTITY"));
        }
        let notional = nonnegative(&p["notional"], precision)?;
        let charges = nonnegative(&p["charges"], precision)?;
        let rebates = nonnegative(&p["rebates"], precision)?;
        let fee = &charges - &rebates;
        let rd = if new_cycle {
            Decimal::zero()
        } else {
            &realized - &existing.realized
        };
        let buy = text(&p["side"])? == "BUY";
        if buy {
            if quantity <= existing.quantity
                || cost <= existing.cost
                || (&cost - &existing.cost)
                    .with_scale_round(i64::from(precision), bigdecimal::RoundingMode::HalfEven)
                    != notional
                || rd != Decimal::zero()
                || (!new_cycle && realized_exact != existing.realized_exact)
            {
                return Err(err("LEDGER_BUY_ALLOCATION_RELATION"));
            }
            let rid = text(&p["reservation"])?;
            let r = self
                .reservations
                .get_mut(rid)
                .ok_or_else(|| err("LEDGER_RESERVATION_UNKNOWN"))?;
            let gross = &notional + &charges;
            let terminal = boolean(&p["terminal_fill"])?;
            if r.order != text(&p["order"])?
                || r.remaining == Decimal::zero()
                || gross > r.remaining
                || (!terminal && gross == r.remaining)
            {
                return Err(err("LEDGER_RESERVATION_SCOPE_OR_AMOUNT"));
            }
            r.sent = true;
            r.consumed += &gross;
            r.remaining -= &gross;
            if terminal {
                let released = r.remaining.clone();
                r.released += &released;
                r.remaining = Decimal::zero();
                r.unknown = false;
                r.cancel_pending = false;
                r.terminal_outcome = Some("FILLED".into());
                if released > Decimal::zero() {
                    self.entry("RELEASE", released, false, p, sequence, precision);
                }
            }
            self.cash -= &notional + &fee;
        } else {
            if !p["reservation"].is_null()
                || quantity >= existing.quantity
                || cost > existing.cost
                || new_cycle
                || &realized_exact - &existing.realized_exact + (&existing.cost - &cost)
                    <= Decimal::zero()
                || (&realized_exact - &existing.realized_exact + (&existing.cost - &cost))
                    .with_scale_round(i64::from(precision), bigdecimal::RoundingMode::HalfEven)
                    != notional
            {
                return Err(err("LEDGER_SELL_ALLOCATION_RELATION"));
            }
            self.cash += &notional - &fee;
        }
        // Residual is accumulated from validated trade deltas, independently of the equity invariant.
        self.rounding_residual += if buy {
            &cost - &existing.cost - &notional
        } else {
            &notional - (&existing.cost - &cost) - &rd
        };
        self.realized += rd;
        self.fees += &fee;
        self.trade_sequence = Some(uint(&p["source_sequence"])?);
        self.economic_version += 1;
        let mark = positive(&p["mark"])?;
        let multiplier = positive(&p["multiplier"])?;
        if self
            .lines
            .get(&inst)
            .is_some_and(|l| l.multiplier != multiplier)
        {
            return Err(err("LEDGER_MULTIPLIER_CONFLICT"));
        }
        let market = (&quantity * &mark * &multiplier)
            .with_scale_round(i64::from(precision), bigdecimal::RoundingMode::HalfEven);
        let unrealized = &market - &cost;
        self.lines.insert(
            inst,
            Line {
                allocation: Allocation {
                    identity: Some(identity),
                    cycle,
                    realized_exact,
                    quantity,
                    cost,
                    realized,
                    version,
                    evidence: text(&p["allocation_evidence"])?.into(),
                },
                mark,
                multiplier,
                market,
                unrealized,
            },
        );
        self.entry(
            if buy {
                "BUY_SETTLEMENT"
            } else {
                "SELL_SETTLEMENT"
            },
            if buy { -notional } else { notional },
            true,
            p,
            sequence,
            precision,
        );
        if fee != Decimal::zero() || charges != Decimal::zero() || rebates != Decimal::zero() {
            self.fee_entries.push(json!({"fee_instruction":p["fee_instruction"],"trade":p["trade"],"order":p["order"],"charges":formatted(&charges,precision),"rebates":formatted(&rebates,precision)}));
            self.entry("FEE", -fee, true, p, sequence, precision);
        }
        Ok(())
    }
}
