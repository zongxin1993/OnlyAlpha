use super::{
    tests::{http, row, source},
    *,
};
use tokio::net::TcpListener;
use tokio_tungstenite::{
    accept_async,
    tungstenite::{
        Error as WsError,
        error::ProtocolError,
        handshake::server::{Callback, ErrorResponse, Request, Response},
    },
};

const MARKER: &str = "provider-raw-secret-marker";

struct CapturePath<'a>(&'a mut String);
impl Callback for CapturePath<'_> {
    fn on_request(self, request: &Request, response: Response) -> Result<Response, ErrorResponse> {
        *self.0 = request.uri().path().to_owned();
        Ok(response)
    }
}

fn reference(symbol: &str) -> Value {
    json!({"symbols":[{"symbol":symbol,"baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[
        {"filterType":"PRICE_FILTER","tickSize":"0.01"},
        {"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}
    ]}],"raw":MARKER})
}
fn healthy_rest() -> Vec<String> {
    vec![
        "{}".into(),
        json!({"serverTime":120000,"raw":MARKER}).to_string(),
        reference("BTCUSDT").to_string(),
        json!([row(0, 1), row(60000, 1)]).to_string(),
    ]
}
fn check<'a>(report: &'a Value, name: &str) -> &'a Value {
    let checks = report["checks"].as_array().unwrap();
    assert_eq!(checks.len(), 4);
    assert_eq!(checks.iter().filter(|r| r["check"] == name).count(), 1);
    checks.iter().find(|r| r["check"] == name).unwrap()
}
async fn next_is_close_or_eof(socket: &mut WebSocketStream<TcpStream>) -> bool {
    loop {
        match socket.next().await {
            Some(Ok(Message::Pong(_))) => (),
            None
            | Some(Ok(Message::Close(_)))
            | Some(Err(
                WsError::ConnectionClosed
                | WsError::Protocol(ProtocolError::ResetWithoutClosingHandshake),
            )) => return true,
            Some(Err(WsError::Io(e))) => {
                return matches!(
                    e.kind(),
                    std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::UnexpectedEof
                );
            }
            _ => return false,
        }
    }
}

#[tokio::test]
async fn probe_rejects_malformed_provider_data_closes_depth_socket_and_redacts_payloads() {
    let healthy_depth =
        json!({"lastUpdateId":1,"bids":[["99","2"]],"asks":[["101","3"]],"raw":MARKER});
    for (name, bad) in [
        ("ping", "CONNECTIVITY"),
        ("time", "CONNECTIVITY"),
        ("empty symbol", "REFERENCE_DATA"),
        ("foreign symbol", "REFERENCE_DATA"),
        ("empty history", "HISTORICAL_DATA"),
        ("out of order", "HISTORICAL_DATA"),
        ("duplicate", "HISTORICAL_DATA"),
        ("bad OHLC", "HISTORICAL_DATA"),
        ("forming tail", "HISTORICAL_DATA"),
        ("empty bids", "REALTIME_DATA"),
        ("valid", ""),
    ] {
        let mut rest = healthy_rest();
        let mut depth = healthy_depth.clone();
        match name {
            "ping" => {
                rest[0] = json!({"raw":MARKER}).to_string();
                rest.remove(3);
                rest.remove(1);
            }
            "time" => {
                rest[1] = json!({"serverTime":MARKER}).to_string();
                rest.pop();
            }
            "empty symbol" | "foreign symbol" => {
                rest[2] = if name == "empty symbol" {
                    json!({"symbols":[],"raw":MARKER})
                } else {
                    reference("ETHUSDT")
                }
                .to_string();
                rest.pop();
            }
            "empty history" => rest[3] = "[]".into(),
            "out of order" => rest[3] = json!([row(60000, 1), row(0, 1)]).to_string(),
            "duplicate" => rest[3] = json!([row(0, 1), row(0, 1)]).to_string(),
            "bad OHLC" => {
                let mut invalid = row(0, 1);
                invalid[2] = json!("8");
                rest[3] = json!([invalid, row(60000, 1)]).to_string();
            }
            "forming tail" => rest[3] = json!([row(60000, 1), row(120000, 1)]).to_string(),
            "empty bids" => depth["bids"] = json!([]),
            "valid" => (),
            _ => unreachable!(),
        }
        let (url, server) = http(rest);
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut s = source(&url);
        s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
        let peer = async {
            let (tcp, _) = listener.accept().await.unwrap();
            let mut path = String::new();
            let mut ws = tokio_tungstenite::accept_hdr_async(tcp, CapturePath(&mut path))
                .await
                .unwrap();
            ws.send(Message::Text(depth.to_string().into()))
                .await
                .unwrap();
            assert!(next_is_close_or_eof(&mut ws).await, "{name}");
            path
        };
        let (report, path) = tokio::time::timeout(Duration::from_secs(6), async {
            tokio::join!(s.probe("BTCUSDT", Budget::from_millis(5000).unwrap()), peer)
        })
        .await
        .unwrap();
        let report = report.unwrap();
        assert_eq!(path, "/ws/btcusdt@depth5@100ms");
        assert!(!report.to_string().contains(MARKER), "{name}");
        assert_eq!(
            report["status"],
            if bad.is_empty() {
                "READY"
            } else {
                "UNAVAILABLE"
            },
            "{name}"
        );
        for target in [
            "CONNECTIVITY",
            "REFERENCE_DATA",
            "HISTORICAL_DATA",
            "REALTIME_DATA",
        ] {
            let unavailable = target == bad
                || (target == "HISTORICAL_DATA"
                    && matches!(bad, "CONNECTIVITY" | "REFERENCE_DATA"));
            assert_eq!(
                check(&report, target)["status"],
                if unavailable { "UNAVAILABLE" } else { "READY" },
                "{name}-{target}"
            );
        }
        let requests = server.join().unwrap();
        let scoped = requests
            .iter()
            .find(|r| r.starts_with("GET /api/v3/exchangeInfo?"))
            .unwrap();
        assert!(scoped.contains("symbols=%5B%22BTCUSDT%22%5D"));
        assert!(!scoped.contains("permissions=SPOT"));
    }
}

#[tokio::test]
async fn pending_probe_obeys_caller_and_per_check_budgets_and_drops_cancelled_socket() {
    for (budget_ms, cancel) in [(1000, false), (12_000, false), (12_000, true)] {
        let (url, server) = http(healthy_rest());
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut s = source(&url);
        s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
        let (started, active) = tokio::sync::oneshot::channel();
        let peer = async {
            let (tcp, _) = listener.accept().await.unwrap();
            let mut ws = accept_async(tcp).await.unwrap();
            ws.send(Message::Ping(vec![1].into())).await.unwrap();
            assert!(matches!(ws.next().await, Some(Ok(Message::Pong(_)))));
            started.send(()).unwrap();
            assert!(next_is_close_or_eof(&mut ws).await);
        };
        let probe = async {
            let mut original = s.probe("BTCUSDT", Budget::from_millis(budget_ms).unwrap());
            tokio::select! {
                () = async { active.await.unwrap(); } => (),
                _ = &mut original => panic!("深度连接尚未进入受控等待"),
            }
            if cancel {
                drop(original);
            } else {
                let report = original.await.unwrap();
                assert_eq!(report["status"], "UNAVAILABLE");
                let realtime = check(&report, "REALTIME_DATA");
                assert_eq!(realtime["status"], "UNAVAILABLE");
                assert_eq!(realtime["detail"], SourceError::Timeout.code());
                assert_eq!(check(&report, "HISTORICAL_DATA")["status"], "READY");
            }
        };
        // 较短的调用预算须在 5 s 单项上限前结束；较长调用受 5 s 单项上限约束。
        let guard = if budget_ms == 1000 { 3 } else { 8 };
        tokio::time::timeout(Duration::from_secs(guard), async {
            tokio::join!(probe, peer);
        })
        .await
        .unwrap();
        assert_eq!(server.join().unwrap().len(), 4);
    }
}

#[tokio::test]
async fn probe_cannot_publish_a_completed_check_as_ready_after_its_budget() {
    struct ClockAtCompletion(std::sync::atomic::AtomicUsize);
    impl Clock for ClockAtCompletion {
        fn now_ns(&self) -> Result<i64, SourceError> {
            let index = self.0.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            if index == 2 {
                // 第一项收到有效 ping/time 后，完成时间的采样尚未返回。
                let (_sender, receiver) = std::sync::mpsc::channel::<()>();
                assert_eq!(
                    receiver.recv_timeout(Duration::from_millis(1000)),
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout)
                );
            }
            Ok(1_800_000_000_000_000_000 + index as i64)
        }
    }
    let (url, server) = http(vec!["{}".into(), json!({"serverTime":120000}).to_string()]);
    let mut s = source(&url);
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    s.ws_base = format!("ws://{}", listener.local_addr().unwrap());
    s.clock = Arc::new(ClockAtCompletion(std::sync::atomic::AtomicUsize::new(0)));
    let report = s
        .probe("BTCUSDT", Budget::from_millis(1000).unwrap())
        .await
        .unwrap();
    let requests = server.join().unwrap();
    assert!(requests[0].starts_with("GET /api/v3/ping "));
    assert!(requests[1].starts_with("GET /api/v3/time "));
    let connectivity = check(&report, "CONNECTIVITY");
    assert_eq!(connectivity["status"], "UNAVAILABLE");
    assert_eq!(connectivity["detail"], SourceError::Timeout.code());
}
