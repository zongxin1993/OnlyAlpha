use super::*;
use crate::{Binding, Config, Environment};
use onlyalpha_broker::Scope;
use onlyalpha_domain::{enums::OnlyCurrencyType, value::OnlyCurrency};
use onlyalpha_integration_contract::source::SourceError;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, pem::PemObject};
use serde_json::json;
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    thread,
};
use tokio_tungstenite::tungstenite::{Message, accept};
// 固定公开 loopback 测试向量，服务端私钥只对应这张链尾证书。
const CA: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/ca.pem");
const CERT: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/server.pem");
const KEY: &[u8] = include_bytes!("../../../../test-data/private-protocol-tls/server-key.pem");
struct Fixed;
impl Clock for Fixed {
    fn now_ns(&self) -> std::result::Result<i64, SourceError> {
        Ok(1_000_000_000)
    }
}
fn io() -> Native {
    let scope=Scope::decode(&json!({"account":"account","gateway":"g","engine":"e","runtime":"r","runtime_kind":"SIM","generation":"a".repeat(64)})).unwrap();
    let c = Config {
        binding: Binding {
            access: crate::Access::Trading,
            artifact_sha256: "e".repeat(64),
            scope,
            uid: 1,
            environment: Environment::SpotTestnet,
            key_slot: "k".into(),
            secret_slot: "s".into(),
        },
        currencies: BTreeMap::from([(
            "BTC".into(),
            OnlyCurrency::new("BTC", 8, OnlyCurrencyType::Crypto).unwrap(),
        )]),
        recv_window_ms: 5000,
        max_requests: 5,
        timeout_ms: 5000,
        max_bytes: 4096,
    };
    Native::new(
        &c,
        Credentials::new("api-key-value".into(), "secret-value".into()).unwrap(),
        &Trust::explicit_roots(vec![CA.into()]).unwrap(),
        Arc::new(Fixed),
    )
    .unwrap()
}
fn listener() -> (TcpListener, String) {
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = l.local_addr().unwrap().to_string();
    (l, addr)
}
fn tls(l: TcpListener) -> rustls::StreamOwned<rustls::ServerConnection, TcpStream> {
    let (tcp, _) = l.accept().unwrap();
    tcp.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    tcp.set_write_timeout(Some(Duration::from_secs(5))).unwrap();
    let conf = rustls::ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![CertificateDer::from_pem_slice(CERT).unwrap()],
            PrivateKeyDer::from_pem_slice(KEY).unwrap(),
        )
        .unwrap();
    rustls::StreamOwned::new(rustls::ServerConnection::new(Arc::new(conf)).unwrap(), tcp)
}
#[test]
fn https_uses_explicit_trust_and_signs_the_exact_transmitted_query() {
    let (l, addr) = listener();
    let server = thread::spawn(move || {
        let mut s = tls(l);
        let mut bytes = Vec::new();
        let mut one = [0u8; 1];
        while !bytes.ends_with(b"\r\n\r\n") {
            s.read_exact(&mut one).unwrap();
            bytes.push(one[0]);
            assert!(bytes.len() < 16384);
        }
        let header = String::from_utf8(bytes).unwrap();
        assert!(header.starts_with("GET /api/v3/order?recvWindow=5000&symbol=BTCUSDT&timestamp=1000&signature=3669540deb37f37c237d516b9124b86e2220f007228afb67198cf7b629c4766c HTTP/1.1\r\n"));
        assert!(
            header
                .to_ascii_lowercase()
                .contains("x-mbx-apikey: api-key-value")
        );
        s.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}").unwrap();
        s.flush().unwrap();
    });
    let mut io = io();
    io.rest = format!("https://{addr}");
    let r = io
        .request(
            "GET",
            "/api/v3/order",
            &BTreeMap::from([("symbol".into(), "BTCUSDT".into())]),
            &Budget::new(5000, 1),
        )
        .unwrap();
    assert_eq!(r.bytes, b"{}");
    server.join().unwrap();
}
#[test]
fn wss_signed_subscription_and_frame_limit_survive_real_tls_handshake() {
    let (l, addr) = listener();
    let server = thread::spawn(move || {
        let mut ws = accept(tls(l)).unwrap();
        let raw = ws.read().unwrap();
        let request: Value = serde_json::from_str(raw.to_text().unwrap()).unwrap();
        assert_eq!(request["method"], "userDataStream.subscribe.signature");
        assert_eq!(request["params"]["timestamp"], 1000);
        ws.send(Message::Text(
            json!({"id":"one","status":200,"result":{"subscriptionId":3}})
                .to_string()
                .into(),
        ))
        .unwrap();
        ws.send(Message::Text("stream-observation".into())).unwrap();
        ws.send(Message::Text("x".repeat(8192).into())).unwrap();
    });
    let mut io = io();
    io.ws = format!("wss://{addr}/ws-api/v3");
    let reply = io.subscribe("one", &Budget::new(5000, 1)).unwrap();
    assert_eq!(wire_json(&reply).unwrap()["result"]["subscriptionId"], 3);
    io.blocked_until
        .set(Some(Instant::now() + Duration::from_secs(60)));
    assert_eq!(
        io.next(&Budget::new(5000, 1)).unwrap(),
        b"stream-observation"
    );
    assert!(io.next(&Budget::new(5000, 1)).is_err());
    assert!(io.socket.borrow().is_none());
    server.join().unwrap();
}
#[test]
fn known_http_cooldown_and_unavailable_clock_precede_the_broker_dispatch_marker() {
    let (l, addr) = listener();
    let server = thread::spawn(move || {
        let mut s = tls(l);
        let mut header = Vec::new();
        let mut byte = [0];
        while !header.ends_with(b"\r\n\r\n") {
            s.read_exact(&mut byte).unwrap();
            header.push(byte[0]);
            assert!(header.len() < 16384);
        }
        s.write_all(b"HTTP/1.1 429 Too Many Requests\r\nRetry-After: 60\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}").unwrap();
        s.flush().unwrap();
    });
    let mut cooling = io();
    cooling.rest = format!("https://{addr}");
    assert_eq!(
        cooling
            .request(
                "GET",
                "/api/v3/account",
                &BTreeMap::new(),
                &Budget::new(5000, 1)
            )
            .unwrap()
            .status,
        429
    );
    server.join().unwrap();
    crate::venue_recovery::verify_native_preflight(cooling);
    struct NoTime;
    impl Clock for NoTime {
        fn now_ns(&self) -> std::result::Result<i64, SourceError> {
            Err(SourceError::Unavailable)
        }
    }
    let mut invalid = io();
    invalid.clock = Arc::new(NoTime);
    crate::venue_recovery::verify_native_preflight(invalid);
}

#[test]
fn blocked_receive_drops_its_socket_and_explicit_close_ends_the_new_subscription() {
    use std::io::ErrorKind;
    use tokio_tungstenite::tungstenite::{Error as WsError, error::ProtocolError};

    let (listener, addr) = listener();
    let server = thread::spawn(move || {
        for (id, session) in [("first", 1), ("second", 2)] {
            let mut ws = accept(tls(listener.try_clone().unwrap())).unwrap();
            let frame = ws.read().unwrap();
            let subscribe = wire_json(frame.to_text().unwrap().as_bytes()).unwrap();
            assert_eq!(subscribe["id"], id);
            assert_eq!(subscribe["method"], "userDataStream.subscribe.signature");
            ws.send(Message::Text(
                json!({"id":id,"status":200,"result":{"subscriptionId":session}})
                    .to_string()
                    .into(),
            ))
            .unwrap();
            match ws.read() {
                Ok(Message::Close(_))
                | Err(
                    WsError::ConnectionClosed
                    | WsError::Protocol(ProtocolError::ResetWithoutClosingHandshake),
                ) => {}
                Err(WsError::Io(e))
                    if matches!(
                        e.kind(),
                        ErrorKind::UnexpectedEof
                            | ErrorKind::ConnectionReset
                            | ErrorKind::ConnectionAborted
                    ) => {}
                result => panic!("private peer did not observe closure: {result:?}"),
            }
        }
    });
    let mut io = io();
    io.ws = format!("wss://{addr}/ws-api/v3");
    for (id, session) in [("first", 1), ("second", 2)] {
        let reply = io.subscribe(id, &Budget::new(5000, 1)).unwrap();
        assert_eq!(
            crate::subscription_id(id, &wire_json(&reply).unwrap()).unwrap(),
            session
        );
        if id == "first" {
            assert_eq!(
                io.next(&Budget::new(250, 1)).unwrap_err(),
                err("BINANCE_DEADLINE")
            );
        } else {
            io.close();
        }
        assert!(io.socket.borrow().is_none());
        assert_eq!(
            io.next(&Budget::new(5000, 1)).unwrap_err(),
            err("BINANCE_WS_DISCONNECTED")
        );
    }
    server.join().unwrap();
}
