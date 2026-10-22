use onlyalpha_http_server::configuration::{Configuration, Error};
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt, symlink};
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
static NEXT: AtomicUsize = AtomicUsize::new(0);
const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const DIGEST: &str = "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb";
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "oa-config-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&path).unwrap();
        Self(path)
    }
    fn write(&self, text: &str) -> PathBuf {
        let path = self.0.join("config.json");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        file.write_all(text.as_bytes()).unwrap();
        path
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn payload(origin: &str) -> String {
    format!(
        r#"{{"schema_version":1,"subject_id":"human","bearer_sha256":"{DIGEST}","origin":"{origin}","grants":[{{"integration_id":"integration","integration_revision_fingerprint":"{}","expected_type_id":"provider","source_id":"bars","environment":"BACKTEST","permissions":["CLOSED_HISTORY"]}}]}}"#,
        "b".repeat(64)
    )
}
fn invalid(text: &str) {
    let root = Root::new();
    let path = root.write(text);
    assert!(matches!(
        Configuration::load(&path, &[]),
        Err(Error::InvalidConfiguration)
    ));
}
#[test]
fn loaded_authority_is_immutable_and_credentials_are_not_reused() {
    let root = Root::new();
    let path = root.write(&payload("http://localhost:8080"));
    let config = Configuration::load(&path, &[]).unwrap();
    assert_eq!(config.origin(), "http://localhost:8080");
    assert_eq!(config.host_header(), "localhost:8080");
    let session = config
        .authority()
        .authenticate(&format!("Bearer {TOKEN}"))
        .unwrap();
    assert_eq!(session.subject_id().unwrap(), "human");
    assert!(Configuration::load(&path, &[TOKEN]).is_err());
    assert!(Configuration::load(&path, &["unrelated", ""]).is_ok());
    fs::write(&path, b"invalid").unwrap();
    assert!(Configuration::load(&path, &[]).is_err());
    assert_eq!(session.subject_id().unwrap(), "human");
    fs::remove_file(path).unwrap();
    assert!(
        config
            .authority()
            .authenticate(&format!("Bearer {TOKEN}"))
            .is_ok()
    );
}
#[test]
fn json_objects_are_strict_at_every_level() {
    let valid = payload("http://127.0.0.1");
    for text in [
        valid.replace("\"schema_version\":1", "\"schema_version\":true"),
        valid.replace("\"schema_version\":1", "\"schema_version\":1.0"),
        valid.replace("\"schema_version\":1", "\"schema_version\":1,\"schema_version\":1"),
        valid.replace("\"schema_version\":1", "\"schema_version\":1,\"extra\":0"),
        valid.replace("\"source_id\":\"bars\"", "\"source_id\":\"bars\",\"source_id\":\"bars\""),
        valid.replace("\"source_id\":\"bars\"", "\"source_id\":\"bars\",\"extra\":0"),
        valid.replace("\"CLOSED_HISTORY\"", "\"UNKNOWN\""),
        valid.replace("\"CLOSED_HISTORY\"", "\"CLOSED_HISTORY\",\"CLOSED_HISTORY\""),
        valid.replace("\"CLOSED_HISTORY\"", "0"),
        valid.replace("\"CLOSED_HISTORY\"", "{\"CLOSED_HISTORY\":null}"),
        valid.replace("\"subject_id\":\"human\"", "\"subject_id\":null"),
        format!("{valid} true"),
        format!(r#"[1,"human","{DIGEST}","http://localhost",[]]"#),
        valid.replace(&format!(r#"{{"integration_id":"integration","integration_revision_fingerprint":"{}","expected_type_id":"provider","source_id":"bars","environment":"BACKTEST","permissions":["CLOSED_HISTORY"]}}"#, "b".repeat(64)), &format!(r#"["integration","{}","provider","bars","BACKTEST",["CLOSED_HISTORY"]]"#, "b".repeat(64))),
        valid.replace("\"grants\":[{", "\"grants\":[] ,\"discard\":[{"),
    ] { invalid(&text); }
    invalid("");
    invalid("null");
    invalid("{}");
}
#[test]
fn only_exact_loopback_origins_are_admitted() {
    for origin in [
        "http://localhost",
        "https://LOCALHOST:443",
        "HTTP://localhost",
        "http://127.0.0.1:0",
        "http://[::1]:65535",
    ] {
        let root = Root::new();
        let path = root.write(&payload(origin));
        assert!(Configuration::load(&path, &[]).is_ok(), "{origin}");
    }
    for origin in [
        "localhost",
        "ftp://localhost",
        "http://example.com",
        "http://localhost/",
        "http://localhost?",
        "http://localhost#",
        "http://user@localhost",
        "http://localhost:",
        "http://localhost:65536",
        "http://localhost:abc",
        "http://localhost:80:90",
        "http://[::ffff:127.0.0.1]",
        "http://localhost.evil",
        "http://127.1",
        " http://localhost",
        "http://localhost\\evil",
    ] {
        invalid(&payload(origin));
    }
}
#[test]
fn filesystem_permissions_links_types_and_bounds_fail_closed() {
    let root = Root::new();
    let path = root.write(&payload("http://localhost"));
    for mode in [0o640, 0o604, 0o666] {
        fs::set_permissions(&path, fs::Permissions::from_mode(mode)).unwrap();
        assert!(Configuration::load(&path, &[]).is_err());
    }
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let link = root.0.join("link");
    symlink(&path, &link).unwrap();
    assert!(Configuration::load(&link, &[]).is_err());
    let hard = root.0.join("hard");
    fs::hard_link(&path, &hard).unwrap();
    assert!(Configuration::load(&path, &[]).is_err());
    fs::remove_file(hard).unwrap();
    let parent = root.0.join("parent");
    symlink(&root.0, &parent).unwrap();
    assert!(Configuration::load(&parent.join("config.json"), &[]).is_err());
    assert!(Configuration::load(&root.0, &[]).is_err());
    assert!(Configuration::load(&PathBuf::from("relative.json"), &[]).is_err());
    assert!(Configuration::load(&root.0.join("../config.json"), &[]).is_err());
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(Configuration::load(&path, &[]).is_err());
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o700)).unwrap();
    for bytes in [vec![], vec![b' '; 32769], vec![255; 4]] {
        fs::write(&path, bytes).unwrap();
        assert!(Configuration::load(&path, &[]).is_err());
    }
}
#[test]
fn fifo_is_rejected_without_waiting_for_a_writer() {
    let root = Root::new();
    let path = root.0.join("fifo");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &path,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    assert!(Configuration::load(&path, &[]).is_err());
}
#[test]
fn bounded_reads_and_all_failure_paths_release_descriptors() {
    let root = Root::new();
    let valid = payload("https://localhost");
    let path = root.write(&valid);
    let mut exact = valid.clone();
    exact.push_str(&" ".repeat(32768 - valid.len()));
    fs::write(&path, exact).unwrap();
    assert!(Configuration::load(&path, &[]).is_ok());
    let before = fs::read_dir("/proc/self/fd").unwrap().count();
    for text in [valid, "invalid".to_owned()] {
        fs::write(&path, text).unwrap();
        for _ in 0..64 {
            let _ = Configuration::load(&path, &[]);
        }
    }
    assert_eq!(fs::read_dir("/proc/self/fd").unwrap().count(), before);
}

#[test]
fn arbitrary_utf8_gateway_credentials_are_excluded_too() {
    let root = Root::new();
    let text = payload("http://localhost").replace(
        DIGEST,
        "7f66cb42235283ffaf1eec969a443bc7357511e924901109a2a618a0dd85c4d2",
    );
    let path = root.write(&text);
    assert!(Configuration::load(&path, &["gateway-密钥"]).is_err());
    assert!(Configuration::load(&path, &["unrelated"]).is_ok());
}
#[test]
fn private_profile_requires_a_nonempty_bounded_grant_set() {
    let base = payload("http://localhost");
    let start = base.find("\"grants\":[").unwrap() + "\"grants\":[".len();
    let grant = &base[start..base.len() - 2];
    for count in [0, 1, 32, 33] {
        let grants = (0..count)
            .map(|index| {
                grant.replace(
                    "\"integration_id\":\"integration\"",
                    &format!("\"integration_id\":\"integration-{index}\""),
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        let text = format!("{}{}]}}", &base[..start], grants);
        let root = Root::new();
        let path = root.write(&text);
        assert_eq!(
            Configuration::load(&path, &[]).is_ok(),
            (1..=32).contains(&count)
        );
    }
    invalid(&format!("{}{grant},{grant}]}}", &base[..start]));
}

#[test]
fn runtime_master_key_loads_original_raw_bytes_once_without_rewriting_them() {
    use onlyalpha_http_server::configuration::load_master_key;
    use onlyalpha_product_runtime::credentials::{Context, CredentialId, Key, Secret, Slot};
    let root = Root::new();
    let path = root.write("kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk");
    let context = Context::new(
        CredentialId::new("11111111-1111-4111-8111-111111111111").unwrap(),
        Slot::new("INTEGRATION", "controlled", "api_key").unwrap(),
        1,
        1,
    )
    .unwrap();
    let original = Key::new(&[b'k'; 32]).unwrap();
    let envelope = original
        .encrypt(&context, &Secret::new("controlled").unwrap(), 65536)
        .unwrap();
    let loaded = load_master_key(&path).unwrap();
    assert_eq!(
        loaded.decrypt(&context, &envelope, 65536).unwrap().expose(),
        "controlled"
    );
    assert_eq!(fs::read(&path).unwrap(), [b'k'; 32]);
    fs::write(&path, [0xff; 32]).unwrap();
    assert_eq!(
        loaded.decrypt(&context, &envelope, 65536).unwrap().expose(),
        "controlled"
    );
    let changed = load_master_key(&path).unwrap();
    assert!(changed.decrypt(&context, &envelope, 65536).is_err());
    let binary = Key::new(&[0xff; 32])
        .unwrap()
        .encrypt(&context, &Secret::new("binary").unwrap(), 65536)
        .unwrap();
    assert_eq!(
        changed.decrypt(&context, &binary, 65536).unwrap().expose(),
        "binary"
    );
    assert_eq!(fs::read(&path).unwrap(), [0xff; 32]);
}

#[test]
fn runtime_master_key_missing_or_malformed_never_creates_or_repairs_a_file() {
    use onlyalpha_http_server::configuration::{MasterKeyFileError, load_master_key};
    let root = Root::new();
    let path = root.0.join("missing");
    assert_eq!(
        load_master_key(&path).err().unwrap(),
        MasterKeyFileError::Missing
    );
    assert!(!path.exists());
    assert_eq!(fs::read_dir(&root.0).unwrap().count(), 0);
    for size in [0, 31, 33, 32769] {
        let root = Root::new();
        let path = root.write("");
        let bytes = vec![b'k'; size];
        fs::write(&path, &bytes).unwrap();
        assert_eq!(
            load_master_key(&path).err().unwrap(),
            MasterKeyFileError::Invalid
        );
        assert_eq!(fs::read(path).unwrap(), bytes);
    }
    assert!(load_master_key(std::path::Path::new("relative-key")).is_err());
}

#[test]
fn runtime_master_key_reuses_the_protected_file_boundary() {
    use onlyalpha_http_server::configuration::load_master_key;
    let root = Root::new();
    let path = root.write("kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk");
    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
    assert!(load_master_key(&path).is_err());
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    let link = root.0.join("link");
    symlink(&path, &link).unwrap();
    assert!(load_master_key(&link).is_err());
    fs::hard_link(&path, root.0.join("hardlink")).unwrap();
    assert!(load_master_key(&path).is_err());
    fs::remove_file(root.0.join("hardlink")).unwrap();
    let alias = root.0.join("alias");
    symlink(&root.0, &alias).unwrap();
    assert!(load_master_key(&alias.join("config.json")).is_err());
    assert!(load_master_key(&root.0.join(".").join("config.json")).is_err());
    let fifo = root.0.join("fifo");
    assert!(
        std::process::Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .unwrap()
            .success()
    );
    assert!(load_master_key(&fifo).is_err());
    assert!(load_master_key(&root.0).is_err());
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(load_master_key(&path).is_err());
    fs::set_permissions(&root.0, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(load_master_key(&path).is_ok());
}
