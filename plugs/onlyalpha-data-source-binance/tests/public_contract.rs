use onlyalpha_data_source_binance::spot_rest::PublicRest;
use onlyalpha_integration_contract::source::Trust;
use serde_json::value::RawValue;
use std::time::{Duration, Instant};

const MINUTE_MS: i64 = 60_000;

#[test]
#[ignore = "真实 Binance 公共行情专项，需显式授权并提供信任根"]
fn authorized_public_spot_reference_and_closed_minutes_on_three_environments() {
    assert_eq!(
        std::env::var("ONLYALPHA_BINANCE_PUBLIC_TEST_AUTHORIZED").as_deref(),
        Ok("1")
    );
    let path =
        std::env::var_os("ONLYALPHA_BINANCE_PUBLIC_TEST_CA_PEM").expect("需要专项信任根路径");
    let trust = Trust::explicit_roots(vec![std::fs::read(path).expect("读取专项信任根")]).unwrap();
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
            for (environment, profile, base) in [
                (
                    "GLOBAL",
                    "PUBLIC_MARKET_DATA",
                    "https://data-api.binance.vision",
                ),
                ("US", "DEFAULT", "https://api.binance.us"),
                ("SPOT_TESTNET", "DEFAULT", "https://testnet.binance.vision"),
            ] {
                let raw = RawValue::from_string(
                    serde_json::json!({"environment":environment,"endpoint_profile":profile})
                        .to_string(),
                )
                .unwrap();
                let rest = PublicRest::from_configuration(&raw, 65_536, &trust).unwrap();
                assert_eq!(rest.rest_base(), base);
                let deadline = Instant::now() + Duration::from_secs(30);
                rest.ping(deadline).await.unwrap();
                let server = rest.server_time(deadline).await.unwrap();
                let info = rest
                    .exchange_info(&["BTCUSDT".into()], deadline)
                    .await
                    .unwrap();
                let symbols = info.value()["symbols"].as_array().unwrap();
                assert_eq!(symbols.len(), 1);
                assert_eq!(symbols[0]["symbol"], "BTCUSDT");
                let instrument =
                    onlyalpha_data_source_binance::spot_normalize::instrument(&symbols[0]).unwrap();
                let end_ms = server.div_euclid(MINUTE_MS) * MINUTE_MS;
                let start_ms = end_ms - 2 * MINUTE_MS;
                let pages = rest
                    .historical_klines_observed(
                        "BTCUSDT",
                        start_ms,
                        end_ms,
                        deadline,
                        &mut |_, _| Ok(()),
                    )
                    .await
                    .unwrap();
                let bars: Vec<_> = pages
                    .iter()
                    .flat_map(|p| p.canonical_bars(rest.source_id(), &instrument).unwrap())
                    .collect();
                assert_eq!(bars.len(), 2, "{environment}");
                for (i, bar) in bars.iter().enumerate() {
                    let open = start_ms + i as i64 * MINUTE_MS;
                    assert_eq!(
                        bar.bar_start().timestamp().total_nanoseconds(),
                        i128::from(open) * 1_000_000
                    );
                    assert_eq!(
                        bar.bar_end().timestamp().total_nanoseconds(),
                        i128::from(open + MINUTE_MS) * 1_000_000
                    );
                    assert!(bar.is_closed());
                }
            }
        });
}
