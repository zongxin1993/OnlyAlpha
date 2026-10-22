//! Native static delivery/physical filesystem evidence, not Shipping business acceptance.
#[path = "support/http.rs"]
mod http_support;
use http::StatusCode;
use http_support::request;
use onlyalpha_http_server::{
    human_access::Access,
    ingress::LocalIngress,
    web_assets::{Assets, Error},
};
use std::{
    fs::{self, DirBuilder, OpenOptions},
    io::Write,
    os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt, symlink},
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};
use tokio::net::TcpListener;
static NEXT: AtomicUsize = AtomicUsize::new(0);
const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const HTML: &str = "<!doctype html><html><body><script type=\"module\" src=\"/assets/main-a.js\"></script></body></html>";
struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "oa-assets-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        DirBuilder::new().mode(0o700).create(&p).unwrap();
        let root = Self(p);
        fs::create_dir_all(root.build().join("assets")).unwrap();
        root.write("index.html", HTML.as_bytes());
        root.write("assets/main-a.js", b"console.log('original');");
        root
    }
    fn build(&self) -> PathBuf {
        self.0.join("build")
    }
    fn write(&self, name: &str, data: &[u8]) {
        let p = self.build().join(name);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .mode(0o600)
            .open(p)
            .unwrap();
        file.write_all(data).unwrap();
    }
    fn load(&self) -> Result<Assets, Error> {
        Assets::load(&self.build(), 1024 * 1024)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
#[test]
fn missing_build_inputs_and_unbounded_assets_never_create_a_partial_service() {
    let root = Root::new();
    assert!(matches!(
        Assets::load(&root.build(), 0),
        Err(Error::Unavailable)
    ));
    assert!(matches!(
        Assets::load(&root.build(), HTML.len() + 65),
        Err(Error::Unavailable)
    ));

    assert!(matches!(
        Assets::load(Path::new("relative"), 1024),
        Err(Error::Invalid)
    ));
    fs::remove_file(root.build().join("index.html")).unwrap();
    assert!(matches!(root.load(), Err(Error::Missing)));
    root.write("index.html", b"");
    assert!(matches!(root.load(), Err(Error::Invalid)));
    root.write("index.html", HTML.as_bytes());
    let large = OpenOptions::new()
        .write(true)
        .open(root.build().join("assets/main-a.js"))
        .unwrap();
    large.set_len(8 * 1024 * 1024 + 1).unwrap();
    assert!(matches!(
        Assets::load(&root.build(), 64 * 1024 * 1024),
        Err(Error::Unavailable)
    ));
}
#[test]
fn root_ancestor_and_leaf_symlinks_cannot_redirect_the_selected_build() {
    for target in ["root", "ancestor", "index", "asset", "asset-directory"] {
        let root = Root::new();
        let path = match target {
            "root" => {
                let actual = root.0.join("actual");
                fs::rename(root.build(), &actual).unwrap();
                symlink(actual, root.build()).unwrap();
                root.build()
            }
            "ancestor" => {
                symlink(&root.0, root.0.join("alias")).unwrap();
                root.0.join("alias/build")
            }
            "index" | "asset" => {
                let leaf = if target == "index" {
                    "index.html"
                } else {
                    "assets/main-a.js"
                };
                let actual = root.0.join("actual");
                fs::rename(root.build().join(leaf), &actual).unwrap();
                symlink(actual, root.build().join(leaf)).unwrap();
                root.build()
            }
            "asset-directory" => {
                let actual = root.0.join("actual");
                fs::rename(root.build().join("assets"), &actual).unwrap();
                symlink(actual, root.build().join("assets")).unwrap();
                root.build()
            }
            _ => unreachable!(),
        };
        assert!(
            matches!(Assets::load(&path, 1024 * 1024), Err(Error::Invalid)),
            "{target}"
        );
    }
}
#[test]
fn unsafe_modes_hardlinks_and_non_shipping_entries_are_rejected() {
    for entry in ["index.html", "assets/main-a.js", "assets", "."] {
        let root = Root::new();
        let path = root.build().join(entry);
        fs::set_permissions(path, fs::Permissions::from_mode(0o777)).unwrap();
        assert!(matches!(root.load(), Err(Error::Invalid)), "{entry}");
    }
    let root = Root::new();
    fs::hard_link(root.build().join("assets/main-a.js"), root.0.join("linked")).unwrap();
    assert!(matches!(root.load(), Err(Error::Invalid)));
    for name in ["assets/.env", "assets/secret.json", "assets/index.html"] {
        let root = Root::new();
        root.write(name, b"not a shipped asset");
        assert!(matches!(root.load(), Err(Error::Invalid)), "{name}");
    }
    let root = Root::new();
    let path = root.build().join("assets/pipe.js");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &path,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR,
        0,
    )
    .unwrap();
    assert!(matches!(root.load(), Err(Error::Invalid)));
}
#[tokio::test(flavor = "current_thread")]
async fn selected_bytes_survive_path_replacement_and_use_the_real_guarded_http_pipeline() {
    let root = Root::new();
    root.write("assets/style-a.css", b"body{color:red}");
    root.write("assets/image-a.png", &[137, 80, 78, 71, 0, 255]);
    let app = root.load().unwrap().router();
    fs::rename(root.build(), root.0.join("old")).unwrap();
    fs::create_dir(root.build()).unwrap();
    root.write("index.html", b"replacement");
    fs::write(
        root.0.join("old/assets/main-a.js"),
        b"modified after snapshot",
    )
    .unwrap();
    let listener = TcpListener::bind("127.0.0.1:5173").await.unwrap();
    let ingress = LocalIngress::new_developer(Access::new(TOKEN).unwrap(), app);
    let nav = [
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-dest", "document"),
        ("sec-fetch-site", "none"),
    ];
    let (status, headers, bytes) = request(&ingress, &listener, "GET", "/", &nav, "").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(bytes, HTML.as_bytes());
    assert_eq!(headers["content-type"], "text/html; charset=utf-8");
    let issued = headers["set-cookie"].to_str().unwrap();
    let cookie = issued.split(';').next().unwrap();
    let auth = [("cookie", cookie)];
    for (path, mime, want) in [
        (
            "/assets/main-a.js",
            "text/javascript; charset=utf-8",
            b"console.log('original');".as_slice(),
        ),
        (
            "/assets/style-a.css",
            "text/css; charset=utf-8",
            b"body{color:red}".as_slice(),
        ),
        (
            "/assets/image-a.png",
            "image/png",
            [137, 80, 78, 71, 0, 255].as_slice(),
        ),
    ] {
        let (status, headers, bytes) = request(&ingress, &listener, "GET", path, &auth, "").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(bytes, want);
        assert_eq!(headers["content-type"], mime);
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-content-type-options"], "nosniff");
        assert!(!headers.contains_key("set-cookie"));
        let (status, headers, bytes) = request(&ingress, &listener, "HEAD", path, &auth, "").await;
        assert_eq!(status, StatusCode::OK);
        assert!(bytes.is_empty());
        assert_eq!(headers["content-length"], want.len().to_string());
    }
    assert_eq!(
        request(&ingress, &listener, "GET", "/assets/main-a.js", &[], "")
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
    for path in [
        "/assets/missing.js",
        "/assets/../index.html",
        "/assets/%2e%2e/index.html",
        "/assets/%252e%252e/index.html",
        "/assets/.env",
        "/src/main.tsx",
    ] {
        let (status, _, bytes) = request(&ingress, &listener, "GET", path, &auth, "").await;
        assert!(
            matches!(status, StatusCode::NOT_FOUND | StatusCode::FORBIDDEN),
            "{path}: {status}"
        );
        assert_ne!(bytes, HTML.as_bytes());
    }
    assert_eq!(
        request(&ingress, &listener, "POST", "/assets/main-a.js", &auth, "")
            .await
            .0,
        StatusCode::FORBIDDEN
    );
}

#[test]
fn excessive_tree_depth_and_entry_count_cannot_escape_the_snapshot_budget() {
    let root = Root::new();
    let nested = format!("assets/{}/main.js", ["nested"; 9].join("/"));
    root.write(&nested, b"1");
    assert!(matches!(root.load(), Err(Error::Unavailable)));
    let root = Root::new();
    for index in 0..1025 {
        root.write(&format!("assets/chunk-{index}.js"), b"1");
    }
    assert!(matches!(root.load(), Err(Error::Unavailable)));
    let root = Root::new();
    fs::remove_dir_all(root.build().join("assets")).unwrap();
    assert!(matches!(root.load(), Err(Error::Missing)));
}
