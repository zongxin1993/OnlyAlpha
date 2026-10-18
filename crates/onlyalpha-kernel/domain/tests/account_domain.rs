use onlyalpha_domain::{
    account::{OnlyBalance, OnlyBalanceInput},
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    value::{OnlyCurrency, OnlyMoney},
};
fn money(value: &str) -> OnlyMoney {
    OnlyMoney::new(
        value.parse().unwrap(),
        OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap(),
    )
    .unwrap()
}
#[test]
fn balance_conserves_amount_and_currency() {
    let fields = OnlyBalanceInput {
        currency: money("0").currency().clone(),
        total: money("3.00"),
        available: money("2.00"),
        locked: money("1.00"),
    };
    let balance = OnlyBalance::new(fields.clone()).unwrap();
    assert_eq!(
        balance.to_json().unwrap(),
        "{\"available\":{\"amount\":\"2.00\",\"currency\":{\"code\":\"USD\",\"currency_type\":\"FIAT\",\"precision\":2,\"schema_version\":1},\"schema_version\":1},\"currency\":{\"code\":\"USD\",\"currency_type\":\"FIAT\",\"precision\":2,\"schema_version\":1},\"locked\":{\"amount\":\"1.00\",\"currency\":{\"code\":\"USD\",\"currency_type\":\"FIAT\",\"precision\":2,\"schema_version\":1},\"schema_version\":1},\"schema_version\":1,\"total\":{\"amount\":\"3.00\",\"currency\":{\"code\":\"USD\",\"currency_type\":\"FIAT\",\"precision\":2,\"schema_version\":1},\"schema_version\":1}}"
    );
    let mut invalid = fields;
    invalid.total = money("4.00");
    assert!(OnlyBalance::new(invalid).is_err());
    assert_eq!(
        OnlyBalance::from_record(&balance.to_record()).unwrap(),
        balance
    );
}

#[test]
fn financial_results_preserve_sign_and_currency_invariants() {
    use onlyalpha_domain::account::{
        OnlyCommission, OnlyCommissionInput, OnlyFee, OnlyFeeInput, OnlyMargin, OnlyMarginInput,
        OnlyPnL, OnlyPnLInput, OnlySlippage, OnlySlippageInput,
    };
    assert!(
        OnlyFee::new(OnlyFeeInput {
            amount: money("-1.00"),
            description: "fee".into()
        })
        .is_err()
    );
    assert!(
        OnlyCommission::new(OnlyCommissionInput {
            amount: money("-1.00")
        })
        .is_err()
    );
    assert!(
        OnlyMargin::new(OnlyMarginInput {
            initial: money("-1.00"),
            maintenance: money("0.00")
        })
        .is_err()
    );
    let pnl = OnlyPnL::new(OnlyPnLInput {
        realized: money("-2.00"),
        unrealized: money("5.00"),
    })
    .unwrap();
    assert_eq!(pnl.total().unwrap(), money("3.00"));
    assert!(
        OnlySlippage::new(OnlySlippageInput {
            amount: money("-1.00"),
            rate: None
        })
        .is_ok()
    );
}
#[test]
fn positions_accounts_and_portfolios_reject_foreign_or_duplicate_members() {
    use onlyalpha_domain::{
        account::{
            OnlyAccount, OnlyAccountInput, OnlyPnL, OnlyPnLInput, OnlyPortfolio,
            OnlyPortfolioInput, OnlyPosition, OnlyPositionInput,
        },
        enums::{OnlyMarginMode, OnlyPositionDirection},
        value::OnlyQuantity,
    };
    let updated = "2025-01-01T00:00:00Z".parse().unwrap();
    let position = OnlyPosition::new(OnlyPositionInput {
        position_id: "position".parse().unwrap(),
        account_id: "account".parse().unwrap(),
        instrument_id: "A.X".parse().unwrap(),
        direction: OnlyPositionDirection::Flat,
        quantity: OnlyQuantity::new("0".parse().unwrap(), 0).unwrap(),
        available_quantity: OnlyQuantity::new("0".parse().unwrap(), 0).unwrap(),
        average_open_price: None,
        pnl: OnlyPnL::new(OnlyPnLInput {
            realized: money("0.00"),
            unrealized: money("0.00"),
        })
        .unwrap(),
        opened_at: None,
        updated_at: updated,
        closed_at: None,
        trade_ids: vec![],
        frozen_quantity: None,
        today_quantity: None,
        yesterday_quantity: None,
        settlement_currency: None,
        margin_mode: None,
    })
    .unwrap();
    let fields = OnlyAccountInput {
        account_id: "account".parse().unwrap(),
        base_currency: None,
        margin_mode: OnlyMarginMode::Cash,
        balances: vec![],
        positions: vec![position.clone()],
        equity: None,
        updated_at: updated,
    };
    let account = OnlyAccount::new(fields.clone()).unwrap();
    assert_eq!(
        OnlyAccount::from_json(&account.to_json().unwrap()).unwrap(),
        account
    );
    let mut foreign = fields.clone();
    foreign.account_id = "foreign".parse().unwrap();
    assert!(OnlyAccount::new(foreign).is_err());
    let mut duplicate = fields;
    duplicate.positions.push(position);
    assert!(OnlyAccount::new(duplicate).is_err());
    assert!(
        OnlyPortfolio::new(OnlyPortfolioInput {
            accounts: vec![account.clone(), account],
            reporting_currency: None,
            total_equity: None,
            as_of: updated
        })
        .is_err()
    );
}
