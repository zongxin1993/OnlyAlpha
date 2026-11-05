use onlyalpha_backend::{application::command::CommandId, persistence::research_runtime::Registry};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::Value;
use std::{fs, path::PathBuf};
#[path = "support/research_runtime_fixture.rs"]
mod research_runtime_fixture;
fn fixture() -> (PathBuf, String, String) {
    let mut entropy = [0; 16];
    getrandom::fill(&mut entropy).unwrap();
    let root = std::env::temp_dir().join(format!("runtime-lifecycle-{entropy:?}"));
    let (generation, ready) = research_runtime_fixture::fixture(&root, true);
    (root, generation, ready)
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
fn fresh_native_owner_roundtrip_preserves_exact_publication_and_work_binding() {
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
    let mut store = Registry::open_existing(&root).unwrap();
    store
        .bind_new_work_exact("native-writer", &generation, "research", "fixture", at())
        .unwrap();
    drop(store);
    let hold = onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
        &root,
        "native-writer",
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

#[test]
fn rejection_is_preparing_only_exact_and_restart_idempotent() {
    let (root, original, ready) = fixture();
    let manifest: Value = serde_json::from_slice(
        &fs::read(root.join(format!("runtime-generations/{original}.json"))).unwrap(),
    )
    .unwrap();
    let candidate = research_runtime_fixture::variant(&manifest, '6');
    let target = candidate["runtime_generation_fingerprint"]
        .as_str()
        .unwrap();
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    for invalid in [&original, &ready, &"f".repeat(64)] {
        assert!(
            registry
                .reject(invalid, "fixture", "fixture", at())
                .is_err()
        );
        assert_eq!(
            fs::read(root.join("generation-events.jsonl")).unwrap(),
            before
        );
    }
    registry
        .prepare_candidate(&candidate, "fixture", at())
        .unwrap();
    assert_eq!(registry.snapshot()["states"][target], "PREPARING");
    assert!(
        !root
            .join(format!("runtime-generation-validation/{target}.json"))
            .exists()
    );
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert!(registry.reject(target, " ", "fixture", at()).is_err());
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    let receipt = registry
        .reject(target, "invalid candidate", "fixture", at())
        .unwrap();
    assert_eq!(registry.snapshot()["states"][target], "REJECTED");
    drop(registry);
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        registry
            .reject(target, "invalid candidate", "fixture", at())
            .unwrap(),
        receipt
    );
    assert!(
        registry
            .reject(target, "different reason", "fixture", at())
            .is_err()
    );
    assert!(
        registry
            .prepare_generation(&candidate, "fixture", at())
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(registry);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn retirement_requires_draining_and_no_live_work_and_preserves_artifacts() {
    let (root, original, ready) = fixture();
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert!(registry.retire(&original, "fixture", at()).is_err());
    assert!(registry.retire(&ready, "fixture", at()).is_err());
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    registry
        .activate(&id(), &ready, Some(&original), "fixture", at())
        .unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert!(registry.retire(&original, "fixture", at()).is_err());
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    registry
        .release_work_exact("work", &original, "research", "fixture", at())
        .unwrap();
    let receipt = registry.retire(&original, "fixture", at()).unwrap();
    assert_eq!(registry.snapshot()["states"][&original], "RETIRED");
    drop(registry);
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        registry.retire(&original, "fixture", at()).unwrap(),
        receipt
    );
    assert!(
        registry
            .activate(
                &CommandId::new("00000000-0000-4000-8000-000000000903").unwrap(),
                &original,
                Some(&ready),
                "fixture",
                at()
            )
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    let manifest: Value = serde_json::from_slice(
        &fs::read(root.join(format!("runtime-generations/{original}.json"))).unwrap(),
    )
    .unwrap();
    for sha in manifest["artifact_sha256s"].as_array().unwrap() {
        let sha = sha.as_str().unwrap();
        assert!(
            root.join("artifacts")
                .join(&sha[..2])
                .join(sha)
                .join("manifest.json")
                .is_file()
        );
    }
    drop(registry);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn closure_requires_explicit_release_and_never_changes_a_different_binding() {
    let (root, original, ready) = fixture();
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        registry
            .close_new_work_exact("work", &original, "research", "cancelled", "fixture", at())
            .unwrap_err(),
        "RUNTIME_WORK_STILL_ACTIVE"
    );
    assert!(
        registry
            .close_new_work_exact("work", &ready, "research", "cancelled", "fixture", at())
            .is_err()
    );
    assert!(
        registry
            .close_new_work_exact(
                "work",
                &original,
                "other-owner",
                "cancelled",
                "fixture",
                at()
            )
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    registry
        .release_work_exact("work", &original, "research", "fixture", at())
        .unwrap();
    let receipt = registry
        .close_new_work_exact("work", &original, "research", "cancelled", "fixture", at())
        .unwrap();
    drop(registry);
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        registry
            .close_new_work_exact("work", &original, "research", "cancelled", "fixture", at())
            .unwrap(),
        receipt
    );
    for (g, owner, reason) in [
        (&ready, "research", "cancelled"),
        (&original, "other", "cancelled"),
        (&original, "research", "different"),
    ] {
        assert!(
            registry
                .close_new_work_exact("work", g, owner, reason, "fixture", at())
                .is_err()
        );
    }
    assert_eq!(
        registry
            .bind_new_work_exact("work", &original, "research", "fixture", at())
            .unwrap_err(),
        "RUNTIME_WORK_ADMISSION_CLOSED"
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(registry);
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn unbound_exact_cancellation_fences_late_admission_without_claiming_completion() {
    let (root, original, ready) = fixture();
    let mut registry = Registry::open_existing(&root).unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert!(
        registry
            .close_new_work_exact(
                "late-work",
                &"f".repeat(64),
                "research",
                "cancelled",
                "fixture",
                at()
            )
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    let receipt = registry
        .close_new_work_exact(
            "late-work",
            &ready,
            "research",
            "cancelled",
            "fixture",
            at(),
        )
        .unwrap();
    assert_eq!(receipt["generation_fingerprint"], ready);
    registry
        .activate(&id(), &ready, Some(&original), "fixture", at())
        .unwrap();
    let before = fs::read(root.join("generation-events.jsonl")).unwrap();
    assert_eq!(
        registry
            .bind_new_work_exact("late-work", &ready, "research", "fixture", at())
            .unwrap_err(),
        "RUNTIME_WORK_ADMISSION_CLOSED"
    );
    assert!(
        registry
            .release_work_exact("late-work", &ready, "research", "fixture", at())
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("generation-events.jsonl")).unwrap(),
        before
    );
    drop(registry);
    fs::remove_dir_all(root).unwrap();
}
