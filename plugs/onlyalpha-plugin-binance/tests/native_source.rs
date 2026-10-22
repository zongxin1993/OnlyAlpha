use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_plugin_binance::spot_normalize::{instrument, rest_bar_interval};
use serde_json::json;

#[test]
fn every_native_interval_has_its_own_closed_bar_semantic_and_grid() {
    let i = instrument(&json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]})).unwrap();
    for minutes in [1, 3, 5, 15, 30, 60, 120, 240] {
        let row = json!([
            0,
            "10",
            "11",
            "9",
            "10.5",
            "1.23",
            i64::from(minutes) * 60000 - 1,
            "12.915",
            3,
            "0",
            "0",
            "0"
        ]);
        let bar = rest_bar_interval(&row, &i, minutes).unwrap().to_record();
        assert_eq!(
            bar["bar_type"]["semantic"]["formation"]["window_minutes"],
            minutes
        );
        assert_eq!(
            bar["bar_type"]["semantic"]["formation"]["stride_minutes"],
            minutes
        );
        let mut anchored = row.clone();
        anchored[0] = json!(86400000);
        anchored[6] = json!(86400000 + i64::from(minutes) * 60000 - 1);
        assert!(rest_bar_interval(&anchored, &i, minutes).is_ok());
        let mut wrong = row.clone();
        wrong[6] = json!(59998);
        assert!(rest_bar_interval(&wrong, &i, minutes).is_err());
        let mut wrong = row;
        wrong[0] = json!(60000);
        wrong[6] = json!((i64::from(minutes) + 1) * 60000 - 1);
        if minutes > 1 {
            assert!(rest_bar_interval(&wrong, &i, minutes).is_err());
        }
    }
    assert!(rest_bar_interval(&json!([]), &i, 7).is_err());
}
