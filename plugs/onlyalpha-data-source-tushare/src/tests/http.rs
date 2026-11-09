use super::*;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, pem::PemObject};
use std::{
    io::{Read, Write},
    net::TcpListener,
    sync::{Arc, mpsc},
    thread,
};
// Fixed public loopback-only vectors generated once with OpenSSL. Never use
// these keys/CA for development or production. No runtime certificate tools.
fn server(
    status: &str,
    headers: &str,
    body: Vec<u8>,
    stall: bool,
) -> (
    String,
    thread::JoinHandle<()>,
    tokio::sync::oneshot::Receiver<()>,
    mpsc::Sender<()>,
) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let status = status.to_owned();
    let headers = headers.to_owned();
    let (observed_tx, observed_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let join = thread::spawn(move || {
        let (socket, _) = listener.accept().unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        socket
            .set_write_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let config = rustls::ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(
                vec![CertificateDer::from_pem_slice(CERT).unwrap()],
                PrivateKeyDer::from_pem_slice(KEY).unwrap(),
            )
            .unwrap();
        let connection = rustls::ServerConnection::new(Arc::new(config)).unwrap();
        let mut stream = rustls::StreamOwned::new(connection, socket);
        let mut header = Vec::new();
        let mut byte = [0];
        while !header.ends_with(b"\r\n\r\n") {
            if stream.read_exact(&mut byte).is_err() {
                return;
            }
            header.push(byte[0]);
            assert!(header.len() < 16384);
        }
        let header = String::from_utf8(header).unwrap();
        let length = header
            .lines()
            .find_map(|line| {
                line.split_once(':')
                    .filter(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                    .map(|(_, v)| v.trim().parse::<usize>().unwrap())
            })
            .unwrap();
        assert!(length < 16384);
        let mut request = vec![0; length];
        stream.read_exact(&mut request).unwrap();
        let request: Value = serde_json::from_slice(&request).unwrap();
        assert_eq!(request["token"], "loopback-test-token");
        assert_eq!(request["api_name"], "daily");
        assert_eq!(request["fields"], "ts_code");
        let _ = observed_tx.send(());
        if stall {
            let _ = release_rx.recv_timeout(Duration::from_secs(5));
            return;
        }
        let _ = write!(
            stream,
            "HTTP/1.1 {status}\r\n{headers}\r\nConnection: close\r\n\r\n"
        );
        let _ = stream.write_all(&body);
        stream.conn.send_close_notify();
        let _ = stream.flush();
    });
    (
        format!("https://localhost:{}", addr.port()),
        join,
        observed_rx,
        release_tx,
    )
}
fn query() -> Query {
    Query::new("daily", BTreeMap::new(), "ts_code").unwrap()
}
fn transport(endpoint: String) -> HttpTransport {
    let mut http = HttpTransport::new(
        "loopback-test-token",
        &Trust::explicit_roots(vec![CA.to_vec()]).unwrap(),
    )
    .unwrap();
    http.test_endpoint = Some(endpoint);
    http
}
fn body() -> Vec<u8> {
    br#"{"code":0,"msg":null,"data":{"fields":["ts_code"],"items":[["600000.SH"]]}}"#.to_vec()
}
#[tokio::test]
async fn trusted_https_posts_exact_body_and_retains_response_bytes() {
    let raw = body();
    let (url, join, _, _) = server(
        "200 OK",
        &format!(
            "Content-Type: application/json\r\nContent-Length: {}",
            raw.len()
        ),
        raw.clone(),
        false,
    );
    let response = transport(url)
        .post(&query(), Instant::now() + Duration::from_secs(5))
        .await
        .unwrap();
    assert_eq!(response, raw);
    join.join().unwrap();
}
#[tokio::test]
async fn https_redirect_permission_media_type_and_token_echo_are_sanitized() {
    let cases = [
        (
            "302 Found",
            "Location: https://localhost:1\r\nContent-Length: 0",
            Vec::new(),
            Error::Status,
        ),
        (
            "200 OK",
            "Content-Type: application/json",
            br#"{"code":2002,"msg":"private remote message"}"#.to_vec(),
            Error::Permission,
        ),
        ("200 OK", "Content-Type: text/plain", body(), Error::Shape),
        (
            "200 OK",
            "Content-Type: application/json",
            br#"{"code":0,"data":{"fields":["a"],"items":[["loopback-test-token"]]}}"#.to_vec(),
            Error::Evidence,
        ),
        (
            "200 OK",
            "Content-Type: application/json",
            br#"{"code":0,"data":{"fields":["a"],"items":[["loopback\u002dtest\u002dtoken"]]}}"#
                .to_vec(),
            Error::Evidence,
        ),
    ];
    for (status, headers, body, error) in cases {
        let (url, join, _, _) = server(status, headers, body, false);
        let result = transport(url)
            .post(&query(), Instant::now() + Duration::from_secs(5))
            .await;
        assert_eq!(result.unwrap_err(), error);
        assert!(!error.to_string().contains("loopback"));
        join.join().unwrap();
    }
}
#[tokio::test]
async fn https_declared_and_streamed_response_limits_are_enforced() {
    let (url, join, _, _) = server(
        "200 OK",
        &format!(
            "Content-Type: application/json\r\nContent-Length: {}",
            MAX_RESPONSE + 1
        ),
        vec![],
        false,
    );
    assert_eq!(
        transport(url)
            .post(&query(), Instant::now() + Duration::from_secs(5))
            .await
            .unwrap_err(),
        Error::TooLarge
    );
    join.join().unwrap();
    let (url, join, _, _) = server(
        "200 OK",
        "Content-Type: application/json",
        vec![b' '; MAX_RESPONSE + 1],
        false,
    );
    assert_eq!(
        transport(url)
            .post(&query(), Instant::now() + Duration::from_secs(5))
            .await
            .unwrap_err(),
        Error::TooLarge
    );
    join.join().unwrap();
}
#[tokio::test]
async fn https_single_deadline_and_original_request_cancellation() {
    let (url, join, observed, release) = server("200 OK", "", vec![], true);
    let http = Arc::new(transport(url));
    let q = query();
    let copy = http.clone();
    let handle =
        tokio::spawn(async move { copy.post(&q, Instant::now() + Duration::from_secs(1)).await });
    observed.await.unwrap();
    assert_eq!(handle.await.unwrap().unwrap_err(), Error::Deadline);
    release.send(()).unwrap();
    join.join().unwrap();
    let (url, join, observed, release) = server("200 OK", "", vec![], true);
    let http = transport(url);
    let q = query();
    let handle =
        tokio::spawn(async move { http.post(&q, Instant::now() + Duration::from_secs(5)).await });
    observed.await.unwrap();
    handle.abort();
    assert!(handle.await.unwrap_err().is_cancelled());
    release.send(()).unwrap();
    join.join().unwrap();
}
#[test]
fn credentials_and_trust_never_fall_back_to_environment() {
    for secret in ["", " token", "token\n"] {
        assert!(
            HttpTransport::new(secret, &Trust::explicit_roots(vec![CA.to_vec()]).unwrap()).is_err()
        )
    }
    assert!(
        HttpTransport::new(
            "loopback-test-token",
            &Trust::explicit_roots(vec![b"not a certificate".to_vec()]).unwrap()
        )
        .is_err()
    );
    for root in [
        b"-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----\n".to_vec(),
        b"-----BEGIN CERTIFICATE-----\ninvalid!base64\n-----END CERTIFICATE-----\n".to_vec(),
    ] {
        assert!(
            HttpTransport::new(
                "loopback-test-token",
                &Trust::explicit_roots(vec![root.clone()]).unwrap()
            )
            .is_err()
        );
        assert!(
            HttpTransport::new(
                "loopback-test-token",
                &Trust::explicit_roots(vec![CA.to_vec(), root]).unwrap()
            )
            .is_err()
        );
    }
    assert!(
        HttpTransport::new(
            "loopback-test-token",
            &Trust::explicit_roots(vec![CA.to_vec(), b"not a certificate".to_vec()]).unwrap()
        )
        .is_err()
    );
    let mut commented = b"# public loopback fixture CA\n".to_vec();
    commented.extend_from_slice(CA);
    commented.extend_from_slice(b"# end of public fixture\n");
    assert!(
        HttpTransport::new(
            "loopback-test-token",
            &Trust::explicit_roots(vec![commented]).unwrap()
        )
        .is_ok()
    );
    assert!(Query::new("pro_bar", BTreeMap::new(), "ts_code").is_err());
    assert!(
        Query::new(
            "daily",
            BTreeMap::from([("token".into(), "forbidden".into())]),
            "ts_code"
        )
        .is_err()
    );
}

const CA: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/ca.pem");

const CERT: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/server.pem");

const KEY: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/server-key.pem");

#[test]
fn successful_decoding_still_requires_a_live_deadline_at_success_boundary() {
    let started = Instant::now();
    let deadline = started + Duration::from_secs(1);
    let after = deadline + Duration::from_secs(1);
    let parsed = Table::decode(&body()).unwrap();
    assert_eq!(
        success_at(deadline, started, parsed.clone()).unwrap(),
        parsed
    );
    assert_eq!(
        success_at(deadline, deadline, parsed.clone()).unwrap_err(),
        Error::Deadline
    );
    assert_eq!(
        success_at(deadline, after, parsed).unwrap_err(),
        Error::Deadline
    );
}
