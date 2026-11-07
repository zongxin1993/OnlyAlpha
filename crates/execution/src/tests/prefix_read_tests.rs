//! Keep the default Store's immediate validation, callback and error order.
use super::*;
use std::cell::RefCell;
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../tests/support/mod.rs"]
mod support;
struct Observed {
    rows: Vec<crate::Record>,
    calls: RefCell<Vec<u64>>,
    fail_second: bool,
    missing_first: bool,
}
impl crate::Store for Observed {
    fn head(&self) -> Result<u64, Error> {
        panic!("prefix preflight must not add a head query to the default Store")
    }
    fn get(&self, n: u64) -> Result<Option<crate::Record>, Error> {
        self.calls.borrow_mut().push(n);
        if n == 2 && self.fail_second {
            return Err(err("SECOND_GET_UNKNOWN"));
        }
        if n == 1 && self.missing_first {
            return Ok(None);
        }
        Ok(self.rows.get((n - 1) as usize).cloned())
    }
    fn commit(&mut self, _: &crate::CommitIntent) -> Result<crate::Record, Error> {
        panic!("read-only")
    }
    fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
        panic!("read-only")
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        panic!("read-only")
    }
}
#[test]
fn default_prefix_keeps_get_callbacks_after_each_original_row_validation() {
    let mut h = support::Harness::new(support::config()).unwrap();
    for input in [support::open(1, "BUY"), support::stage(2, 1, "UNKNOWN")] {
        let p = h.prepare(&input).unwrap();
        crate::coordinate(&mut h.store, &mut h.components, &p).unwrap();
    }
    let mut store = Observed {
        rows: h.store.rows.clone(),
        calls: RefCell::new(Vec::new()),
        fail_second: false,
        missing_first: false,
    };
    let before = h.components.checkpoint().unwrap();
    assert_eq!(
        Components::ready_prefix(&store, &support::config(), 2).unwrap(),
        h.components.payload_hashes().unwrap()
    );
    assert_eq!(*store.calls.borrow(), [1, 2]);
    store.calls.borrow_mut().clear();
    store.fail_second = true;
    assert_eq!(
        Components::ready_prefix(&store, &support::config(), 2)
            .unwrap_err()
            .0,
        "SECOND_GET_UNKNOWN"
    );
    assert_eq!(*store.calls.borrow(), [1, 2]);
    let original = store.rows.clone();
    for fault in [
        "missing",
        "unready",
        "configuration",
        "lineage",
        "account-format",
    ] {
        store.rows = original.clone();
        store.calls.borrow_mut().clear();
        store.missing_first = fault == "missing";
        if fault == "unready" {
            store.rows[0] = store.rows[0].with_observed_flags(false, false).unwrap();
        }
        if matches!(fault, "configuration" | "lineage" | "account-format") {
            let mut raw = store.rows[0].record();
            let p = &mut raw["prepared"];
            match fault {
                "configuration" => p["config_hash"] = json!("f".repeat(64)),
                "lineage" => p["projections"][0]["before_hash"] = json!("f".repeat(64)),
                _ => {
                    p["projections"][2]["result"]["schema_version"] = json!(5);
                    p["projections"][2]["result_hash"] =
                        json!(hash(&p["projections"][2]["result"]));
                }
            }
            p.as_object_mut().unwrap().remove("payload_hash");
            p["payload_hash"] = json!(hash(p));
            store.rows[0] = crate::Record::decode(&raw).unwrap();
        }
        let expected = match fault {
            "missing" => "EXECUTION_READY_SOURCE_MISSING",
            "unready" | "configuration" => "EXECUTION_READY_SOURCE_CONFLICT",
            "lineage" => "EXECUTION_READY_LINEAGE_CONFLICT",
            _ => "EXECUTION_ACCOUNT_CHECKPOINT_FORMAT",
        };
        assert_eq!(
            Components::ready_prefix(&store, &support::config(), 2)
                .unwrap_err()
                .0,
            expected,
            "{fault}"
        );
        assert_eq!(
            *store.calls.borrow(),
            [1],
            "get2 must not run after row1 {fault} has already failed"
        );
    }
    assert_eq!(h.components.checkpoint().unwrap(), before);
    store.calls.borrow_mut().clear();
    assert_eq!(
        Components::ready_prefix(&store, &support::config(), 0).unwrap(),
        Components::genesis_payload_hashes(&support::config()).unwrap()
    );
    assert!(store.calls.borrow().is_empty());
}

#[test]
fn batch_data_errors_or_invalid_prefixes_never_fall_back_to_point_reads() {
    struct Batch {
        answer: Result<Option<Vec<crate::Record>>, Error>,
    }
    impl crate::Store for Batch {
        fn read_prefix(&self, _: u64) -> Result<Option<Vec<crate::Record>>, Error> {
            self.answer.clone()
        }
        fn head(&self) -> Result<u64, Error> {
            panic!("batch prefix must not add a head observation")
        }
        fn get(&self, _: u64) -> Result<Option<crate::Record>, Error> {
            panic!("a batch error or malformed result cannot trigger point-read fallback")
        }
        fn commit(&mut self, _: &crate::CommitIntent) -> Result<crate::Record, Error> {
            panic!("read-only")
        }
        fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
            panic!("read-only")
        }
        fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
            panic!("read-only")
        }
    }
    let mut h = support::Harness::new(support::config()).unwrap();
    for input in [support::open(1, "BUY"), support::stage(2, 1, "UNKNOWN")] {
        let p = h.prepare(&input).unwrap();
        crate::coordinate(&mut h.store, &mut h.components, &p).unwrap();
    }
    let original = h.store.rows.clone();
    let mut unready = original.clone();
    unready[0] = unready[0].with_observed_flags(false, false).unwrap();
    let mut reversed = original.clone();
    reversed.reverse();
    let mut excessive = original.clone();
    excessive.push(original[1].clone());
    for (kind, answer) in [
        ("error", Err(err("BATCH_SOURCE_UNKNOWN"))),
        ("short", Ok(Some(original[..1].to_vec()))),
        ("excessive", Ok(Some(excessive))),
        ("sequence", Ok(Some(reversed))),
        ("unready", Ok(Some(unready))),
        ("complete", Ok(Some(original))),
    ] {
        let actual = Components::ready_prefix(&Batch { answer }, &support::config(), 2);
        if kind == "complete" {
            assert_eq!(actual.unwrap(), h.components.payload_hashes().unwrap());
        } else if kind == "error" {
            assert_eq!(actual.unwrap_err().0, "BATCH_SOURCE_UNKNOWN");
        } else {
            assert!(
                actual.is_err(),
                "{kind} batch data cannot certify a Ready prefix"
            );
        }
    }
}

#[test]
fn execution_genesis_memo_is_exact_and_shared_only_as_configuration_data() {
    let components = Components::new(support::config()).unwrap();
    let expected = Components::genesis_payload_hashes(&support::config()).unwrap();
    assert_eq!(
        components.cached_genesis_payload_hashes().unwrap(),
        expected
    );
    let fork = components.clone_data();
    let mut detached = fork.cached_genesis_payload_hashes().unwrap();
    detached[0] = "f".repeat(64);
    assert_eq!(
        components.cached_genesis_payload_hashes().unwrap(),
        expected
    );
    assert_eq!(fork.cached_genesis_payload_hashes().unwrap(), expected);
    // A warm pure genesis memo must not hide an absent actual Ready source.
    let mut history = support::Harness::new(support::config()).unwrap();
    let prepared = history.prepare(&support::open(1, "BUY")).unwrap();
    crate::coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
    history.components.cached_genesis_payload_hashes().unwrap();
    history.store.rows.clear();
    assert!(history.components.reconcile(&history.store).is_err());
    assert!(history.components.ready_source(&history.store).is_err());
}

#[test]
fn execution_genesis_memo_recomputes_changed_config_and_rejects_invalid_config() {
    let mut components = Components::new(support::config()).unwrap();
    let original = components.cached_genesis_payload_hashes().unwrap();
    let mut configuration = support::config();
    configuration["initial_cash"] = json!("2000.00");
    configuration["capitals"]["cluster"] = json!("2000.00");
    let expected = Components::genesis_payload_hashes(&configuration).unwrap();
    assert_ne!(expected, original);
    components.config = configuration;
    assert_eq!(
        components.cached_genesis_payload_hashes().unwrap(),
        expected
    );
    components.config = Value::Null;
    assert!(components.cached_genesis_payload_hashes().is_err());
    components.config = support::config();
    assert_eq!(
        components.cached_genesis_payload_hashes().unwrap(),
        original
    );
}
