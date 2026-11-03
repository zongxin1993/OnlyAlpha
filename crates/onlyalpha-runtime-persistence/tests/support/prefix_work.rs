//! Actual SQL work and physical faults of the existing public owning query.
use super::*;
#[test]
fn actual_store_observations_do_not_share_expansion_memos_with_the_codec_cache() {
    let h = dictionary_history();
    let expected = h
        .reference
        .store
        .rows
        .iter()
        .map(|record| record.prepared().encode().unwrap())
        .collect::<Vec<_>>();
    for cached in h.store.decoded_rows.borrow_mut().values_mut() {
        cached.record = cached
            .record
            .observation_snapshot(cached.record.ready(), cached.record.delivered())
            .unwrap();
    }
    reset_source_work();
    let observed = h.store.read_records().unwrap();
    assert_eq!(
        SOURCE_RAW_ROWS.with(std::cell::Cell::get),
        expected.len() as u64
    );
    assert_eq!(
        observed[0].prepared().value(),
        &serde_json::from_slice::<Value>(&expected[0]).unwrap()
    );
    assert!(
        !std::ptr::eq(
            observed[0].prepared().value(),
            h.store
                .decoded_rows
                .borrow()
                .get(&1)
                .unwrap()
                .record
                .prepared()
                .value()
        ),
        "expanding a returned observation must not use the long-lived codec cache memo"
    );
    drop(observed);
    drop(h.store);
    let cold = SqliteStore::open(&h.root.0, config(), &"b".repeat(64)).unwrap();
    let observed = cold.read_records().unwrap();
    assert_eq!(
        observed
            .iter()
            .map(|row| row.prepared().encode().unwrap())
            .collect::<Vec<_>>(),
        expected
    );
    for (index, record) in observed.iter().enumerate() {
        assert!(
            !std::ptr::eq(
                record.prepared().value(),
                cold.decoded_rows
                    .borrow()
                    .get(&(index as u64 + 1))
                    .unwrap()
                    .record
                    .prepared()
                    .value()
            ),
            "cold observations must have independent expansion lifetimes"
        );
    }
    drop(observed);
    drop(cold);
}

fn next_planned_valuation(h: &History) -> onlyalpha_execution::Prepared {
    let n = h.inputs.len() as u64 + 1;
    let state = h.components.state(&h.store).unwrap();
    let value = input(
        n,
        "VALUATION",
        json!({"schema_version":1,"valuation":format!("original-plan-{n}"),"version":n,
        "position_evidence":hash(&h.components.checkpoint().unwrap()["components"][1]),
        "economic_version":state["account"]["snapshot"]["economic_version"],
        "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"14.00","source_ref":format!("original-plan-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
    );
    h.components.prepare(&h.store, &value).unwrap()
}

#[test]
fn original_plan_cannot_be_reauthored_against_a_different_actual_before_state() {
    let h = history(5, "12.00");
    let donor = history(5, "13.00");
    let plan = next_planned_valuation(&donor);
    let original = plan.encode().unwrap();
    let mut runtime = crate::Runtime {
        store: h.store,
        components: h.components,
        healthy: true,
    };
    let before = fs::read(h.root.db()).unwrap();
    assert!(
        runtime.apply_prepared(&plan).is_err(),
        "a valid plan from a different before-state must not be replaced by replanning its input"
    );
    assert!(
        runtime.records().is_err(),
        "a rejected installation retains the recovery boundary"
    );
    assert_eq!(fs::read(h.root.db()).unwrap(), before);
    assert_eq!(plan.encode().unwrap(), original);
    drop(runtime);
}

#[test]
fn original_plan_commits_exact_bytes_and_decoded_data_cannot_create_a_new_fact() {
    let h = history(5, "12.00");
    let plan = next_planned_valuation(&h);
    let bytes = plan.encode().unwrap();
    let wire = onlyalpha_execution::Prepared::decode(&bytes).unwrap();
    let mut runtime = crate::Runtime {
        store: h.store,
        components: h.components,
        healthy: true,
    };
    let before = fs::read(h.root.db()).unwrap();
    assert!(
        runtime.apply_prepared(&wire).is_err(),
        "JSON transport cannot create planner authority"
    );
    assert_eq!(fs::read(h.root.db()).unwrap(), before);
    runtime.recover().unwrap();
    runtime.apply_prepared(&plan).unwrap();
    assert_eq!(
        runtime
            .records()
            .unwrap()
            .last()
            .unwrap()
            .prepared()
            .encode()
            .unwrap(),
        bytes
    );
    let committed = fs::read(h.root.db()).unwrap();
    runtime.apply_prepared(&plan).unwrap();
    assert_eq!(fs::read(h.root.db()).unwrap(), committed);
    runtime.apply_prepared(&wire).unwrap(); // Exact existing fact, no new planner grant.
    assert_eq!(fs::read(h.root.db()).unwrap(), committed);
    let mut conflict = plan.record();
    conflict["projections"][5]["result"]["last_runtime_sequence"] = json!(999);
    conflict["projections"][5]["result_hash"] = json!(hash(&conflict["projections"][5]["result"]));
    rehash_prepared(&mut conflict);
    let conflict =
        onlyalpha_execution::Prepared::decode(&serde_json::to_vec(&conflict).unwrap()).unwrap();
    assert_eq!(conflict.input(), plan.input());
    assert!(
        runtime.apply_prepared(&conflict).is_err(),
        "same input is not permission to replace the complete existing Prepared body"
    );
    assert_eq!(fs::read(h.root.db()).unwrap(), committed);
    runtime.recover().unwrap();
    let old = runtime.store.get(2).unwrap().unwrap().prepared().record();
    replace_prepared_source(&runtime.store, 2, &old, false, false);
    let changed = fs::read(h.root.db()).unwrap();
    assert!(
        runtime.apply_prepared(&plan).is_err(),
        "original planner origin cannot hide a changed old Ready flag"
    );
    assert_eq!(fs::read(h.root.db()).unwrap(), changed);
    drop(runtime);
}

#[test]
fn runtime_records_and_duplicate_apply_reconcile_each_fresh_source_only_once() {
    let h = dictionary_history();
    let count = h.inputs.len() as u64;
    let expected = h.reference.store.rows.clone();
    let duplicate = h.inputs[0].clone();
    let mut runtime = crate::Runtime {
        store: h.store,
        components: h.components,
        healthy: true,
    };
    let before = fs::read(h.root.db()).unwrap();
    for _ in 0..2 {
        reset_source_work();
        CHECKPOINT_PROOF_GETS.with(|n| n.set(0));
        assert_eq!(runtime.records().unwrap(), expected);
        assert_eq!(
            SOURCE_RAW_ROWS.with(std::cell::Cell::get),
            count,
            "every public call must read every actual SQL row"
        );
        assert_eq!(
            CHECKPOINT_PROOF_GETS.with(std::cell::Cell::get),
            2 * count,
            "full reconciliation already checks the same private immutable source"
        );
        reset_source_work();
        CHECKPOINT_PROOF_GETS.with(|n| n.set(0));
        runtime.apply(&duplicate).unwrap();
        assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get), count);
        assert_eq!(
            CHECKPOINT_PROOF_GETS.with(std::cell::Cell::get),
            2 * count,
            "idempotent apply must retain full reconciliation without a second identical traversal"
        );
    }
    assert_eq!(
        fs::read(h.root.db()).unwrap(),
        before,
        "idempotent apply and records cannot rewrite facts"
    );
    runtime
        .store
        .connection
        .execute("UPDATE records SET delivered=1 WHERE sequence=1", [])
        .unwrap();
    let observed = runtime.records().unwrap();
    assert!(observed[0].delivered());
    assert!(!expected[0].delivered());
    runtime
        .store
        .connection
        .execute(
            "UPDATE records SET ready=0,delivered=0 WHERE sequence=2",
            [],
        )
        .unwrap();
    let corrupted = fs::read(h.root.db()).unwrap();
    assert!(runtime.records().is_err());
    assert!(runtime.apply(&duplicate).is_err());
    assert_eq!(
        fs::read(h.root.db()).unwrap(),
        corrupted,
        "a warm view must neither hide nor repair changed old flags"
    );
    drop(runtime);
}

#[test]
fn sqlite_prefix_queries_read_actual_rows_once_instead_of_revisiting_head_and_anchor() {
    for count in [16, 32, 0] {
        let h = if count == 0 {
            dictionary_history()
        } else {
            source_history(count)
        };
        let count = h.inputs.len() as u64;
        let expected = h
            .reference
            .components
            .position_order_view(&h.reference.store)
            .unwrap();
        h.components.position_order_view(&h.store).unwrap();
        let before = fs::read(h.root.db()).unwrap();
        for _ in 0..2 {
            reset_source_work();
            assert_eq!(
                h.components.position_order_view(&h.store).unwrap(),
                expected
            );
            assert_eq!(
                SOURCE_HEAD_AGGREGATES.with(std::cell::Cell::get),
                1,
                "a prefix repeated the full SQL head aggregate for {count} records"
            );
            let actual = SOURCE_RAW_ROWS.with(std::cell::Cell::get);
            assert!(
                (count..=count + 2).contains(&actual),
                "prefix needs every actual row plus only its original outer head/base observation, got {actual} at {count}"
            );
        }
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            before,
            "read-only source batching cannot write or repair history"
        );
    }
}
#[test]
fn sqlite_warm_prefix_queries_reject_actual_old_rows_flags_identity_and_head_without_repair() {
    let h = dictionary_history();
    let expected = h.components.position_order_view(&h.store).unwrap();
    let checkpoint = h.components.checkpoint().unwrap();
    let records = h.store.read_records().unwrap();
    let (meta, meta_sha): (String, String) = h
        .store
        .connection
        .query_row("SELECT payload,digest FROM meta", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap();
    let head: String = h
        .store
        .connection
        .query_row("SELECT last_hash FROM state", [], |row| row.get(0))
        .unwrap();
    let (raw, physical) = dictionary_raw(&h.store, 2);
    for fault in [
        "old-lineage",
        "old-flags",
        "index",
        "identity",
        "head",
        "version",
        "application",
    ] {
        h.components.position_order_view(&h.store).unwrap();
        match fault {
            "old-lineage" => {
                let mut p = records[1].prepared().record();
                p["projections"][0]["before_hash"] = json!("f".repeat(64));
                rehash_prepared(&mut p);
                replace_prepared_source(&h.store, 2, &p, true, false);
            }
            "old-flags" => {
                h.store
                    .connection
                    .execute(
                        "UPDATE records SET ready=0,delivered=0 WHERE sequence=2",
                        [],
                    )
                    .unwrap();
            }
            "index" => {
                h.store
                    .connection
                    .execute(
                        "UPDATE records SET input_id='foreign-index' WHERE sequence=2",
                        [],
                    )
                    .unwrap();
            }
            "identity" => {
                let mut p: Value = serde_json::from_str(&meta).unwrap();
                p["configuration"]["generation"] = json!("f".repeat(64));
                h.store
                    .connection
                    .execute(
                        "UPDATE meta SET payload=?1,digest=?2",
                        params![p.to_string(), hash(&p)],
                    )
                    .unwrap();
            }
            "head" => {
                h.store
                    .connection
                    .execute("UPDATE state SET last_hash=?1", ["f".repeat(64)])
                    .unwrap();
            }
            "version" => h
                .store
                .connection
                .pragma_update(None, "user_version", 3_i64)
                .unwrap(),
            _ => h
                .store
                .connection
                .pragma_update(None, "application_id", 0_i64)
                .unwrap(),
        }
        let actual = fs::read(h.root.db()).unwrap();
        assert!(
            h.components.position_order_view(&h.store).is_err(),
            "warm prefix hid actual {fault}"
        );
        assert_eq!(
            fs::read(h.root.db()).unwrap(),
            actual,
            "{fault} must not be repaired"
        );
        assert_eq!(h.components.checkpoint().unwrap(), checkpoint);
        h.store
            .connection
            .pragma_update(None, "user_version", 4_i64)
            .unwrap();
        h.store
            .connection
            .pragma_update(None, "application_id", APPLICATION)
            .unwrap();
        h.store.connection.execute("UPDATE records SET input_id=?1,payload=?2,digest=?3,ready=1,delivered=0 WHERE sequence=2",params![records[1].prepared().input()["input_id"].as_str().unwrap(),&raw,&physical]).unwrap();
        h.store
            .connection
            .execute(
                "UPDATE meta SET payload=?1,digest=?2",
                params![&meta, &meta_sha],
            )
            .unwrap();
        h.store
            .connection
            .execute("UPDATE state SET last_hash=?1", [&head])
            .unwrap();
        assert_eq!(
            h.components.position_order_view(&h.store).unwrap(),
            expected
        );
    }
}
#[test]
fn a_legal_pending_tail_is_not_a_ready_prefix_and_still_recovers_the_original_transaction() {
    struct Unknown<'a>(&'a mut SqliteStore);
    impl Store for Unknown<'_> {
        fn head(&self) -> Result<u64, Error> {
            self.0.head()
        }
        fn get(&self, n: u64) -> Result<Option<Record>, Error> {
            self.0.get(n)
        }
        fn commit(&mut self, intent: &CommitIntent) -> Result<Record, Error> {
            self.0.commit(intent)?;
            Err(Error("ORIGINAL_COMMIT_UNKNOWN".into()))
        }
        fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
            self.0.mark_ready(n)
        }
        fn acknowledge(&mut self, n: u64) -> Result<(), Error> {
            self.0.acknowledge(n)
        }
    }
    let mut h = history(4, "12.00");
    let state = h.components.state(&h.store).unwrap();
    let checkpoint = h.components.checkpoint().unwrap();
    let value = input(
        5,
        "VALUATION",
        json!({"schema_version":1,"valuation":"prefix-pending","version":5,"position_evidence":hash(&checkpoint["components"][1]),"economic_version":state["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":"prefix-pending-mark","family":"CLOSED_BAR","version":5,"time":5,"as_of_sequence":5}]}),
    );
    let planned = h.components.prepare(&h.store, &value).unwrap();
    let original = planned.encode().unwrap();
    let error = coordinate(&mut Unknown(&mut h.store), &mut h.components, &planned).unwrap_err();
    assert_eq!(error.0, "ORIGINAL_COMMIT_UNKNOWN");
    assert_eq!(h.components.checkpoint().unwrap(), checkpoint);
    assert!(!h.store.get(5).unwrap().unwrap().ready());
    assert!(h.components.position_order_view(&h.store).is_err());
    let before = fs::read(h.root.db()).unwrap();
    assert!(h.store.save_checkpoint(&h.components).is_err());
    assert_eq!(fs::read(h.root.db()).unwrap(), before);
    let reference = h.reference.prepare(&value).unwrap();
    coordinate(
        &mut h.reference.store,
        &mut h.reference.components,
        &reference,
    )
    .unwrap();
    recover(&mut h.store, &mut h.components).unwrap();
    assert_eq!(
        h.store
            .get(5)
            .unwrap()
            .unwrap()
            .prepared()
            .encode()
            .unwrap(),
        original
    );
    assert!(h.store.get(5).unwrap().unwrap().ready());
    assert_eq!(h.store.head().unwrap(), 5);
    assert_eq!(
        h.components.checkpoint().unwrap(),
        h.reference.components.checkpoint().unwrap()
    );
    assert_eq!(
        h.components.position_order_view(&h.store).unwrap(),
        h.reference
            .components
            .position_order_view(&h.reference.store)
            .unwrap()
    );
}

#[test]
fn sqlite_zero_prefix_still_observes_every_actual_row_header_identity_and_head() {
    let h = dictionary_history();
    let count = h.inputs.len() as u64;
    reset_source_work();
    assert!(h.store.read_prefix(0).unwrap().unwrap().is_empty());
    assert_eq!(SOURCE_RAW_ROWS.with(std::cell::Cell::get), count);
    assert!(
        h.store.read_prefix(count + 1).is_err(),
        "an absent requested prefix is not partial success"
    );
    let (meta, physical): (String, String) = h
        .store
        .connection
        .query_row("SELECT payload,digest FROM meta", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap();
    let head: String = h
        .store
        .connection
        .query_row("SELECT last_hash FROM state", [], |row| row.get(0))
        .unwrap();
    for fault in ["version", "application", "identity", "head", "old-flags"] {
        match fault {
            "version" => h
                .store
                .connection
                .pragma_update(None, "user_version", 3_i64)
                .unwrap(),
            "application" => h
                .store
                .connection
                .pragma_update(None, "application_id", 0_i64)
                .unwrap(),
            "identity" => {
                h.store
                    .connection
                    .execute("UPDATE meta SET digest=?1", ["f".repeat(64)])
                    .unwrap();
            }
            "head" => {
                h.store
                    .connection
                    .execute("UPDATE state SET last_hash=?1", ["f".repeat(64)])
                    .unwrap();
            }
            _ => {
                h.store
                    .connection
                    .execute(
                        "UPDATE records SET ready=0,delivered=0 WHERE sequence=1",
                        [],
                    )
                    .unwrap();
            }
        }
        let before = fs::read(h.root.db()).unwrap();
        assert!(
            h.store.read_prefix(0).is_err(),
            "a zero request bypassed actual {fault}"
        );
        assert_eq!(fs::read(h.root.db()).unwrap(), before);
        h.store
            .connection
            .pragma_update(None, "user_version", 4_i64)
            .unwrap();
        h.store
            .connection
            .pragma_update(None, "application_id", APPLICATION)
            .unwrap();
        h.store
            .connection
            .execute(
                "UPDATE meta SET payload=?1,digest=?2",
                params![&meta, &physical],
            )
            .unwrap();
        h.store
            .connection
            .execute("UPDATE state SET last_hash=?1", [&head])
            .unwrap();
        h.store
            .connection
            .execute("UPDATE records SET ready=1 WHERE sequence=1", [])
            .unwrap();
        assert!(h.store.read_prefix(0).unwrap().unwrap().is_empty());
    }
}

#[test]
fn commit_readback_verifies_actual_codec_without_redecoding_the_same_validated_body() {
    let mut h = dictionary_history();
    let plan = next_planned_valuation(&h);
    let canonical = plan.encode().unwrap();
    PREPARED_BODY_REDECODES.with(|n| n.set(0));
    crate::codec::DECODED_BYTES.with(|n| n.set(0));
    crate::codec::PHYSICAL_HASHES.with(|n| n.set(0));
    reset_source_work();
    coordinate(&mut h.store, &mut h.components, &plan).unwrap();
    assert_eq!(
        h.store
            .get(plan.sequence())
            .unwrap()
            .unwrap()
            .prepared()
            .encode()
            .unwrap(),
        canonical
    );
    assert!(SOURCE_RAW_ROWS.with(std::cell::Cell::get) > 0);
    assert!(
        crate::codec::DECODED_BYTES.with(std::cell::Cell::get) >= canonical.len() as u64,
        "actual compressed frame must still be fully decompressed and hashed"
    );
    assert!(crate::codec::PHYSICAL_HASHES.with(std::cell::Cell::get) > 0);
    assert_eq!(
        PREPARED_BODY_REDECODES.with(std::cell::Cell::get),
        0,
        "same-call exact canonical data should not take the independent Prepared decoder again"
    );
}

#[test]
fn same_call_readback_never_substitutes_known_data_for_missing_or_changed_actual_source() {
    for sequence in [17_u64, 18] {
        for fault in [
            "physical",
            "base64",
            "zstd-tail",
            "logical",
            "size",
            "codec",
            "summary",
            "body",
            "index",
            "missing-target",
            "missing-base",
            "base-ready",
            "base-physical",
        ] {
            if sequence == 17 && matches!(fault, "missing-base" | "base-ready" | "base-physical") {
                continue;
            }
            let h = dictionary_history();
            let known = h.reference.store.rows[sequence as usize - 1].clone();
            let (raw, _) = dictionary_raw(&h.store, sequence);
            let mut frame: Value = serde_json::from_str(&raw).unwrap();
            match fault {
                "missing-target" => {
                    h.store
                        .connection
                        .execute("DELETE FROM records WHERE sequence=?1", [sequence as i64])
                        .unwrap();
                }
                "missing-base" => {
                    h.store
                        .connection
                        .execute("DELETE FROM records WHERE sequence=17", [])
                        .unwrap();
                }
                "base-ready" => {
                    h.store
                        .connection
                        .execute(
                            "UPDATE records SET ready=0,delivered=0 WHERE sequence=17",
                            [],
                        )
                        .unwrap();
                }
                "base-physical" => {
                    let (raw, _) = dictionary_raw(&h.store, 17);
                    let mut base: Value = serde_json::from_str(&raw).unwrap();
                    base["summary"]["extra"] = json!(true);
                    let raw = base.to_string();
                    h.store
                        .connection
                        .execute(
                            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=17",
                            params![&raw, digest(raw.as_bytes())],
                        )
                        .unwrap();
                }
                "index" => {
                    h.store
                        .connection
                        .execute(
                            "UPDATE records SET input_id='another-input' WHERE sequence=?1",
                            [sequence as i64],
                        )
                        .unwrap();
                }
                _ => {
                    match fault {
                        "physical" => {}
                        "base64" => frame["data"] = json!("!!!!"),
                        "zstd-tail" => {
                            use base64::Engine;
                            let mut data = base64::engine::general_purpose::STANDARD
                                .decode(frame["data"].as_str().unwrap())
                                .unwrap();
                            data.push(0);
                            frame["data"] =
                                json!(base64::engine::general_purpose::STANDARD.encode(data));
                        }
                        "logical" => frame["logical_sha256"] = json!("f".repeat(64)),
                        "size" => frame["logical_size"] = json!(1),
                        "codec" => frame["codec"] = json!("ANOTHER_CODEC"),
                        "summary" => frame["summary"]["sequence"] = json!(sequence + 1),
                        "body" => {
                            // A complete, independently validated Prepared from a
                            // different original state is still not this commit.
                            let donor = history(sequence, "13.00");
                            let bytes = donor.reference.store.rows[sequence as usize - 1]
                                .prepared()
                                .encode()
                                .unwrap();
                            let anchor = h.store.dictionary_anchor_for(sequence).unwrap();
                            frame = serde_json::from_str(
                                &crate::dictionary_codec::encode_bytes(
                                    &bytes,
                                    frame["summary"].clone(),
                                    sequence,
                                    anchor.as_ref().map(|source| &source.anchor),
                                )
                                .unwrap(),
                            )
                            .unwrap();
                        }
                        _ => unreachable!(),
                    }
                    let raw = frame.to_string();
                    let physical = if fault == "physical" {
                        "f".repeat(64)
                    } else {
                        digest(raw.as_bytes())
                    };
                    h.store
                        .connection
                        .execute(
                            "UPDATE records SET payload=?1,digest=?2 WHERE sequence=?3",
                            params![raw, physical, sequence as i64],
                        )
                        .unwrap();
                }
            }
            h.store.decoded_rows.borrow_mut().clear();
            let before = fs::read(h.root.db()).unwrap();
            let observed = h.store.read_one_expected(sequence, Some(&known));
            assert!(
                match observed {
                    Ok(None) => fault == "missing-target",
                    Err(_) => true,
                    Ok(Some(_)) => false,
                },
                "known data concealed actual {fault} at {sequence}"
            );
            assert_eq!(
                fs::read(h.root.db()).unwrap(),
                before,
                "readback repaired actual {fault}"
            );
        }
    }
}

#[test]
fn same_call_readback_retains_actual_flags_and_full_cold_body_without_planner_origin() {
    let h = dictionary_history();
    for sequence in [17_u64, 18] {
        let known = &h.reference.store.rows[sequence as usize - 1];
        for (ready, delivered) in [(true, false), (true, true), (false, false)] {
            h.store
                .connection
                .execute(
                    "UPDATE records SET ready=?1,delivered=?2 WHERE sequence=?3",
                    params![ready, delivered, sequence as i64],
                )
                .unwrap();
            h.store.decoded_rows.borrow_mut().clear();
            let observed = h
                .store
                .read_one_expected(sequence, Some(known))
                .unwrap()
                .unwrap()
                .0;
            assert_eq!((observed.ready(), observed.delivered()), (ready, delivered));
            assert_eq!(
                observed.prepared().encode().unwrap(),
                known.prepared().encode().unwrap()
            );
            assert!(!std::ptr::eq(
                observed.prepared().value(),
                known.prepared().value()
            ));
            h.store.decoded_rows.borrow_mut().clear();
            let cold = h.store.read_one(sequence).unwrap().unwrap().0;
            assert_eq!(cold, observed);
            let donor = history(sequence, "13.00");
            assert!(
                h.store
                    .read_one_expected(
                        sequence,
                        Some(&donor.reference.store.rows[sequence as usize - 1])
                    )
                    .is_err(),
                "warm cache accepted a different complete known body"
            );
        }
        // The passive observation cannot be used as a new original planner,
        // even when its exact predecessor exists at the receiving source.
        if sequence == 17 {
            let observed = h
                .store
                .read_one_expected(sequence, Some(known))
                .unwrap()
                .unwrap()
                .0;
            let mut receiver = Harness::new(config()).unwrap();
            for value in &h.inputs[..16] {
                let plan = receiver.prepare(value).unwrap();
                coordinate(&mut receiver.store, &mut receiver.components, &plan).unwrap();
            }
            assert!(
                coordinate(
                    &mut receiver.store,
                    &mut receiver.components,
                    observed.prepared()
                )
                .is_err()
            );
            assert_eq!(
                receiver.store.rows.len(),
                16,
                "passive data minted a new fact"
            );
        }
        h.store
            .connection
            .execute_batch("PRAGMA ignore_check_constraints=ON")
            .unwrap();
        h.store
            .connection
            .execute(
                "UPDATE records SET ready=0,delivered=1 WHERE sequence=?1",
                [sequence as i64],
            )
            .unwrap();
        assert!(
            h.store.read_one_expected(sequence, Some(known)).is_err(),
            "illegal actual flags bypassed the original flag reader"
        );
        h.store
            .connection
            .execute_batch("PRAGMA ignore_check_constraints=OFF")
            .unwrap();
        // The next dependent target needs its actual predecessor Ready.
        h.store
            .connection
            .execute(
                "UPDATE records SET ready=1,delivered=0 WHERE sequence=?1",
                [sequence as i64],
            )
            .unwrap();
    }
}
