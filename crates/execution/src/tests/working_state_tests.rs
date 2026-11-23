use super::*;
use crate::{components::DATA_FORKS, support, verify_finite_backtest_result};

fn reseal_account_checkpoint(result: &mut Value, checkpoint: &Value) {
    let performance = &mut result["runtime_performance"];
    performance["account_checkpoint"] = json!(hash(checkpoint));
    performance.as_object_mut().unwrap().remove("id");
    performance["id"] = json!(format!("AP-{}", hash(performance)));
    result["account_equity_timeline"] = performance["timeline"].clone();
}

fn reseal_account_command(
    result: &mut Value,
    checkpoint: &mut Value,
    command: &Value,
    aliases: &[(&str, &Value)],
) {
    let command_id = command["command_id"].as_str().unwrap();
    let receipt = json!(hash(command));
    checkpoint["state"]["receipts"][command_id] = receipt.clone();
    let mut unsigned = command.clone();
    unsigned.as_object_mut().unwrap().remove("command_id");
    let semantic = json!(hash(&unsigned));
    for (family, identity) in aliases {
        let key = json!([family, identity]).to_string();
        assert!(checkpoint["state"]["semantic"].get(&key).is_some());
        checkpoint["state"]["semantic"][key] = semantic.clone();
    }
    let point = result["runtime_performance"]["timeline"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|point| point["provenance"]["command"] == command_id)
        .unwrap();
    point["provenance"]["cause"] = receipt.clone();
    point["cause"] = receipt;
    reseal_account_checkpoint(result, checkpoint);
}

#[test]
fn finite_spot_accept_uses_the_production_payload_contract() {
    let mut configuration = support::config();
    configuration["schema_version"] = json!(2);
    configuration["account_checkpoint_version"] = json!(5);
    let kernel = "a".repeat(64);
    let pin = "b".repeat(64);
    let binding = json!({"configuration":hash(&configuration),"kernel_artifact":kernel,"input_pin":pin});
    let inputs = [
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::fill(4, 1, "3", "10.00", "1.00"),
        support::open(5, "SELL"),
        support::stage(6, 2, "DISPATCHED"),
        support::input(
            7,
            "ACCEPT",
            json!({"schema_version":1,"order":support::order(2),"venue_order":"venue-2"}),
        ),
        support::fill(8, 2, "4", "12.00", "1.00"),
    ];
    let accept_index = 6;
    let invalid_accepts = [
        ("venue_order", json!(" venue-2 "), "EXECUTION_ID"),
        ("extra", json!(true), "EXECUTION_FIELDS"),
    ];
    for (field, value, code) in &invalid_accepts {
        let mut owner = WorkingState::new(configuration.clone()).unwrap();
        for input in &inputs[..accept_index] {
            owner.apply(input).unwrap();
        }
        let mut input = inputs[accept_index].clone();
        input["payload"][*field] = value.clone();
        assert_eq!(owner.apply(&input).err().unwrap().0, *code);
    }
    let mut owner = WorkingState::new(configuration.clone()).unwrap();
    for input in &inputs {
        owner.apply(input).unwrap();
    }
    let completed = owner.finish(&inputs, &binding, 0, 8).unwrap();
    let verify = |result: &Value| {
        verify_finite_backtest_result(
            result,
            completed.account_checkpoint(),
            &configuration,
            &kernel,
            &pin,
            0,
            8,
        )
    };
    verify(completed.result()).unwrap();

    for (field, value, code) in invalid_accepts {
        let mut altered_inputs = inputs.clone();
        let accept = &mut altered_inputs[accept_index];
        accept["payload"][field] = value;
        let cause = hash(accept);
        let mut result = completed.result().clone();
        result["facts"][accept_index] =
            json!({"sequence":accept_index + 1,"transaction":format!("ETX-{cause}"),"input":accept});
        result["manifest"]["inputs"][accept_index] = json!(cause);
        result["source"]["inputs"] = json!(hash(&json!(altered_inputs)));
        result["reconciliation"]["source"] = result["source"].clone();
        let error = verify(&result).err().map(|error| error.0);
        assert_eq!(error.as_deref(), Some(code), "{field}");
    }
}

#[test]
fn finite_result_verifies_retained_economics_and_rejects_changed_body() {
    let mut config = support::config();
    config["schema_version"] = json!(2);
    config["account_checkpoint_version"] = json!(5);
    config["capitals"] = json!({"cluster":"500.00","second":"500.00"});
    config["profiles"]["second"] = config["profiles"]["cluster"].clone();
    let kernel = "a".repeat(64);
    let pin = "b".repeat(64);
    let binding = json!({"configuration":hash(&config),"kernel_artifact":kernel,"input_pin":pin});
    let round_trip = [
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::fill(4, 1, "3", "10.00", "1.00"),
        support::open(5, "SELL"),
        support::stage(6, 2, "UNKNOWN"),
        support::fill(7, 2, "1", "12.00", "1.00"),
        support::fill(8, 2, "3", "12.00", "1.00"),
    ];
    let partial_cancel = [
        round_trip[0].clone(),
        round_trip[1].clone(),
        round_trip[2].clone(),
        support::terminal(4, 1, "CANCELLED"),
    ];

    for (inputs, closed_cycles) in [
        (&round_trip[..0], 0),
        (&round_trip[..4], 0),
        (&partial_cancel[..], 0),
        (&round_trip[..], 1),
    ] {
        let mut owner = WorkingState::new(config.clone()).unwrap();
        let mut position_before_first_fill = None;
        for (index, input) in inputs.iter().enumerate() {
            if index == 2 {
                position_before_first_fill =
                    Some(owner.owners.position.checkpoint_record().unwrap().0);
            }
            owner.apply(input).unwrap();
        }
        let mut inputs = inputs.to_vec();
        if !inputs.is_empty() {
            let marks = json!([{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":"close-valuation","family":"CLOSED_BAR","version":1,"time":9,"as_of_sequence":9}]);
            let mut valuation = support::input(
                9,
                "VALUATION",
                json!({"schema_version":1,"valuation":"close-valuation","version":1,"position_evidence":owner.owners.payload_digest(1).unwrap(),"economic_version":owner.account_snapshot().unwrap()["economic_version"],"marks":marks}),
            );
            valuation["trading_day"] = json!("2026-10-20");
            valuation["day_index"] = json!(2);
            owner.apply(&valuation).unwrap();
            inputs.push(valuation);
        }
        let completed = owner.finish(&inputs, &binding, 0, 9).unwrap();
        let verify = |result: &Value| {
            verify_finite_backtest_result(
                result,
                completed.account_checkpoint(),
                &config,
                &kernel,
                &pin,
                0,
                9,
            )
        };
        let verified = verify(completed.result()).unwrap_or_else(|error| {
            panic!(
                "valid transcript with {} inputs and {closed_cycles} closed cycles: {error}",
                inputs.len()
            )
        });
        assert_eq!(verified.equity_points(), completed.equity_points());
        assert_eq!(
            verified.closed_cycles(),
            &BTreeMap::from([("cluster".into(), closed_cycles), ("second".into(), 0)])
        );

        if inputs.len() == 5 {
            let original = completed.result();
            let first_fill = hash(&inputs[2]);
            let original_checkpoint = completed.account_checkpoint();
            for (index, error) in [
                ("semantic", "ACCOUNT_CHECKPOINT_SEMANTIC"),
                ("position_trades", "ACCOUNT_CHECKPOINT_POSITION_TRADES"),
            ] {
                let mut changed = original.clone();
                let mut checkpoint = original_checkpoint.clone();
                let entries = checkpoint["state"][index].as_object_mut().unwrap();
                let key = entries.keys().next().unwrap().clone();
                entries.remove(&key).unwrap();
                reseal_account_checkpoint(&mut changed, &checkpoint);
                assert_eq!(
                    verify_finite_backtest_result(
                        &changed,
                        &checkpoint,
                        &config,
                        &kernel,
                        &pin,
                        0,
                        9
                    )
                    .err()
                    .unwrap()
                    .0,
                    error,
                );
            }

            let mut changed = original.clone();
            let mut checkpoint = original_checkpoint.clone();
            let command = checkpoint["journal"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|command| command["cause"] == first_fill)
                .unwrap();
            let wrong = json!("e".repeat(64));
            assert_ne!(command["payload"]["position_evidence"], wrong);
            command["payload"]["position_evidence"] = wrong.clone();
            let command = command.clone();
            let payload = &command["payload"];
            let trade = payload["trade"].as_str().unwrap();
            checkpoint["state"]["position_trades"][trade]["position_evidence"] = wrong.clone();
            let point = changed["runtime_performance"]["timeline"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|point| point["provenance"]["upstream_cause"] == first_fill)
                .unwrap();
            point["snapshot"]["position_evidence"] = wrong;
            reseal_account_command(
                &mut changed,
                &mut checkpoint,
                &command,
                &[
                    ("trade", &payload["trade"]),
                    ("execution", &payload["execution"]),
                    ("venue_trade", &payload["venue_trade"]),
                    ("fee_instruction", &payload["fee_instruction"]),
                ],
            );
            assert_eq!(
                verify_finite_backtest_result(&changed, &checkpoint, &config, &kernel, &pin, 0, 9)
                    .err()
                    .unwrap()
                    .0,
                "RESULT_FINITE_ACCOUNT_POSITION",
            );

            let mut changed = original.clone();
            let mut checkpoint = original_checkpoint.clone();
            let position = position_before_first_fill.unwrap();
            let reference = hash(&position);
            let command = checkpoint["journal"]
                .as_array_mut()
                .unwrap()
                .last_mut()
                .unwrap();
            assert_eq!(command["op"], "VALUATION");
            let old_reference = command["payload"]["position_ref"]
                .as_str()
                .unwrap()
                .to_owned();
            assert_ne!(reference, old_reference);
            command["payload"]["position_ref"] = json!(reference);
            command["payload"]["intent"]["position_evidence"] = json!(reference);
            let mut command = command.clone();
            command["payload"]
                .as_object_mut()
                .unwrap()
                .remove("position_ref");
            command["payload"]["position"] = position.as_ref().clone();
            let positions = checkpoint["positions"].as_object_mut().unwrap();
            assert_eq!(positions.len(), 1);
            positions.remove(&old_reference).unwrap();
            positions.insert(reference.clone(), position.as_ref().clone());
            let last = changed["runtime_performance"]["timeline"]
                .as_array_mut()
                .unwrap()
                .last_mut()
                .unwrap();
            last["snapshot"]["position_evidence"] = json!(reference);
            changed["final_account"] = last["snapshot"].clone();
            checkpoint["state"]["snapshot"] = changed["final_account"].clone();
            reseal_account_command(
                &mut changed,
                &mut checkpoint,
                &command,
                &[("valuation", &command["payload"]["intent"]["valuation"])],
            );
            assert_eq!(
                verify_finite_backtest_result(&changed, &checkpoint, &config, &kernel, &pin, 0, 9)
                    .err()
                    .unwrap()
                    .0,
                "RESULT_FINITE_ACCOUNT_POSITION",
            );

            for (field, error) in [
                ("fees", "RESULT_FINITE_TRADE_FEES"),
                ("cause", "RESULT_FINITE_ACCOUNT_RECEIPT"),
            ] {
                let mut changed = original.clone();
                let performance = &mut changed["runtime_performance"];
                let point = performance["timeline"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|point| point["provenance"]["upstream_cause"] == first_fill)
                    .unwrap();
                assert_eq!(point["source"], "TRADE");
                if field == "fees" {
                    assert_ne!(point["snapshot"]["fees"], "0.00");
                    point["snapshot"]["fees"] = json!("0.00");
                } else {
                    let wrong = json!("f".repeat(64));
                    assert_ne!(point["cause"], wrong);
                    point["cause"] = wrong.clone();
                    point["provenance"]["cause"] = wrong;
                }
                performance.as_object_mut().unwrap().remove("id");
                performance["id"] = json!(format!("AP-{}", hash(performance)));
                changed["account_equity_timeline"] = performance["timeline"].clone();
                assert_eq!(verify(&changed).err().unwrap().0, error, "{field}");
            }

            let mut changed = original.clone();
            let ledger_point = changed["cluster_equity_timelines"][0]["points"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|entry| entry["point"]["cause"] == first_fill)
                .unwrap();
            assert_ne!(ledger_point["point"]["snapshot"]["fees"], "0.00");
            ledger_point["point"]["snapshot"]["fees"] = json!("0.00");
            assert_eq!(
                verify(&changed).err().unwrap().0,
                "RESULT_FINITE_TRADE_FEES"
            );

            for field in [
                "cash",
                "position_cost",
                "reserved",
                "economic_version",
                "valuation_version",
            ] {
                let mut changed = original.clone();
                let point = changed["cluster_equity_timelines"][0]["points"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|entry| entry["point"]["cause"] == first_fill)
                    .unwrap();
                let actual = &mut point["point"]["snapshot"][field];
                *actual = match actual.as_u64() {
                    Some(version) => json!(version + 1),
                    None => {
                        assert!(actual.is_string());
                        assert_ne!(*actual, "123.00");
                        json!("123.00")
                    }
                };
                assert_eq!(
                    verify(&changed).err().unwrap().0,
                    "RESULT_FINITE_LEDGER_SNAPSHOT",
                    "{field}"
                );
            }

            for owner in ["final_positions", "final_allocations"] {
                for (field, value, error) in [
                    ("cost", "41", "RESULT_FINITE_POSITION_COST"),
                    ("average", "11.00", "RESULT_FINITE_POSITION_AVERAGE"),
                ] {
                    let mut changed = original.clone();
                    let actual = &mut changed[owner][0]["snapshot"][field];
                    assert_ne!(*actual, value);
                    *actual = json!(value);
                    assert_eq!(verify(&changed).err().unwrap().0, error, "{owner}.{field}");
                }
            }

            for field in ["simple_return", "daily_return"] {
                let mut changed = original.clone();
                let points = changed["cluster_equity_timelines"][0]["points"]
                    .as_array_mut()
                    .unwrap();
                let actual = &mut points.last_mut().unwrap()["point"]["snapshot"][field];
                assert_ne!(*actual, "1.00000000");
                *actual = json!("1.00000000");
                changed["final_ledgers"][0][field] = actual.clone();
                changed["cluster_results"][0]["final_ledger"] = changed["final_ledgers"][0].clone();
                if field == "simple_return" {
                    changed["cluster_results"][0]["cluster_performance"]["summary"][field] =
                        json!("1.00000000");
                }
                assert_eq!(
                    verify(&changed).err().unwrap().0,
                    "RESULT_FINITE_LEDGER_RETURN",
                    "{field}"
                );
            }
        }

        if !inputs.is_empty() {
            let mut changed = completed.result().clone();
            let performance = &mut changed["runtime_performance"];
            let timeline = performance["timeline"].as_array_mut().unwrap();
            assert_eq!(timeline.remove(2)["source"], "STAGE");
            for (index, point) in timeline.iter_mut().enumerate().skip(2) {
                point["sequence"] = json!(index);
                point["account_sequence"] = json!(index);
                point["snapshot"]["sequence"] = json!(index);
            }
            let final_account = timeline.last().unwrap()["snapshot"].clone();
            performance["summary"]["valuation_count"] = json!(timeline.len());
            performance.as_object_mut().unwrap().remove("id");
            performance["id"] = json!(format!("AP-{}", hash(performance)));
            changed["account_equity_timeline"] = performance["timeline"].clone();
            changed["final_account"] = final_account;
            assert_eq!(
                verify(&changed).err().unwrap().0,
                "RESULT_FINITE_ACCOUNT_OCCURRENCES"
            );

            let mut changed = completed.result().clone();
            let timeline = changed["cluster_equity_timelines"][0]["points"]
                .as_array_mut()
                .unwrap();
            assert_eq!(timeline.remove(3)["point"]["sequence"], 67);
            for (index, point) in timeline.iter_mut().enumerate().skip(3) {
                point["timeline_sequence"] = json!(index);
            }
            assert_eq!(
                verify(&changed).err().unwrap().0,
                "RESULT_FINITE_LEDGER_OCCURRENCES"
            );

            let mut changed = completed.result().clone();
            changed["final_allocations"][0]["snapshot"]["cycle"] = json!(2);
            assert!(verify(&changed).is_err());

            let mut changed = completed.result().clone();
            changed["final_allocations"][0]["cluster"] = json!("foreign");
            assert!(verify(&changed).is_err());
        }

        for missing in [
            "final_account",
            "final_ledgers",
            "trades",
            "cluster_equity_timelines",
        ] {
            let mut changed = completed.result().clone();
            changed.as_object_mut().unwrap().remove(missing);
            assert!(verify(&changed).is_err(), "accepted missing {missing}");
        }

        let mut changed = completed.result().clone();
        changed["final_account"]["cash"] = json!("NaN");
        let timeline = changed["runtime_performance"]["timeline"]
            .as_array_mut()
            .unwrap();
        timeline.last_mut().unwrap()["snapshot"]["cash"] = json!("NaN");
        changed["account_equity_timeline"] = changed["runtime_performance"]["timeline"].clone();
        let performance = &mut changed["runtime_performance"];
        performance.as_object_mut().unwrap().remove("id");
        performance["id"] = json!(format!("AP-{}", hash(performance)));
        assert!(verify(&changed).is_err());

        let mut changed = completed.result().clone();
        let performance = &mut changed["runtime_performance"];
        performance["summary"]["return_since_start"] = json!("1.00000000");
        performance.as_object_mut().unwrap().remove("id");
        performance["id"] = json!(format!("AP-{}", hash(performance)));
        assert_eq!(
            verify(&changed).err().unwrap().0,
            "RESULT_FINITE_ACCOUNT_SUMMARY"
        );

        let mut changed = completed.result().clone();
        changed["reconciliation"]["totals"]["ledger_cash"]["difference"] = json!("0");
        assert!(verify(&changed).is_err());
    }
}

#[test]
fn finite_result_rejects_resealed_trade_rounding_prefix() {
    let mut config = support::config();
    config["instruments"][0]["quantity_precision"] = json!(2);
    let mut opening = support::open(1, "BUY");
    opening["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    opening["payload"]["market"]["request_digest"] = json!(hash(&opening["payload"]["request"]));
    let inputs = [
        opening,
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1.05", "9.99", "1.00"),
        support::fill(4, 1, "2.95", "10.00", "1.00"),
    ];
    let mut owner = WorkingState::new(config.clone()).unwrap();
    for input in &inputs {
        owner.apply(input).unwrap();
    }
    let kernel = "a".repeat(64);
    let pin = "b".repeat(64);
    let binding = json!({"configuration":hash(&config),"kernel_artifact":kernel,"input_pin":pin});
    let completed = owner.finish(&inputs, &binding, 0, 4).unwrap();
    let verify = |result: &Value, checkpoint: &Value| {
        verify_finite_backtest_result(result, checkpoint, &config, &kernel, &pin, 0, 4)
    };
    verify(completed.result(), completed.account_checkpoint()).unwrap();

    let first_fill = hash(&inputs[2]);
    let mut changed = completed.result().clone();
    let mut checkpoint = completed.account_checkpoint().clone();
    let command = checkpoint["journal"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|command| command["cause"] == first_fill)
        .unwrap();
    let field = "realized_rounding_adjustment";
    assert_eq!(command["payload"][field], "-0.0005");
    command["payload"][field] = json!("0.00");
    let command = command.clone();
    let point = changed["runtime_performance"]["timeline"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|point| point["provenance"]["upstream_cause"] == first_fill)
        .unwrap();
    assert_eq!(point["snapshot"][field], "-0.0005");
    point["snapshot"][field] = json!("0.00");
    let payload = &command["payload"];
    reseal_account_command(
        &mut changed,
        &mut checkpoint,
        &command,
        &[
            ("trade", &payload["trade"]),
            ("execution", &payload["execution"]),
            ("venue_trade", &payload["venue_trade"]),
            ("fee_instruction", &payload["fee_instruction"]),
        ],
    );
    assert_eq!(
        verify(&changed, &checkpoint).err().unwrap().0,
        "RESULT_FINITE_ACCOUNT_ROUNDING"
    );

    let mut changed = completed.result().clone();
    let entry = changed["cluster_equity_timelines"][0]["points"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|entry| entry["point"]["cause"] == first_fill)
        .unwrap();
    assert_eq!(entry["point"]["snapshot"][field], "-0.0005");
    entry["point"]["snapshot"][field] = json!("0.00");
    assert_eq!(
        verify(&changed, completed.account_checkpoint())
            .err()
            .unwrap()
            .0,
        "RESULT_FINITE_LEDGER_ROUNDING"
    );
}

#[test]
fn exclusive_admission_does_not_fork_all_owners_and_normal_rejection_is_atomic() {
    let mut owner = WorkingState::new(support::config()).unwrap();
    DATA_FORKS.with(|n| n.set(0));
    owner.apply(&support::open(1, "BUY")).unwrap();
    assert_eq!(
        DATA_FORKS.with(|n| n.get()),
        0,
        "exclusive admission must not create a whole composition copy"
    );
    let mut config = support::config();
    config["initial_cash"] = json!("1.00");
    config["capitals"]["cluster"] = json!("1.00");
    let mut owner = WorkingState::new(config).unwrap();
    let before = owner.state().unwrap();
    DATA_FORKS.with(|n| n.set(0));
    assert_eq!(
        owner.apply(&support::open(1, "BUY")).unwrap_err().0,
        "EXECUTION_RISK_DENIED"
    );
    assert_eq!(owner.state().unwrap(), before);
    assert_eq!(owner.sequence(), 0);
    assert_eq!(DATA_FORKS.with(|n| n.get()), 0);
}

#[test]
fn full_account_history_denies_new_admission_without_mutating_any_owner() {
    let mut cfg = support::config();
    cfg["instruments"][0]["quantity_precision"] = json!(2);
    let mut owner = WorkingState::new(cfg).unwrap();
    let mut opening = support::open(1, "BUY");
    opening["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    opening["payload"]["market"]["request_digest"] = json!(hash(&opening["payload"]["request"]));
    owner.apply(&opening).unwrap();
    owner.apply(&support::stage(2, 1, "UNKNOWN")).unwrap();
    let mut n = 3;
    for _ in 0..64 {
        owner
            .apply(&support::fill(n, 1, "0.05", "10.00", "1.00"))
            .unwrap();
        n += 1;
    }
    owner
        .apply(&support::fill(n, 1, "0.80", "10.00", "1.00"))
        .unwrap();
    n += 1;
    let mut full = false;
    for _ in 0..300 {
        let cp: Value =
            serde_json::from_slice(&owner.owners.account.checkpoint().unwrap().0).unwrap();
        let bytes = cp["journal"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.to_string().len())
            .sum::<usize>();
        if bytes > 4 * 1024 * 1024 {
            full = true;
            break;
        }
        let marks = json!([{"schema_version":1,"instrument":"600000.XSHG","mark":"10.00","source_ref":format!("capacity-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]);
        let payload = json!({"schema_version":1,"valuation":format!("memory-cap-{n}"),"version":n,"economic_version":owner.owners.account.snapshot()["economic_version"],"position_evidence":owner.owners.payload_digest(1).unwrap(),"marks":marks});
        owner
            .apply(&support::input(n, "VALUATION", payload))
            .unwrap();
        n += 1;
    }
    assert!(
        full,
        "the actual Account journal must reach the unchanged admission budget"
    );
    let mut next = support::open(n, "BUY");
    next["payload"]["order"] = json!(support::order(2));
    next["payload"]["request"]["request_id"]["value"] = json!("request-2");
    next["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    next["payload"]["fee_contract"] = support::fixture()["second_fee_contract"].clone();
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        fee::{OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput},
        time::OnlyTimestamp,
    };
    let original =
        OnlyOrderFeePolicyBinding::from_record(&next["payload"]["fee_contract"]["binding"])
            .unwrap();
    let rebound = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: original.runtime_id().clone(),
        account_id: original.account_id().clone(),
        cluster_id: original.cluster_id().clone(),
        order_id: original.order_id().clone(),
        instrument_id: original.instrument_id().clone(),
        market_product_id: original.market_product_id().clone(),
        market_product_version: original.market_product_version().clone(),
        market_fee_pack: original.market_fee_pack().clone(),
        broker_fee_contract: original.broker_fee_contract().clone(),
        applicability_scope: original.applicability_scope().clone(),
        order_fixed_schedules: original.order_fixed_schedules().clone(),
        fill_effective_families: original.fill_effective_families().clone(),
        charge_currency: original.charge_currency().clone(),
        bound_at: OnlyTimestamp::from_unix_nanos(n.into()),
        fingerprint: String::new(),
    })
    .unwrap();
    next["payload"]["fee_contract"]["binding"] = rebound.to_record();
    for key in ["expected", "maximum"] {
        next["payload"]["fee_contract"]["estimate"][key]["binding"] = rebound.to_record();
    }
    next["payload"]["fee_contract"]["funding"]["binding_fingerprint"] =
        json!(rebound.fingerprint());

    next["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"] = json!("40.00");
    next["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("40.00");
    next["payload"]["market"]["request_digest"] = json!(hash(&next["payload"]["request"]));
    let before = owner.state().unwrap();
    let prefix = owner.sequence();
    DATA_FORKS.with(|c| c.set(0));
    assert_eq!(
        owner.apply(&next).unwrap_err().0,
        "EXECUTION_ACCOUNT_CAPACITY_DENIED"
    );
    assert_eq!(owner.sequence(), prefix);
    assert_eq!(owner.state().unwrap(), before);
    assert_eq!(DATA_FORKS.with(|c| c.get()), 0);
}
