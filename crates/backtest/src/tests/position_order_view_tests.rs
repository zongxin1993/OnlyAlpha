//! Compare the original retained actual Kernel projections, never a DTO grant.
use super::*;
use crate::execution_test_fixture::{configuration, original_three_facts};
fn current_view(c: &OriginalExecution<'_>) -> Result<Value, Error> {
    c.position_order_view()
}
#[test]
fn original_position_order_view_borrows_actual_prepared_components_without_full_state() {
    for modern in [false, true] {
        let configuration = configuration(modern);
        let genesis = Components::new(configuration.clone())
            .unwrap()
            .checkpoint()
            .unwrap()["components"]
            .as_array()
            .unwrap()
            .clone();
        let mut history = crate::Candidate::new(configuration.clone(), vec![]).unwrap();
        for input in original_three_facts() {
            history.apply(&input).unwrap();
        }
        let original = history.records().to_vec();
        for cursor in 0..=history.records().len() {
            let c = OriginalExecution {
                configuration: &configuration,
                records: history.records(),
                genesis: genesis.clone(),
                cursor,
                end: history.records().len(),
                admission: Default::default(),
            };
            let state = c.state().unwrap();
            let checkpoint = c.checkpoint().unwrap();
            let active = checkpoint["components"][0]["state"]["orders"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|row| {
                    !matches!(
                        row["snapshot"]["status"].as_str(),
                        Some("FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED")
                    )
                })
                .map(|row| row["snapshot"]["order_id"]["value"].clone())
                .collect::<Vec<_>>();
            let expected = json!({"schema_version":2,"active_order_ids":active,"orders":state["execution"]["orders"],"position_accounts":state["position"]["accounts"],"position_allocations":state["position"]["allocations"],"economic_version":state["account"]["snapshot"]["economic_version"],"position_checkpoint_fingerprint":onlyalpha_execution::digest(checkpoint["components"][1].to_string().as_bytes())});
            FULL_ORIGINAL_STATE_CONSTRUCTIONS.with(|n| n.set(0));
            ORIGINAL_BODY_READS.with(|n| n.set(0));
            assert_eq!(current_view(&c).unwrap(), expected);
            assert_eq!(
                FULL_ORIGINAL_STATE_CONSTRUCTIONS.with(std::cell::Cell::get),
                0,
                "original readonly query rebuilt all six full owner projections"
            );
            assert_eq!(
                ORIGINAL_BODY_READS.with(std::cell::Cell::get),
                0,
                "fixed original position data must not expand complete historical bodies"
            );
            assert_eq!(c.checkpoint().unwrap(), checkpoint);
            assert_eq!(history.records(), original.as_slice());
        }
        let c = OriginalExecution {
            configuration: &configuration,
            records: history.records(),
            genesis: genesis.clone(),
            cursor: history.records().len() + 1,
            end: history.records().len(),
            admission: Default::default(),
        };
        assert!(
            current_view(&c).is_err(),
            "missing actual original source never becomes an empty view"
        );
    }
}

#[test]
fn original_order_lookup_reads_only_original_order_data_and_keeps_full_snapshot_validation() {
    for modern in [false, true] {
        let configuration = configuration(modern);
        let genesis = Components::new(configuration.clone())
            .unwrap()
            .checkpoint()
            .unwrap()["components"]
            .as_array()
            .unwrap()
            .clone();
        let mut history = crate::Candidate::new(configuration.clone(), vec![]).unwrap();
        for input in original_three_facts() {
            history.apply(&input).unwrap();
        }
        let c = OriginalExecution {
            configuration: &configuration,
            records: history.records(),
            genesis,
            cursor: history.records().len(),
            end: history.records().len(),
            admission: Default::default(),
        };
        let expected = c.component(0).unwrap()["state"]["orders"][0]["snapshot"].clone();
        ORIGINAL_BODY_READS.with(|n| n.set(0));
        let actual = c.order("cluster", "runtime-ORDER-000001").unwrap();
        assert_eq!(actual, expected);
        assert_eq!(
            ORIGINAL_BODY_READS.with(std::cell::Cell::get),
            0,
            "reading one original Order must not expand unrelated Account/Ledger/Position histories"
        );
        assert!(c.order("foreign", "runtime-ORDER-000001").is_err());
        assert!(c.order("cluster", "missing").is_err());
    }
}

#[test]
fn compact_order_data_never_waives_duplicate_scope_or_deep_domain_snapshot_validation() {
    let configuration = configuration(true);
    let genesis = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap()["components"]
        .as_array()
        .unwrap()
        .clone();
    let mut history = crate::Candidate::new(configuration.clone(), vec![]).unwrap();
    for input in original_three_facts() {
        history.apply(&input).unwrap();
    }
    for fault in [
        "duplicate",
        "cluster",
        "unknown-status",
        "fee-subject",
        "omitted-metadata",
        "runtime",
        "account",
    ] {
        let mut records = history.records().to_vec();
        let mut raw = records.last().unwrap().record();
        let result = &mut raw["prepared"]["projections"][0]["result"];
        match fault {
            "duplicate" => {
                let duplicate = result["state"]["orders"][0].clone();
                result["state"]["orders"]
                    .as_array_mut()
                    .unwrap()
                    .push(duplicate);
            }
            "cluster" => {
                result["state"]["orders"][0]["snapshot"]["cluster_id"]["value"] = json!("foreign")
            }
            "unknown-status" => {
                result["state"]["orders"][0]["snapshot"]["status"] = json!("UNKNOWN")
            }
            "omitted-metadata" => {}
            "runtime" | "account" => {
                let snapshot = &mut result["state"]["orders"][0]["snapshot"];
                snapshot[format!("{fault}_id")]["value"] = json!("foreign");
                for field in ["fee_policy_binding", "fee_estimate", "funding_plan"] {
                    snapshot[field] = Value::Null;
                }
                assert!(
                    OnlyOrderSnapshot::from_record(snapshot).is_ok(),
                    "scope vector must be a complete different valid Domain snapshot"
                );
            }
            _ => {
                result["state"]["orders"][0]["snapshot"]["fee_estimate"]["expected"]["subject"]["order_id"]
                    ["value"] = json!("foreign-order")
            }
        }
        if fault == "omitted-metadata" {
            raw["prepared"]["projections"][5]["result"]["orders"] = json!({});
        }
        for index in [0, 5] {
            raw["prepared"]["projections"][index]["result_hash"] = json!(crate::hash(
                &raw["prepared"]["projections"][index]["result"]
            ));
        }
        let mut content = raw["prepared"].clone();
        content.as_object_mut().unwrap().remove("payload_hash");
        raw["prepared"]["payload_hash"] = json!(crate::hash(&content));
        *records.last_mut().unwrap() = onlyalpha_execution::Record::decode(&raw).unwrap();
        let c = OriginalExecution {
            configuration: &configuration,
            records: &records,
            genesis: genesis.clone(),
            cursor: records.len(),
            end: records.len(),
            admission: Default::default(),
        };
        if fault == "omitted-metadata" {
            assert!(c.order("cluster", "runtime-ORDER-000001").is_ok());
        } else {
            assert!(
                c.order("cluster", "runtime-ORDER-000001").is_err(),
                "compact raw rows hid {fault}"
            );
        }
        assert!(
            c.position_order_view().is_err(),
            "activity projection hid {fault}"
        );
    }
}

#[test]
fn retained_account_capacity_denial_is_positive_exact_and_preserves_safety_recovery() {
    use crate::execution_test_fixture::{
        account_capacity_history, capacity_admission, close_and_cancel_at_capacity,
        expanded_account_journal_bytes,
    };
    let mut history = account_capacity_history(false);
    let configuration = history.configuration().clone();
    let before = history.checkpoint().unwrap();
    let records = history.records().to_vec();
    assert!(expanded_account_journal_bytes(&before) > 4 * 1024 * 1024);
    assert!(before["components"][2]["journal"].as_array().unwrap().len() < 4096);
    let denied = capacity_admission(&history, true);
    assert_eq!(
        history.apply(&denied).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    assert_eq!(history.checkpoint().unwrap(), before);
    assert_eq!(history.records(), records.as_slice());
    let genesis = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap()["components"]
        .as_array()
        .unwrap()
        .clone();
    let mut original = OriginalExecution {
        configuration: &configuration,
        records: &records,
        genesis: genesis.clone(),
        cursor: records.len(),
        end: records.len(),
        admission: Default::default(),
    };
    assert_eq!(
        original.apply(&denied).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    for n in 0..4 {
        let mut next = denied.clone();
        next["input_id"] = json!(format!("denied-preview-{n}"));
        next["source_ref"] = json!(format!("denied-preview-source-{n}"));
        assert_eq!(
            original.apply(&next).unwrap_err().0,
            "EXECUTION_ACCOUNT_CAPACITY_DENIED"
        );
    }
    assert_eq!(original.cursor, records.len());
    assert_eq!(original.checkpoint().unwrap(), before);
    for field in ["runtime", "account", "generation", "revision"] {
        let mut foreign = denied.clone();
        foreign[field] = json!("foreign");
        assert!(original.apply(&foreign).is_err());
        assert_ne!(
            original.apply(&foreign).unwrap_err().0,
            "EXECUTION_ACCOUNT_CAPACITY_DENIED"
        );
    }
    let mut stale = denied.clone();
    stale["runtime_sequence"] =
        records.last().unwrap().prepared().input()["runtime_sequence"].clone();
    assert_eq!(
        original.apply(&stale).unwrap_err().0,
        "EXECUTION_RUNTIME_SEQUENCE"
    );
    let mut malformed = denied.clone();
    malformed["payload"]["request"]["quantity"]["value"] =
        json!({"$serde_json::private::Number":"4"});
    assert_ne!(
        original.apply(&malformed).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    let mut aliased = denied.clone();
    aliased["source_ref"] = records[0].prepared().input()["source_ref"].clone();
    assert_ne!(
        original.apply(&aliased).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    let mut bad = before.clone();
    bad["components"][2]["journal"][0]["cause"] = json!("broken");
    assert!(Components::admission_rejection(&configuration, &bad, &denied).is_err());
    let mut missing = OriginalExecution {
        configuration: &configuration,
        records: &records[..records.len() - 1],
        genesis,
        cursor: records.len(),
        end: records.len(),
        admission: Default::default(),
    };
    assert_ne!(
        missing.apply(&denied).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    // Cold transport decoding plus actual source recovery, not a retained DTO.
    let bytes =
        serde_json::to_vec(&records.iter().map(Record::record).collect::<Vec<_>>()).unwrap();
    let values: Vec<Value> = serde_json::from_slice(&bytes).unwrap();
    let decoded = values
        .iter()
        .map(Record::decode)
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let mut cold = crate::Candidate::new(configuration, decoded).unwrap();
    assert_eq!(cold.checkpoint().unwrap(), before);
    assert_eq!(
        cold.apply(&denied).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    assert_eq!(cold.checkpoint().unwrap(), before);
    close_and_cancel_at_capacity(&mut cold);
    assert_eq!(
        cold.state().unwrap()["position"]["accounts"][0]["snapshot"]["quantity"]
            .as_str()
            .unwrap()
            .parse::<onlyalpha_domain::numeric::OnlyDecimal>()
            .unwrap(),
        "2".parse::<onlyalpha_domain::numeric::OnlyDecimal>()
            .unwrap()
    );
    assert_eq!(
        cold.order("cluster", "runtime-ORDER-000002").unwrap()["status"],
        "CANCELLED"
    );
    let recovered =
        crate::Candidate::new(cold.configuration().clone(), cold.records().to_vec()).unwrap();
    assert_eq!(recovered.checkpoint().unwrap(), cold.checkpoint().unwrap());
}

#[test]
fn warm_admissible_preview_never_invents_missing_original_admit() {
    let configuration = configuration(true);
    let genesis = Components::new(configuration.clone())
        .unwrap()
        .checkpoint()
        .unwrap()["components"]
        .as_array()
        .unwrap()
        .clone();
    let mut original = OriginalExecution {
        configuration: &configuration,
        records: &[],
        genesis,
        cursor: 0,
        end: 0,
        admission: Default::default(),
    };
    let input = original_three_facts()[0].clone();
    for _ in 0..3 {
        assert_eq!(
            original.apply(&input).unwrap_err().0,
            err("TERMINAL_NATIVE_INPUT_MISSING").0
        );
        assert_eq!(original.cursor, 0);
    }
    original.cursor = 1;
    original.end = 1;
    assert_eq!(
        original.apply(&input).unwrap_err().0,
        err("TERMINAL_EXECUTION_PREFIX").0
    );
}
