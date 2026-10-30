use onlyalpha_backend::persistence::research_runtime::RuntimeInputHold;
use serde_json::Value;
use std::{fs, process::Command};
fn fixture(root: &std::path::Path) -> String {
    let out = Command::new("python")
        .arg(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/application/support/research_runtime_reference.py"),
        )
        .arg(root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let v: Value = serde_json::from_slice(&out.stdout).unwrap();
    v["generation"].as_str().unwrap().into()
}
#[test]
fn existing_writer_binding_is_exact_and_lock_is_retained() {
    let root = std::env::temp_dir().join(format!("research-runtime-{}", {
        let mut bytes = [0_u8; 16];
        getrandom::fill(&mut bytes).unwrap();
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    }));
    let g = fixture(&root);
    let h = RuntimeInputHold::open(&root, "work", "research", &g).unwrap();
    assert_eq!(h.manifest()["runtime_generation_fingerprint"], g);
    assert_eq!(h.binding()["work_id"], "work");
    h.verify().unwrap();
    for (work, owner, generation) in [
        ("other", "research", g.as_str()),
        ("work", "other", g.as_str()),
        ("work", "research", &"f".repeat(64)),
    ] {
        assert!(RuntimeInputHold::open(&root, work, owner, generation).is_err());
    }
    let fd = fs::File::open(root.join(".generation-authority.lock")).unwrap();
    assert!(rustix::fs::flock(&fd, rustix::fs::FlockOperation::NonBlockingLockExclusive).is_err());
    drop(h);
    rustix::fs::flock(&fd, rustix::fs::FlockOperation::NonBlockingLockExclusive).unwrap();
    drop(fd);
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn truncated_or_replaced_ledger_never_becomes_eligible() {
    let root = std::env::temp_dir().join(format!("research-runtime-{}", {
        let mut bytes = [0_u8; 16];
        getrandom::fill(&mut bytes).unwrap();
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    }));
    let g = fixture(&root);
    let hold = RuntimeInputHold::open(&root, "work", "research", &g).unwrap();
    let ledger = root.join("generation-events.jsonl");
    let raw = fs::read(&ledger).unwrap();
    fs::write(&ledger, &raw[..raw.len() - 1]).unwrap();
    assert!(hold.verify().is_err());
    assert!(RuntimeInputHold::open(&root, "work", "research", &g).is_err());
    drop(hold);
    fs::remove_dir_all(root).unwrap();
}

fn rehash(root: &std::path::Path, original: &str, mutate: impl FnOnce(&mut Value)) -> String {
    use onlyalpha_backend::application::factor_content::hash;
    let path = root.join(format!("runtime-generations/{original}.json"));
    let mut manifest: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    mutate(&mut manifest);
    manifest
        .as_object_mut()
        .unwrap()
        .remove("runtime_generation_fingerprint");
    let generation = hash(&manifest).unwrap();
    manifest["runtime_generation_fingerprint"] = generation.clone().into();
    fs::write(
        root.join(format!("runtime-generations/{generation}.json")),
        manifest.to_string(),
    )
    .unwrap();
    let mut validation: Value = serde_json::from_slice(
        &fs::read(root.join(format!("runtime-generation-validation/{original}.json"))).unwrap(),
    )
    .unwrap();
    validation["runtime_generation_fingerprint"] = generation.clone().into();
    validation["core_execution_fingerprint"] = hash(&manifest["core_execution"]).unwrap().into();
    for k in ["providers", "implementations", "private_factor_bindings"] {
        validation[k] = manifest[k].clone();
    }
    validation
        .as_object_mut()
        .unwrap()
        .remove("validation_evidence_fingerprint");
    let vp = hash(&validation).unwrap();
    validation["validation_evidence_fingerprint"] = vp.clone().into();
    fs::write(
        root.join(format!("runtime-generation-validation/{generation}.json")),
        validation.to_string(),
    )
    .unwrap();
    let mut prior = Value::Null;
    let records: Vec<_> = fs::read_to_string(root.join("generation-events.jsonl"))
        .unwrap()
        .lines()
        .map(|line| {
            let mut e: Value = serde_json::from_str(line).unwrap();
            e["generation_fingerprint"] = generation.clone().into();
            e["previous_event_fingerprint"] = prior.clone();
            if e["kind"] == "GenerationValidated" {
                e["validation_evidence_fingerprint"] = vp.clone().into();
            }
            e.as_object_mut().unwrap().remove("event_fingerprint");
            prior = hash(&e).unwrap().into();
            e["event_fingerprint"] = prior.clone();
            e.to_string() + "\n"
        })
        .collect();
    fs::write(root.join("generation-events.jsonl"), records.concat()).unwrap();
    generation
}
#[test]
fn self_consistent_rehash_cannot_admit_invalid_nested_contracts() {
    use serde_json::json;
    for case in [
        "empty-providers",
        "duplicate-provider",
        "bad-core",
        "extra-core",
        "bad-implementation",
        "duplicate-implementation",
        "bad-private-entry",
    ] {
        let mut bytes = [0; 16];
        getrandom::fill(&mut bytes).unwrap();
        let root = std::env::temp_dir().join(format!("research-nested-{bytes:?}"));
        let g = fixture(&root);
        let g = rehash(&root, &g, |m| match case {
            "empty-providers" => m["providers"] = json!([]),
            "duplicate-provider" => {
                let p = m["providers"][0].clone();
                m["providers"].as_array_mut().unwrap().push(p)
            }
            "bad-core" => m["core_execution"]["distribution_name"] = json!("../outside"),
            "extra-core" => m["core_execution"]["ignored"] = json!(true),
            "bad-implementation" => {
                m["implementations"] = json!([{"kind":"FACTOR","type_id":"bad/id","semantic_version":"1","backend":"RESEARCH","implementation_fingerprint":"a".repeat(64)}])
            }
            "duplicate-implementation" => {
                let i = json!({"kind":"FACTOR","type_id":"fixture","semantic_version":"1","backend":"RESEARCH","implementation_fingerprint":"a".repeat(64)});
                m["implementations"] = json!([i, i]);
            }
            _ => {
                m["private_factor_bindings"] = json!([{"provider_snapshot_fingerprint":"a".repeat(64),"runtime_artifact_fingerprint":"b".repeat(64),"entry":{}}])
            }
        });
        assert!(
            RuntimeInputHold::open(&root, "work", "research", &g).is_err(),
            "accepted {case}"
        );
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn rehashed_event_alias_and_nested_types_preserve_original_dto_rules() {
    use onlyalpha_backend::application::factor_content::hash;
    for case in [
        "time-alias",
        "redundant-micros",
        "bad-expected",
        "bad-reason",
    ] {
        let mut bytes = [0; 16];
        getrandom::fill(&mut bytes).unwrap();
        let root = std::env::temp_dir().join(format!("event-types-{bytes:?}"));
        let g = fixture(&root);
        let mut prior = Value::Null;
        let records: Vec<_> = fs::read_to_string(root.join("generation-events.jsonl"))
            .unwrap()
            .lines()
            .enumerate()
            .map(|(i, line)| {
                let mut e: Value = serde_json::from_str(line).unwrap();
                if i == 0 {
                    match case {
                        "time-alias" => e["occurred_at"] = "2026-10-29T00:00:00Z".into(),
                        "redundant-micros" => {
                            e["occurred_at"] = "2026-10-29T00:00:00.000000+00:00".into()
                        }
                        "bad-expected" => e["expected_current"] = "not-a-sha".into(),
                        _ => e["reason"] = serde_json::json!({}),
                    }
                }
                e["previous_event_fingerprint"] = prior.clone();
                e.as_object_mut().unwrap().remove("event_fingerprint");
                prior = hash(&e).unwrap().into();
                e["event_fingerprint"] = prior.clone();
                e.to_string() + "\n"
            })
            .collect();
        fs::write(root.join("generation-events.jsonl"), records.concat()).unwrap();
        assert!(
            RuntimeInputHold::open(&root, "work", "research", &g).is_err(),
            "accepted {case}"
        );
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn draining_work_survives_other_closed_retired_and_rejected_histories() {
    let mut bytes = [0; 16];
    getrandom::fill(&mut bytes).unwrap();
    let root = std::env::temp_dir().join(format!("runtime-history-{bytes:?}"));
    let out = Command::new("python")
        .arg(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/application/support/research_runtime_reference.py"),
        )
        .arg(&root)
        .arg("histories")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let v: Value = serde_json::from_slice(&out.stdout).unwrap();
    let g = v["generation"].as_str().unwrap();
    let h = RuntimeInputHold::open(&root, "work", "research", g).unwrap();
    h.verify().unwrap();
    assert_eq!(h.manifest()["runtime_generation_fingerprint"], g);
    assert!(RuntimeInputHold::open(&root, "other", "research", g).is_err());
    drop(h);
    fs::remove_dir_all(root).unwrap();
}
