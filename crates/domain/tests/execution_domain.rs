use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::*,
    execution::*,
    value::{OnlyPrice, OnlyQuantity},
};
#[test]
fn requests_normalize_intent_without_adding_order_authority() {
    let fields = OnlyOrderRequestInput {
        request_id: "request".parse().unwrap(),
        instrument_id: "A.X".parse().unwrap(),
        side: OnlyOrderSide::Buy,
        order_type: OnlyOrderType::Limit,
        quantity: OnlyQuantity::new("2".parse().unwrap(), 0).unwrap(),
        time_in_force: OnlyTimeInForce::Day,
        account_id: None,
        offset: OnlyOffset::None,
        price: Some(OnlyPrice::new("10.00".parse().unwrap(), 2).unwrap()),
        stop_price: None,
        expire_time: None,
        tags: vec![],
        metadata: Default::default(),
        execution_intent: None,
    };
    let request = OnlyOrderRequest::new(fields).unwrap();
    assert!(request.execution_intent().is_some());
    assert_eq!(request.limit_price(), request.price());
    assert_eq!(
        OnlyOrderRequest::from_record(&request.to_record()).unwrap(),
        request
    );
    let mut fields = request.input();
    fields.order_type = OnlyOrderType::Market;
    assert!(OnlyOrderRequest::new(fields).is_err());
    let mut fields = request.input();
    fields.time_in_force = OnlyTimeInForce::Gtd;
    assert!(OnlyOrderRequest::new(fields).is_err());
}
#[test]
fn fills_reject_bad_time_and_cancel_metadata_is_typed() {
    use onlyalpha_domain::time::OnlyTimestamp;
    let fields = OnlyOrderFillInput {
        trade_id: "trade".parse().unwrap(),
        order_id: "order".parse().unwrap(),
        price: OnlyPrice::new("1.00".parse().unwrap(), 2).unwrap(),
        quantity: OnlyQuantity::new("1".parse().unwrap(), 0).unwrap(),
        ts_event: OnlyTimestamp::from_unix_nanos(2.into()),
        ts_init: OnlyTimestamp::from_unix_nanos(1.into()),
        venue_trade_id: None,
        venue_order_id: None,
        liquidity_side: OnlyLiquiditySide::Unknown,
        external_sequence: None,
        external_event_id: None,
        metadata: Default::default(),
        reference_price: None,
    };
    assert!(OnlyOrderFill::new(fields.clone()).is_err());
    let mut fields = fields;
    fields.ts_init = OnlyTimestamp::from_unix_nanos(2.into());
    let fill = OnlyOrderFill::new(fields).unwrap();
    assert_eq!(OnlyOrderFill::from_record(&fill.to_record()).unwrap(), fill);
    let cancel = OnlyCancelOrderRequest::new(OnlyCancelOrderRequestInput {
        request_id: "cancel".parse().unwrap(),
        order_id: "order".parse().unwrap(),
        reason: " reason ".into(),
        metadata: Default::default(),
    })
    .unwrap();
    assert_eq!(cancel.reason(), "reason");
    let mut record = cancel.to_record();
    record["metadata"] = serde_json::json!({"x":1});
    assert!(OnlyCancelOrderRequest::from_record(&record).is_err());
}
