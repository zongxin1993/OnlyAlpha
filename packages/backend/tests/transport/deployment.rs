use onlyalpha_backend::bootstrap::deployment::Error;
use onlyalpha_backend::bootstrap::deployment::load_semantic_store_id;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt, symlink};
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
static NEXT: AtomicUsize = AtomicUsize::new(0);
const ID: &str = "550e8400-e29b-41d4-a716-446655440000";
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-deployment-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        Self(path)
    }
    fn write(&self) -> PathBuf {
        let path = self.0.join(".onlyalpha-semantic-store.json");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o644)
            .open(&path)
            .unwrap();
        write!(file, r#"{{"schema_version":1,"store_id":"{ID}"}}"#).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        path
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
#[test]
fn existing_public_metadata_and_interrupted_link_publication_remain_readable() {
    let root = Root::new();
    let path = root.write();
    fs::hard_link(&path, root.0.join(".publication.tmp")).unwrap();
    let loaded = load_semantic_store_id(&path).unwrap();
    assert_eq!(loaded.value(), ID);
    let other = Root::new();
    let other_path = other.write();
    assert_eq!(load_semantic_store_id(&other_path).unwrap(), loaded);
    fs::write(&path, b"invalid").unwrap();
    assert_eq!(loaded.value(), ID);
    assert_eq!(load_semantic_store_id(&path), Err(Error::Corrupt));
    fs::remove_file(&path).unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Missing));
    assert!(!path.exists());
}
#[test]
fn missing_does_not_initialize_or_repair_and_operational_bound_is_not_corruption() {
    let root = Root::new();
    let missing = root.0.join("absent").join("identity");
    assert_eq!(load_semantic_store_id(&missing), Err(Error::Missing));
    assert!(!root.0.join("absent").exists());
    let path = root.write();
    fs::write(&path, vec![b' '; 32769]).unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Unavailable));
    assert_eq!(fs::metadata(&path).unwrap().len(), 32769);
    fs::write(&path, b"").unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Corrupt));
    fs::write(&path, [0xff]).unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Corrupt));
}
#[test]
fn symlink_paths_writable_metadata_and_fifo_never_supply_identity() {
    let root = Root::new();
    let path = root.write();
    let alias = root.0.join("alias");
    symlink(&path, &alias).unwrap();
    assert_eq!(load_semantic_store_id(&alias), Err(Error::Corrupt));
    let alias_dir = root.0.join("alias-dir");
    symlink(&root.0, &alias_dir).unwrap();
    assert_eq!(
        load_semantic_store_id(&alias_dir.join(".onlyalpha-semantic-store.json")),
        Err(Error::Corrupt)
    );
    assert_eq!(
        load_semantic_store_id(&root.0.join(".").join(".onlyalpha-semantic-store.json")),
        Err(Error::Corrupt)
    );
    assert_eq!(
        load_semantic_store_id(&PathBuf::from("relative")),
        Err(Error::Corrupt)
    );
    fs::set_permissions(&path, fs::Permissions::from_mode(0o666)).unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Corrupt));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o777)).unwrap();
    assert_eq!(load_semantic_store_id(&path), Err(Error::Corrupt));
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o700)).unwrap();
    let fifo = root.0.join("fifo");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &fifo,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    assert_eq!(load_semantic_store_id(&fifo), Err(Error::Corrupt));
}

#[test]
fn metadata_read_sharing_does_not_relax_secret_file_policy() {
    use onlyalpha_backend::bootstrap::configuration::{MasterKeyFileError, load_master_key};
    let root = Root::new();
    let path = root.0.join("key");
    fs::write(&path, [7; 32]).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(matches!(
        load_master_key(&path),
        Err(MasterKeyFileError::Invalid)
    ));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    fs::hard_link(&path, root.0.join("key-alias")).unwrap();
    assert!(matches!(
        load_master_key(&path),
        Err(MasterKeyFileError::Invalid)
    ));
    fs::remove_file(root.0.join("key-alias")).unwrap();
    assert!(load_master_key(&path).is_ok());
}
