use onlyalpha_backend::application::research_factor::{Window, compile};
use serde_json::{Value, json};
fn reference() -> Value {
    serde_json::from_slice(
        &std::fs::read(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/application/fixtures/research_factor.json"),
        )
        .unwrap(),
    )
    .unwrap()
}
#[test]
fn historical_graph_keeps_its_original_exact_identity() {
    use onlyalpha_calculation::product::Graph;
    let r = reference();
    let historical = Graph::from_record(&r["graph"], 1024 * 1024).unwrap();
    assert_eq!(historical.to_record(), r["graph"]);
    assert_eq!(
        historical.fingerprint(),
        r["graph_fingerprint"].as_str().unwrap()
    );
    for definition in historical.ordered_nodes() {
        assert_eq!(definition.to_record()["semantic_version"], "1");
    }
}
#[test]
fn current_graph_uses_actual_native_operator_contracts_and_a_distinct_identity() {
    use onlyalpha_calculation_bridge::native_operators::OperatorCalculation;
    let r = reference();
    let c = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    assert_ne!(c.graph().to_record(), r["graph"]);
    assert_ne!(
        c.graph().fingerprint(),
        r["graph_fingerprint"].as_str().unwrap()
    );
    assert_ne!(
        c.root_fingerprint(),
        r["root_fingerprint"].as_str().unwrap()
    );
    let mut operators = 0;
    for definition in c.graph().ordered_nodes() {
        let record = definition.to_record();
        if record["kind"] == "INDICATOR" {
            operators += 1;
            assert_eq!(record["semantic_version"], "2");
            let actual = OperatorCalculation::from_record(&record).unwrap();
            assert_eq!(actual.definition(), definition);
        } else {
            assert_eq!(record["kind"], "FACTOR");
            assert_eq!(record["semantic_version"], "1");
        }
    }
    assert_eq!(operators, 2);
    assert_eq!(c.required_history_bars(), 20);
    assert_eq!(c.columns(), &["close".to_string(), "volume".to_string()]);
}
#[test]
fn revision_source_and_reviewed_candidate_cannot_be_substituted() {
    let r = reference();
    for pointer in [
        "/source_text",
        "/input_contract/close/type",
        "/parent_revision_fingerprint",
        "/source_sha256",
        "/revision_fingerprint",
        "/factor_id",
        "/description",
    ] {
        let mut revision = r["revision"].clone();
        *revision.pointer_mut(pointer).unwrap() = json!("changed");
        assert!(
            compile(&r["candidate"], &r["draft"], &revision).is_err(),
            "{pointer}"
        );
    }
    let mut candidate = r["candidate"].clone();
    candidate["expression"]["left"]["left"]["right"]["lag"] = json!(21);
    assert!(compile(&candidate, &r["draft"], &r["revision"]).is_err());

    let mut revision = r["revision"].clone();
    revision["unverified_executable"] = json!({"artifact_fingerprint": "f".repeat(64)});
    assert!(compile(&r["candidate"], &r["draft"], &revision).is_err());
}
#[test]
fn exact_scope_includes_warmup_but_never_extends_forecast_beyond_approved_end() {
    let r = reference();
    let c = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    let w = Window {
        start_ns: 1000,
        end_ns: 2000,
        bar_ns: 10,
        horizon_bars: 3,
    };
    let prepared = c.window(w).unwrap();
    assert_eq!(prepared.dataset_start_ns(), 800);
    assert_eq!(prepared.dataset_end_ns(), 2000);
    assert_eq!(prepared.eligible_end_ns(), 1970);
    assert_eq!(prepared.observation_count(), 100);
    assert_eq!(prepared.pair_capacity(), 97);
    assert_ne!(
        prepared.fingerprint(),
        c.window(Window {
            horizon_bars: 4,
            ..w
        })
        .unwrap()
        .fingerprint()
    );
}
#[test]
fn invalid_or_unrepresentable_window_is_denied_without_clamping() {
    let r = reference();
    let c = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    for w in [
        Window {
            start_ns: 0,
            end_ns: 1000,
            bar_ns: 10,
            horizon_bars: 1,
        },
        Window {
            start_ns: 1000,
            end_ns: 2000,
            bar_ns: 0,
            horizon_bars: 1,
        },
        Window {
            start_ns: 1000,
            end_ns: 2000,
            bar_ns: 10,
            horizon_bars: 0,
        },
        Window {
            start_ns: 1000,
            end_ns: 2001,
            bar_ns: 10,
            horizon_bars: 1,
        },
        Window {
            start_ns: 1000,
            end_ns: 2000,
            bar_ns: 10,
            horizon_bars: 100,
        },
    ] {
        assert!(c.window(w).is_err());
    }
    let large_bar = u64::MAX / 3;
    assert!(
        c.window(Window {
            start_ns: 1,
            end_ns: large_bar * 2 + 1,
            bar_ns: large_bar,
            horizon_bars: 1
        })
        .is_err()
    );
    for (start, end) in [(1000, 1000), (2000, 1000)] {
        assert!(
            c.window(Window {
                start_ns: start,
                end_ns: end,
                bar_ns: 10,
                horizon_bars: 1
            })
            .is_err()
        );
    }
}

#[test]
fn valid_but_unreviewed_source_cannot_replace_the_approved_program() {
    use onlyalpha_backend::application::private_assets::authoring::Draft;
    let r = reference();
    let mut changed = r["draft"].clone();
    changed["source_text"] =
        json!("def calculate(api, inputs, parameters):\n    return {'value': 1}\n");
    let valid_revision = Draft::new(changed.clone()).unwrap().revision().unwrap();
    assert!(compile(&r["candidate"], &changed, &valid_revision).is_err());
    assert!(compile(&r["candidate"], &r["draft"], &Value::Null).is_err());
}

fn from_candidate(candidate: &Value) -> (Value, Value) {
    use onlyalpha_backend::application::{factor_content, private_assets::authoring::Draft};
    let draft =
        factor_content::preview(candidate, "private.factor.volume_momentum").unwrap()["draft"]
            .clone();
    let revision = Draft::new(draft.clone()).unwrap().revision().unwrap();
    (draft, revision)
}

#[test]
fn presentation_does_not_rewrite_content_identity_and_graph_does_not_prove_source_identity() {
    let r = reference();
    let first = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    let mut candidate = r["candidate"].clone();
    candidate["name"] = json!("另一名称");
    candidate["purpose"] = json!("修改用途说明");
    let renamed = compile(&candidate, &r["draft"], &r["revision"]).unwrap();
    assert_eq!(first.fingerprint(), renamed.fingerprint());
    candidate["expression"]["op"] = json!("div");
    let (draft, revision) = from_candidate(&candidate);
    let changed = compile(&candidate, &draft, &revision).unwrap();
    assert_eq!(first.graph().fingerprint(), changed.graph().fingerprint());
    assert_ne!(first.fingerprint(), changed.fingerprint());
    assert_ne!(first.revision_fingerprint(), changed.revision_fingerprint());
}

#[test]
fn declared_history_is_shared_and_one_bar_rolling_boundaries_are_exact() {
    let mut candidate = reference()["candidate"].clone();
    candidate["expression"] =
        json!({"op":"add","left":{"input":"close","lag":1},"right":{"input":"close","lag":1}});
    let (draft, revision) = from_candidate(&candidate);
    let c = compile(&candidate, &draft, &revision).unwrap();
    assert_eq!(c.graph().ordered_nodes().count(), 2);
    assert_eq!(c.required_history_bars(), 1);
    candidate["expression"] = json!({"input":"volume","mean":1});
    let (draft, revision) = from_candidate(&candidate);
    let c = compile(&candidate, &draft, &revision).unwrap();
    assert_eq!(c.required_history_bars(), 0);
    assert_eq!(c.columns(), &["volume".to_string()]);
    let window = c
        .window(Window {
            start_ns: 0,
            end_ns: 100,
            bar_ns: 1,
            horizon_bars: 1,
        })
        .unwrap();
    assert_eq!(
        window.to_record()["dataset_columns"],
        json!(["close", "volume"])
    );
}

#[test]
fn exact_parent_is_preserved_without_latest_rebasing() {
    use onlyalpha_backend::application::private_assets::authoring::Draft;
    let r = reference();
    let first = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    let mut draft = r["draft"].clone();
    draft["base_revision_fingerprint"] = r["revision"]["revision_fingerprint"].clone();
    let child = Draft::new(draft.clone()).unwrap().revision().unwrap();
    assert!(compile(&r["candidate"], &draft, &r["revision"]).is_err());
    let prepared = compile(&r["candidate"], &draft, &child).unwrap();
    assert_eq!(first.graph().fingerprint(), prepared.graph().fingerprint());
    assert_ne!(first.fingerprint(), prepared.fingerprint());
}

#[test]
fn future_features_and_undeclared_candidate_fields_are_not_compiled() {
    let r = reference();
    let mut candidate = r["candidate"].clone();
    candidate["expression"] = json!({"input":"future"});
    assert!(compile(&candidate, &r["draft"], &r["revision"]).is_err());
    candidate = r["candidate"].clone();
    candidate["source_text"] = json!("unseen program");
    assert!(compile(&candidate, &r["draft"], &r["revision"]).is_err());
}

#[test]
fn constant_factor_uses_only_the_observation_axis_without_feature_history() {
    let mut candidate = reference()["candidate"].clone();
    candidate["expression"] = json!({"integer":7});
    let (draft, revision) = from_candidate(&candidate);
    let c = compile(&candidate, &draft, &revision).unwrap();
    assert_eq!(c.graph().ordered_nodes().count(), 1);
    assert_eq!(c.columns(), &["close".to_string()]);
    assert_eq!(c.required_history_bars(), 0);
    let w = c
        .window(Window {
            start_ns: 0,
            end_ns: 100,
            bar_ns: 1,
            horizon_bars: 1,
        })
        .unwrap();
    assert_eq!(w.dataset_start_ns(), 0);
    assert_eq!(w.to_record()["dataset_columns"], json!(["close"]));
    assert_eq!(w.pair_capacity(), 99);
}

#[test]
fn preparation_and_window_identity_survive_a_fresh_process() {
    let r = reference();
    let c = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    let result = format!(
        "{} {}",
        c.fingerprint(),
        c.window(Window {
            start_ns: 1000,
            end_ns: 2000,
            bar_ns: 10,
            horizon_bars: 3
        })
        .unwrap()
        .fingerprint()
    );
    if std::env::var_os("ONLYALPHA_FACTOR_PREPARATION_CHILD").is_some() {
        println!("PREPARATION={result}");
        return;
    }
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "preparation_and_window_identity_survive_a_fresh_process",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("ONLYALPHA_FACTOR_PREPARATION_CHILD", "1")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(
        String::from_utf8(out.stdout)
            .unwrap()
            .contains(&format!("PREPARATION={result}"))
    );
}

#[test]
fn an_exact_published_revision_and_explicit_strategy_bindings_share_the_original_graph() {
    use onlyalpha_backend::application::research_factor::compile_revision;
    let r = reference();
    let dependencies = json!({"close":{"input":"close","closed_only":true},
        "close_lag_20":{"input":"close","operator":"onlyalpha.operator.delay","semantic_version":"2","period":20,"closed_only":true},
        "volume":{"input":"volume","closed_only":true},
        "volume_mean_20":{"input":"volume","operator":"onlyalpha.operator.rolling_mean","semantic_version":"2","period":20,"closed_only":true}});
    let compiled = compile_revision(&r["revision"], &dependencies).unwrap();
    let original = compile(&r["candidate"], &r["draft"], &r["revision"]).unwrap();
    assert_eq!(compiled.graph().to_record(), original.graph().to_record());
    assert_eq!(compiled.fingerprint(), original.fingerprint());
    assert_eq!(
        compiled.revision_fingerprint(),
        r["revision"]["revision_fingerprint"].as_str().unwrap()
    );
    for mutation in [
        "missing-port",
        "extra-port",
        "not-closed",
        "unsupported-operator",
        "unbounded-period",
        "missing-version",
        "legacy-version",
        "semantic-version",
    ] {
        let mut bindings = dependencies.clone();
        match mutation {
            "missing-port" => {
                bindings.as_object_mut().unwrap().remove("close");
            }
            "extra-port" => {
                bindings["unexpected"] = json!({"input":"close","closed_only":true});
            }
            "not-closed" => bindings["close"]["closed_only"] = json!(false),
            "unsupported-operator" => bindings["close_lag_20"]["operator"] = json!("other.delay"),
            "unbounded-period" => bindings["close_lag_20"]["period"] = json!(u64::MAX),
            "missing-version" => {
                bindings["close_lag_20"]
                    .as_object_mut()
                    .unwrap()
                    .remove("semantic_version");
            }
            "legacy-version" => bindings["close_lag_20"]["semantic_version"] = json!("1"),
            _ => bindings["close_lag_20"]["semantic_version"] = json!("3"),
        }
        assert!(
            compile_revision(&r["revision"], &bindings).is_err(),
            "{mutation}"
        );
    }
}
