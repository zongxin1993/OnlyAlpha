//! Adversarial relations at the same private validators used by native composition.
use super::*;
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf};
struct Fixture(PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        for p in [
            &self.0,
            &self.0.join("lib"),
            &self.0.join("lib/site-packages"),
            &self.0.join("bin"),
        ] {
            let _ = fs::set_permissions(p, fs::Permissions::from_mode(0o755));
        }
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn fixture() -> (Fixture, ChartQuery, Value) {
    let root = std::env::temp_dir().join(format!("chart-admission-{}", std::process::id()));
    fs::create_dir(&root).unwrap();
    fs::create_dir_all(root.join("lib/site-packages")).unwrap();
    fs::create_dir(root.join("bin")).unwrap();
    for name in [
        "lib/site-packages/math.py",
        "bin/python",
        "pyvenv.cfg",
        "runtime1",
        "runtime2",
        "runtime3",
    ] {
        fs::write(root.join(name), name).unwrap();
        fs::set_permissions(root.join(name), fs::Permissions::from_mode(0o444)).unwrap();
    }
    let runtime: serde_json::Map<String, Value> = ["runtime1", "runtime2", "runtime3"]
        .into_iter()
        .map(|name| {
            (
                root.join(name).to_str().unwrap().into(),
                json!(hash(name.as_bytes())),
            )
        })
        .collect();
    let installation = json!({"schema_version":1,"kind":"ONLYALPHA_ALGORITHM_INSTALLATION","distribution_version":"1","environment_files":{"pyvenv.cfg":hash(b"pyvenv.cfg")},"runtime_files":runtime,"files":{"lib/site-packages/math.py":hash(b"lib/site-packages/math.py")},"interpreter_sha256":hash(b"bin/python")});
    let bytes = installation.to_string();
    fs::write(root.join("algorithm-installation.json"), &bytes).unwrap();
    fs::set_permissions(
        root.join("algorithm-installation.json"),
        fs::Permissions::from_mode(0o444),
    )
    .unwrap();
    for name in ["lib/site-packages", "lib", "bin"] {
        fs::set_permissions(root.join(name), fs::Permissions::from_mode(0o555)).unwrap();
    }
    let query =
        ChartQuery::new(ChartInstallation::open(&root, &hash(bytes.as_bytes())).unwrap()).unwrap();
    let v: Value = serde_json::from_str(include_str!("admission-vector.json")).unwrap();
    let d = &v["descriptor"];
    let values=d["parameters"].as_array().unwrap().iter().map(|p| {
        let scalar=|v:&Value|json!({"type":if v.is_null(){"NULL"}else{p["parameter_type"].as_str().unwrap()},"value":v});
        json!({"default":scalar(&p["default"]),"minimum":scalar(&p["minimum"]),"maximum":scalar(&p["maximum"]),"enum_values":p["enum_values"].as_array().unwrap().iter().map(scalar).collect::<Vec<_>>()})
    }).collect::<Vec<_>>();
    let m = manifest(
        json!({"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]}),
        json!([{"relative_path":"math.py","byte_sha256":hash(b"lib/site-packages/math.py")}]),
        json!([]),
        "controlled:math",
    )
    .unwrap();
    let row = json!({"schema_version":1,"descriptor":d,"parameter_values":values,"implementation_fingerprint":m["implementation_fingerprint"],"implementation":m,"artifact_fingerprint":"a".repeat(64),"numeric_binding":v["numeric_execution_binding"],"support":v["presentation"]});
    (
        Fixture(root),
        query,
        json!({"artifact_fingerprint":"a".repeat(64),"entries":[row]}),
    )
}
#[test]
fn fixed_catalog_rechecks_every_installation_proof_and_preserves_identity() {
    let (fixture, query, catalog) = fixture();
    query.admit_catalog(&catalog).unwrap();
    query.check_catalog(&catalog, true).unwrap();
    let read = || query.registered_capabilities_before(Instant::now() + Duration::from_secs(10));
    // This fixture's interpreter is deliberately not executable. A retained
    // declaration does not promise current worker availability.
    let expected = read().unwrap();
    for name in [
        "algorithm-installation.json",
        "bin/python",
        "pyvenv.cfg",
        "runtime1",
        "runtime2",
        "runtime3",
        "lib/site-packages/math.py",
    ] {
        let path = fixture.0.join(name);
        let bytes = fs::read(&path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        fs::write(&path, b"changed").unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o444)).unwrap();
        assert!(read().is_err(), "changed {name}");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        fs::write(&path, &bytes).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o444)).unwrap();
        assert_eq!(read().unwrap(), expected, "restored {name}");
    }
    let path = fixture.0.join("lib/site-packages/math.py");
    fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o755)).unwrap();
    let saved = path.with_extension("saved");
    fs::rename(&path, &saved).unwrap();
    assert!(read().is_err(), "missing exact resource");
    fs::rename(&saved, &path).unwrap();
    fs::set_permissions(path.parent().unwrap(), fs::Permissions::from_mode(0o555)).unwrap();
    assert_eq!(read().unwrap(), expected);
    let permit = query.slot.clone().try_acquire_owned().unwrap();
    assert_eq!(read().unwrap(), expected);
    let second = query.slot.clone().try_acquire_owned().unwrap();
    assert!(matches!(read(), Err(Error::Capacity)));
    drop(permit);
    assert_eq!(read().unwrap(), expected);
    drop(second);
    assert!(
        query
            .registered_capabilities_before(Instant::now())
            .is_err()
    );
    query.close().unwrap();
    assert!(read().is_err());
}

#[test]
fn fixed_catalog_conflicts_are_atomic_and_never_replace_the_original() {
    let (_fixture, query, catalog) = fixture();
    let query = Arc::new(query);
    let barrier = Arc::new(std::sync::Barrier::new(3));
    let mut other = catalog.clone();
    other["artifact_fingerprint"] = json!("b".repeat(64));
    other["entries"][0]["artifact_fingerprint"] = json!("b".repeat(64));
    query.admit_catalog(&other).unwrap();
    let handles = [catalog.clone(), other]
        .into_iter()
        .map(|observed| {
            let query = query.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                query.check_catalog(&observed, true).is_ok()
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();
    assert_eq!(
        handles
            .into_iter()
            .map(|h| h.join().unwrap() as usize)
            .sum::<usize>(),
        1
    );
    assert!(query.check_catalog(&catalog, true).is_err());
    assert!(
        query
            .registered_capabilities_before(Instant::now() + Duration::from_secs(10))
            .is_err()
    );
}

#[test]
fn fixed_catalog_never_mixes_another_native_invocation() {
    let (_fixture, mut query, catalog) = fixture();
    query.check_catalog(&catalog, true).unwrap();
    let original = query.invocation.clone();
    query.invocation["implementation_fingerprint"] = json!("b".repeat(64));
    assert!(
        query
            .registered_capabilities_before(Instant::now() + Duration::from_secs(10))
            .is_err()
    );
    assert!(query.check_catalog(&catalog, false).is_err());
    query.invocation = original;
    assert!(query.check_catalog(&catalog, false).is_err());
}
#[test]
fn catalog_resolver_and_result_mutations_are_rejected_by_native_admission() {
    let (_fixture, query, good) = fixture();
    let admitted = query.admit_catalog(&good).unwrap();
    for case in 0..10 {
        let mut bad = good.clone();
        match case {
            0 => {
                bad["entries"]
                    .as_array_mut()
                    .unwrap()
                    .push(good["entries"][0].clone());
            }
            1 => bad["entries"][0]["descriptor"]["kind"] = json!("FACTOR"),
            2 => bad["entries"][0]["descriptor"]["parameters"][0]["default"] = json!(true),
            3 => bad["entries"][0]["implementation_fingerprint"] = json!("b".repeat(64)),
            4 => {
                bad["entries"][0]["implementation"]["resources"][0]["byte_sha256"] =
                    json!("b".repeat(64))
            }
            5 => bad["entries"][0]["numeric_binding"]["precision"] = json!(38),
            6 => {
                bad["entries"][0]["numeric_binding"]["core_policy_fingerprint"] =
                    json!("b".repeat(64))
            }
            7 => bad["entries"][0]["support"]["series"][0]["output_name"] = json!("unknown"),
            8 => bad["entries"][0]["artifact_fingerprint"] = json!("b".repeat(64)),
            _ => bad["entries"][0]["extra"] = json!(1),
        }
        assert!(query.admit_catalog(&bad).is_err(), "catalog case {case}");
    }
    let entry = admitted.values().next().unwrap();
    let record: Value = serde_json::from_str(include_str!("admission-definition.json")).unwrap();
    let candidate = Definition::from_record(&record, WORK).unwrap();
    let good_resolved =
        json!({"definition":record,"definition_fingerprint":candidate.fingerprint()});
    let definition = resolved_definition(entry, &good_resolved).unwrap();
    for case in 0..10 {
        let mut bad = good_resolved.clone();
        match case {
            0 => bad["definition"]["type_id"] = json!("other"),
            1 => bad["definition"]["numeric"]["precision"] = json!(38),
            2 => bad["definition"]["input_bindings"]["value"]["source"] = json!("node.output"),
            3 => bad["definition"]["warmup"]["minimum_observations"] = json!(10001),
            4 => bad["definition"]["outputs"][0]["nullable"] = json!(false),
            5 => bad["definition"]["parameters"]["period"] = json!({"type":"BOOLEAN","value":true}),
            6 => bad["definition_fingerprint"] = json!("b".repeat(64)),
            7 => bad["definition_fingerprint"] = json!(42),
            8 => bad["unexpected"] = json!(true),
            _ => {
                bad.as_object_mut().unwrap().remove("definition");
            }
        }
        // Coherent new fingerprints must not hide an invalid descriptor relation.
        if case < 6
            && let Ok(d) = Definition::from_record(&bad["definition"], WORK)
        {
            bad["definition_fingerprint"] = json!(d.fingerprint());
        }
        assert!(
            matches!(resolved_definition(entry, &bad), Err(Error::Unavailable)),
            "resolve case {case}"
        );
    }
    let declaration = entry.declaration.to_record();
    let artifact = json!("a".repeat(64));
    let input = "c".repeat(64);
    let result = json!({"type_declaration":declaration,"artifact_fingerprint":artifact,"input_fingerprint":input,"definition":definition.to_record(),"definition_fingerprint":definition.fingerprint(),"implementation_fingerprint":entry.capability["implementation_fingerprint"],"outputs":{"value":{"values":["1.000000000000"],"states":["PARTIAL"],"reasons":["WARMUP_INCOMPLETE"]}}});
    execution_result(
        &result,
        &declaration,
        &artifact,
        &input,
        &definition,
        &entry.capability,
        1,
    )
    .unwrap();
    for case in 0..10 {
        let mut bad = result.clone();
        match case {
            0 => bad["type_declaration"]["descriptor"]["semantic_version"] = json!("9"),
            1 => bad["artifact_fingerprint"] = json!("b".repeat(64)),
            2 => bad["input_fingerprint"] = json!("b".repeat(64)),
            3 => bad["definition_fingerprint"] = json!("b".repeat(64)),
            4 => bad["implementation_fingerprint"] = json!("b".repeat(64)),
            5 => bad["outputs"]["extra"] = bad["outputs"]["value"].clone(),
            6 => bad["outputs"]["value"]["values"] = json!([]),
            7 => bad["outputs"]["value"]["states"] = json!(["READY"]),
            8 => bad["outputs"]["value"]["values"] = json!(["1e0"]),
            _ => bad["outputs"]["value"]["reasons"] = json!(["VALUE_UNDEFINED"]),
        }
        assert!(
            execution_result(
                &bad,
                &declaration,
                &artifact,
                &input,
                &definition,
                &entry.capability,
                1
            )
            .is_err(),
            "result case {case}"
        );
    }
}
