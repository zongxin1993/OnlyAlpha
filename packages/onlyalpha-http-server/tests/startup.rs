//! Concrete node storage input proof; not production READY or business acceptance.
use onlyalpha_http_server::{
    configuration::MasterKeyFileError,
    startup::{Directory, Error, StorageInputs, StorageRoots},
};
use onlyalpha_product_runtime::{
    credentials::{Key, Secret},
    integration_configuration::IntegrationId,
};
use std::{
    fs::{self, DirBuilder, OpenOptions},
    io::Write,
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt, symlink},
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};
const NAMESPACE: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-startup-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        let r = Self(path);
        for name in [
            "data/research/artifacts",
            "data/backtest/evidence",
            "data/research/datasets",
            "data/research/dataset-economic-bindings",
            "data/secrets",
            "sql",
        ] {
            fs::create_dir_all(r.0.join(name)).unwrap();
        }
        r.write(
            "data/research/.onlyalpha-semantic-store.json",
            format!("{{\"schema_version\":1,\"store_id\":\"{NAMESPACE}\"}}").as_bytes(),
        );
        r.write("data/secrets/dev-master-key", &[1; 32]);
        r.write("sql/0001_initial.sql", b"-- selected original bytes\n");
        r
    }
    fn data(&self) -> PathBuf {
        self.0.join("data")
    }
    fn write(&self, path: &str, bytes: &[u8]) {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .mode(0o600)
            .open(self.0.join(path))
            .unwrap();
        file.write_all(bytes).unwrap();
    }
    fn load(&self) -> Result<StorageInputs, Error> {
        StorageInputs::load(
            StorageRoots::open(&self.data())?,
            &self.0.join("sql"),
            100000,
        )
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn complete_inputs_retain_the_selected_namespace_key_and_actual_directory_capabilities() {
    let root = Root::new();
    let inputs = root.load().unwrap();
    assert_eq!(inputs.namespace().value(), NAMESPACE);
    let secret = Secret::new("controlled key selection").unwrap();
    let integration = IntegrationId::new("33333333-3333-4333-8333-333333333333").unwrap();
    assert_eq!(
        inputs
            .key()
            .secret_commitment(&integration, "api_key", &secret, 100000)
            .unwrap(),
        Key::new(&[1; 32])
            .unwrap()
            .secret_commitment(&integration, "api_key", &secret, 100000)
            .unwrap()
    );
    for (kind, path) in [
        (Directory::UserData, "data"),
        (Directory::Research, "data/research"),
        (Directory::Secrets, "data/secrets"),
        (Directory::Artifacts, "data/research/artifacts"),
        (Directory::BacktestEvidence, "data/backtest/evidence"),
        (Directory::Datasets, "data/research/datasets"),
        (
            Directory::EconomicBindings,
            "data/research/dataset-economic-bindings",
        ),
    ] {
        assert_eq!(
            rustix::fs::fstat(inputs.roots().directory(kind))
                .unwrap()
                .st_ino,
            fs::metadata(root.0.join(path)).unwrap().ino()
        );
    }
}
#[test]
fn replacing_the_original_path_after_selection_cannot_rebind_key_namespace_or_roots() {
    let root = Root::new();
    let roots = StorageRoots::open(&root.data()).unwrap();
    let original = fs::metadata(root.data()).unwrap().ino();
    fs::rename(root.data(), root.0.join("retained")).unwrap();
    let replacement = Root::new();
    fs::rename(replacement.data(), root.data()).unwrap();
    root.write(
        "data/research/.onlyalpha-semantic-store.json",
        format!("{{\"schema_version\":1,\"store_id\":\"{OTHER}\"}}").as_bytes(),
    );
    root.write("data/secrets/dev-master-key", &[2; 32]);
    let inputs = StorageInputs::load(roots, &root.0.join("sql"), 100000).unwrap();
    assert_eq!(inputs.namespace().value(), NAMESPACE);
    assert_eq!(
        rustix::fs::fstat(inputs.roots().directory(Directory::UserData))
            .unwrap()
            .st_ino,
        original
    );
    let secret = Secret::new("controlled key selection").unwrap();
    let integration = IntegrationId::new("33333333-3333-4333-8333-333333333333").unwrap();
    assert_eq!(
        inputs
            .key()
            .secret_commitment(&integration, "api_key", &secret, 100000)
            .unwrap(),
        Key::new(&[1; 32])
            .unwrap()
            .secret_commitment(&integration, "api_key", &secret, 100000)
            .unwrap()
    );
    assert_eq!(root.load().unwrap().namespace().value(), OTHER);
}
#[test]
fn missing_or_unsafe_required_directories_do_not_initialize_repair_or_accept_partial_inputs() {
    for relative in [
        "research/artifacts",
        "backtest/evidence",
        "research/datasets",
        "research/dataset-economic-bindings",
    ] {
        let root = Root::new();
        fs::remove_dir(root.data().join(relative)).unwrap();
        assert!(matches!(root.load(), Err(Error::RequiredRootUnusable)));
        assert!(!root.data().join(relative).exists());
        let root = Root::new();
        fs::set_permissions(
            root.data().join(relative),
            fs::Permissions::from_mode(0o777),
        )
        .unwrap();
        assert!(matches!(root.load(), Err(Error::RequiredRootUnusable)));
    }
    let root = Root::new();
    fs::rename(root.data().join("research"), root.data().join("original")).unwrap();
    symlink(root.data().join("original"), root.data().join("research")).unwrap();
    assert!(matches!(root.load(), Err(Error::RequiredRootUnusable)));
}
#[test]
fn missing_or_invalid_secret_and_namespace_remain_distinct_fail_closed_inputs() {
    let root = Root::new();
    fs::remove_file(root.data().join("secrets/dev-master-key")).unwrap();
    assert!(matches!(
        root.load(),
        Err(Error::MasterKey(MasterKeyFileError::Missing))
    ));
    assert!(!root.data().join("secrets/dev-master-key").exists());
    let root = Root::new();
    root.write("data/secrets/dev-master-key", &[1; 31]);
    assert!(matches!(
        root.load(),
        Err(Error::MasterKey(MasterKeyFileError::Invalid))
    ));
    let root = Root::new();
    fs::remove_file(root.data().join("research/.onlyalpha-semantic-store.json")).unwrap();
    assert!(matches!(
        root.load(),
        Err(Error::Namespace(
            onlyalpha_product_runtime::deployment::Error::Missing
        ))
    ));
    assert!(
        !root
            .data()
            .join("research/.onlyalpha-semantic-store.json")
            .exists()
    );
    let root = Root::new();
    root.write("data/research/.onlyalpha-semantic-store.json", b"{}");
    assert!(matches!(
        root.load(),
        Err(Error::Namespace(
            onlyalpha_product_runtime::deployment::Error::Corrupt
        ))
    ));
}

#[test]
fn readable_directory_without_search_permission_cannot_satisfy_required_roots() {
    assert_ne!(
        rustix::process::geteuid().as_raw(),
        0,
        "canonical non-root validation required for this DAC counterexample"
    );
    let mut accepted = Vec::new();
    for relative in [
        ".",
        "research/artifacts",
        "backtest/evidence",
        "research/datasets",
        "research/dataset-economic-bindings",
    ] {
        let root = Root::new();
        let path = if relative == "." {
            root.data()
        } else {
            root.data().join(relative)
        };
        fs::set_permissions(&path, fs::Permissions::from_mode(0o500)).unwrap();
        let readonly_usable = root.load().is_ok();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o400)).unwrap();
        let denied = matches!(root.load(), Err(Error::RequiredRootUnusable));
        fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
        assert!(
            readonly_usable,
            "read/search permissions need no writable probe: {relative}"
        );
        if !denied {
            accepted.push(relative);
        }
    }
    assert!(
        accepted.is_empty(),
        "accepted unreadable descendants through non-searchable roots: {accepted:?}"
    );
}
