use onlyalpha_backend::application::frozen_strategy::{Error, FreezeRelation};
use serde_json::Value;
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/frozen_strategy.json")).unwrap()
}
#[test]
fn current_relation_identity_and_exact_references() {
    let original = fixture()["relation"].clone();
    let relation = FreezeRelation::from_json(&original.to_string(), 1024 * 1024).unwrap();
    assert_eq!(relation.to_record(), original);
    assert_eq!(
        relation.fingerprint(),
        original["relation_fingerprint"].as_str().unwrap()
    );
    assert_eq!(
        relation.strategy_fingerprint(),
        fixture()["source"]["strategy_fingerprint"]
            .as_str()
            .unwrap()
    );
    for field in [
        "strategy_fingerprint",
        "candidate_fingerprint",
        "research_result_fingerprint",
        "admission_evidence_fingerprint",
        "relation_fingerprint",
    ] {
        for value in [
            serde_json::json!("A".repeat(64)),
            serde_json::json!(12),
            Value::Null,
        ] {
            let mut bad = original.clone();
            bad[field] = value;
            assert!(matches!(
                FreezeRelation::from_json(&bad.to_string(), 1024 * 1024),
                Err(Error::Corrupt)
            ));
        }
    }
    for values in [
        serde_json::json!([]),
        serde_json::json!(["c".repeat(64), "c".repeat(64)]),
        serde_json::json!(["d".repeat(64), "c".repeat(64)]),
    ] {
        let mut bad = original.clone();
        bad["research_execution_evidence_fingerprints"] = values;
        assert!(matches!(
            FreezeRelation::from_json(&bad.to_string(), 1024 * 1024),
            Err(Error::Corrupt)
        ));
    }
    assert!(matches!(
        FreezeRelation::from_json(&original.to_string(), 1),
        Err(Error::Unavailable)
    ));
}
use onlyalpha_backend::application::frozen_strategy::FrozenStore;
use onlyalpha_backend::security::protected_files::{self, FilePolicy, ReadError};
use std::{
    fs::{self, DirBuilder},
    os::{
        fd::AsFd,
        unix::fs::{DirBuilderExt, PermissionsExt, symlink},
    },
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};
const WORK: usize = 64 * 1024 * 1024;
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "oa-frozen-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&p).unwrap();
        Self(p)
    }
    fn store(&self) -> FrozenStore {
        let fd = protected_files::open_directory(&self.0).unwrap();
        FrozenStore::open(fd.as_fd()).unwrap()
    }
    fn publish(&self, kind: &str, id: &str, v: &Value) -> PathBuf {
        let dir = self
            .0
            .join(format!("strategy/{kind}/sha256/{}/{id}", &id[..2]));
        fs::create_dir_all(&dir).unwrap();
        let file = dir.join("manifest.json");
        fs::write(&file, v.to_string()).unwrap();
        file
    }
    fn pair(&self) -> (String, PathBuf, PathBuf) {
        let f = fixture();
        let id = f["source"]["strategy_fingerprint"].as_str().unwrap();
        let a = self.publish("frozen-revisions", id, &f["manifest"]);
        let rel = &f["relation"];
        let b = self.publish(
            "freeze-relations",
            rel["relation_fingerprint"].as_str().unwrap(),
            rel,
        );
        (id.into(), a, b)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap()
    }
}
#[test]
fn physical_history_requires_exact_canonical_pair_and_preserves_selected_root() {
    let r = Root::new();
    let store = r.store();
    let (id, _, _) = r.pair();
    assert_eq!(store.load_verified(&id, WORK).unwrap().fingerprint(), id);
    let moved = r.0.with_extension("selected");
    fs::rename(&r.0, &moved).unwrap();
    fs::create_dir(&r.0).unwrap();
    let selected = store.load_verified(&id, WORK);
    fs::remove_dir(&r.0).unwrap();
    fs::rename(&moved, &r.0).unwrap();
    assert_eq!(selected.unwrap().fingerprint(), id);
    assert!(matches!(
        store.load_verified(&id, WORK / 8),
        Err(Error::Unavailable)
    ));
}
#[test]
fn published_missing_relation_is_corrupt_and_valid_orphan_does_not_create_revision() {
    let r = Root::new();
    let (id, a, b) = r.pair();
    fs::remove_file(&b).unwrap();
    assert!(matches!(
        r.store().load_verified(&id, WORK),
        Err(Error::Corrupt)
    ));
    fs::remove_dir_all(r.0.join("strategy")).unwrap();
    let rel = &fixture()["relation"];
    r.publish(
        "freeze-relations",
        rel["relation_fingerprint"].as_str().unwrap(),
        rel,
    );
    assert!(matches!(
        r.store().load_verified(&id, WORK),
        Err(Error::Missing)
    ));
    assert!(!a.exists());
}
#[test]
fn malformed_published_entries_bytes_paths_and_links_fail_closed() {
    for attack in 0..9 {
        let r = Root::new();
        let (id, a, b) = r.pair();
        match attack {
            0 => {
                let raw = fs::read_to_string(&a).unwrap();
                fs::write(&a, format!("{raw}\n")).unwrap();
            }
            1 => {
                fs::write(a.parent().unwrap().join("extra"), b"{}").unwrap();
            }
            2 => {
                fs::remove_file(&a).unwrap();
                symlink(&b, &a).unwrap();
            }
            3 => {
                let raw = fs::read_to_string(&a).unwrap();
                let replacement = a.with_extension("copy");
                fs::write(&replacement, raw).unwrap();
                fs::remove_file(&a).unwrap();
                symlink(&replacement, &a).unwrap();
            }
            4 => {
                fs::set_permissions(&a, fs::Permissions::from_mode(0o666)).unwrap();
            }
            5 => {
                fs::rename(
                    a.parent().unwrap(),
                    a.parent().unwrap().with_file_name("a".repeat(64)),
                )
                .unwrap();
            }
            6 => {
                fs::create_dir(
                    a.parent()
                        .unwrap()
                        .parent()
                        .unwrap()
                        .join(".stage-leftover"),
                )
                .unwrap();
            }
            7 => {
                let mut v: Value = serde_json::from_slice(&fs::read(&a).unwrap()).unwrap();
                v["revision"]["signal_semantics"]["missing_decision"] = serde_json::json!("TRUE");
                fs::write(&a, v.to_string()).unwrap();
            }
            _ => {
                let mut v: Value = serde_json::from_slice(&fs::read(&b).unwrap()).unwrap();
                v["strategy_fingerprint"] = serde_json::json!("0".repeat(64));
                fs::write(&b, v.to_string()).unwrap();
            }
        }
        assert!(
            matches!(r.store().load_verified(&id, WORK), Err(Error::Corrupt)),
            "attack {attack}"
        );
    }
}
#[test]
fn protected_single_components_and_history_hardlinks_keep_existing_policy() {
    let r = Root::new();
    let (_, a, _) = r.pair();
    let fd = protected_files::open_directory(a.parent().unwrap()).unwrap();
    for bad in ["", ".", "..", "../manifest.json", "/tmp", "x/y"] {
        assert!(matches!(
            protected_files::open_directory_at(&fd, std::ffi::OsStr::new(bad)),
            Err(ReadError::Invalid)
        ));
        assert!(matches!(
            protected_files::read_file_at(
                &fd,
                std::ffi::OsStr::new(bad),
                FilePolicy::HistoryDocument,
                WORK
            ),
            Err(ReadError::Invalid)
        ));
    }
    let link = r.0.join("paired-copy");
    fs::hard_link(&a, &link).unwrap();
    assert!(
        protected_files::read_file_at(
            &fd,
            std::ffi::OsStr::new("manifest.json"),
            FilePolicy::HistoryDocument,
            WORK
        )
        .is_ok()
    );
    assert!(matches!(
        protected_files::read_file_at(
            &fd,
            std::ffi::OsStr::new("manifest.json"),
            FilePolicy::Asset,
            WORK
        ),
        Err(ReadError::Invalid)
    ));
}

#[test]
fn selected_directory_is_protected_and_duplicate_is_close_on_exec() {
    let r = Root::new();
    let fd = protected_files::open_directory(&r.0).unwrap();
    let dup = protected_files::duplicate_directory(fd.as_fd()).unwrap();
    assert!(
        rustix::io::fcntl_getfd(&dup)
            .unwrap()
            .contains(rustix::io::FdFlags::CLOEXEC)
    );
    fs::set_permissions(&r.0, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(matches!(
        protected_files::duplicate_directory(fd.as_fd()),
        Err(ReadError::Invalid)
    ));
    fs::set_permissions(&r.0, fs::Permissions::from_mode(0o700)).unwrap();
    let regular = r.0.join("regular");
    fs::write(&regular, b"not a directory").unwrap();
    let regular = fs::File::open(regular).unwrap();
    assert!(matches!(
        FrozenStore::open(regular.as_fd()),
        Err(Error::Corrupt)
    ));
}
