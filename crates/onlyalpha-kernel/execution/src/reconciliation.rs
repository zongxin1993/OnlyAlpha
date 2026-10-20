use crate::{Components, Record, Store, model::*};
use bigdecimal::{BigDecimal, Zero};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// Immutable diagnostic derived only from the current owning Ready source.
/// It neither authorizes execution nor writes an accounting owner.
/// ```compile_fail
/// use onlyalpha_execution::LedgerReconciliation;
/// let forged = LedgerReconciliation { value: serde_json::json!({"status":"MATCHED"}) };
/// ```
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LedgerReconciliation {
    value: Value,
}
impl LedgerReconciliation {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
}
impl Components {
    /// Final-barrier/recovery diagnostic. An incomplete source is an error, not MATCHED.
    pub fn reconcile<S: Store>(&self, store: &S) -> Result<LedgerReconciliation, Error> {
        self.ready_source(store)?;
        let checkpoint = &self.meta["fee_authority"];
        let mut fee_owner = boundary(onlyalpha_fee::Manager::new(
            checkpoint["config"].clone(),
            usize::try_from(uint(&checkpoint["capacity"])?)
                .map_err(|_| err("RECONCILIATION_FEE_CAPACITY"))?,
        ))?;
        let mut expected = BTreeMap::new();
        let mut head = Value::Null;
        let mut time = Value::Null;
        let owners = self.payloads()?;
        if object(&self.meta["transactions"])?.len() as u64 != self.sequence {
            return Err(err("RECONCILIATION_TRANSACTION_COMPLETENESS"));
        }
        // Capture the exact same immutable prefix used for fee attribution below.
        let mut predecessor: Vec<_> = Self::new(self.config.clone())?
            .payloads()?
            .iter()
            .map(hash)
            .collect();
        for sequence in 1..=self.sequence {
            let record = store
                .get(sequence)?
                .ok_or_else(|| err("RECONCILIATION_SOURCE_MISSING"))?;
            let prepared = record.prepared();
            if self.meta["transactions"][sequence.to_string()] != prepared.id() {
                return Err(err("RECONCILIATION_TRANSACTION_CAUSE"));
            }
            if !record.ready()
                || prepared.sequence() != sequence
                || prepared.value["config_hash"] != hash(&self.config)
            {
                return Err(err("RECONCILIATION_SOURCE_PREFIX"));
            }
            for (i, previous) in predecessor.iter_mut().enumerate() {
                let projection = &prepared.value["projections"][i];
                if projection["before_hash"] != *previous {
                    return Err(err("RECONCILIATION_SOURCE_LINEAGE"));
                }
                *previous = text(&projection["result_hash"])?.to_owned();
            }
            record_fee(&self.config, &record, &mut fee_owner, &mut expected)?;
            head =
                json!({"transaction":prepared.id(),"payload_hash":prepared.value["payload_hash"]});
            time = prepared.input()["time"].clone();
        }
        if predecessor != owners.iter().map(hash).collect::<Vec<_>>() {
            return Err(err("RECONCILIATION_SOURCE_HEAD"));
        }
        if fee_owner.checkpoint() != *checkpoint {
            return Err(err("RECONCILIATION_FEE_HISTORY_UNAVAILABLE"));
        }
        let (totals, differences) = compare(
            &self.config,
            &owners[2],
            &owners[3],
            &expected,
            self.precision,
        )?;
        let scope: serde_json::Map<_, _> = [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
            "currency",
        ]
        .into_iter()
        .map(|k| (k.into(), self.config[k].clone()))
        .collect();
        let source = json!({"configuration":hash(&self.config),"sequence":self.sequence,
            "time":time,"head":head,
            "owners":COMPONENTS.iter().zip(&owners).map(|(name,cp)|json!({"component":name,"checkpoint":hash(cp)})).collect::<Vec<_>>()});
        let mut value = json!({"schema_version":1,"semantic_version":"RUNTIME_LEDGER_RECONCILIATION@1",
            "scope":scope,"cluster_ids":self.config["capitals"].as_object().expect("validated capitals").keys().collect::<Vec<_>>(),"source":source,"trade_count":expected.len(),
            "status":if differences.is_empty(){"MATCHED"}else{"MISMATCHED"},"totals":totals,"differences":differences});
        value["id"] = json!(format!("RLR-{}", hash(&value)));
        Ok(LedgerReconciliation { value })
    }
}

// Reuse the owning Fee reducer: cumulative targets are not incremental Trade fees.
fn record_fee(
    config: &Value,
    record: &Record,
    owner: &mut onlyalpha_fee::Manager,
    expected: &mut BTreeMap<String, Value>,
) -> Result<(), Error> {
    let input = record.prepared().input();
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ] {
        if input[k] != config[k] {
            return Err(err("RECONCILIATION_FACT_SCOPE"));
        }
    }
    let cluster = text(&input["cluster"])?;
    if config["profiles"].get(cluster).is_none()
        || input["revision"] != config["profiles"][cluster]["revision"]
    {
        return Err(err("RECONCILIATION_FACT_CLUSTER"));
    }
    if input["op"] != "FILL" {
        return Ok(());
    }
    let application = boundary(owner.apply_admitted_target(&input["payload"]["fees"]))?.record();
    let trade = text(&application["trade"])?;
    if application["subject"]["cluster"] != cluster
        || application["order"] != input["payload"]["order"]
        || application["trade"] != input["payload"]["trade"]
    {
        return Err(err("RECONCILIATION_FEE_RELATION"));
    }
    if expected
        .insert(
            trade.into(),
            json!({"cluster":cluster,"entry":{
            "trade":trade,"order":application["order"],"fee_instruction":application["id"],
            "charges":application["charges"],"rebates":application["rebates"]}}),
        )
        .is_some()
    {
        return Err(err("RECONCILIATION_DUPLICATE_TRADE"));
    }
    Ok(())
}

fn array(v: &Value) -> Result<&Vec<Value>, Error> {
    v.as_array()
        .ok_or_else(|| err("RECONCILIATION_SOURCE_ARRAY"))
}
fn object(v: &Value) -> Result<&serde_json::Map<String, Value>, Error> {
    v.as_object()
        .ok_or_else(|| err("RECONCILIATION_SOURCE_OBJECT"))
}
fn fee_entry(payload: &Value) -> Result<Value, Error> {
    for k in ["trade", "order", "fee_instruction"] {
        id(&payload[k])?;
    }
    for k in ["charges", "rebates"] {
        if exact(&payload[k])? < BigDecimal::zero() {
            return Err(err("RECONCILIATION_NEGATIVE_FEE_COMPONENT"));
        }
    }
    Ok(
        json!({"trade":payload["trade"],"order":payload["order"],"fee_instruction":payload["fee_instruction"],"charges":payload["charges"],"rebates":payload["rebates"]}),
    )
}

// Private comparison: raw snapshots never constitute a public proof-authoring API.
fn compare(
    config: &Value,
    account: &Value,
    ledger: &Value,
    expected: &BTreeMap<String, Value>,
    precision: u8,
) -> Result<(Value, Vec<Value>), Error> {
    for (owner, keys) in [
        (
            account,
            vec![
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "currency",
            ],
        ),
        (
            ledger,
            vec![
                "engine",
                "runtime",
                "account",
                "generation",
                "runtime_kind",
                "currency",
            ],
        ),
    ] {
        for k in keys {
            if owner["config"][k] != config[k] {
                return Err(err("RECONCILIATION_OWNER_SCOPE"));
            }
        }
    }
    if account["config"]["initial_cash"] != config["initial_cash"]
        || ledger["config"]["account_initial_cash"] != config["initial_cash"]
        || ledger["config"]["capitals"] != config["capitals"]
    {
        return Err(err("RECONCILIATION_CAPITAL_CONFIGURATION"));
    }
    let configured = object(&config["capitals"])?;
    let ledgers = object(&ledger["state"]["ledgers"])?;
    if configured.is_empty()
        || configured.keys().collect::<Vec<_>>() != ledgers.keys().collect::<Vec<_>>()
    {
        return Err(err("RECONCILIATION_CLUSTER_COMPLETENESS"));
    }
    let clusters: Vec<_> = configured.keys().cloned().collect();
    let snapshot = &account["state"]["snapshot"];
    for k in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "currency",
    ] {
        if snapshot[k] != config[k] {
            return Err(err("RECONCILIATION_SNAPSHOT_SCOPE"));
        }
    }
    if ledger["state"]["config"] != ledger["config"] {
        return Err(err("RECONCILIATION_OWNER_CONFIGURATION"));
    }

    let mut totals = json!({});
    let mut differences = vec![];
    for (field, account_value, ledger_field) in [
        (
            "initial_equity",
            &account["config"]["initial_cash"],
            "initial_capital",
        ),
        ("ledger_cash", &snapshot["cash"], "cash"),
        (
            "position_market_value",
            &snapshot["market_value"],
            "market_value",
        ),
        ("realized_pnl", &snapshot["realized_pnl"], "realized_pnl"),
        (
            "unrealized_pnl",
            &snapshot["unrealized_pnl"],
            "unrealized_pnl",
        ),
        ("fees", &snapshot["fees"], "fees"),
        ("equity", &snapshot["equity"], "equity"),
    ] {
        let a = exact(account_value)?;
        let mut total = BigDecimal::zero();
        for row in ledgers.values() {
            total += exact(&row["snapshot"][ledger_field])?;
        }
        let delta = &a - &total;
        let values = json!({"account_value":exact_record(&a,precision),"ledger_total":exact_record(&total,precision),"difference":exact_record(&delta,precision)});
        totals[field] = values.clone();
        if !delta.is_zero() {
            differences.push(
                json!({"kind":"AGGREGATE","field":field,"values":values,"cluster_ids":clusters}),
            );
        }
    }
    let mut source_fees = BigDecimal::zero();
    for e in expected.values() {
        source_fees += exact(&e["entry"]["charges"])? - exact(&e["entry"]["rebates"])?;
    }
    let account_fees = exact(&snapshot["fees"])?;
    let ledger_fees = exact(&totals["fees"]["ledger_total"])?;
    if source_fees != account_fees || source_fees != ledger_fees {
        differences.push(json!({"kind":"COMMITTED_FEES","field":"fees_from_committed_trades","cluster_ids":clusters,
            "values":{"committed_total":exact_record(&source_fees,precision),"account_value":exact_record(&account_fees,precision),"ledger_total":exact_record(&ledger_fees,precision),
            "account_difference":exact_record(&(&account_fees-&source_fees),precision),"ledger_difference":exact_record(&(&ledger_fees-&source_fees),precision)}}));
    }
    let mut account_entries = BTreeMap::<String, Vec<Value>>::new();
    for command in array(&account["journal"])? {
        if command["op"] == "TRADE" {
            let entry = fee_entry(&command["payload"])?;
            account_entries
                .entry(text(&entry["trade"])?.into())
                .or_default()
                .push(entry);
        } else if command["op"] == "FEE" {
            // No owning Fee Adjustment transaction is admitted by this Execution contract.
            return Err(err("RECONCILIATION_FEE_HISTORY_UNAVAILABLE"));
        }
    }
    let mut actual = BTreeMap::<String, Vec<Value>>::new();
    for (cluster, row) in ledgers {
        for entry in array(&row["fee_entries"])? {
            let normalized = fee_entry(entry)?;
            actual
                .entry(text(&normalized["trade"])?.into())
                .or_default()
                .push(json!({"cluster":cluster,"entry":normalized}));
        }
    }
    let trades = object(&ledger["state"]["trades"])?;
    let account_trades = object(&account["state"]["position_trades"])?;
    let union: BTreeSet<_> = expected
        .keys()
        .chain(actual.keys())
        .chain(account_entries.keys())
        .chain(trades.keys())
        .chain(account_trades.keys())
        .collect();
    for trade in union {
        let e = expected.get(trade);
        let entries = actual.get(trade).cloned().unwrap_or_default();
        let accounts = account_entries.get(trade).cloned().unwrap_or_default();
        let owner = trades.get(trade).cloned();
        let valid = if let Some(e) = e {
            let zero = exact(&e["entry"]["charges"])?.is_zero()
                && exact(&e["entry"]["rebates"])?.is_zero();
            accounts == vec![e["entry"].clone()]
                && entries == if zero { vec![] } else { vec![e.clone()] }
                && owner == Some(json!([e["cluster"], e["entry"]["order"]]))
                && account_trades.contains_key(trade)
        } else {
            false
        };
        if !valid {
            differences.push(json!({"kind":"TRADE_FEE","field":"trade_fee_attribution","trade":trade,
                "expected":e,"account_entries":accounts,"ledger_entries":entries,"ledger_owner":owner,
                "account_trade_present":account_trades.contains_key(trade)}));
        }
    }
    Ok((totals, differences))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn source() -> (Value, Value, Value) {
        let c = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00","capitals":{"a":"400.00","b":"600.00"},"profiles":{"a":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]},"b":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},"instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
        let owners = Components::new(c.clone()).unwrap().payloads().unwrap();
        (c, owners[2].clone(), owners[3].clone())
    }
    fn fee_source() -> (Value, Value, Value, BTreeMap<String, Value>) {
        let (c, mut a, mut l) = source();
        let entry = json!({"trade":"trade","order":"order","fee_instruction":"instruction","charges":"5.00","rebates":"1.00"});
        a["state"]["snapshot"]["fees"] = json!("4.00");
        l["state"]["ledgers"]["a"]["snapshot"]["fees"] = json!("4.00");
        a["journal"] = json!([{"op":"TRADE","payload":entry}]);
        a["state"]["position_trades"] = json!({"trade":{}});
        l["state"]["trades"] = json!({"trade":["a","order"]});
        l["state"]["ledgers"]["a"]["fee_entries"] = json!([entry]);
        (
            c,
            a,
            l,
            BTreeMap::from([("trade".into(), json!({"cluster":"a","entry":entry}))]),
        )
    }
    #[test]
    fn completeness_scope_missing_fields_and_wrong_owner_are_never_zero() {
        let (c, a, l) = source();
        let expected = BTreeMap::new();
        for field in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "currency",
        ] {
            let mut bad = a.clone();
            bad["config"][field] = Value::Null;
            assert!(
                compare(&c, &bad, &l, &expected, 2).is_err(),
                "account {field}"
            );
        }
        for field in [
            "engine",
            "runtime",
            "account",
            "generation",
            "runtime_kind",
            "currency",
        ] {
            let mut bad = l.clone();
            bad["config"][field] = json!("different");
            assert!(
                compare(&c, &a, &bad, &expected, 2).is_err(),
                "ledger {field}"
            );
        }
        for shape in [
            Value::Null,
            json!([]),
            json!({}),
            json!({"a":l["state"]["ledgers"]["a"]}),
            json!({"a":l["state"]["ledgers"]["a"],"b":l["state"]["ledgers"]["b"],"extra":l["state"]["ledgers"]["a"]}),
        ] {
            let mut bad = l.clone();
            bad["state"]["ledgers"] = shape;
            assert!(compare(&c, &a, &bad, &expected, 2).is_err());
        }
        for field in [
            "cash",
            "market_value",
            "realized_pnl",
            "unrealized_pnl",
            "fees",
            "equity",
        ] {
            let mut bad = a.clone();
            bad["state"]["snapshot"]
                .as_object_mut()
                .unwrap()
                .remove(field);
            assert!(compare(&c, &bad, &l, &expected, 2).is_err(), "{field}");
        }
    }
    #[test]
    fn every_aggregate_field_reports_exact_values_and_sign_without_mutating() {
        let (c, a, l) = source();
        for (field, key) in [
            ("ledger_cash", "cash"),
            ("position_market_value", "market_value"),
            ("realized_pnl", "realized_pnl"),
            ("unrealized_pnl", "unrealized_pnl"),
            ("fees", "fees"),
            ("equity", "equity"),
        ] {
            let mut bad = a.clone();
            let original = exact(&bad["state"]["snapshot"][key]).unwrap();
            bad["state"]["snapshot"][key] =
                json!(exact_record(&(original - BigDecimal::from(1)), 2));
            let before = bad.clone();
            let (totals, diffs) = compare(&c, &bad, &l, &BTreeMap::new(), 2).unwrap();
            assert_eq!(diffs.len(), if field == "fees" { 2 } else { 1 });
            assert_eq!(diffs[0]["field"], field);
            assert_eq!(totals[field]["difference"], "-1.00");
            assert_eq!(bad, before);
        }
        let mut bad = l.clone();
        bad["state"]["ledgers"]["a"]["snapshot"]["initial_capital"] = json!("399.00");
        let (_, diffs) = compare(&c, &a, &bad, &BTreeMap::new(), 2).unwrap();
        assert_eq!(diffs[0]["field"], "initial_equity");
        assert_eq!(diffs[0]["values"]["difference"], "1.00");
    }
    #[test]
    fn complete_trade_fee_relation_detects_net_equal_wrong_missing_extra_and_duplicate_entries() {
        let (c, a, l, e) = fee_source();
        assert!(compare(&c, &a, &l, &e, 2).unwrap().1.is_empty());
        let mut cases = vec![];
        let mut x = l.clone();
        x["state"]["ledgers"]["b"]["fee_entries"] =
            x["state"]["ledgers"]["a"]["fee_entries"].clone();
        x["state"]["ledgers"]["a"]["fee_entries"] = json!([]);
        cases.push(x);
        let mut x = l.clone();
        x["state"]["ledgers"]["a"]["fee_entries"] = json!([]);
        cases.push(x);
        let entry = l["state"]["ledgers"]["a"]["fee_entries"][0].clone();
        let mut x = l.clone();
        x["state"]["ledgers"]["a"]["fee_entries"] = json!([entry, entry]);
        cases.push(x);
        for field in ["trade", "order", "fee_instruction"] {
            let mut x = l.clone();
            x["state"]["ledgers"]["a"]["fee_entries"][0][field] = json!("foreign");
            cases.push(x);
        }
        let mut x = l.clone();
        x["state"]["ledgers"]["a"]["fee_entries"][0]["charges"] = json!("6.00");
        x["state"]["ledgers"]["a"]["fee_entries"][0]["rebates"] = json!("2.00");
        cases.push(x);
        let mut x = l.clone();
        x["state"]["trades"]["trade"] = json!(["b", "order"]);
        cases.push(x);
        let mut x = l.clone();
        x["state"]["trades"]["extra"] = json!(["a", "order"]);
        cases.push(x);
        for (n, x) in cases.iter().enumerate() {
            let diff = compare(&c, &a, x, &e, 2).unwrap().1;
            assert!(!diff.is_empty(), "case {n}");
            assert_eq!(diff[0]["kind"], "TRADE_FEE");
        }
        for journal in [json!([]), json!([a["journal"][0], a["journal"][0]])] {
            let mut x = a.clone();
            x["journal"] = journal;
            assert!(!compare(&c, &x, &l, &e, 2).unwrap().1.is_empty());
        }
        let mut x = a.clone();
        x["state"]["position_trades"] = json!({});
        assert!(!compare(&c, &x, &l, &e, 2).unwrap().1.is_empty());
        let mut x = a.clone();
        x["journal"] = json!([{"op":"FEE","payload":entry}]);
        assert!(compare(&c, &x, &l, &e, 2).is_err());
    }
    #[test]
    fn zero_fee_needs_trade_ownership_and_does_not_license_orphan_zero_entries() {
        let (c, mut a, mut l, mut e) = fee_source();
        for field in ["charges", "rebates"] {
            a["journal"][0]["payload"][field] = json!("0.00");
            e.get_mut("trade").unwrap()["entry"][field] = json!("0.00");
        }
        l["state"]["ledgers"]["a"]["fee_entries"] = json!([]);
        a["state"]["snapshot"]["fees"] = json!("0.00");
        l["state"]["ledgers"]["a"]["snapshot"]["fees"] = json!("0.00");
        assert!(compare(&c, &a, &l, &e, 2).unwrap().1.is_empty());
        let mut x = l.clone();
        x["state"]["trades"] = json!({});
        assert!(!compare(&c, &a, &x, &e, 2).unwrap().1.is_empty());
        let mut x = l.clone();
        x["state"]["ledgers"]["a"]["fee_entries"] = json!([e["trade"]["entry"]]);
        assert!(!compare(&c, &a, &x, &e, 2).unwrap().1.is_empty());
    }

    #[test]
    fn equal_aggregate_totals_cannot_jointly_omit_committed_fee_economics() {
        let (c, mut a, mut l, e) = fee_source();
        a["state"]["snapshot"]["fees"] = json!("0.00");
        l["state"]["ledgers"]["a"]["snapshot"]["fees"] = json!("0.00");
        let differences = compare(&c, &a, &l, &e, 2).unwrap().1;
        assert!(differences.iter().any(|d| d["kind"] == "COMMITTED_FEES"));
    }
}
