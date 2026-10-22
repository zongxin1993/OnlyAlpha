//! Real loopback HTTP infrastructure proof, not Shipping UI acceptance.
use axum::{
    Router,
    extract::Request,
    routing::{get, post},
};
use http::{HeaderMap, StatusCode};
use onlyalpha_http_server::{human_access::Access, ingress::LocalIngress, integration_types};
use onlyalpha_product_runtime::{
    integration_catalog::AuthoringCatalog, source_access::Session as SourceSession,
};
use serde_json::{Value, json};
use std::sync::Arc;
use tokio::net::{TcpListener, TcpStream};
const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
fn unadmitted_command() -> StatusCode {
    panic!("unadmitted command must not run")
}
fn app(fail_root: bool) -> Router {
    integration_types::router(Arc::new(AuthoringCatalog::new(vec![]).unwrap()))
        .route(
            "/",
            get(move || async move {
                if fail_root {
                    (StatusCode::SERVICE_UNAVAILABLE, "index unavailable")
                } else {
                    (StatusCode::OK, "<html>controlled transport input</html>")
                }
            }),
        )
        .route(
            "/assets/identity.json",
            get(|request: Request| async move {
                let human = request
                    .extensions()
                    .get::<onlyalpha_http_server::human_access::Session>()
                    .unwrap();
                assert!(request.extensions().get::<SourceSession>().is_none());
                axum::Json(json!({"subject":human.subject_id().unwrap()}))
            }),
        )
        .route("/health/live", get(|| async { "live" }))
        .route(
            "/api/v2/integrations",
            post(|| async { unadmitted_command() }),
        )
}
use http_support::request;
#[path = "support/http.rs"]
mod http_support;
fn protected(headers: &HeaderMap) {
    assert_eq!(headers["cache-control"], "no-store");
    assert_eq!(headers["x-frame-options"], "DENY");
    assert_eq!(headers["content-security-policy"], "frame-ancestors 'none'");
}
#[tokio::test(flavor = "current_thread")]
async fn guarded_bootstrap_cookie_and_actual_native_type_routes_share_the_http_pipeline() {
    // Fixed origin is the actual dev contract. This container-local technical
    // listener publishes no host port and creates no second application deployment.
    let listener = TcpListener::bind("127.0.0.1:5173").await.unwrap();
    let ingress = LocalIngress::new_developer(Access::new(TOKEN).unwrap(), app(false));
    let (status, headers, _) = request(&ingress, &listener, "GET", "/", &[], "").await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    protected(&headers);
    assert!(!headers.contains_key("set-cookie"));
    let navigation = [
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-dest", "document"),
        ("sec-fetch-site", "none"),
    ];
    let (status, headers, _) = request(&ingress, &listener, "GET", "/", &navigation, "").await;
    assert_eq!(status, StatusCode::OK);
    protected(&headers);
    let issued = headers["set-cookie"].to_str().unwrap();
    assert!(issued.contains("HttpOnly"));
    assert!(issued.contains("SameSite=Strict"));
    assert!(issued.contains("Path=/"));
    assert!(!issued.contains("Domain="));
    let cookie = issued.split(';').next().unwrap().to_owned();
    let (status, headers, bytes) = request(
        &ingress,
        &listener,
        "GET",
        "/api/v2/integration-types?category=DATA_SOURCE",
        &[("cookie", &cookie)],
        "",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    protected(&headers);
    assert!(!headers.contains_key("set-cookie"));
    assert_eq!(
        serde_json::from_slice::<Value>(&bytes).unwrap(),
        json!({"items":[]})
    );
    let (status, _, bytes) = request(
        &ingress,
        &listener,
        "GET",
        "/assets/identity.json",
        &[("cookie", &cookie)],
        "",
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        serde_json::from_slice::<Value>(&bytes).unwrap(),
        json!({"subject":"local-developer"})
    );
    for headers in [
        vec![],
        vec![("authorization", format!("Bearer {TOKEN}"))],
        vec![("cookie", "onlyalpha_dev_session=wrong".into())],
        vec![("cookie", cookie.clone()), ("cookie", cookie.clone())],
    ] {
        let borrowed = headers
            .iter()
            .map(|(key, value)| (*key, value.as_str()))
            .collect::<Vec<_>>();
        let (status, headers, _) = request(
            &ingress,
            &listener,
            "GET",
            "/api/v2/integration-types",
            &borrowed,
            "",
        )
        .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
        protected(&headers);
    }
    for extra in [
        ("host", "evil.test"),
        ("origin", "http://evil.test"),
        ("sec-fetch-site", "cross-site"),
        ("x-forwarded-for", "127.0.0.1"),
    ] {
        assert_eq!(
            request(
                &ingress,
                &listener,
                "GET",
                "/api/v2/integration-types",
                &[("cookie", &cookie), extra],
                ""
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );
    }
    assert_eq!(
        request(
            &ingress,
            &listener,
            "POST",
            "/api/v2/integrations",
            &[
                ("cookie", &cookie),
                ("origin", "http://127.0.0.1:5173"),
                ("content-type", "application/json")
            ],
            "{}"
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        request(
            &ingress,
            &listener,
            "GET",
            "/api/v2/integration-types",
            &[("cookie", &cookie)],
            "{}"
        )
        .await
        .0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        request(
            &ingress,
            &listener,
            "HEAD",
            "/api/v2/integration-types",
            &[("cookie", &cookie)],
            ""
        )
        .await
        .0,
        StatusCode::METHOD_NOT_ALLOWED
    );
    let failing = LocalIngress::new_developer(Access::new(TOKEN).unwrap(), app(true));
    let (status, headers, _) = request(&failing, &listener, "GET", "/", &navigation, "").await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert!(!headers.contains_key("set-cookie"));
    let (status, headers, _) = request(&ingress, &listener, "GET", "/health/live", &[], "").await;
    assert_eq!(status, StatusCode::OK);
    protected(&headers);
    assert!(!headers.contains_key("set-cookie"));
    for path in [
        "/api/v2/market-data/sources",
        "/api/v2/chart/studies/capabilities",
        "/api/v2/market-data/stream",
    ] {
        assert_eq!(
            request(
                &ingress,
                &listener,
                "GET",
                path,
                &[("cookie", &cookie), ("origin", "http://127.0.0.1:5173")],
                ""
            )
            .await
            .0,
            StatusCode::FORBIDDEN
        );
    }
    let wrong_port = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let client = TcpStream::connect(wrong_port.local_addr().unwrap())
        .await
        .unwrap();
    let (server, _) = wrong_port.accept().await.unwrap();
    assert_eq!(
        ingress.serve_connection(server).await,
        Err(onlyalpha_http_server::ingress::Error::UnsupportedTransport)
    );
    drop(client);
    ingress.withdraw().unwrap();
    for path in ["/", "/health/live", "/api/v2/integration-types"] {
        assert_eq!(
            request(&ingress, &listener, "GET", path, &[("cookie", &cookie)], "")
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );
    }
}
