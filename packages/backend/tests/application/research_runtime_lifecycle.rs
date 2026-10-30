use onlyalpha_backend::{application::command::CommandId, persistence::research_runtime::Registry};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::Value;
use std::path::Path;
use std::{fs, path::PathBuf, process::Command};

fn fixture() -> (PathBuf, String, String) {
    let mut entropy = [0; 16];
    getrandom::fill(&mut entropy).unwrap();
    let root = std::env::temp_dir().join(format!("runtime-lifecycle-{entropy:?}"));
    let out = Command::new("python")
        .arg(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/application/support/research_runtime_reference.py"),
        )
        .arg(&root)
        .arg("ready")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let value: Value = serde_json::from_slice(&out.stdout).unwrap();
    (
        root,
        value["generation"].as_str().unwrap().into(),
        value["ready"].as_str().unwrap().into(),
    )
}
fn at() -> OnlyUtcDateTime {
    "2026-10-29T01:00:00.123400Z".parse().unwrap()
}
fn id() -> CommandId {
    CommandId::new("00000000-0000-4000-8000-000000000901").unwrap()
}

#[test]
fn read_only_inspection_shares_the_original_work_lock_without_admitting_new_work() {
    let (root, original, _) = fixture();
    let mut writer = Registry::open_existing(&root).unwrap();
    writer
        .bind_new_work_exact(
            "inspection-work",
            &original,
            "research",
            "local-developer",
            at(),
        )
        .unwrap();
    let expected = writer.snapshot();
    drop(writer);
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    let hold = onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
        &root,
        "inspection-work",
        "research",
        &original,
    )
    .unwrap();
    assert!(Registry::open_existing(&root).is_err());
    assert_eq!(Registry::inspect(&root).unwrap(), expected);
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(hold);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn explicit_activation_and_binding_survive_fresh_readers_without_retargeting_old_work() {
    let (root, original, target) = fixture();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    let mut store = Registry::open_existing(&root).unwrap();
    assert_eq!(store.snapshot()["active_for_new_work"], original);
    let receipt = store
        .activate(&id(), &target, Some(&original), "local-developer", at())
        .unwrap();
    assert_eq!(store.snapshot()["active_for_new_work"], target);
    let binding = store
        .bind_new_work_exact("new-work", &target, "research", "local-developer", at())
        .unwrap();
    assert_eq!(binding["generation_fingerprint"], target);
    drop(store);
    let mut store = Registry::open_existing(&root).unwrap();
    assert_eq!(
        store
            .activate(&id(), &target, Some(&original), "local-developer", at())
            .unwrap(),
        receipt
    );
    assert_eq!(
        store
            .bind_new_work_exact("new-work", &target, "research", "local-developer", at())
            .unwrap(),
        binding
    );
    let after = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert!(after.starts_with(&before));
    assert_eq!(
        after.split(|b| *b == b'\n').count(),
        before.split(|b| *b == b'\n').count() + 2
    );
    assert_eq!(store.snapshot()["states"][&original], "DRAINING");
    drop(store);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn stale_activation_and_conflicting_work_binding_preserve_the_original_journal() {
    let (root, original, target) = fixture();
    let mut store = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        store
            .activate(&id(), &target, None, "local-developer", at())
            .unwrap_err(),
        "GENERATION_ACTIVATION_CONFLICT"
    );
    assert_eq!(
        store
            .activate(
                &id(),
                &"f".repeat(64),
                Some(&original),
                "local-developer",
                at()
            )
            .unwrap_err(),
        "RUNTIME_GENERATION_NOT_READY"
    );
    assert_eq!(
        store
            .bind_new_work_exact("unbound", &target, "research", "local-developer", at())
            .unwrap_err(),
        "RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"
    );
    assert_eq!(
        store
            .bind_new_work_exact("work", &original, "other", "local-developer", at())
            .unwrap_err(),
        "RUNTIME_WORK_GENERATION_BINDING_CONFLICT"
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(store);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn original_activation_replay_after_another_switch_never_reactivates_the_old_target() {
    let (root, original, target) = fixture();
    let mut store = Registry::open_existing(&root).unwrap();
    let receipt = store
        .activate(&id(), &target, Some(&original), "local-developer", at())
        .unwrap();
    let next = CommandId::new("00000000-0000-4000-8000-000000000902").unwrap();
    store
        .activate(&next, &original, Some(&target), "local-developer", at())
        .unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        store
            .activate(&id(), &target, Some(&original), "local-developer", at())
            .unwrap(),
        receipt
    );
    assert_eq!(store.snapshot()["active_for_new_work"], original);
    assert_eq!(
        store
            .activate(&id(), &original, Some(&target), "local-developer", at())
            .unwrap_err(),
        "RUNTIME_GENERATION_COMMAND_CONFLICT"
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(store);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn original_lock_and_root_identity_cannot_be_bypassed_by_the_native_writer() {
    let (root, original, target) = fixture();
    let lock = fs::File::open(root.join(".generation-authority.lock")).unwrap();
    rustix::fs::flock(&lock, rustix::fs::FlockOperation::NonBlockingLockShared).unwrap();
    assert!(Registry::open_existing(&root).is_err());
    drop(lock);
    let mut store = Registry::open_existing(&root).unwrap();
    let held = root.with_extension("held");
    fs::rename(&root, &held).unwrap();
    fs::create_dir(&root).unwrap();
    let before = fs::read(held.join("generation-events.jsonl")).unwrap();
    assert!(
        store
            .activate(&id(), &target, Some(&original), "local-developer", at())
            .is_err()
    );
    assert_eq!(
        fs::read(held.join("generation-events.jsonl")).unwrap(),
        before
    );
    assert!(fs::read_dir(&root).unwrap().next().is_none());
    drop(store);
    fs::remove_dir_all(root).unwrap();
    fs::remove_dir_all(held).unwrap();
}

#[test]
fn fresh_native_publication_remains_usable_by_the_original_actual_writer() {
    let (reference, generation, _) = fixture();
    let root = reference.with_extension("native");
    let mut store = Registry::initialize_fresh(&root).unwrap();
    assert_eq!(store.snapshot()["active_for_new_work"], Value::Null);
    assert!(Registry::initialize_fresh(&root).is_err());
    let manifest: Value = serde_json::from_slice(
        &fs::read(reference.join(format!("runtime-generations/{generation}.json"))).unwrap(),
    )
    .unwrap();
    for sha in manifest["artifact_sha256s"].as_array().unwrap() {
        let sha = sha.as_str().unwrap();
        let directory = reference.join("artifacts").join(&sha[..2]).join(sha);
        let artifact: Value =
            serde_json::from_slice(&fs::read(directory.join("manifest.json")).unwrap()).unwrap();
        let bytes = fs::read(directory.join(if artifact["role"] == "RESEARCH_RUNTIME" {
            "artifact.elf"
        } else {
            "artifact.whl"
        }))
        .unwrap();
        store.install_artifact(&artifact, &bytes).unwrap();
        store.install_artifact(&artifact, &bytes).unwrap();
        assert!(store.install_artifact(&artifact, b"wrong bytes").is_err());
        if artifact["role"] == "RESEARCH_RUNTIME" {
            use sha2::{Digest, Sha256};
            let mut bad = bytes.clone();
            bad[0] ^= 1;
            let mut rebound = artifact.clone();
            rebound["artifact_sha256"] = Sha256::digest(&bad)
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
                .into();
            rebound
                .as_object_mut()
                .unwrap()
                .remove("manifest_fingerprint");
            rebound["manifest_fingerprint"] =
                onlyalpha_backend::application::factor_content::hash(&rebound)
                    .unwrap()
                    .into();
            assert!(
                store.install_artifact(&rebound, &bad).is_err(),
                "rehashed malformed ELF envelope was accepted"
            );
        }
    }
    drop(store);
    // Still-active original callers must be able to append to a freshly
    // provisioned native journal before any native mutation has replaced it.
    let prepared=Command::new("python").arg("-c").arg("from pathlib import Path;import sys,json;from datetime import datetime,UTC;from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry;from onlyalpha.generation_identity import OnlyRuntimeGenerationManifest;OnlyRuntimeGenerationRegistry(Path(sys.argv[1])).prepare(OnlyRuntimeGenerationManifest.from_dict(json.loads(Path(sys.argv[2]).read_text())),actor='fixture',occurred_at=datetime(2026,10,29,1,tzinfo=UTC))").arg(&root).arg(reference.join(format!("runtime-generations/{generation}.json"))).output().unwrap();
    assert!(
        prepared.status.success(),
        "{}",
        String::from_utf8_lossy(&prepared.stderr)
    );
    let mut store = Registry::open_existing(&root).unwrap();
    let validation = store
        .prepare_generation(&manifest, "local-developer", at())
        .unwrap();
    let expected: Value = serde_json::from_slice(
        &fs::read(reference.join(format!("runtime-generation-validation/{generation}.json")))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(validation, expected);
    assert_eq!(
        store
            .prepare_generation(&manifest, "local-developer", at())
            .unwrap(),
        validation
    );
    store
        .activate(&id(), &generation, None, "local-developer", at())
        .unwrap();
    drop(store);
    let out=Command::new("python").arg("-c").arg("from pathlib import Path;import sys;from datetime import datetime,UTC;from onlyalpha_runtime_generation_manager.registry import OnlyRuntimeGenerationRegistry;OnlyRuntimeGenerationRegistry(Path(sys.argv[1])).bind_new_work_exact('original-writer',sys.argv[2],owner='research',actor='fixture',occurred_at=datetime(2026,10,29,2,tzinfo=UTC))").arg(&root).arg(&generation).output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let hold = onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
        &root,
        "original-writer",
        "research",
        &generation,
    )
    .unwrap();
    hold.verify().unwrap();
    drop(hold);
    fs::remove_dir_all(root).unwrap();
    fs::remove_dir_all(reference).unwrap();
}

#[test]
fn missing_physical_artifacts_cannot_publish_a_ready_generation() {
    let (reference, generation, _) = fixture();
    let root = reference.with_extension("missing-artifacts");
    let mut store = Registry::initialize_fresh(&root).unwrap();
    let manifest: Value = serde_json::from_slice(
        &fs::read(reference.join(format!("runtime-generations/{generation}.json"))).unwrap(),
    )
    .unwrap();
    assert!(
        store
            .prepare_generation(&manifest, "local-developer", at())
            .is_err()
    );
    assert_eq!(fs::read(root.join("generation-events.jsonl")).unwrap(), b"");
    assert_eq!(store.snapshot()["active_for_new_work"], Value::Null);
    drop(store);
    fs::remove_dir_all(root).unwrap();
    fs::remove_dir_all(reference).unwrap();
}
