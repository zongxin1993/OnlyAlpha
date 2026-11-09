use onlyalpha_data_source_binance::spot_rest::Error;
use onlyalpha_data_source_binance::{
    spot_facts, spot_normalize,
    trade_continuity::{State, TradeContinuity},
};
use onlyalpha_domain::market::OnlyTradeTick;
use serde_json::json;
fn trade(n: i64) -> OnlyTradeTick {
    let i=spot_normalize::instrument(&json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]})).unwrap();
    spot_facts::rest_trade(
        &json!({"id":n,"price":"10.50","qty":"1","time":1000+n,"isBuyerMaker":false}),
        &i,
    )
    .unwrap()
}
fn ready(maximum: usize) -> TradeContinuity {
    let mut c = TradeContinuity::new("BTCUSDT.BINANCE".parse().unwrap(), maximum).unwrap();
    c.connected().unwrap();
    c.subscription_established().unwrap();
    c.begin_recovery().unwrap();
    c.accept_baseline(trade(100), &mut |_| Ok(())).unwrap();
    assert!(
        c.complete_recovery(vec![], &mut |_| Ok(()))
            .unwrap()
            .is_empty()
    );
    assert_eq!(c.state(), State::Ready);
    c
}
#[test]
fn exact_trade_recovery_and_buffer_cutover_commit_once_in_sequence() {
    let mut c = ready(10);
    let mut durable = Vec::new();
    assert!(c.accept(trade(103), &mut |_| Ok(())).unwrap().is_empty());
    assert_eq!(c.state(), State::Recovering);
    c.buffer(trade(104)).unwrap();
    c.buffer(trade(103)).unwrap();
    let accepted = c
        .complete_recovery(vec![trade(102), trade(101), trade(103)], &mut |t| {
            durable.push(t.sequence().to_string());
            Ok(())
        })
        .unwrap();
    assert_eq!(durable, vec!["101", "102", "103", "104"]);
    assert_eq!(accepted.len(), 4);
    assert_eq!(c.checkpoint(), Some(104));
    assert_eq!(c.buffered_count(), 0);
    assert_eq!(c.state(), State::Ready);
    assert!(
        c.accept(trade(103), &mut |_| panic!("duplicate must not persist"))
            .unwrap()
            .is_empty()
    );
    assert!(
        c.accept(trade(99), &mut |_| panic!("stale must not persist"))
            .unwrap()
            .is_empty()
    );
}
#[test]
fn inline_and_buffered_trade_arrivals_converge_to_the_same_persisted_facts() {
    let mut immediate = ready(10);
    let mut inline = Vec::new();
    let mut inline_durable = Vec::new();
    for id in [101, 102, 103, 104] {
        inline.extend(
            immediate
                .accept(trade(id), &mut |t| {
                    inline_durable.push(t.clone());
                    Ok(())
                })
                .unwrap(),
        );
    }
    let mut delayed = ready(10);
    let mut delayed_durable = Vec::new();
    assert!(
        delayed
            .accept(trade(103), &mut |_| panic!("缺口补齐前不能持久化"))
            .unwrap()
            .is_empty()
    );
    delayed.buffer(trade(104)).unwrap();
    let suffix = delayed
        .complete_recovery(vec![trade(102), trade(101), trade(103)], &mut |t| {
            delayed_durable.push(t.clone());
            Ok(())
        })
        .unwrap();
    assert_eq!(inline_durable, (101..=104).map(trade).collect::<Vec<_>>());
    assert_eq!(inline, inline_durable);
    assert_eq!(suffix, inline);
    assert_eq!(delayed_durable, inline_durable);
    for state in [immediate, delayed] {
        assert_eq!(state.checkpoint(), Some(104));
        assert_eq!(state.buffered_count(), 0);
        assert_eq!(state.state(), State::Ready);
    }
}
#[test]
fn incomplete_or_wrong_scope_recovery_never_advances_checkpoint_or_ready() {
    let mut c = ready(10);
    c.accept(trade(103), &mut |_| Ok(())).unwrap();
    assert_eq!(
        c.complete_recovery(vec![trade(102)], &mut |_| panic!(
            "proof before persistence"
        ))
        .err(),
        Some(Error::Order)
    );
    assert_eq!(c.checkpoint(), Some(100));
    assert_eq!(c.state(), State::Recovering);
    let mut fields = trade(101).input();
    fields.instrument_id = "ETHUSDT.BINANCE".parse().unwrap();
    let wrong = OnlyTradeTick::new(fields).unwrap();
    assert_eq!(
        c.complete_recovery(vec![wrong], &mut |_| panic!("foreign must not persist"))
            .err(),
        Some(Error::Shape)
    );
    assert_eq!(c.checkpoint(), Some(100));
}
#[test]
fn overflow_failure_and_disconnect_invalidate_ready() {
    let mut c = ready(1);
    c.accept(trade(103), &mut |_| Ok(())).unwrap();
    assert_eq!(c.buffer(trade(104)), Err(Error::TooLarge));
    assert_eq!(c.state(), State::Failed);
    assert!(c.connected().is_err());
    let mut c = ready(5);
    c.disconnected();
    assert_eq!(c.state(), State::Disconnected);
    assert!(
        c.accept(trade(101), &mut |_| panic!("disconnected must not persist"))
            .is_err()
    );
    c.connected().unwrap();
    c.subscription_established().unwrap();
    c.begin_recovery().unwrap();
    c.accept_baseline(trade(103), &mut |_| {
        panic!("reconnect baseline cannot skip")
    })
    .unwrap();
    assert_eq!(c.checkpoint(), Some(100));
    assert!(
        c.complete_recovery(vec![], &mut |_| panic!("gap must not persist"))
            .is_err()
    );
}
#[test]
fn durability_failure_prevents_sequence_advance_and_is_terminal() {
    let mut c = ready(5);
    assert_eq!(
        c.accept(trade(101), &mut |_| Err(Error::Evidence)).err(),
        Some(Error::Evidence)
    );
    assert_eq!(c.checkpoint(), Some(100));
    assert_eq!(c.state(), State::Failed);
    assert!(
        c.accept(trade(101), &mut |_| panic!("failed cannot resume"))
            .is_err()
    );
}
#[test]
fn ready_requires_real_baseline_subscription_and_conflicts_fail_closed() {
    let mut c = TradeContinuity::new("BTCUSDT.BINANCE".parse().unwrap(), 5).unwrap();
    assert!(c.begin_recovery().is_err());
    c.connected().unwrap();
    assert!(c.begin_recovery().is_err());
    c.subscription_established().unwrap();
    c.begin_recovery().unwrap();
    assert!(c.complete_recovery(vec![], &mut |_| Ok(())).is_err());
    c.accept_baseline(trade(100), &mut |_| Ok(())).unwrap();
    c.complete_recovery(vec![], &mut |_| Ok(())).unwrap();
    let mut fields = trade(100).input();
    fields.price = onlyalpha_domain::value::OnlyPrice::new("11".parse().unwrap(), 2).unwrap();
    assert!(
        c.accept(OnlyTradeTick::new(fields).unwrap(), &mut |_| panic!(
            "conflict"
        ))
        .is_err()
    );
    assert_eq!(c.state(), State::Failed);
}
#[test]
fn explicit_recorded_empty_baseline_and_first_real_trade_can_become_ready() {
    let mut c = TradeContinuity::new("BTCUSDT.BINANCE".parse().unwrap(), 5).unwrap();
    c.connected().unwrap();
    c.subscription_established().unwrap();
    c.begin_recovery().unwrap();
    c.establish_empty_baseline().unwrap();
    c.complete_recovery(vec![], &mut |_| Ok(())).unwrap();
    assert_eq!(c.state(), State::Ready);
    assert_eq!(c.checkpoint(), None);
    assert_eq!(c.accept(trade(100), &mut |_| Ok(())).unwrap().len(), 1);
    assert_eq!(c.checkpoint(), Some(100));
}
#[test]
fn conflicting_first_seen_recovery_rows_fail_permanently_instead_of_retrying_ready() {
    let mut c = ready(10);
    c.accept(trade(103), &mut |_| Ok(())).unwrap();
    let first = trade(101);
    let mut fields = first.input();
    fields.price = onlyalpha_domain::value::OnlyPrice::new("11".parse().unwrap(), 2).unwrap();
    let conflict = OnlyTradeTick::new(fields).unwrap();
    assert_eq!(
        c.complete_recovery(vec![first, conflict], &mut |_| panic!(
            "conflict must be proved before persistence"
        ))
        .err(),
        Some(Error::Order)
    );
    assert_eq!(c.state(), State::Failed);
    assert_eq!(c.checkpoint(), Some(100));
    assert!(
        c.complete_recovery(vec![trade(101), trade(102)], &mut |_| panic!(
            "failed recovery cannot commit"
        ))
        .is_err()
    );
    assert!(c.connected().is_err());
    assert_eq!(c.state(), State::Failed);
}
