use onlyalpha_backend::application::factor_content::hash;
use onlyalpha_backend::bootstrap::{deployment::SemanticStoreId, research_namespace};
use serde_json::{Value, json};
use std::{fs, path::PathBuf};

fn temp_root() -> PathBuf {
    let mut bytes = [0_u8; 16];
    getrandom::fill(&mut bytes).unwrap();
    let path = std::env::temp_dir().join(format!(
        "research-namespace-{}",
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    ));
    fs::create_dir(&path).unwrap();
    path
}
#[test]
fn fresh_owner_profile_and_original_policy_identity_reopen_exactly() {
    let root = temp_root();
    let id: SemanticStoreId = research_namespace::initialize_fresh(&root).unwrap();
    assert_eq!(research_namespace::open_existing(&root).unwrap(), id);
    assert!(research_namespace::initialize_fresh(&root).is_err());
    let profile = research_namespace::profile();
    assert_eq!(
        profile["contract"],
        "ONLYALPHA_FACTOR_RESEARCH_OWNER_PROFILE_V1"
    );
    let policy = research_namespace::policy();
    assert_eq!(policy["policy_id"], "onlyalpha.factor-research");
    assert_eq!(policy["policy_version"], "1");
    let mut identity = policy.clone();
    let pin = identity
        .as_object_mut()
        .unwrap()
        .remove("policy_fingerprint")
        .unwrap();
    identity["domain"] = "onlyalpha.research.novelty-policy".into();
    assert_eq!(pin, hash(&identity).unwrap());
    let roots = research_namespace::source_roots(&root);
    assert_eq!(roots.len(), 7);
    assert_eq!(
        roots["RESEARCH_STATISTICS"],
        roots["RESEARCH_FACTOR_PAIR_STATISTICS"]
    );
    assert_eq!(
        roots["RESEARCH_STATISTICS"],
        roots["RESEARCH_SUMMARY_STATISTICS"]
    );
    for path in roots.values() {
        assert!(path.join("sha256").is_dir());
        assert!(path.join(".source-cut.lock").is_file());
    }
    research_namespace::novelty(&root).unwrap();
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn missing_owner_or_lock_is_not_repaired_or_interpreted_as_empty_history() {
    for missing in ["results/.source-cut.lock", "search-provenance"] {
        let root = temp_root();
        research_namespace::initialize_fresh(&root).unwrap();
        let path = root.join("research").join(missing);
        if path.is_dir() {
            fs::remove_dir_all(&path).unwrap();
        } else {
            fs::remove_file(&path).unwrap();
        }
        assert!(research_namespace::open_existing(&root).is_err());
        assert!(research_namespace::initialize_fresh(&root).is_err());
        assert!(!path.exists());
        fs::remove_dir_all(root).unwrap();
    }
}
#[test]
fn preexisting_empty_or_unmarked_namespace_cannot_acquire_a_fresh_token() {
    let root = temp_root();
    fs::create_dir(root.join("research")).unwrap();
    assert!(research_namespace::initialize_fresh(&root).is_err());
    assert!(research_namespace::open_existing(&root).is_err());
    assert!(
        fs::read_dir(root.join("research"))
            .unwrap()
            .next()
            .is_none()
    );
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn policy_corruption_and_source_symlinks_fail_without_fallback() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let root = temp_root();
    research_namespace::initialize_fresh(&root).unwrap();
    let policy = root.join("research/novelty-policies/onlyalpha.factor-research/1/manifest.json");
    fs::set_permissions(&policy, fs::Permissions::from_mode(0o600)).unwrap();
    fs::write(&policy, b"{}").unwrap();
    assert!(research_namespace::open_existing(&root).is_err());
    assert_eq!(fs::read(&policy).unwrap(), b"{}");
    assert!(research_namespace::novelty(&root).is_err());
    fs::remove_dir_all(root).unwrap();
    let root = temp_root();
    research_namespace::initialize_fresh(&root).unwrap();
    let source = root.join("research/agent-provenance");
    let other = root.join("other");
    fs::rename(&source, &other).unwrap();
    symlink(&other, &source).unwrap();
    assert!(research_namespace::open_existing(&root).is_err());
    fs::remove_dir_all(root).unwrap();
}
#[test]
fn existing_exact_namespace_is_read_only_and_preserves_nonempty_source_inventory() {
    let root = temp_root();
    let id = research_namespace::initialize_fresh(&root).unwrap();
    let sources = research_namespace::source_roots(&root);
    let source = &sources["AGENT_PROVENANCE"];
    let locator = "a".repeat(64);
    let leaf = source.join("sha256/aa").join(locator);
    fs::create_dir_all(&leaf).unwrap();
    fs::write(
        leaf.join("manifest.json"),
        b"unavailable original source fact",
    )
    .unwrap();
    // Opening verifies deployment structure; it does not certify source-cut completeness.
    assert_eq!(research_namespace::open_existing(&root).unwrap(), id);
    assert_eq!(
        fs::read(leaf.join("manifest.json")).unwrap(),
        b"unavailable original source fact"
    );
    assert!(research_namespace::initialize_fresh(&root).is_err());
    let retained: Value = serde_json::from_slice(
        &fs::read(root.join("research/.onlyalpha-semantic-store.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(retained, json!({"schema_version":1,"store_id":id.value()}));
    fs::remove_dir_all(root).unwrap();
}

#[test]
fn layout_reopen_preserves_an_active_source_cut_without_claiming_its_barrier() {
    use std::collections::BTreeMap;
    use std::os::unix::fs::MetadataExt;
    fn files(root: &std::path::Path, base: &std::path::Path) -> BTreeMap<PathBuf, Vec<u8>> {
        let mut result = BTreeMap::new();
        for entry in fs::read_dir(root).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                result.insert(path.strip_prefix(base).unwrap().to_owned(), Vec::new());
                result.extend(files(&path, base));
            } else {
                result.insert(
                    path.strip_prefix(base).unwrap().to_owned(),
                    fs::read(path).unwrap(),
                );
            }
        }
        result
    }
    // The agent owner reaches namespace's own cut loop; Results/statistics also
    // exercise the nested Evidence-store constructor's publication locks.
    for family in ["AGENT_PROVENANCE", "RESEARCH_RESULT", "RESEARCH_STATISTICS"] {
        let root = temp_root();
        let id = research_namespace::initialize_fresh(&root).unwrap();
        let owner = research_namespace::source_roots(&root)[family].clone();
        let path = owner.join(".source-cut.lock");
        let cut = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap();
        rustix::fs::flock(&cut, rustix::fs::FlockOperation::NonBlockingLockExclusive).unwrap();
        let prior = files(&root, &root);
        let binding = fs::metadata(&path).unwrap();
        // This opens structure only. The held cut must neither reject a layout
        // observation nor be released/downgraded by it.
        assert_eq!(research_namespace::open_existing(&root).unwrap(), id);
        research_namespace::novelty(&root).unwrap();
        assert_eq!(files(&root, &root), prior);
        let after = fs::metadata(&path).unwrap();
        assert_eq!(
            (after.dev(), after.ino(), after.mtime(), after.mtime_nsec()),
            (
                binding.dev(),
                binding.ino(),
                binding.mtime(),
                binding.mtime_nsec()
            )
        );
        let other = fs::File::open(&path).unwrap();
        assert!(
            rustix::fs::flock(&other, rustix::fs::FlockOperation::NonBlockingLockShared).is_err()
        );
        assert!(
            rustix::fs::flock(&other, rustix::fs::FlockOperation::NonBlockingLockExclusive)
                .is_err()
        );
        drop(cut);
        research_namespace::open_existing(&root).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}

#[test]
fn layout_reopen_rejects_unsafe_or_substituted_source_coordination_files() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    for mutation in ["missing", "symlink", "hardlink", "writable"] {
        let root = temp_root();
        research_namespace::initialize_fresh(&root).unwrap();
        let lock = root.join("research/agent-provenance/.source-cut.lock");
        match mutation {
            "missing" => fs::remove_file(&lock).unwrap(),
            "symlink" => {
                fs::rename(&lock, root.join("retained-lock")).unwrap();
                symlink(root.join("retained-lock"), &lock).unwrap();
            }
            "hardlink" => fs::hard_link(&lock, root.join("duplicate-lock")).unwrap(),
            "writable" => fs::set_permissions(&lock, fs::Permissions::from_mode(0o666)).unwrap(),
            _ => unreachable!(),
        }
        assert!(research_namespace::open_existing(&root).is_err());
        assert!(research_namespace::novelty(&root).is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
