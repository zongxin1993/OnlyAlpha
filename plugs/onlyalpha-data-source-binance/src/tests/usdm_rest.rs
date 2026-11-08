use super::*;
use std::{
    io::{Read, Write},
    net::TcpListener,
    time::Duration,
};
fn http(bodies: Vec<String>) -> (String, std::thread::JoinHandle<Vec<String>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = format!("http://{}", listener.local_addr().unwrap());
    let thread = std::thread::spawn(move || {
        let mut requests = Vec::new();
        for body in bodies {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            loop {
                let mut b = [0u8; 1];
                stream.read_exact(&mut b).unwrap();
                request.push(b[0]);
                if request.ends_with(b"\r\n\r\n") {
                    break;
                }
            }
            requests.push(String::from_utf8(request).unwrap());
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
        }
        requests
    });
    (address, thread)
}
fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
}
fn row(t: i64) -> Value {
    serde_json::json!([
        t,
        "10",
        "11",
        "9",
        "10.5",
        "1",
        t + 59_999,
        "10.5",
        3,
        "0",
        "0",
        "0"
    ])
}
#[test]
fn usdm_endpoint_parameters_pages_and_original_recording_are_exact() {
    for (kind, path, key) in [
        (History::Contract, "/fapi/v1/klines", "symbol"),
        (History::Mark, "/fapi/v1/markPriceKlines", "symbol"),
        (History::Index, "/fapi/v1/indexPriceKlines", "pair"),
    ] {
        let bodies = vec![
            serde_json::json!([row(0)]).to_string(),
            serde_json::json!([row(60_000)]).to_string(),
        ];
        let (base, thread) = http(bodies.clone());
        let rest = UsdmRest::test_transport(&base, 1);
        let mut retained = Vec::new();
        let result = runtime()
            .block_on(rest.history_observed(
                kind,
                "BTCUSDT",
                0,
                120_000,
                Instant::now() + Duration::from_secs(5),
                &mut |context, bytes| {
                    assert_eq!(context.path(), path);
                    retained.push(bytes.to_vec());
                    Ok(())
                },
            ))
            .unwrap();
        assert_eq!(result.len(), 2);
        assert_eq!(
            retained,
            bodies
                .iter()
                .map(|s| s.as_bytes().to_vec())
                .collect::<Vec<_>>()
        );
        let requests = thread.join().unwrap();
        assert!(requests[0].contains(&format!("{key}=BTCUSDT")));
        assert!(requests[0].contains("endTime=119999"));
        assert!(requests[1].contains("startTime=60000"));
    }
}
#[test]
fn funding_uses_millisecond_cursor_and_shared_deadline_without_retry() {
    let (base,thread)=http(vec![serde_json::json!([{"symbol":"BTCUSDT","fundingTime":1,"markPrice":"10","fundingRate":"0.001"}]).to_string(),"[]".into()]);
    let rest = UsdmRest::test_transport(&base, 1);
    let pages = runtime()
        .block_on(rest.history_observed(
            History::Funding,
            "BTCUSDT",
            0,
            100,
            Instant::now() + Duration::from_secs(5),
            &mut |_, _| Ok(()),
        ))
        .unwrap();
    assert_eq!(pages.len(), 2);
    let requests = thread.join().unwrap();
    assert!(requests[1].contains("startTime=2"));
    assert!(!requests[0].contains("interval="));
    assert_eq!(
        runtime()
            .block_on(rest.history_observed(
                History::Funding,
                "BTCUSDT",
                0,
                100,
                Instant::now(),
                &mut |_, _| Ok(())
            ))
            .err(),
        Some(Error::Deadline)
    );
}
#[test]
fn invalid_order_identity_and_recorder_failure_retain_input_and_stop() {
    for body in [
        serde_json::json!([row(60_000), row(0)]).to_string(),
        serde_json::json!([row(0), row(0)]).to_string(),
        "not-json".into(),
    ] {
        let (base, thread) = http(vec![body.clone()]);
        let rest = UsdmRest::test_transport(&base, 2);
        let mut observed = Vec::new();
        assert!(
            runtime()
                .block_on(rest.history_observed(
                    History::Contract,
                    "BTCUSDT",
                    0,
                    120_000,
                    Instant::now() + Duration::from_secs(5),
                    &mut |_, bytes| {
                        observed.push(bytes.to_vec());
                        Ok(())
                    }
                ))
                .is_err()
        );
        assert_eq!(observed, vec![body.into_bytes()]);
        assert_eq!(thread.join().unwrap().len(), 1);
    }
    let (base, thread) = http(vec![serde_json::json!([row(0)]).to_string()]);
    let rest = UsdmRest::test_transport(&base, 1);
    assert_eq!(
        runtime()
            .block_on(rest.history_observed(
                History::Contract,
                "BTCUSDT",
                0,
                120_000,
                Instant::now() + Duration::from_secs(5),
                &mut |_, _| Err(Error::Evidence)
            ))
            .err(),
        Some(Error::Evidence)
    );
    assert_eq!(thread.join().unwrap().len(), 1);
    let (base, thread) = http(vec![
        serde_json::json!([{"symbol":"ETHUSDT","fundingTime":1}]).to_string(),
    ]);
    let rest = UsdmRest::test_transport(&base, 1);
    assert_eq!(
        runtime()
            .block_on(rest.history_observed(
                History::Funding,
                "BTCUSDT",
                0,
                100,
                Instant::now() + Duration::from_secs(5),
                &mut |_, _| Ok(())
            ))
            .err(),
        Some(Error::Shape)
    );
    thread.join().unwrap();
}
#[test]
fn spot_raw_trade_locator_never_becomes_a_trade_and_suffix_requires_exact_ids() {
    let locator = serde_json::json!([{"a":999,"f":100,"l":100,"T":1000}]).to_string();
    let page=serde_json::json!([{"id":100,"price":"10","qty":"1","time":1000,"isBuyerMaker":false},{"id":101,"price":"10","qty":"1","time":2000,"isBuyerMaker":true}]).to_string();
    let (base, thread) = http(vec![locator.clone(), page.clone()]);
    let mut rest = PublicRest::test_transport(&base);
    rest.page_size_for_test(2);
    let mut retained = Vec::new();
    let result = runtime()
        .block_on(rest.historical_trades_observed(
            "BTCUSDT",
            1000,
            2000,
            Instant::now() + Duration::from_secs(5),
            &mut |ctx, bytes| {
                retained.push((ctx.path().to_string(), bytes.to_vec()));
                Ok(())
            },
        ))
        .unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].value()[0]["id"], 100);
    assert_eq!(
        retained,
        vec![
            ("/api/v3/aggTrades".into(), locator.into_bytes()),
            ("/api/v3/historicalTrades".into(), page.into_bytes())
        ]
    );
    let requests = thread.join().unwrap();
    assert!(requests[1].contains("fromId=100"));
    for ids in [vec![101, 102], vec![100, 102], vec![100, 100]] {
        let body = serde_json::json!(
            ids.into_iter()
                .map(|id| serde_json::json!({"id":id}))
                .collect::<Vec<_>>()
        )
        .to_string();
        let (base, thread) = http(vec![body]);
        let mut rest = PublicRest::test_transport(&base);
        rest.page_size_for_test(2);
        assert_eq!(
            runtime()
                .block_on(rest.trade_suffix_observed(
                    "BTCUSDT",
                    100,
                    101,
                    Instant::now() + Duration::from_secs(5),
                    &mut |_, _| Ok(())
                ))
                .err(),
            Some(Error::Order)
        );
        thread.join().unwrap();
    }
}
#[test]
fn spot_reference_and_usdm_public_reference_use_distinct_exact_endpoints() {
    let (base, thread) = http(vec![
        serde_json::json!({"symbol":"BTCUSDT","referencePrice":null,"timestamp":1000}).to_string(),
    ]);
    let rest = PublicRest::test_transport(&base);
    let r = runtime()
        .block_on(rest.reference_price_observed(
            "BTCUSDT",
            Instant::now() + Duration::from_secs(5),
            &mut |_, _| Ok(()),
        ))
        .unwrap();
    assert!(r.value()["referencePrice"].is_null());
    assert!(thread.join().unwrap()[0].contains("/api/v3/referencePrice?symbol=BTCUSDT"));
    let (base, thread) = http(vec![
        serde_json::json!({"symbols":[{"symbol":"BTCUSDT","contractType":"PERPETUAL"}]})
            .to_string(),
        serde_json::json!([{"symbol":"BTCUSDT","fundingIntervalHours":4}]).to_string(),
    ]);
    let rest = UsdmRest::test_transport(&base, 1);
    runtime()
        .block_on(
            rest.exchange_info_observed(
                Instant::now() + Duration::from_secs(5),
                &mut |_, _| Ok(()),
            ),
        )
        .unwrap();
    runtime()
        .block_on(
            rest.funding_info_observed(Instant::now() + Duration::from_secs(5), &mut |_, _| Ok(())),
        )
        .unwrap();
    let requests = thread.join().unwrap();
    assert!(requests[0].contains("/fapi/v1/exchangeInfo "));
    assert!(requests[1].contains("/fapi/v1/fundingInfo "));
}
#[test]
fn unsupported_rest_profiles_fail_before_io_and_explicit_global_standard_keeps_identity() {
    for (configuration, unsupported, identity) in [
        ("{}", true, "binance.spot.market_data.live"),
        (
            r#"{"environment":"GLOBAL","endpoint_profile":"PUBLIC_MARKET_DATA"}"#,
            true,
            "binance.spot.market_data.live",
        ),
        (
            r#"{"environment":"US","endpoint_profile":"DEFAULT"}"#,
            true,
            "binance.spot.market_data.us",
        ),
        (
            r#"{"environment":"SPOT_TESTNET","endpoint_profile":"DEFAULT"}"#,
            true,
            "binance.spot.market_data.spot_testnet",
        ),
        (
            r#"{"environment":"GLOBAL","endpoint_profile":"STANDARD"}"#,
            false,
            "binance.spot.market_data.live",
        ),
        (
            r#"{"environment":"GLOBAL","endpoint_profile":"GCP"}"#,
            false,
            "binance.spot.market_data.live",
        ),
        (
            r#"{"environment":"GLOBAL","endpoint_profile":"API1"}"#,
            false,
            "binance.spot.market_data.live",
        ),
    ] {
        let raw = RawValue::from_string(configuration.into()).unwrap();
        let rest = PublicRest::configured(&raw, 64 * 1024 * 1024, &[]).unwrap();
        assert_eq!(rest.source_id(), identity);
        let expected = Some(if unsupported {
            Error::Unsupported
        } else {
            Error::Deadline
        });
        let deadline = Instant::now();
        assert_eq!(
            runtime()
                .block_on(
                    rest.reference_price_observed("BTCUSDT", deadline, &mut |_, _| panic!(
                        "no I/O observation expected"
                    ))
                )
                .err(),
            expected
        );
        assert_eq!(
            runtime()
                .block_on(rest.trade_suffix_observed(
                    "BTCUSDT",
                    100,
                    101,
                    deadline,
                    &mut |_, _| panic!("no I/O observation expected")
                ))
                .err(),
            expected
        );
        assert_eq!(
            runtime()
                .block_on(rest.historical_trades_observed(
                    "BTCUSDT",
                    1000,
                    2000,
                    deadline,
                    &mut |_, _| panic!("no I/O observation expected")
                ))
                .err(),
            expected
        );
        assert_eq!(rest.source_id(), identity);
    }
    assert_eq!(
        onlyalpha_integration_contract::source::SourceError::from(Error::Unsupported),
        onlyalpha_integration_contract::source::SourceError::Unsupported
    );
}
