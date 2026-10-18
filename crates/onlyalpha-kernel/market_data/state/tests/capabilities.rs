use onlyalpha_market_data_state::OnlyMarketDataSnapshot;
#[test]
fn immutable_snapshot_is_send_and_sync() {
    fn check<T: Send + Sync>() {}
    check::<OnlyMarketDataSnapshot>();
}
