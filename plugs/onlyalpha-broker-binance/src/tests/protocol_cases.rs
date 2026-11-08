use super::*;
use onlyalpha_broker::{DispatchResult, Scope};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    trading::{OnlyExecutionIntent, OnlyPositionMode},
};
fn scope() -> Scope {
    Scope::decode(&json!({"engine":"engine","runtime":"runtime","gateway":"spot","account":"account","generation":"a".repeat(64),"runtime_kind":"SIM"})).unwrap()
}
fn submit(order: &str, client: &str) -> BrokerCommand {
    let mut req = serde_json::from_str::<Value>(include_str!(
        "../../../../test-data/broker/domain-inputs.json"
    ))
    .unwrap()["request"]
        .clone();
    req["instrument_id"]["symbol"]["value"] = json!("BTCUSDT");
    req["instrument_id"]["venue"]["value"] = json!("BINANCE");
    req["time_in_force"] = json!("GTC");
    req["request_id"]["value"] = json!(format!("request-{order}"));
    BrokerCommand::decode(&json!({"schema_version":1,"scope":scope().record(),"operation":"SUBMIT","command_id":format!("submit-{order}"),"order":order,"client":client,"request":req})).unwrap()
}
#[test]
fn sorted_signing_encodes_client_delimiters_before_hashing() {
    let key = Credentials::new("api".into(), "secret-value".into()).unwrap();
    let p = BTreeMap::from([("symbol".into(), "BTCUSDT".into())]);
    assert_eq!(
        signed_query(&key, &p, 1000, 5000).unwrap().as_str(),
        "recvWindow=5000&symbol=BTCUSDT&timestamp=1000&signature=3669540deb37f37c237d516b9124b86e2220f007228afb67198cf7b629c4766c"
    );
    assert!(
        signed_query(
            &key,
            &BTreeMap::from([("origClientOrderId".into(), "a/&b".into())]),
            1000,
            5000
        )
        .unwrap()
        .starts_with("origClientOrderId=a%2F%26b&")
    );
    assert!(signed_query(&key, &p, 1000, 60001).is_err());
}
#[test]
fn only_exact_cancel_or_submit_ack_can_be_received() {
    let one = submit("one", "one");
    let two = submit("two", "two");
    let ack = json!({"orderId":7,"symbol":"BTCUSDT","clientOrderId":"one"});
    assert_eq!(ack_venue(&one, &one, None, &ack).unwrap(), 7);
    assert!(ack_venue(&two, &two, None, &ack).is_err());
    let cancel=BrokerCommand::decode(&json!({"schema_version":1,"scope":scope().record(),"operation":"CANCEL","command_id":"cx","order":"one","client":"one","request":{"schema_version":1,"request_id":{"schema_version":1,"value":"c1"},"order_id":{"schema_version":1,"value":"one"},"reason":"cancel","metadata":{}}})).unwrap();
    let mut ack = json!({"orderId":7,"symbol":"BTCUSDT","clientOrderId":cancel_client(&cancel),"origClientOrderId":"one","status":"CANCELED"});
    assert_eq!(ack_venue(&cancel, &one, Some(7), &ack).unwrap(), 7);
    assert!(ack_venue(&cancel, &one, Some(8), &ack).is_err());
    ack["origClientOrderId"] = json!("two");
    assert!(ack_venue(&cancel, &one, Some(7), &ack).is_err());
    assert_eq!(error_outcome(503, Some(-1102)), DispatchResult::Unknown);
}
#[test]
fn paginated_trades_bind_original_order_cursor_and_executed_quantity() {
    let c = submit("one", "one");
    let trade = |id: u64, order: u64, qty: &str| json!({"id":id,"orderId":order,"symbol":"BTCUSDT","qty":qty,"isBuyer":true});
    let mut p = TradePages::new(&c, 7, "4", 2).unwrap();
    assert_eq!(p.cursor(), 0);
    assert!(
        !p.push(&json!([trade(3, 7, "1"), trade(6, 7, "2")]))
            .unwrap()
    );
    assert_eq!(p.cursor(), 7);
    assert!(p.push(&json!([trade(8, 7, "1")])).unwrap());
    for wrong in [
        json!([trade(1, 8, "4")]),
        json!([]),
        json!([trade(1, 7, "2"), trade(1, 7, "2")]),
    ] {
        assert!(
            TradePages::new(&c, 7, "4", 2)
                .unwrap()
                .push(&wrong)
                .is_err()
        );
    }
}
#[test]
fn ambiguous_nested_json_and_symbol_aliases_fail_closed() {
    assert!(wire_json(br#"[{"id":1,"\u0069d":2}]"#).is_err());
    assert_eq!(
        wire_json(br#"{"id":9007199254740993,"qty":"0.00000001"}"#).unwrap()["id"].as_u64(),
        Some(9007199254740993)
    );
    assert_ne!(
        venue_id("BTCUSDT", 7).unwrap(),
        venue_id("ETHUSDT", 7).unwrap()
    );
    assert!(venue_id("BTC:USDT", 7).is_err());
}
#[test]
fn signed_subscription_rebinds_request_and_session() {
    let key = Credentials::new("api-key-value".into(), "secret-value".into()).unwrap();
    let raw = subscribe_frame(&key, "request", 1000, 5000).unwrap();
    let sub: Value = serde_json::from_str(raw.as_str()).unwrap();
    assert_eq!(sub["method"], "userDataStream.subscribe.signature");
    assert_eq!(
        sub["params"]["signature"],
        "4e09f9d199acfbbee72e15e3e276fe722982d1cd4bcb8865e368ddb6a817513d"
    );
    let ack = json!({"id":"request","status":200,"result":{"subscriptionId":0}});
    assert_eq!(subscription_id("request", &ack).unwrap(), 0);
    assert!(subscription_id("old", &ack).is_err());
    assert!(
        subscription_event(
            0,
            &json!({"subscriptionId":2,"event":{"e":"executionReport"}})
        )
        .is_err()
    );
}
#[test]
fn usdm_close_short_wire_retains_actual_account_mode() {
    let i=OnlyExecutionIntent::from_record(&json!({"schema_version":2,"side":"BUY","position_side":"SHORT","position_effect":"CLOSE","close_scope":"ANY","exposure_constraint":"REDUCE_ONLY","position_mode":"NETTING"})).unwrap();
    assert_eq!(
        usdm_order_parameters(&i, OnlyPositionMode::Netting).unwrap(),
        BTreeMap::from([
            ("side", "BUY"),
            ("positionSide", "BOTH"),
            ("reduceOnly", "true")
        ])
    );
    assert_eq!(
        usdm_order_parameters(&i, OnlyPositionMode::Hedging).unwrap(),
        BTreeMap::from([("side", "BUY"), ("positionSide", "SHORT")])
    );
}
#[test]
fn long_client_order_id_matches_the_archived_wire_codec() {
    assert_eq!(
        wire_client("runtime-with-a-very-long-identity-CLIENT-000001"),
        "oa_4a27f1b8483385b66ada9182efebf378"
    );
    assert_eq!(wire_client("a_B.c:/-1"), "a_B.c:/-1");
    assert_ne!(
        wire_client("runtime-with-a-very-long-identity-CLIENT-000001"),
        wire_client("runtime-with-a-very-long-identity-CLIENT-000001x")
    );
}
