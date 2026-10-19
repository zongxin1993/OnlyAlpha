use crate::{Manager, model::*};
use bigdecimal::Zero;
use serde_json::Value;
impl Manager {
    pub(crate) fn reserve(&mut self, p: &Value) -> Result<(), Error> {
        let amount = nonnegative(&p["amount"], self.precision)?;
        let rid = id(&p["reservation"])?;
        let order = id(&p["order"])?;
        if !self.state.flags.is_empty()
            || amount <= Decimal::zero()
            || amount > self.state.withdrawable()
        {
            return Err(err("ACCOUNT_RESERVE_BLOCKED_OR_INSUFFICIENT"));
        }
        if self.state.reservations.contains_key(&rid)
            || self.state.reservations.values().any(|r| r.order == order)
        {
            return Err(err("ACCOUNT_RESERVATION_ORDER_CONFLICT"));
        }
        self.state.reservations.insert(
            rid,
            Reservation {
                order,
                original: amount.clone(),
                consumed: Decimal::zero(),
                remaining: amount,
                released: Decimal::zero(),
                sent: false,
                acknowledged: false,
                unknown: false,
                cancel_pending: false,
                terminal_outcome: None,
            },
        );
        Ok(())
    }
    pub(crate) fn stage(&mut self, p: &Value) -> Result<(), Error> {
        let r = self
            .state
            .reservations
            .get_mut(text(&p["reservation"])?)
            .ok_or_else(|| err("ACCOUNT_RESERVATION_UNKNOWN"))?;
        if r.remaining == Decimal::zero() {
            return Err(err("ACCOUNT_RESERVATION_TERMINAL"));
        }
        match text(&p["stage"])? {
            "SENT_TO_BROKER" => {
                if r.sent {
                    return Err(err("ACCOUNT_STAGE_REGRESSION"));
                }
                r.sent = true;
            }
            "SUBMIT_UNKNOWN" => {
                r.sent = true;
                r.unknown = true;
            }
            "BROKER_ACKNOWLEDGED" => {
                r.sent = true;
                r.acknowledged = true;
                r.unknown = false;
            }
            "CANCEL_REQUESTED" => {
                if !r.sent {
                    return Err(err("ACCOUNT_CANCEL_BEFORE_SEND"));
                }
                r.cancel_pending = true;
            }
            _ => return Err(err("ACCOUNT_STAGE_INVALID")),
        }
        Ok(())
    }
    pub(crate) fn release(&mut self, p: &Value) -> Result<Status, Error> {
        let r = self
            .state
            .reservations
            .get_mut(text(&p["reservation"])?)
            .ok_or_else(|| err("ACCOUNT_RESERVATION_UNKNOWN"))?;
        let observed = text(&p["outcome"])?;
        if let Some(terminal) = &r.terminal_outcome {
            return if terminal == observed {
                Ok(Status::Duplicate)
            } else {
                Err(err("ACCOUNT_TERMINAL_OUTCOME_CONFLICT"))
            };
        }
        match observed {
            "UNKNOWN" => {
                r.sent = true;
                r.unknown = true;
                r.cancel_pending = true;
            }
            "NOT_SENT" => {
                if r.sent {
                    return Err(err("ACCOUNT_RELEASE_OUTCOME_UNPROVEN"));
                }
                r.released += &r.remaining;
                r.remaining = Decimal::zero();
            }
            "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED" => {
                r.released += &r.remaining;
                r.remaining = Decimal::zero();
                r.unknown = false;
                r.cancel_pending = false;
            }
            _ => return Err(err("ACCOUNT_RELEASE_OUTCOME_INVALID")),
        }
        if r.remaining == Decimal::zero() {
            r.terminal_outcome = Some(observed.into());
        }
        Ok(Status::Applied)
    }
    pub(crate) fn consume(&mut self, p: &Value, debit: &Decimal) -> Result<(), Error> {
        let id = text(&p["reservation"])?;
        let r = self
            .state
            .reservations
            .get(id)
            .ok_or_else(|| err("ACCOUNT_BUY_REQUIRES_RESERVATION"))?;
        if text(&p["order"])? != r.order || r.remaining == Decimal::zero() {
            return Err(err("ACCOUNT_RESERVATION_SCOPE_OR_TERMINAL"));
        }
        if debit > &r.remaining || (!boolean(&p["terminal_fill"])? && debit == &r.remaining) {
            return Err(err("ACCOUNT_RESERVATION_INSUFFICIENT"));
        }
        let r = self
            .state
            .reservations
            .get_mut(id)
            .expect("validated reservation");
        // An observed Fill proves submission even when the send callback has not arrived.
        r.sent = true;
        r.remaining -= debit;
        r.consumed += debit;
        if boolean(&p["terminal_fill"])? {
            r.released += &r.remaining;
            r.remaining = Decimal::zero();
            r.unknown = false;
            r.cancel_pending = false;
            r.terminal_outcome = Some("FILLED".into());
        }
        Ok(())
    }
}
