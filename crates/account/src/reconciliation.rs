use crate::{Manager, model::*};
use serde_json::Value;
impl Manager {
    pub(crate) fn observe_broker(
        &mut self,
        p: &Value,
        t: &num_bigint::BigInt,
    ) -> Result<Status, Error> {
        for f in [
            "cash",
            "reserved",
            "trade_available",
            "withdrawable",
            "equity",
        ] {
            nonnegative(&p[f], self.precision)?;
        }
        let seq = uint(&p["sequence"])?;
        if self.state.broker_sequence.is_some_and(|old| seq <= old)
            || self.state.now.as_ref().is_some_and(|old| t < old)
        {
            return Ok(Status::Stale);
        }
        self.state.broker_sequence = Some(seq);
        self.state.broker = Some(p.clone());
        if p["quality"] != "VERIFIED" || uint(&p["basis_sequence"])? != self.state.sequence {
            self.state.flags.insert("BROKER_PROOF_UNAVAILABLE".into());
            return Ok(Status::Applied);
        }
        let snapshot = self.snapshot();
        self.state.differences.clear();
        for (field, local) in [
            ("cash", "cash"),
            ("reserved", "reserved"),
            ("trade_available", "trade_available"),
            ("withdrawable", "withdrawable"),
            ("equity", "equity"),
        ] {
            if p[field] != snapshot[local] {
                self.state.differences.push(field.into());
            }
        }
        self.state.flags.remove("BROKER_PROOF_UNAVAILABLE");
        if self.state.differences.is_empty() {
            self.state.flags.remove("BROKER_LOCAL_CONFLICT");
        } else {
            self.state.flags.insert("BROKER_LOCAL_CONFLICT".into());
        }
        Ok(Status::Applied)
    }
}
