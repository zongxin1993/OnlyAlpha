//! Physical reader composition only; this fixture does not admit a Generation.
use super::*;
use std::{
    cell::{Cell, RefCell},
    os::unix::fs::{DirBuilderExt, OpenOptionsExt},
};

#[test]
fn backtest_binding_scan_distinguishes_lock_contention_from_unavailable_storage() {
    let fixture = Fixture::new();
    let root = fixture.root.join("scan");
    let writer = Registry::initialize_fresh(&root).unwrap();
    assert_eq!(
        Registry::try_unreleased_work_bindings(&root),
        Ok(None)
    );
    assert_eq!(
        Registry::unreleased_work_bindings(&root),
        Err(UNAVAILABLE)
    );
    assert_eq!(
        Registry::try_unreleased_work_bindings(&root.join("missing")),
        Err(UNAVAILABLE)
    );
    drop(writer);
    assert!(Registry::try_unreleased_work_bindings(&root).unwrap().unwrap().is_empty());
}

type BeforeFinalRead = Box<dyn FnOnce()>;
std::thread_local! {
    pub(super) static SCANS: Cell<u64> = const { Cell::new(0) };
    pub(super) static SCANNED_BYTES: Cell<u64> = const { Cell::new(0) };
    static BEFORE_FINAL: RefCell<Option<BeforeFinalRead>> = const { RefCell::new(None) };
}
pub(super) fn before_final_read() {
    let action = BEFORE_FINAL.with(|hook| hook.borrow_mut().take());
    if let Some(action) = action {
        action();
    }
}
fn write(path: &Path, bytes: &[u8]) {
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .unwrap();
    file.write_all(bytes).unwrap();
}
struct Fixture {
    root: PathBuf,
    hold: RuntimeEvidenceHold,
    proof: PathBuf,
    algorithm: String,
    bytes: u64,
}
impl Fixture {
    fn new() -> Self {
        use sha2::{Digest, Sha256};
        let mut entropy = [0; 16];
        getrandom::fill(&mut entropy).unwrap();
        let root = std::env::temp_dir().join(format!("history-metadata-{entropy:?}"));
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&root)
            .unwrap();
        write(&root.join(".generation-authority.lock"), b"");
        let mut retained =
            RuntimeInputHold::acquire(&root, fs::FlockOperation::NonBlockingLockShared).unwrap();
        let generation = "a".repeat(64);
        let algorithm = "b".repeat(64);
        retained.manifest = json!({"runtime_generation_fingerprint":generation,"core_execution":{"schema_version":1,"source":"controlled unit data"}});
        retained.binding = json!({"kind":"RuntimeWorkBound","work_id":"original-work","generation_fingerprint":generation});
        let mut bytes = 0;
        for (name, data) in [
            (
                "original.elf",
                b"exact retained executable bytes".as_slice(),
            ),
            (
                "original.whl",
                b"exact retained numerical SDK bytes".as_slice(),
            ),
        ] {
            write(&root.join(name), data);
            bytes += data.len() as u64;
            retained.artifacts.push((
                name.into(),
                Sha256::digest(data)
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect(),
                data.len() as u64,
            ));
        }
        retained.executor = Some(
            json!({"schema_version":2,"role":"BACKEND_RUNTIME","execution_capabilities":[{"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}],"manifest_fingerprint":"c".repeat(64),"artifact_sha256":retained.artifacts[0].1,"distribution_version":"unit-version","tested_core_execution_fingerprint":hash(&retained.manifest["core_execution"]).unwrap()}),
        );
        let directory = root
            .join("runtime-generation-installed-proof")
            .join(&generation);
        std::fs::create_dir_all(&directory).unwrap();
        let mut proof = json!({"schema_version":2,"contract":"ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V2","runtime_generation_fingerprint":generation,"algorithm_artifact":algorithm,"original":"selected history"});
        let identity = hash(&proof).unwrap();
        proof["installed_proof_fingerprint"] = json!(identity);
        let proof_path = directory.join(format!("{identity}.json"));
        write(&proof_path, proof.to_string().as_bytes());
        Self {
            root,
            hold: RuntimeEvidenceHold { retained },
            proof: proof_path,
            algorithm,
            bytes,
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        BEFORE_FINAL.with(|hook| {
            hook.borrow_mut().take();
        });
        std::fs::remove_dir_all(&self.root).unwrap();
    }
}
fn reset() {
    SCANS.with(|v| v.set(0));
    SCANNED_BYTES.with(|v| v.set(0));
}

#[test]
fn combined_metadata_keeps_original_values_with_two_complete_physical_cuts() {
    let mut f = Fixture::new();
    let binding = json!({"executor_manifest_fingerprint":"c".repeat(64),"executor_artifact_sha256":f.hold.retained.artifacts[0].1,"executor_version":"unit-version","core_execution_fingerprint":hash(&f.hold.retained.manifest["core_execution"]).unwrap(),"protocol":"onlyalpha.backtest.executor/1"});
    let installed = f.hold.installed_proof(&f.algorithm).unwrap();
    let executor = f.hold.retained.executor.as_ref().unwrap().clone();
    reset();
    let metadata = f.hold.backtest_metadata(&f.algorithm).unwrap();
    assert_eq!(metadata.binding, binding);
    assert_eq!(metadata.installed, installed);
    assert_eq!(metadata.executor, executor);
    assert_eq!(
        SCANS.with(Cell::get),
        2,
        "metadata selection must keep complete actual pre/post cuts without nested full artifact scans"
    );
    assert_eq!(
        SCANNED_BYTES.with(Cell::get),
        2 * f.bytes,
        "both complete cuts must read every actual artifact byte"
    );
    let known = f
        .hold
        .retained
        .records
        .iter()
        .any(|(path, _)| f.root.join(path) == f.proof);
    assert!(
        known,
        "newly read installed proof must join the final actual record cut"
    );
}

#[test]
fn metadata_mid_read_changes_never_survive_the_final_actual_cut() {
    for fault in ["elf", "wheel", "missing", "proof", "duplicate", "lock"] {
        let mut f = Fixture::new();
        let root = f.root.clone();
        let proof = f.proof.clone();
        BEFORE_FINAL.with(|hook| {
            *hook.borrow_mut() = Some(Box::new(move || match fault {
                "elf" | "wheel" => {
                    let path = root.join(if fault == "elf" {
                        "original.elf"
                    } else {
                        "original.whl"
                    });
                    let raw = std::fs::read(&path).unwrap();
                    std::fs::write(path, vec![b'x'; raw.len()]).unwrap();
                }
                "missing" => std::fs::remove_file(root.join("original.elf")).unwrap(),
                "proof" => {
                    let mut raw = std::fs::read(&proof).unwrap();
                    raw.push(b' ');
                    std::fs::write(proof, raw).unwrap();
                }
                "duplicate" => {
                    let mut value: Value =
                        serde_json::from_slice(&std::fs::read(&proof).unwrap()).unwrap();
                    value
                        .as_object_mut()
                        .unwrap()
                        .remove("installed_proof_fingerprint");
                    value["other"] = json!(true);
                    let identity = hash(&value).unwrap();
                    value["installed_proof_fingerprint"] = json!(identity);
                    write(
                        &proof.parent().unwrap().join(format!("{identity}.json")),
                        value.to_string().as_bytes(),
                    );
                }
                "lock" => {
                    std::fs::rename(
                        root.join(".generation-authority.lock"),
                        root.join("original.lock"),
                    )
                    .unwrap();
                    write(&root.join(".generation-authority.lock"), b"");
                }
                _ => unreachable!(),
            }))
        });
        assert!(
            f.hold.backtest_metadata(&f.algorithm).is_err(),
            "mid-read {fault} must not return metadata"
        );
    }
}

#[test]
fn metadata_mid_read_root_replacement_is_rejected_without_touching_the_original_history() {
    let mut f = Fixture::new();
    let root = f.root.clone();
    let moved = root.with_extension("retained-original");
    let saved = moved.clone();
    BEFORE_FINAL.with(|hook| {
        *hook.borrow_mut() = Some(Box::new(move || {
            std::fs::rename(&root, &saved).unwrap();
            std::fs::create_dir(&root).unwrap();
        }))
    });
    let result = f.hold.backtest_metadata(&f.algorithm);
    std::fs::remove_dir(&f.root).unwrap();
    std::fs::rename(&moved, &f.root).unwrap();
    assert!(
        result.is_err(),
        "a new root cannot authenticate the original descriptor-held history"
    );
    assert!(
        f.hold.backtest_metadata(&f.algorithm).is_ok(),
        "the original unmodified readonly history remains usable"
    );
}

#[test]
fn target_selection_uses_the_held_generation_wheel_across_distribution_names() {
    for distribution in ["onlyalpha-plugin-targets", "onlyalpha-backend-algorithms"] {
        use sha2::{Digest, Sha256};

        let mut fixture = Fixture::new();
        let relative = "target/artifact.whl";
        std::fs::create_dir(fixture.root.join("target")).unwrap();
        let bytes = distribution.as_bytes();
        let digest: String = Sha256::digest(bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        write(&fixture.root.join(relative), bytes);
        write(
            &fixture.root.join("target/manifest.json"),
            &serde_json::to_vec(&json!({
                "distribution_name": distribution,
                "distribution_version": "bound-version",
                "implementations": [{
                    "kind": "TARGET",
                    "type_id": "onlyalpha.target.forward_return",
                    "semantic_version": "1",
                    "backend": "RESEARCH",
                }],
            }))
            .unwrap(),
        );
        fixture.hold.retained.artifacts = vec![(relative.into(), digest.clone(), bytes.len() as u64)];

        let selected = fixture.hold.retained.target_artifact().unwrap();
        assert_eq!(selected["sha256"], digest);
        assert_eq!(selected["path"], json!(fixture.root.join(relative)));
        assert_eq!(selected["distribution_version"], "bound-version");

        std::fs::write(fixture.root.join(relative), b"changed").unwrap();
        assert!(fixture.hold.retained.target_artifact().is_err());
    }
}
