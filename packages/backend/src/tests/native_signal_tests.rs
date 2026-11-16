//! Pure graph mathematics; these fixtures grant no READY, Run or publication.
use super::*;
#[test]
fn batch_blocks_downstream_until_every_parent_is_ready() {
    let image = "f".repeat(64);
    let source =
        json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}});
    let mean = OperatorCalculation::resolve(
        "onlyalpha.operator.rolling_mean",
        "2",
        &json!({"period":{"type":"INTEGER","value":2}}),
        &source,
    )
    .unwrap();
    let predicate = |binding: Value| {
        PredicateCalculation::resolve(
            "onlyalpha.predicate.internal.compare.gt.decimal.literal",
            "1",
            &json!({"literal":{"type":"DECIMAL","value":"0"}}),
            &json!({"left":binding}),
        )
        .unwrap()
    };
    let left = predicate(
        json!({"node_fingerprint":mean.definition().fingerprint(),"output_name":"value","source":null}),
    );
    let right =
        predicate(json!({"node_fingerprint":null,"output_name":"value","source":"bar.close"}));
    let or=PredicateCalculation::resolve("onlyalpha.predicate.internal.boolean.or","1",&json!({}),&json!({"left":{"node_fingerprint":left.definition().fingerprint(),"output_name":"value","source":null},"right":{"node_fingerprint":right.definition().fingerprint(),"output_name":"value","source":null}})).unwrap();
    let mut definitions = vec![mean.definition().clone()];
    definitions.extend([
        left.definition().clone(),
        right.definition().clone(),
        or.definition().clone(),
    ]);
    let graph=Graph::from_record(&json!({"schema_version":1,"nodes":definitions.iter().map(|d|json!({"alias":null,"definition":d.to_record()})).collect::<Vec<_>>()}),8*1024*1024).unwrap();
    let mut bindings = Vec::new();
    for (d, research, trading) in std::iter::once((
        mean.definition(),
        mean.implementation_manifest("RESEARCH", &image).unwrap(),
        mean.implementation_manifest("TRADING", &image).unwrap(),
    ))
    .chain([&left, &right, &or].into_iter().map(|c| {
        (
            c.definition(),
            c.implementation_manifest("RESEARCH", &image).unwrap(),
            c.implementation_manifest("TRADING", &image).unwrap(),
        )
    })) {
        bindings.push(json!({"node_fingerprint":d.fingerprint(),"research_implementation_fingerprint":research["implementation_fingerprint"],"trading_implementation_fingerprint":trading["implementation_fingerprint"]}));
    }
    let programs = SignalPrograms::new(&graph, &[], &json!(bindings), &image).unwrap();
    let output = programs
        .batch(
            &graph,
            &json!([{"at_ns":"1","values":{"close":"1"}},{"at_ns":"2","values":{"close":"3"}}]),
            || Ok(()),
        )
        .unwrap();
    let values = output
        .as_array()
        .unwrap()
        .iter()
        .find(|n| n["node_fingerprint"] == or.definition().fingerprint())
        .unwrap();
    assert_eq!(
        values["values"]["value"],
        json!([null, true]),
        "OR cannot turn an unexecuted upstream into a computed true"
    );
    let completed = programs
        .complete_batch(
            &graph,
            &json!([{"at_ns":"1","values":{"close":"1"}},{"at_ns":"2","values":{"close":"3"}}]),
            || Ok(()),
        )
        .unwrap();
    assert_eq!(completed.values(), &output);
    assert_eq!(
        completed.evidence()["contract"],
        "NATIVE_GRAPH_BATCH_COMPLETED_V1"
    );
    assert_eq!(completed.evidence()["graph"], graph.fingerprint());
    for implementation in completed.evidence()["implementations"].as_array().unwrap() {
        assert_eq!(implementation["backend_kind"], "RESEARCH");
        let original = bindings
            .iter()
            .find(|b| {
                b["research_implementation_fingerprint"]
                    == implementation["implementation_fingerprint"]
            })
            .unwrap();
        assert_ne!(
            implementation["implementation_fingerprint"],
            original["trading_implementation_fingerprint"]
        );
    }
    assert!(
        programs
            .complete_batch(
                &graph,
                &json!([{"at_ns":"1","values":{"close":"1"}}]),
                || Err("OWNER_CANCELLED")
            )
            .is_err()
    );
    let mut calls = 0;
    assert!(
        programs
            .batch(
                &graph,
                &json!([{"at_ns":"1","values":{"close":"1"}}]),
                || {
                    calls += 1;
                    Err("OWNER_CANCELLED")
                }
            )
            .is_err()
    );
    assert_eq!(calls, 1);
}

#[test]
fn batch_provenance_uses_the_completed_result_content_budget() {
    // Pure payload values grant no READY or completed job. Inputs and outputs
    // can exceed factor metadata's 8 MiB while fitting the result contract.
    for key in ["input_rows", "output_columns"] {
        let value = json!({key: "x".repeat(9 * 1024 * 1024)});
        let expected = crate::persistence::job_publication::content_fingerprint(&value).unwrap();
        assert_eq!(batch_content_fingerprint(&value).unwrap(), expected);
    }
}
