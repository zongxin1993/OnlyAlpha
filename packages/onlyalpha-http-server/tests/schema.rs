use onlyalpha_http_server::configuration::load_schema_history;
use onlyalpha_product_runtime::schema::{Error, SchemaHistory};
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt, symlink};
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-schema-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        Self(path)
    }
    fn write(&self, name: &str, bytes: &[u8]) -> PathBuf {
        let path = self.0.join(name);
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o644)
            .open(&path)
            .unwrap();
        file.write_all(bytes).unwrap();
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
fn only_selected_current_source_files_and_exact_original_bytes_define_the_snapshot() {
    let root = Root::new();
    let second = root.write("0002_second.sql", b"SELECT 2;\r\n");
    root.write("0001_first.sql", b"SELECT 1;\n");
    root.write("0003_.sql", b"");
    root.write("README.md", b"not SQL");
    root.write("0000_ignore.sql.bak", b"ignored");
    let expected = SchemaHistory::from_sql(
        vec![
            ("0001_first".into(), b"SELECT 1;\n".to_vec()),
            ("0002_second".into(), b"SELECT 2;\r\n".to_vec()),
            ("0003_".into(), vec![]),
        ],
        4096,
    )
    .unwrap();
    let loaded = load_schema_history(&root.0, 4096).unwrap();
    assert_eq!(loaded, expected);
    fs::write(&second, b"SELECT 3;\n").unwrap();
    assert_ne!(load_schema_history(&root.0, 4096).unwrap(), loaded);
    assert_eq!(loaded, expected);
}
#[test]
fn absent_or_empty_input_never_falls_back_or_initializes() {
    let root = Root::new();
    let missing = root.0.join("absent");
    assert_eq!(load_schema_history(&missing, 4096), Err(Error::Integrity));
    assert!(!missing.exists());
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    assert_eq!(fs::read_dir(&root.0).unwrap().count(), 0);
    assert_eq!(
        load_schema_history(&PathBuf::from("relative"), 4096),
        Err(Error::Integrity)
    );
}
#[test]
fn individual_and_whole_directory_budget_exhaustion_is_unavailable() {
    let root = Root::new();
    let path = root.write("0001_first.sql", &vec![b' '; 32768]);
    assert!(load_schema_history(&root.0, 65536).is_ok());
    assert_eq!(load_schema_history(&root.0, 0), Err(Error::Unavailable));
    fs::write(&path, vec![b' '; 32769]).unwrap();
    assert_eq!(
        load_schema_history(&root.0, 1048576),
        Err(Error::Unavailable)
    );
    assert_eq!(fs::metadata(&path).unwrap().len(), 32769);
    fs::write(&path, vec![b' '; 20000]).unwrap();
    root.write("0002_second.sql", &vec![b' '; 20000]);
    root.write("0003_third.sql", &vec![b' '; 20000]);
    assert_eq!(load_schema_history(&root.0, 50000), Err(Error::Unavailable));
    assert!(load_schema_history(&root.0, 70000).is_ok());
}
#[test]
fn invalid_source_bytes_are_not_silently_decoded_or_repaired() {
    let root = Root::new();
    let path = root.write("0001_first.sql", &[0xff]);
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    assert_eq!(fs::read(&path).unwrap(), vec![0xff]);
}
#[test]
fn unsafe_root_entry_and_file_permissions_cannot_supply_expected_history() {
    let root = Root::new();
    let path = root.write("0001_first.sql", b"SELECT 1;");
    let alias = root.0.join("alias");
    symlink(&root.0, &alias).unwrap();
    assert_eq!(load_schema_history(&alias, 4096), Err(Error::Integrity));
    assert_eq!(
        load_schema_history(&root.0.join("."), 4096),
        Err(Error::Integrity)
    );
    fs::set_permissions(&path, fs::Permissions::from_mode(0o666)).unwrap();
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o777)).unwrap();
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o700)).unwrap();
    let link = root.0.join("0002_link.sql");
    symlink(&path, &link).unwrap();
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    fs::remove_file(link).unwrap();
    let fifo = root.0.join("0002_fifo.sql");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &fifo,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
    fs::remove_file(fifo).unwrap();
    fs::create_dir(root.0.join("0002_directory.sql")).unwrap();
    assert_eq!(load_schema_history(&root.0, 4096), Err(Error::Integrity));
}
