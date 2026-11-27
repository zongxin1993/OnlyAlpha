use onlyalpha_domain::{
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    identifiers::OnlyInstrumentId,
    strategy::{NamedFactor, OrderIntent, ReadonlyAccountState, ReadonlyPosition},
    time::OnlyTimestamp,
};
use std::str::FromStr;

fn decimal(text: &str) -> onlyalpha_domain::numeric::OnlyDecimal {
    text.parse().unwrap()
}

fn instrument(text: &str) -> OnlyInstrumentId {
    OnlyInstrumentId::from_str(text).unwrap()
}

fn intent(order_type: OnlyOrderType, limit_price: Option<&str>) -> Result<OrderIntent, String> {
    OrderIntent::new(
        instrument("600000.XSHG"),
        OnlyOrderSide::Buy,
        order_type,
        decimal("100"),
        limit_price.map(decimal),
        OnlyTimeInForce::Day,
        "BREAKOUT",
    )
    .map_err(|error| error.to_string())
}

#[test]
fn factor_bindings_keep_missingness_distinct_from_zero() {
    let missing = NamedFactor::new("momentum", None).unwrap();
    let zero = NamedFactor::new("momentum", Some(decimal("0"))).unwrap();
    assert_eq!(missing.value(), None);
    assert_eq!(zero.value(), Some(&decimal("0")));
    assert_ne!(missing, zero);
    assert!(NamedFactor::new("", None).is_err());
}

#[test]
fn intent_requires_positive_size_and_a_reason() {
    assert!(intent(OnlyOrderType::Market, None).is_ok());
    let quantity = OrderIntent::new(
        instrument("600000.XSHG"),
        OnlyOrderSide::Buy,
        OnlyOrderType::Market,
        decimal("0"),
        None,
        OnlyTimeInForce::Day,
        "BREAKOUT",
    );
    assert!(quantity.is_err());
    let reason = OrderIntent::new(
        instrument("600000.XSHG"),
        OnlyOrderSide::Buy,
        OnlyOrderType::Market,
        decimal("100"),
        None,
        OnlyTimeInForce::Day,
        "  ",
    );
    assert!(reason.is_err());
}

#[test]
fn intent_price_must_match_the_order_type() {
    assert!(intent(OnlyOrderType::Limit, Some("10.5")).is_ok());
    assert!(intent(OnlyOrderType::Limit, None).is_err());
    assert!(intent(OnlyOrderType::Market, Some("10.5")).is_err());
    assert!(intent(OnlyOrderType::Limit, Some("0")).is_err());
    assert!(intent(OnlyOrderType::Limit, Some("-1")).is_err());
}

#[test]
fn intent_carries_formal_identity_and_round_trips_its_fields() {
    let accepted = intent(OnlyOrderType::Limit, Some("10.5")).unwrap();
    assert_eq!(accepted.instrument().to_string(), "600000.XSHG");
    assert_eq!(accepted.instrument().symbol().value(), "600000");
    assert_eq!(accepted.instrument().venue().value(), "XSHG");
    assert_eq!(accepted.side(), OnlyOrderSide::Buy);
    assert_eq!(accepted.order_type(), OnlyOrderType::Limit);
    assert_eq!(accepted.quantity(), &decimal("100"));
    assert_eq!(accepted.limit_price(), Some(&decimal("10.5")));
    assert_eq!(accepted.time_in_force(), OnlyTimeInForce::Day);
    assert_eq!(accepted.reason_code(), "BREAKOUT");
}

#[test]
fn readonly_state_orders_positions_and_rejects_duplicates() {
    let state = ReadonlyAccountState::new(
        OnlyTimestamp::from_unix_nanos(7.into()),
        decimal("1000"),
        decimal("2000"),
        vec![
            ReadonlyPosition::new(instrument("000001.XSHE"), decimal("10"), None).unwrap(),
            ReadonlyPosition::new(
                instrument("600000.XSHG"),
                decimal("20"),
                Some(decimal("9.5")),
            )
            .unwrap(),
        ],
    )
    .unwrap();
    assert_eq!(
        state
            .positions()
            .iter()
            .map(|position| position.instrument().to_string())
            .collect::<Vec<_>>(),
        ["000001.XSHE", "600000.XSHG"]
    );
    assert_eq!(state.positions()[1].average_cost(), Some(&decimal("9.5")));
    assert!(
        ReadonlyAccountState::new(
            OnlyTimestamp::from_unix_nanos(7.into()),
            decimal("1000"),
            decimal("2000"),
            vec![
                ReadonlyPosition::new(instrument("600000.XSHG"), decimal("1"), None).unwrap(),
                ReadonlyPosition::new(instrument("600000.XSHG"), decimal("2"), None).unwrap(),
            ],
        )
        .is_err()
    );
    assert!(ReadonlyPosition::new(instrument("600000.XSHG"), decimal("-1"), None).is_err());
}
