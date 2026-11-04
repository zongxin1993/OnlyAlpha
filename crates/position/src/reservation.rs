use crate::{Manager, model::*};
use bigdecimal::Zero;
use serde_json::{Value, json};
impl Manager {
    pub(crate) fn reserve_command(
        &mut self,
        op: &str,
        v: &Value,
        _at: &num_bigint::BigInt,
    ) -> Result<(Status, Value), Error> {
        if op == "RESERVE" {
            let r = row(v, &["instrument", "cluster", "order", "quantity"])?;
            let i = id(&r["instrument"])?;
            let c = self.cluster_id(&r["cluster"])?;
            let order = id(&r["order"])?;
            let quantity = self.spec(&i)?.quantity(&r["quantity"])?;
            if let Some(previous) = self.state.reservations.get(&order) {
                return Ok((
                    if previous.instrument == i
                        && previous.cluster == c
                        && previous.quantity == quantity
                    {
                        Status::Duplicate
                    } else {
                        Status::Conflict
                    },
                    Value::Null,
                ));
            }
            if quantity > self.cluster_available(&c, &i)? {
                return Err(err("POSITION_RESERVATION_UNAVAILABLE"));
            }
            let reservation = Reservation {
                instrument: i,
                cluster: c,
                order: order.clone(),
                quantity: quantity.clone(),
                remaining: quantity,
                consumed: Decimal::zero(),
                released: Decimal::zero(),
                stage: "LOCAL_ONLY".into(),
                acknowledged: false,
                state: "ACTIVE".into(),
                version: 1,
            };
            let details = reservation.record();
            self.state.reservations.insert(order, reservation);
            return Ok((Status::Applied, details));
        }
        let fields = if op == "STAGE" {
            vec!["order", "cluster", "stage"]
        } else {
            vec!["order", "cluster", "broker_confirmed"]
        };
        let r = row(v, &fields)?;
        let order = id(&r["order"])?;
        let cluster = self.cluster_id(&r["cluster"])?;
        let reservation = self
            .state
            .reservations
            .get_mut(&order)
            .ok_or_else(|| err("POSITION_RESERVATION_REQUIRED"))?;
        if reservation.cluster != cluster {
            return Err(err("POSITION_RESERVATION_OWNER"));
        }
        if reservation.remaining.is_zero() {
            return Err(err("POSITION_RESERVATION_TERMINAL"));
        }
        if op == "STAGE" {
            let next = text(&r["stage"])?;
            let late_ack = reservation.stage == "RELEASE_PENDING"
                && !reservation.acknowledged
                && next == "BROKER_ACKNOWLEDGED";
            let allowed = late_ack
                || matches!(
                    (reservation.stage.as_str(), next),
                    ("LOCAL_ONLY", "SENT_TO_BROKER") | ("SENT_TO_BROKER", "BROKER_ACKNOWLEDGED")
                );
            if !allowed {
                return Err(err("POSITION_STAGE_TRANSITION"));
            }
            if next == "BROKER_ACKNOWLEDGED" {
                reservation.acknowledged = true;
            }
            if !late_ack {
                reservation.stage = next.into();
            }
        } else {
            let confirmed = boolean(&r["broker_confirmed"])?;
            if !confirmed && reservation.stage != "LOCAL_ONLY" {
                if reservation.stage == "RELEASE_PENDING" {
                    return Err(err("POSITION_RELEASE_ALREADY_PENDING"));
                }
                reservation.stage = "RELEASE_PENDING".into();
            } else {
                reservation.released += &reservation.remaining;
                reservation.remaining = Decimal::zero();
                reservation.stage = "RELEASED".into();
                reservation.state = "RELEASED".into();
            }
        }
        reservation.version += 1;
        Ok((Status::Applied, json!({"reservation":reservation.record()})))
    }
}
