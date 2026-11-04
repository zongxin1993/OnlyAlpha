use crate::{Manager, model::*};
use bigdecimal::Zero;
use serde_json::{Value, json};
impl Manager {
    pub(crate) fn reconcile(
        &mut self,
        v: &Value,
        at: &num_bigint::BigInt,
    ) -> Result<(Status, Value), Error> {
        let r = row(
            v,
            &[
                "instrument",
                "snapshot_id",
                "sequence",
                "position_side",
                "total",
                "settled",
                "unsettled",
                "available",
                "frozen",
                "average",
                "quality",
            ],
        )?;
        let i = id(&r["instrument"])?;
        let spec = self.spec(&i)?;
        let sid = id(&r["snapshot_id"])?;
        let seq = uint(&r["sequence"])?;
        if !matches!(text(&r["position_side"])?, "LONG" | "SHORT" | "FLAT") {
            return Err(err("POSITION_BROKER_SIDE"));
        }
        if r["quality"] != "VERIFIED" {
            return Err(err("POSITION_BROKER_PROOF_UNAVAILABLE"));
        }
        let mut values = std::collections::BTreeMap::new();
        for k in ["total", "settled", "unsettled", "available", "frozen"] {
            let d = nonnegative(&r[k])?;
            onlyalpha_domain::value::OnlyQuantity::new(d.to_string().parse()?, spec.qp)?;
            values.insert(k, d);
        }
        if &values["settled"] + &values["unsettled"] != values["total"]
            || values["available"] > values["total"]
            || values["frozen"] > values["total"]
            || &values["available"] + &values["frozen"] > values["total"]
        {
            return Err(err("POSITION_BROKER_BUCKETS"));
        }
        let avg = if r["average"].is_null() {
            None
        } else {
            Some(spec.price(&r["average"])?)
        };
        if values["total"] > Decimal::zero() && (avg.is_none() || r["position_side"] == "FLAT") {
            return Err(err("POSITION_BROKER_INCOMPLETE"));
        }
        let sig = hash(&json!([v, at.to_string()]));
        let receipt = format!("broker:{sid}");
        if let Some(old) = self.state.receipts.get(&receipt) {
            return Ok((
                if old == &sig {
                    Status::Duplicate
                } else {
                    Status::Conflict
                },
                Value::Null,
            ));
        }
        if let Some(old) = self.state.brokers.get(&i)
            && (seq <= uint(&old["snapshot"]["sequence"])? || at < &time(&old["time"])?)
        {
            self.state.receipts.insert(receipt, sig);
            return Ok((
                Status::Stale,
                json!({"instrument":i,"reason":"STALE_BROKER_OBSERVATION"}),
            ));
        }
        if self.state.accounts.get(&i).is_some_and(|b| at < &b.updated) {
            self.state.receipts.insert(receipt, sig);
            return Ok((
                Status::Stale,
                json!({"instrument":i,"reason":"BROKER_PRECEDES_LOCAL_ECONOMICS"}),
            ));
        }
        let local = self.state.accounts.get(&i);
        let zero = Decimal::zero();
        let total = local.map_or(&zero, |b| &b.qty);
        let settled = local.map_or(&zero, |b| &b.settled);
        let unsettled = total - settled;
        let mut differences = Vec::new();
        let mut blocking = false;
        for (k, actual) in [
            ("total", total),
            ("settled", settled),
            ("unsettled", &unsettled),
        ] {
            if actual != &values[k] {
                differences.push(json!({"field":k,"authority":if k=="total"{"BROKER"}else{"RECONCILED"},"local":number(actual),"broker":number(&values[k]),"severity":"BLOCK_INSTRUMENT"}));
                blocking = true;
            }
        }
        if total > &zero && r["position_side"] != "LONG" {
            differences.push(
                json!({"field":"position_side","authority":"BROKER","severity":"BLOCK_INSTRUMENT"}),
            );
            blocking = true;
        }
        let account_available = self.account_available(&i)?;
        if account_available != values["available"] {
            differences
                .push(json!({"field":"available","authority":"RECONCILED","severity":"WARNING"}));
        }
        let acknowledged = self.holds(&i, None, false) - self.holds(&i, None, true);
        if acknowledged != values["frozen"] {
            differences
                .push(json!({"field":"frozen","authority":"RECONCILED","severity":"WARNING"}));
        }
        if let (Some(b), Some(average)) = (local, avg)
            && !b.qty.is_zero()
            && ratio(&b.cost, &b.qty, i64::from(spec.pp))? != average
        {
            differences.push(json!({"field":"average","authority":"LOCAL_AND_BROKER_SEPARATE","severity":"INFO"}));
        }
        let result = json!({"instrument":i,"snapshot":v,"time":serde_json::from_str::<Value>(&at.to_string())?,"blocking":blocking,"differences":differences,"actions":if blocking{vec!["RECORD_DIFFERENCE","QUERY_ORDERS_AND_TRADES","BLOCK_INSTRUMENT"]}else{vec!["RECORD_COMPARISON"]}});
        self.state.brokers.insert(i, result.clone());
        self.state.receipts.insert(receipt, sig);
        Ok((Status::Applied, result))
    }
}
