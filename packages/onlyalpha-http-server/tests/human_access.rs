//! Request identity admission only; not physical transport or Shipping proof.
use http::{Request, header::HeaderValue};
use onlyalpha_http_server::human_access::{Access, Admission};
use onlyalpha_product_runtime::source_access::Error;
const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
fn request(method: &str, path: &str, headers: &[(&str, &str)]) -> Request<()> {
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("host", "127.0.0.1:5173");
    for (key, value) in headers {
        builder = builder.header(*key, *value);
    }
    builder.body(()).unwrap()
}
fn cookie() -> String {
    format!("onlyalpha_dev_session={TOKEN}")
}
fn owner(access: &Access) -> onlyalpha_http_server::human_access::Session {
    match access
        .admit(&request(
            "GET",
            "/api/v2/integration-types",
            &[("cookie", &cookie())],
        ))
        .unwrap()
    {
        Admission::Owner(session) => session,
        _ => panic!("expected human identity"),
    }
}
#[test]
fn only_the_explicit_cookie_issues_a_distinct_issuer_bound_human_identity() {
    let access = Access::new(TOKEN).unwrap();
    let session = owner(&access);
    assert_eq!(session.subject_id().unwrap(), "local-developer");
    assert!(access.check_session(&session).is_ok());
    assert_eq!(
        Access::new(TOKEN).unwrap().check_session(&session),
        Err(Error::Unauthorized)
    );
    for headers in [
        vec![],
        vec![("authorization", format!("Bearer {TOKEN}"))],
        vec![("cookie", "other=1".into())],
        vec![(
            "cookie",
            format!("onlyalpha_dev_session={}", "b".repeat(64)),
        )],
    ] {
        let borrowed = headers
            .iter()
            .map(|(key, value)| (*key, value.as_str()))
            .collect::<Vec<_>>();
        assert!(matches!(
            access.admit(&request("GET", "/api/v2/integration-types", &borrowed)),
            Err(Error::Unauthorized)
        ));
    }
    assert!(matches!(
        access.admit(&request(
            "GET",
            "/api/v2/integration-types",
            &[("cookie", &format!("other=1; {}", cookie()))]
        )),
        Ok(Admission::Owner(_))
    ));
    access.withdraw();
    assert_eq!(session.subject_id(), Err(Error::Unauthorized));
    assert_eq!(access.check_session(&session), Err(Error::Unauthorized));
    assert!(matches!(
        access.admit(&request(
            "GET",
            "/api/v2/integration-types",
            &[("cookie", &cookie())]
        )),
        Err(Error::Unauthorized)
    ));
}
#[test]
fn only_guarded_root_navigation_bootstraps_the_existing_host_only_cookie() {
    let access = Access::new(TOKEN).unwrap();
    let headers = [
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-dest", "document"),
        ("sec-fetch-site", "none"),
    ];
    for path in ["/", "/?"] {
        match access.admit(&request("GET", path, &headers)).unwrap() {
            Admission::Navigation(header) => assert_eq!(
                header,
                HeaderValue::from_str(&format!("{}; HttpOnly; SameSite=Strict; Path=/", cookie()))
                    .unwrap()
            ),
            _ => panic!("no navigation"),
        }
    }
    for (path, headers) in [
        ("/", vec![]),
        ("/?input=1", headers.to_vec()),
        (
            "/",
            vec![("sec-fetch-mode", "navigate"), ("sec-fetch-dest", "iframe")],
        ),
        (
            "/",
            vec![("sec-fetch-mode", "cors"), ("sec-fetch-dest", "document")],
        ),
    ] {
        assert!(matches!(
            access.admit(&request("GET", path, &headers)),
            Err(Error::Unauthorized)
        ));
    }
    for path in ["/health/live", "/health/ready"] {
        assert!(matches!(
            access.admit(&request("GET", path, &[])),
            Ok(Admission::Health)
        ));
    }
    access.withdraw();
    for path in ["/", "/health/live", "/health/ready"] {
        assert!(matches!(
            access.admit(&request("GET", path, &headers)),
            Err(Error::Unauthorized)
        ));
    }
}
#[test]
fn guard_cardinality_and_untrusted_metadata_apply_before_anonymous_branches() {
    let access = Access::new(TOKEN).unwrap();
    for headers in [
        vec![("host", "evil.test")],
        vec![("host", "127.0.0.1:5173")],
        vec![("origin", "http://evil.test")],
        vec![
            ("origin", "http://127.0.0.1:5173"),
            ("origin", "http://127.0.0.1:5173"),
        ],
        vec![("sec-fetch-site", "cross-site")],
        vec![("sec-fetch-site", "same-site")],
        vec![("sec-fetch-site", "none"), ("sec-fetch-site", "none")],
        vec![("forwarded", "for=127.0.0.1")],
        vec![("x-forwarded-host", "127.0.0.1:5173")],
        vec![("x-user", "local-developer")],
    ] {
        for path in ["/health/live", "/api/v2/integration-types"] {
            assert!(matches!(
                access.admit(&request("GET", path, &headers)),
                Err(Error::Forbidden)
            ));
        }
    }
    let named = cookie();
    let duplicate = format!("{named}; {named}");
    let malformed = format!("onlyalpha_dev_session; {named}");
    for headers in [
        vec![("authorization", "Bearer rejected")],
        vec![("cookie", named.as_str()), ("cookie", named.as_str())],
        vec![("cookie", duplicate.as_str())],
        vec![("cookie", malformed.as_str())],
    ] {
        for path in ["/health/live", "/api/v2/integration-types"] {
            assert!(matches!(
                access.admit(&request("GET", path, &headers)),
                Err(Error::Unauthorized)
            ));
        }
    }
}
#[test]
fn mutations_and_stream_gets_require_exact_origin_from_the_request() {
    let access = Access::new(TOKEN).unwrap();
    let named = cookie();
    for (method, path) in [
        ("POST", "/api/v2/integrations"),
        ("PUT", "/api/v2/watchlists"),
        ("PATCH", "/api/v2/integrations/a"),
        ("DELETE", "/api/v2/integrations/a"),
        ("GET", "/api/v2/market-data/stream"),
    ] {
        assert!(matches!(
            access.admit(&request(method, path, &[("cookie", &named)])),
            Err(Error::Forbidden)
        ));
        assert!(matches!(
            access.admit(&request(
                method,
                path,
                &[("cookie", &named), ("origin", "http://127.0.0.1:5173")]
            )),
            Ok(Admission::Owner(_))
        ));
    }
    assert!(matches!(
        access.admit(&request(
            "GET",
            "/api/v2/market-data/quotes",
            &[("cookie", &named), ("upgrade", "websocket")]
        )),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        access.admit(&request(
            "GET",
            "/api/v2/market-data/stream",
            &[
                ("cookie", &named),
                ("origin", "http://127.0.0.1:5173"),
                ("upgrade", "websocket")
            ]
        )),
        Ok(Admission::Owner(_))
    ));
}
#[test]
fn canonical_path_boundaries_block_control_authorities_without_prefix_confusion() {
    let access = Access::new(TOKEN).unwrap();
    let named = cookie();
    for path in [
        "/internal",
        "/internal/v1/healthz",
        "/api/v2/agent",
        "/api/v2/agent/runtime",
        "/api/v2/live",
        "/api/v2/live/activate",
        "/api/v2/trading",
        "/api/v2/trading/order",
        "/api/v2/%6cive/activate",
        "/api/v2/%256cive/activate",
        "/api/v2/integrations/../live",
        "/api/v2/integrations/%2e%2e/live",
        "/api/v2/integrations/%5c../live",
        "/api/v2/integrations/%00",
        "http://127.0.0.1:5173/health/live",
    ] {
        assert!(
            matches!(
                access.admit(&request("GET", path, &[("cookie", &named)])),
                Err(Error::Forbidden)
            ),
            "{path}"
        );
    }
    for path in [
        "/api/v2/agent-providers",
        "/api/v2/agent-providers/provider",
        "/api/v2/integration-types",
        "/assets/index-abc.js",
    ] {
        assert!(
            matches!(
                access.admit(&request("GET", path, &[("cookie", &named)])),
                Ok(Admission::Owner(_))
            ),
            "{path}"
        );
    }
}
#[test]
fn invalid_credentials_cannot_become_default_configuration() {
    for credential in [
        "".to_owned(),
        "a".repeat(63),
        "a".repeat(65),
        "A".repeat(64),
        "g".repeat(64),
    ] {
        assert!(matches!(
            Access::new(&credential),
            Err(Error::InvalidConfiguration)
        ));
    }
}
