use crate::transport::routes::navigation;
use http::{Method, Request};

fn navigation_paths() -> [&'static str; 8] {
    [
        "/",
        "/overview",
        "/research/new",
        "/strategies",
        "/backtest",
        "/backtest/runs",
        "/data/inputs",
        "/system/health",
    ]
}

#[test]
fn human_navigation_serves_every_registered_screen_page() {
    for path in navigation_paths() {
        let request = Request::builder()
            .method(Method::GET)
            .uri(path)
            .body(())
            .expect("request builds");
        assert!(
            navigation(request.method(), path),
            "{path} must be a navigation page"
        );
    }
}

#[test]
fn human_navigation_rejects_unregistered_and_non_get_paths() {
    for path in ["/overview-x", "/totally-unknown", "/assets/app.js"] {
        let request = Request::builder()
            .method(Method::GET)
            .uri(path)
            .body(())
            .expect("request builds");
        assert!(
            !navigation(request.method(), path),
            "{path} is not a navigation page"
        );
    }
    let request = Request::builder()
        .method(Method::POST)
        .uri("/overview")
        .body(())
        .expect("request builds");
    assert!(!navigation(request.method(), "/overview"));
}
