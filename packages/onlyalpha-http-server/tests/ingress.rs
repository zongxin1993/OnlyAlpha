//! Native transport infrastructure fixtures; these do not certify a Product flow.
use axum::{
    Extension, Json, Router,
    body::{Body, to_bytes},
    routing::get,
};
use http::{Request, StatusCode};
use hyper_util::rt::TokioIo;
use onlyalpha_http_server::{configuration::Configuration, ingress::LocalIngress};
use onlyalpha_product_runtime::source_access::Session;
use serde_json::{Value, json};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    net::SocketAddr,
    os::unix::fs::OpenOptionsExt,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};
use tokio::net::{TcpListener, TcpStream};

const TOKEN: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static NEXT: AtomicUsize = AtomicUsize::new(0);
struct ConfigFile(PathBuf);
impl ConfigFile {
    fn load(origin: &str) -> (Self, Configuration) {
        let path = std::env::temp_dir().join(format!(
            "oa-ingress-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        write!(file, "{}", json!({"schema_version":1,"subject_id":"human","bearer_sha256":"ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb","origin":origin,"grants":[{"integration_id":"integration","integration_revision_fingerprint":"b".repeat(64),"expected_type_id":"provider","source_id":"bars","environment":"BACKTEST","permissions":["CLOSED_HISTORY"]}]})).unwrap();
        let config = Configuration::load(&path, &[]).unwrap();
        (Self(path), config)
    }
}
impl Drop for ConfigFile {
    fn drop(&mut self) {
        fs::remove_file(&self.0).unwrap();
    }
}
async fn protected(Extension(session): Extension<Session>) -> Json<Value> {
    Json(json!({"subject":session.subject_id().unwrap()}))
}
fn router() -> Router {
    Router::new()
        .route(
            "/health/live",
            get(|| async { Json(json!({"health":"live"})) }),
        )
        .route("/api/v2/market-data/sources", get(protected))
        .route("/api/v2/market-data/acquisitions/{id}", get(protected))
}
async fn request(
    ingress: &LocalIngress,
    listener: &TcpListener,
    path: &str,
    headers: &[(&str, &str)],
) -> (StatusCode, Value) {
    let address: SocketAddr = listener.local_addr().unwrap();
    let stream = TcpStream::connect(address).await.unwrap();
    let (server, _) = listener.accept().await.unwrap();
    let owned = ingress.clone();
    let server_task = tokio::spawn(async move { owned.serve_connection(server).await });
    let (mut sender, connection) = hyper::client::conn::http1::handshake(TokioIo::new(stream))
        .await
        .unwrap();
    let client_task = tokio::spawn(connection);
    let mut builder = Request::builder()
        .uri(path)
        .header("host", address.to_string());
    for (key, value) in headers {
        builder = builder.header(*key, *value);
    }
    let response = sender
        .send_request(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(Body::new(response.into_body()), 1024 * 1024)
        .await
        .unwrap();
    drop(sender);
    server_task.await.unwrap().unwrap();
    client_task.await.unwrap().unwrap();
    (status, serde_json::from_slice(&body).unwrap())
}
#[tokio::test(flavor = "current_thread")]
async fn exact_source_session_and_withdrawal_preserve_public_health() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (_file, config) = ConfigFile::load(&format!("http://{}", listener.local_addr().unwrap()));
    let ingress = LocalIngress::new(config, router(), false).unwrap();
    let authorization = format!("Bearer {TOKEN}");
    let path = "/api/v2/market-data/sources";
    assert_eq!(
        request(&ingress, &listener, path, &[]).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        request(
            &ingress,
            &listener,
            path,
            &[("authorization", &authorization)]
        )
        .await,
        (StatusCode::OK, json!({"subject":"human"}))
    );
    ingress.withdraw().unwrap();
    assert_eq!(
        request(
            &ingress,
            &listener,
            path,
            &[("authorization", &authorization)]
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        request(&ingress, &listener, "/health/live", &[]).await,
        (StatusCode::OK, json!({"health":"live"}))
    );
    assert_eq!(ingress.active_work(), 0);
}
#[tokio::test(flavor = "current_thread")]
async fn private_route_decoding_is_closed_and_rejects_double_encoding() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (_file, config) = ConfigFile::load(&format!("http://{}", listener.local_addr().unwrap()));
    let ingress = LocalIngress::new(config, router(), false).unwrap();
    let authorization = format!("Bearer {TOKEN}");
    for path in [
        "/api/v2/market-data/%73ources",
        "/api/v2/market-data/acquisitions/run%3A1",
    ] {
        assert_eq!(
            request(
                &ingress,
                &listener,
                path,
                &[("authorization", &authorization)]
            )
            .await
            .0,
            StatusCode::OK,
            "{path}"
        );
    }
    for path in [
        "/api/v2/market-data/acquisitions/%",
        "/api/v2/market-data/acquisitions/%2",
        "/api/v2/market-data/acquisitions/%GG",
        "/api/v2/market-data/acquisitions/%252F",
        "/api/v2/market-data/acquisitions/%252e",
        "/api/v2/market-data/acquisitions/a%2Fb",
        "/api/v2/product/commands",
        "/api/v2/market-data/acquisitions/%FF",
    ] {
        assert_eq!(
            request(
                &ingress,
                &listener,
                path,
                &[("authorization", &authorization)]
            )
            .await
            .0,
            StatusCode::FORBIDDEN,
            "{path}"
        );
    }
}
#[test]
fn clear_http_adapter_never_downgrades_https_configuration() {
    let (_file, config) = ConfigFile::load("https://localhost:8443");
    assert!(LocalIngress::new(config, router(), false).is_err());
}

async fn raw_request(ingress: &LocalIngress, listener: &TcpListener, raw: &[u8]) -> Vec<u8> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut client = TcpStream::connect(listener.local_addr().unwrap())
        .await
        .unwrap();
    let (server, _) = listener.accept().await.unwrap();
    let owned = ingress.clone();
    let task = tokio::spawn(async move { owned.serve_connection(server).await });
    client.write_all(raw).await.unwrap();
    let mut response = Vec::new();
    // Invalid HTTP may close without a Product JSON response.
    let _ = client.read_to_end(&mut response).await;
    let _ = task.await.unwrap();
    response
}
#[tokio::test(flavor = "current_thread")]
async fn raw_duplicate_framing_is_denied_before_owning_handler() {
    use std::sync::Arc;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (_file, config) = ConfigFile::load(&format!("http://{address}"));
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let app = Router::new().route(
        "/api/v2/market-data/sources",
        get(move || {
            let observed = observed.clone();
            async move {
                observed.fetch_add(1, Ordering::SeqCst);
                Json(json!({"source":true}))
            }
        }),
    );
    let ingress = LocalIngress::new(config, app, false).unwrap();
    for extra in [
        "Content-Length: 0\r\ncOnTeNt-LeNgTh: 0\r\n",
        "Content-Length: 0\r\nContent-Length: 00\r\n",
        "Content-Length: 0\r\nTransfer-Encoding: chunked\r\n",
        "Host: duplicate\r\n",
        "Forwarded: for=127.0.0.1\r\n",
        "Origin: http://untrusted\r\n",
        "Authorization: invalid\r\n",
    ] {
        let raw = format!(
            "GET /api/v2/market-data/sources HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {TOKEN}\r\n{extra}\r\n"
        );
        let response = raw_request(&ingress, &listener, raw.as_bytes()).await;
        let text = String::from_utf8(response).unwrap();
        let expected = if extra.starts_with("Authorization:") {
            "HTTP/1.1 401"
        } else {
            "HTTP/1.1 403"
        };
        assert!(text.starts_with(expected), "{text}");
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    let raw = format!(
        "GET /api/v2/market-data/sources HTTP/1.1\r\nHost: {address}\r\nContent-Length: 0\r\nContent-Length: 1\r\n\r\n"
    );
    let response = raw_request(&ingress, &listener, raw.as_bytes()).await;
    assert!(response.is_empty() || response.starts_with(b"HTTP/1.1 400"));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let once = format!(
        "GET /api/v2/market-data/sources HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {TOKEN}\r\n\r\n"
    );
    let response = raw_request(&ingress, &listener, format!("{once}{once}").as_bytes()).await;
    assert!(response.starts_with(b"HTTP/1.1 200"));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test(flavor = "current_thread")]
async fn chart_post_and_raw_query_use_the_same_native_pipeline() {
    use axum::routing::post;
    use std::sync::Arc;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (_file, config) = ConfigFile::load(&format!("http://{address}"));
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = calls.clone();
    let app = Router::new()
        .route(
            "/api/v2/chart/studies/evaluate",
            post(
                move |Extension(session): Extension<Session>, Json(value): Json<Value>| {
                    let observed = observed.clone();
                    async move {
                        session.subject_id().unwrap();
                        observed.fetch_add(1, Ordering::SeqCst);
                        Json(value)
                    }
                },
            ),
        )
        .route(
            "/api/v2/market-data/sources",
            get(|uri: http::Uri| async move { Json(json!({"raw_query":uri.query()})) }),
        );
    let ingress = LocalIngress::new(config, app, true).unwrap();
    for (body, expected) in [
        (r#"{"x":[1,2],"nested":{"x":3}}"#, "HTTP/1.1 200"),
        (r#"{"x":1,"x":2}"#, "HTTP/1.1 400"),
        (r#"{"nested":[{"x":1,"\u0078":2}]}"#, "HTTP/1.1 400"),
        ("{}{}", "HTTP/1.1 400"),
        ("NaN", "HTTP/1.1 400"),
    ] {
        let raw = format!(
            "POST /api/v2/chart/studies/evaluate HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {TOKEN}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",
            body.len()
        );
        let bytes = raw_request(&ingress, &listener, raw.as_bytes()).await;
        assert!(
            bytes.starts_with(expected.as_bytes()),
            "{}",
            String::from_utf8_lossy(&bytes)
        );
        if expected.ends_with("400") {
            assert!(String::from_utf8_lossy(&bytes).contains("CHART_STUDY_REQUEST_INVALID"));
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }
    let authorization = format!("Bearer {TOKEN}");
    let (status, value) = request(
        &ingress,
        &listener,
        "/api/v2/market-data/%73ources?value=%252F&value=%E4%B8%AD",
        &[("authorization", &authorization)],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(value, json!({"raw_query":"value=%252F&value=%E4%B8%AD"}));
    for (path, expected) in [
        (
            format!("/api/v2/market-data/sources?{}", "x".repeat(4096)),
            StatusCode::OK,
        ),
        (
            format!("/api/v2/market-data/sources?{}", "x".repeat(4097)),
            StatusCode::FORBIDDEN,
        ),
    ] {
        assert_eq!(
            request(
                &ingress,
                &listener,
                &path,
                &[("authorization", &authorization)]
            )
            .await
            .0,
            expected
        );
    }
}

#[tokio::test(flavor = "current_thread")]
async fn actual_tcp_shutdown_keeps_owned_handler_until_drain_and_returns_no_late_bytes() {
    use std::{
        future::Future,
        sync::{Arc, Mutex},
        task::Poll,
    };
    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        sync::{Semaphore, oneshot},
    };
    let release = Arc::new(Semaphore::new(0));
    let (entered, observed) = oneshot::channel();
    let entered = Arc::new(Mutex::new(Some(entered)));
    let app = Router::new().route(
        "/api/v2/market-data/sources",
        get({
            let release = release.clone();
            move |Extension(session): Extension<Session>| {
                let release = release.clone();
                let entered = entered.clone();
                async move {
                    session.check_active().unwrap();
                    entered.lock().unwrap().take().unwrap().send(()).unwrap();
                    release.acquire().await.unwrap().forget();
                    Json(json!({"result":"completed after disconnect"}))
                }
            }
        }),
    );
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (_file, config) = ConfigFile::load(&format!("http://{address}"));
    let ingress = LocalIngress::new(config, app, false).unwrap();
    let mut client = TcpStream::connect(address).await.unwrap();
    let (socket, _) = listener.accept().await.unwrap();
    let owned = ingress.clone();
    let connection = tokio::spawn(async move { owned.serve_connection(socket).await });
    client.write_all(format!("GET /api/v2/market-data/sources HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {TOKEN}\r\n\r\n").as_bytes()).await.unwrap();
    observed.await.unwrap();
    let drain = ingress.shutdown_and_drain();
    tokio::pin!(drain);
    std::future::poll_fn(|cx| {
        assert!(drain.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    assert!(connection.await.unwrap().is_err());
    let mut bytes = Vec::new();
    client.read_to_end(&mut bytes).await.unwrap();
    assert!(bytes.is_empty());
    assert_eq!(ingress.active_work(), 1);
    assert_eq!(ingress.retained_reads(), 1);
    std::future::poll_fn(|cx| {
        assert!(drain.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    release.add_permits(1);
    drain.await.unwrap();
    assert_eq!(ingress.active_work(), 0);
    assert_eq!(ingress.retained_reads(), 0);
}
