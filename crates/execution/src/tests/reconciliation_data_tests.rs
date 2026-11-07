//! Exact pure calculation reuse; every owning source observation stays fresh.
use super::*;
use crate::{CommitIntent, Prepared, coordinate};
use std::cell::RefCell;
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../tests/support/mod.rs"]
mod support;
use support::{Harness, config, fill, open, stage, terminal};

struct Observed {
    rows: Vec<Record>,
    calls: RefCell<Vec<u64>>,
    later_error: bool,
}
impl Observed {
    fn new(rows: Vec<Record>) -> Self {
        Self {
            rows,
            calls: RefCell::new(Vec::new()),
            later_error: false,
        }
    }
}
impl Store for Observed {
    fn head(&self) -> Result<u64, Error> {
        Ok(self.rows.len() as u64)
    }
    fn get(&self, sequence: u64) -> Result<Option<Record>, Error> {
        let mut calls = self.calls.borrow_mut();
        calls.push(sequence);
        if self.later_error && calls.len() > self.rows.len() && sequence == 5 {
            return Err(err("LATER_SOURCE_UNAVAILABLE"));
        }
        Ok(self.rows.get((sequence - 1) as usize).cloned())
    }
    fn commit(&mut self, _: &CommitIntent) -> Result<Record, Error> {
        panic!("read only")
    }
    fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
        panic!("read only")
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        panic!("read only")
    }
}
fn history() -> Harness {
    let mut history = Harness::new(config()).unwrap();
    for input in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
        fill(4, 1, "1", "10.00", "2.00"),
        terminal(5, 1, "CANCELLED"),
    ] {
        let prepared = history.prepare(&input).unwrap();
        coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    }
    *history.components.reconciliation_data.lock().unwrap() = None;
    history
}
fn reset() {
    FEE_FOLD_APPLICATIONS.with(|n| n.set(0));
    FEE_COMPARISONS.with(|n| n.set(0));
}
fn counts() -> (u64, u64) {
    (
        FEE_FOLD_APPLICATIONS.with(std::cell::Cell::get),
        FEE_COMPARISONS.with(std::cell::Cell::get),
    )
}
// Literal original orchestrator, including validation/error order and fresh
// report/identity construction. Only the renamed pure record helper is shared.
fn original_reconcile<S: Store>(c: &Components, store: &S) -> Result<LedgerReconciliation, Error> {
    let checkpoint = &c.meta["fee_authority"];
    let mut fee_owner = boundary(onlyalpha_fee::Manager::new(
        checkpoint["config"].clone(),
        usize::try_from(uint(&checkpoint["capacity"])?)
            .map_err(|_| err("RECONCILIATION_FEE_CAPACITY"))?,
    ))?;
    let mut expected = BTreeMap::new();
    let owners = c.payloads()?;
    let genesis = c.cached_genesis_payload_hashes()?;
    let source = c.verified_source_with_genesis(store, &genesis, |record| {
        record_fee_input(record.prepared().input(), &mut fee_owner, &mut expected)
    })?;
    if fee_owner.checkpoint() != *checkpoint {
        return Err(err("RECONCILIATION_FEE_HISTORY_UNAVAILABLE"));
    }
    let (totals, differences) = compare(&c.config, &owners[2], &owners[3], &expected, c.precision)?;
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
    .map(|k| (k.into(), c.config[k].clone()))
    .collect();
    let mut value = json!({"schema_version":1,"semantic_version":"RUNTIME_LEDGER_RECONCILIATION@1",
            "scope":scope,"cluster_ids":c.config["capitals"].as_object().expect("validated capitals").keys().collect::<Vec<_>>(),"source":source,"trade_count":expected.len(),
            "status":if differences.is_empty(){"MATCHED"}else{"MISMATCHED"},"totals":totals,"differences":differences});
    value["id"] = json!(format!("RLR-{}", hash(&value)));
    Ok(LedgerReconciliation { value })
}

#[test]
fn warm_reconciliation_reuses_only_pure_work_and_reads_the_complete_actual_source() {
    let history = history();
    let store = Observed::new(history.store.rows.clone());
    let expected = original_reconcile(&history.components, &store).unwrap();
    store.calls.borrow_mut().clear();
    reset();
    assert_eq!(history.components.reconcile(&store).unwrap(), expected);
    assert_eq!(counts(), (2, 1));
    assert_eq!(store.calls.borrow().len(), 2 * store.rows.len());
    for _ in 0..3 {
        store.calls.borrow_mut().clear();
        reset();
        let actual = history.components.reconcile(&store).unwrap();
        assert_eq!(actual.encode().unwrap(), expected.encode().unwrap());
        assert_eq!(counts(), (0, 0));
        assert_eq!(*store.calls.borrow(), [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]);
    }
    // Same immutable bytes in another owning Store still require all its reads.
    let foreign_source = Observed::new(store.rows.clone());
    reset();
    assert_eq!(
        history.components.reconcile(&foreign_source).unwrap(),
        expected
    );
    assert_eq!(foreign_source.calls.borrow().len(), 10);
    assert_eq!(counts(), (0, 0));
    let checkpoint = history.components.checkpoint().unwrap();
    let mut restored = Components::new(config()).unwrap();
    restored.restore(&checkpoint, &hash(&checkpoint)).unwrap();
    assert!(restored.reconciliation_data.lock().unwrap().is_none());
    reset();
    assert_eq!(restored.reconcile(&store).unwrap(), expected);
    assert_eq!(counts(), (2, 1));
}

fn remembered(c: &Components) -> Arc<ReconciliationData> {
    Arc::clone(c.reconciliation_data.lock().unwrap().as_ref().unwrap())
}
#[test]
fn warm_memo_cannot_hide_missing_flags_unknown_or_foreign_actual_source() {
    let history = history();
    history.components.reconcile(&history.store).unwrap();
    let original = remembered(&history.components);
    for fault in ["missing", "flags", "unknown"] {
        let mut store = Observed::new(history.store.rows.clone());
        match fault {
            "missing" => {
                store.rows.pop();
            }
            "flags" => store.rows[2] = store.rows[2].with_observed_flags(false, false).unwrap(),
            _ => store.later_error = true,
        }
        let expected = original_reconcile(&history.components, &store).unwrap_err();
        store.calls.borrow_mut().clear();
        assert_eq!(
            history.components.reconcile(&store).unwrap_err(),
            expected,
            "{fault}"
        );
        assert!(
            Arc::ptr_eq(&original, &remembered(&history.components)),
            "{fault}"
        );
    }
    let mut foreign = Components::new(config()).unwrap();
    foreign.config["generation"] = json!("f".repeat(64));
    foreign.reconciliation_data = Arc::clone(&history.components.reconciliation_data);
    let store = Observed::new(history.store.rows.clone());
    assert_eq!(
        foreign.reconcile(&store),
        original_reconcile(&foreign, &store)
    );
    assert!(foreign.reconcile(&store).is_err());
}

fn fold(cached: Option<Arc<FeeFoldData>>, config: Value, capacity: usize) -> FeeFold {
    FeeFold {
        owner: onlyalpha_fee::Manager::new(config.clone(), capacity).unwrap(),
        config,
        capacity,
        cached,
        expected: BTreeMap::new(),
        matched: 0,
        inputs: Vec::new(),
    }
}
#[test]
fn fee_fold_uses_complete_ordered_inputs_config_and_capacity_not_digests_or_prefixes() {
    let history = history();
    history.components.reconcile(&history.store).unwrap();
    let cached = Arc::clone(&remembered(&history.components).fold);
    for count in [0, 1, 2] {
        let fills = history
            .store
            .rows
            .iter()
            .filter(|r| r.prepared().input()["op"] == "FILL")
            .take(count)
            .collect::<Vec<_>>();
        let mut warm = fold(
            Some(Arc::clone(&cached)),
            cached.config.clone(),
            cached.capacity,
        );
        let mut cold = fold(None, cached.config.clone(), cached.capacity);
        for row in fills {
            warm.visit(row).unwrap();
            cold.visit(row).unwrap();
        }
        let actual = warm.finish().unwrap();
        let expected = cold.finish().unwrap();
        assert_eq!(actual.inputs, expected.inputs);
        assert_eq!(actual.expected, expected.expected);
        assert_eq!(actual.checkpoint, expected.checkpoint);
        assert_eq!(Arc::ptr_eq(&actual, &cached), count == 2);
    }
    let mut changed = cached.config.clone();
    changed["generation"] = json!("f".repeat(64));
    // The production lookup must miss a different complete config/capacity.
    assert!(cached.capacity > 1);
    for (configuration, capacity) in [
        (changed, cached.capacity),
        (cached.config.clone(), cached.capacity - 1),
    ] {
        let found = Some(Arc::clone(&cached))
            .filter(|c| c.config == configuration && c.capacity == capacity);
        assert!(found.is_none());
        let mut candidate = fold(found, configuration.clone(), capacity);
        let mut cold = fold(None, configuration, capacity);
        for row in &history.store.rows {
            let actual = candidate.visit(row);
            let expected = cold.visit(row);
            assert_eq!(actual, expected);
            if actual.is_err() {
                break;
            }
        }
    }
    let mut duplicate = fold(
        Some(Arc::clone(&cached)),
        cached.config.clone(),
        cached.capacity,
    );
    for row in &history.store.rows {
        duplicate.visit(row).unwrap();
    }
    let fill = history
        .store
        .rows
        .iter()
        .find(|r| r.prepared().input()["op"] == "FILL")
        .unwrap();
    assert!(
        duplicate.visit(fill).is_err(),
        "an extra identical FILL is not the cached full history"
    );
}

// Re-seal supplied test source data through the actual Prepared/Record decoder.
// Preserve full projection lineage, metadata transaction mapping and fresh head;
// this exercises integrity-valid tampering rather than malformed JSON shortcuts.
fn reseal(history: &mut Harness, selected: usize, mutate: impl FnOnce(&mut Value)) {
    let mut values = history
        .store
        .rows
        .iter()
        .map(Record::record)
        .collect::<Vec<_>>();
    mutate(&mut values[selected]["prepared"]["input"]);
    let mut transactions = BTreeMap::new();
    let mut previous = None;
    for raw in &mut values {
        let body = &mut raw["prepared"];
        let transaction = format!("ETX-{}", hash(&body["input"]));
        body["transaction_id"] = json!(transaction);
        transactions.insert(
            body["sequence"].as_u64().unwrap().to_string(),
            body["transaction_id"].clone(),
        );
        let meta = &mut body["projections"][5]["result"];
        for (sequence, id) in &transactions {
            meta["transactions"][sequence] = id.clone();
        }
        if let Some(before) = previous.take() {
            body["projections"][5]["before_hash"] = before;
        }
        body["projections"][5]["result_hash"] = json!(hash(&body["projections"][5]["result"]));
        previous = Some(body["projections"][5]["result_hash"].clone());
        body["events"] = json!([{"schema_version":1,"event_id":format!("{transaction}-EVENT-1"),"transaction_id":transaction,"sequence":body["sequence"],"input":body["input"]}]);
        body.as_object_mut().unwrap().remove("payload_hash");
        *body = Prepared::new(body.clone()).unwrap().record();
    }
    history.store.rows = values
        .iter()
        .map(|raw| Record::decode(raw).unwrap())
        .collect();
    history.components.meta = Arc::new(
        history.store.rows.last().unwrap().prepared().value()["projections"][5]["result"].clone(),
    );
    history.components.invalidate_payloads();
}
#[test]
fn integrity_valid_reseals_preserve_streaming_fee_error_precedence_and_fresh_report_identity() {
    let mut history = history();
    let original = history.components.reconcile(&history.store).unwrap();
    reseal(&mut history, 4, |input| {
        input["source_ref"] = json!("another-actual-source")
    });
    let expected = original_reconcile(&history.components, &history.store).unwrap();
    reset();
    let actual = history.components.reconcile(&history.store).unwrap();
    assert_eq!(actual, expected);
    assert_ne!(actual.record()["id"], original.record()["id"]);
    assert_eq!(
        counts().0,
        0,
        "same full FILL data must reuse only the Fee fold"
    );
    // Even a FILL field outside the fee target is part of the complete key.
    reseal(&mut history, 3, |input| {
        input["source_ref"] = json!("changed-full-fill-source")
    });
    let expected = original_reconcile(&history.components, &history.store).unwrap();
    reset();
    assert_eq!(
        history.components.reconcile(&history.store).unwrap(),
        expected
    );
    assert_eq!(
        counts().0,
        2,
        "a changed actual FILL must re-run the whole pure fold"
    );
    let previous = remembered(&history.components);
    reseal(&mut history, 3, |input| {
        input["payload"]["fees"]["charge_target"] = json!("0.00")
    });
    let mut store = Observed::new(history.store.rows.clone());
    store.later_error = true;
    let expected = original_reconcile(&history.components, &store).unwrap_err();
    assert_ne!(expected.0, "LATER_SOURCE_UNAVAILABLE");
    store.calls.borrow_mut().clear();
    assert_eq!(history.components.reconcile(&store).unwrap_err(), expected);
    assert_eq!(*store.calls.borrow(), [1, 2, 3, 4, 5, 1, 2, 3, 4]);
    assert!(Arc::ptr_eq(&previous, &remembered(&history.components)));
}

#[test]
fn changed_owner_images_precision_and_branch_failure_cannot_reuse_a_comparison_result() {
    let history = history();
    history.components.reconcile(&history.store).unwrap();
    let original = remembered(&history.components);
    let mut branch = history.components.clone_data();
    branch.precision = 3;
    let expected = original_reconcile(&branch, &history.store).unwrap();
    reset();
    assert_eq!(branch.reconcile(&history.store).unwrap(), expected);
    assert_eq!(counts(), (0, 1));
    reset();
    assert_eq!(
        history.components.reconcile(&history.store),
        original_reconcile(&history.components, &history.store)
    );
    assert!(FEE_COMPARISONS.with(std::cell::Cell::get) > 0);
    let before = remembered(&history.components);
    let mut store = Observed::new(history.store.rows.clone());
    store.rows.pop();
    assert!(branch.reconcile(&store).is_err());
    assert!(Arc::ptr_eq(&before, &remembered(&history.components)));
    assert!(!Arc::ptr_eq(&original, &before));
    let mut detached = history.components.clone_data();
    detached.invalidate_payloads();
    reset();
    let expected = original_reconcile(&detached, &history.store).unwrap();
    reset();
    assert_eq!(detached.reconcile(&history.store).unwrap(), expected);
    assert_eq!(
        counts(),
        (0, 1),
        "equal but independently allocated owner image is not a pointer hit"
    );
}

#[test]
fn actual_valuation_owner_changes_recompute_comparison_but_keep_the_same_fee_fold() {
    let mut history = history();
    history.components.reconcile(&history.store).unwrap();
    let before = remembered(&history.components);
    let view = history
        .components
        .position_order_view(&history.store)
        .unwrap();
    let value = support::input(
        6,
        "VALUATION",
        json!({"schema_version":1,"valuation":"memo-owner-change","version":6,
        "position_evidence":view["position_checkpoint_fingerprint"],"economic_version":view["economic_version"],
        "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":"memo-owner-mark-6",
            "family":"CLOSED_BAR","version":6,"time":6,"as_of_sequence":6}]}),
    );
    let prepared = history.prepare(&value).unwrap();
    coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    let expected = original_reconcile(&history.components, &history.store).unwrap();
    reset();
    assert_eq!(
        history.components.reconcile(&history.store).unwrap(),
        expected
    );
    assert_eq!(counts(), (0, 1));
    let after = remembered(&history.components);
    assert!(Arc::ptr_eq(&before.fold, &after.fold));
    assert!(!Arc::ptr_eq(
        &before.comparison.owners,
        &after.comparison.owners
    ));
}

fn change_last_metadata(history: &mut Harness, change: impl FnOnce(&mut Value)) {
    let last = history.store.rows.len() - 1;
    let mut raw = history.store.rows[last].record();
    let body = &mut raw["prepared"];
    change(&mut body["projections"][5]["result"]);
    body["projections"][5]["result_hash"] = json!(hash(&body["projections"][5]["result"]));
    body.as_object_mut().unwrap().remove("payload_hash");
    *body = Prepared::new(body.clone()).unwrap().record();
    let metadata = body["projections"][5]["result"].clone();
    history.store.rows[last] = Record::decode(&raw).unwrap();
    history.components.meta = Arc::new(metadata);
    history.components.invalidate_payloads();
}
#[test]
fn current_metadata_checkpoint_and_fee_header_are_rechecked_even_with_warm_pure_data() {
    let mut history = history();
    history.components.reconcile(&history.store).unwrap();
    change_last_metadata(&mut history, |meta| {
        meta["fee_authority"]["capacity"] = json!(4095)
    });
    let expected = original_reconcile(&history.components, &history.store).unwrap();
    reset();
    assert_eq!(
        history.components.reconcile(&history.store).unwrap(),
        expected
    );
    assert_eq!(
        counts(),
        (2, 1),
        "a capacity change must miss the pure fold key"
    );
    let saved = remembered(&history.components);
    change_last_metadata(&mut history, |meta| {
        meta["fee_authority"]["state_hash"] = json!("f".repeat(64))
    });
    let expected = original_reconcile(&history.components, &history.store).unwrap_err();
    reset();
    assert_eq!(expected.0, "RECONCILIATION_FEE_HISTORY_UNAVAILABLE");
    assert_eq!(
        history.components.reconcile(&history.store).unwrap_err(),
        expected
    );
    assert_eq!(counts(), (0, 0));
    assert!(Arc::ptr_eq(&saved, &remembered(&history.components)));
    // Keep the old early header error ahead of missing/invalid Source state.
    Arc::make_mut(&mut history.components.meta)["fee_authority"]["capacity"] = json!("bad");
    let store = Observed::new(Vec::new());
    let expected = original_reconcile(&history.components, &store).unwrap_err();
    assert_eq!(history.components.reconcile(&store).unwrap_err(), expected);
    assert!(store.calls.borrow().is_empty());
}

#[test]
fn resealed_foreign_fill_scope_is_refused_before_the_cached_fold_can_select_it() {
    for field in ["account", "cluster", "revision"] {
        let mut history = history();
        history.components.reconcile(&history.store).unwrap();
        let previous = remembered(&history.components);
        reseal(&mut history, 3, |input| input[field] = json!("foreign"));
        let store = Observed::new(history.store.rows.clone());
        let expected = original_reconcile(&history.components, &store).unwrap_err();
        assert!(matches!(
            expected.0.as_str(),
            "RECONCILIATION_FACT_SCOPE" | "RECONCILIATION_FACT_CLUSTER"
        ));
        store.calls.borrow_mut().clear();
        reset();
        assert_eq!(history.components.reconcile(&store).unwrap_err(), expected);
        assert_eq!(*store.calls.borrow(), [1, 2, 3, 4, 5, 1, 2, 3, 4]);
        assert!(Arc::ptr_eq(&previous, &remembered(&history.components)));
    }
}
