use onlyalpha_calculation::{Backend, Definition, Graph, Registry, TypeDefinition, TypeReference};
use serde_json::{Value, json};
fn sample() -> Value {
    serde_json::from_str::<Value>(
        include_str!("../../../../test-data/calculation/definitions-v1.jsonl")
            .lines()
            .next()
            .unwrap(),
    )
    .unwrap()["record"]
        .clone()
}
fn types(version: &str) -> TypeDefinition {
    let mut v = sample();
    v.as_object_mut().unwrap().remove("parameters");
    v.as_object_mut().unwrap().remove("input_bindings");
    v.as_object_mut().unwrap().remove("warmup");
    v.as_object_mut().unwrap().remove("extensions");
    v["schema_version"] = json!(1);
    v["semantic_version"] = json!(version);
    v["parameters"] = json!([]);
    v["execution_shape"] = json!("TIME_SERIES");
    TypeDefinition::from_record(&v).unwrap()
}
fn pair() -> (Definition, Definition) {
    let a = Definition::from_record(&sample()).unwrap();
    let mut b = sample();
    b["type_id"] = json!("example.child");
    b["input_bindings"]["close"] =
        json!({"node_fingerprint":a.fingerprint(),"source":null,"output_name":"value"});
    (a, Definition::from_record(&b).unwrap())
}
#[test]
fn graph_orders_dependencies_and_excludes_only_aliases() {
    let (a, b) = pair();
    let g = Graph::new(vec![
        (b.clone(), Some("child".into())),
        (a.clone(), Some("root".into())),
    ])
    .unwrap();
    assert_eq!(g.ordered_nodes(), vec![&a, &b]);
    let h = Graph::new(vec![(a.clone(), None), (b.clone(), Some("other".into()))]).unwrap();
    assert_eq!(g.fingerprint(), h.fingerprint());
    assert_ne!(g.to_record(), h.to_record());
    assert_eq!(Graph::from_record(&g.to_record()).unwrap(), g);
    assert!(Graph::new(vec![(a.clone(), None), (a, None)]).is_err());
    assert!(Graph::new(vec![(b, None)]).is_err());
}
#[test]
fn graph_enforces_every_port_axis_and_target_separation() {
    let (a, b) = pair();
    for (key, value) in [
        ("data_type", json!("INTEGER")),
        ("dimensions", json!(["ASSET"])),
        ("semantic_type", json!("RETURN")),
        ("unit", json!("EUR")),
    ] {
        let mut record = b.to_record();
        record["inputs"][0][key] = value;
        let changed = Definition::from_record(&record).unwrap();
        assert!(
            Graph::new(vec![(a.clone(), None), (changed, None)]).is_err(),
            "{key}"
        );
    }
    let mut root = a.to_record();
    root["outputs"][0]["nullable"] = json!(true);
    let root = Definition::from_record(&root).unwrap();
    let mut child = b.to_record();
    child["input_bindings"]["close"]["node_fingerprint"] = json!(root.fingerprint());
    assert!(
        Graph::new(vec![
            (root, None),
            (Definition::from_record(&child).unwrap(), None)
        ])
        .is_err()
    );
    let mut target = a.to_record();
    target["kind"] = json!("TARGET");
    assert!(
        Graph::new(vec![
            (a, None),
            (Definition::from_record(&target).unwrap(), None)
        ])
        .is_err()
    );
}
#[test]
fn predicate_operand_wildcard_does_not_coerce_dtype() {
    let (a, b) = pair();
    let mut b = b.to_record();
    b["inputs"][0]["semantic_type"] = json!("PREDICATE_OPERAND");
    b["inputs"][0]["unit"] = json!("OTHER");
    assert!(
        Graph::new(vec![
            (a.clone(), None),
            (Definition::from_record(&b).unwrap(), None)
        ])
        .is_ok()
    );
    b["inputs"][0]["data_type"] = json!("STRING");
    assert!(
        Graph::new(vec![
            (a, None),
            (Definition::from_record(&b).unwrap(), None)
        ])
        .is_err()
    );
}
#[test]
fn graph_rejects_output_alias_and_schema_malformations() {
    let (a, b) = pair();
    assert!(
        Graph::new(vec![
            (a.clone(), Some("same".into())),
            (b.clone(), Some("same".into()))
        ])
        .is_err()
    );
    let mut bad = b.to_record();
    bad["input_bindings"]["close"]["output_name"] = json!("absent");
    assert!(
        Graph::new(vec![
            (a, None),
            (Definition::from_record(&bad).unwrap(), None)
        ])
        .is_err()
    );
    assert!(Graph::from_record(&json!({"schema_version":true,"nodes":[]})).is_err());
    assert!(Graph::from_record(&json!({"schema_version":1,"nodes":[],"ready":true})).is_err());
    assert!(Graph::new(vec![]).is_ok());
}
#[test]
fn registry_exact_lookup_stable_introspection_and_atomic_conflicts() {
    let mut r = Registry::new();
    let t = types("1");
    let reference = t.reference().clone();
    r.register(t.clone(), Backend::Trading, 7).unwrap();
    r.register(t.clone(), Backend::Research, 8).unwrap();
    r.register(types("2"), Backend::Trading, 9).unwrap();
    assert_eq!(
        *r.resolve(&reference, Backend::Trading).unwrap().provider(),
        7
    );
    assert_eq!(
        *r.resolve(&reference, Backend::Research).unwrap().provider(),
        8
    );
    assert_eq!(r.resolve_type(&reference).unwrap(), &t);
    assert!(r.register(t, Backend::Trading, 99).is_err());
    let before = r.registrations().len();
    let mut changed = types("2").to_record();
    changed["numeric"]["precision"] = json!(29);
    assert!(
        r.register(
            TypeDefinition::from_record(&changed).unwrap(),
            Backend::Research,
            100
        )
        .is_err()
    );
    assert_eq!(r.registrations().len(), before);
    assert_eq!(r.types().len(), 2);
    assert!(
        r.resolve(
            &TypeReference::new("INDICATOR", "example.mean", "3").unwrap(),
            Backend::Trading
        )
        .is_err()
    );
    assert!(
        r.resolve(
            &TypeReference::new("INDICATOR", "example.other", "1").unwrap(),
            Backend::Trading
        )
        .is_err()
    );
    assert!(
        r.resolve(
            &TypeReference::new("INDICATOR", "example.mean", "2").unwrap(),
            Backend::Research
        )
        .is_err()
    );
}
#[test]
fn iterative_deep_graph_is_deterministic() {
    let mut nodes = vec![];
    let mut previous = None;
    for i in 0..600 {
        let mut record = sample();
        record["semantic_version"] = json!(i.to_string());
        if let Some(hash) = previous {
            record["input_bindings"]["close"] =
                json!({"node_fingerprint":hash,"output_name":"value","source":null});
        }
        let d = Definition::from_record(&record).unwrap();
        previous = Some(d.fingerprint());
        nodes.push((d, None));
    }
    let forward = Graph::new(nodes.clone()).unwrap();
    nodes.reverse();
    assert_eq!(
        forward.fingerprint(),
        Graph::new(nodes).unwrap().fingerprint()
    );
}
