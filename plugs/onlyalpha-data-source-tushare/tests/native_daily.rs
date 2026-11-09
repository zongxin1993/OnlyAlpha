mod support;
use onlyalpha_data_source_tushare::{daily::*, http::*, mapping};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTradingDay};
use onlyalpha_integration_contract::source::Budget;
use serde_json::json;
use std::{sync::atomic::Ordering, time::Instant};
use support::*;
fn budget() -> Budget {
    Budget::from_millis(5000).unwrap()
}
fn now() -> onlyalpha_domain::time::OnlyUtcDateTime {
    "2025-01-07T00:00:00Z".parse().unwrap()
}
#[test]
fn response_protocol_rejects_non_table_permissions_duplicates_and_wrong_width() {
    for raw in [
        br#"null"#.as_slice(),
        br#"{"code":0,"data":{"fields":["a","a"],"items":[]}}"#,
        br#"{"code":0,"code":0,"data":{"fields":["a"],"items":[]}}"#,
        br#"{"code":0,"data":{"fields":["a"],"items":[[1,2]]}}"#,
    ] {
        assert!(Table::decode(raw).is_err())
    }
    assert_eq!(
        Table::decode(br#"{"code":2002,"msg":"SECRET token echo"}"#).unwrap_err(),
        Error::Permission
    );
    assert_eq!(
        Table::decode(br#"{"code":-2001,"msg":"SECRET"}"#).unwrap_err(),
        Error::Provider
    );
    assert!(!Error::Provider.to_string().contains("SECRET"));
    assert_eq!(
        Table::decode(&vec![b' '; MAX_RESPONSE + 1]).unwrap_err(),
        Error::TooLarge
    );
}
#[test]
fn exact_rational_adjustment_independent_fixed_vectors() {
    for (p, f, a, want) in [
        ("10.35", "2", "4", "5.18"),
        ("10.35", "2", "1", "20.70"),
        ("1.005", "1", "1", "1.00"),
        ("1.015", "1", "1", "1.02"),
        (
            "100000000000000000000.005",
            "1",
            "1",
            "100000000000000000000.00",
        ),
        ("1", "1", "3", "0.33"),
    ] {
        assert_eq!(adjusted_price(p, f, a).unwrap(), want)
    }
    for (p, f, a) in [
        ("1", "0", "1"),
        ("NaN", "1", "1"),
        ("1", "1", "0"),
        ("-1", "1", "1"),
    ] {
        assert!(adjusted_price(p, f, a).is_err())
    }
}
#[test]
fn symbols_and_historical_reference_require_explicit_joined_facts() {
    assert!(date("00000101").is_err());
    assert!(date("20250230").is_err());
    assert_eq!(mapping::symbol("600000.XSHG").unwrap(), "600000.SH");
    assert_eq!(mapping::symbol("000001.XSHE").unwrap(), "000001.SZ");
    assert_eq!(mapping::symbol("430047.XBSE").unwrap(), "430047.BJ");
    for id in ["60000.XSHG", "600000.XHKG", "６０００００.XSHG"] {
        assert!(mapping::symbol(id).is_err())
    }
    let raw = json!({"ts_code":"600000.SH","exchange":"SSE","market":"主板","security_type":"COMMON_STOCK","lot_size":"100","price_tick":"0.01","st_status":false,"suspended":false,"pre_close":"10.00","trade_date":"2025-01-02","effective_to":"2025-01-03","source_version":"tushare-fixture-v1","data_version":"reference-v1"});
    let r = mapping::ashare_reference(&raw).unwrap();
    assert_eq!(r.instrument().to_string(), "600000.XSHG");
    assert_eq!(r.record()["previous_close"], "10");
    assert_eq!(r.record()["source"], "TUSHARE");
    for field in [
        "st_status",
        "suspended",
        "security_type",
        "source_version",
        "data_version",
        "trade_date",
    ] {
        let mut v = raw.clone();
        v.as_object_mut().unwrap().remove(field);
        assert!(mapping::ashare_reference(&v).is_err(), "{field}")
    }
    let mut mismatch = raw.clone();
    mismatch["exchange"] = json!("SZSE");
    assert!(mapping::ashare_reference(&mismatch).is_err());
}
#[tokio::test]
async fn daily_native_calendar_time_units_order_duplicate_and_cache_only() {
    let fixture = Fixture::new(vec![daily(vec![
        row("20250106"),
        row("20250103"),
        row("20250103"),
    ])]);
    let cache = Memory::default();
    let client = DailyClient::new(fixture.clone());
    let request = request();
    let result = client
        .load(&request, CachePolicy::PreferCache, &cache, budget(), now())
        .await
        .unwrap();
    assert_eq!(result.bars.len(), 2);
    assert_eq!(result.identical_duplicates, 1);
    let bar = &result.bars[0];
    assert_eq!(bar.trading_day().to_string(), "2025-01-03");
    assert_eq!(bar.bar_start().to_string(), "2025-01-03T01:30:00Z");
    assert_eq!(bar.bar_end().to_string(), "2025-01-03T07:00:00Z");
    assert_eq!(bar.ts_event(), bar.bar_end());
    assert_eq!(bar.volume().value().to_string(), "12345");
    assert_eq!(
        bar.turnover().as_ref().unwrap().amount().to_string(),
        "127777"
    );
    assert_eq!(
        bar.to_record()["bar_type"]["semantic"]["formation"]["kind"],
        "CALENDAR_PERIOD"
    );
    assert_eq!(
        bar.to_record()["bar_type"]["semantic"]["formation"]["unit"],
        "DAY"
    );
    {
        let queries = fixture.queries.lock().unwrap();
        let q = &queries[0];
        assert_eq!(q.api, "daily");
        assert_eq!(q.parameters["start_date"], "20250103");
        assert_eq!(q.parameters["end_date"], "20250106");
        assert!(!q.parameters.contains_key("token"));
    }
    let again = client
        .load(&request, CachePolicy::CacheOnly, &cache, budget(), now())
        .await
        .unwrap();
    assert!(again.cache_hit);
    assert_eq!(again.bars, result.bars);
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
}
#[tokio::test]
async fn adjustment_anchor_is_end_date_latest_factor_not_last_bar_and_cache_identity() {
    let factors = table(
        &["ts_code", "trade_date", "adj_factor"],
        vec![
            json!(["600000.SH", "20250103", "2"]),
            json!(["600000.SH", "20250106", "4"]),
        ],
    );
    let fixture = Fixture::new(vec![
        daily(vec![row("20250103")]),
        factors.clone(),
        daily(vec![row("20250103")]),
        factors,
    ]);
    let client = DailyClient::new(fixture.clone());
    let cache = Memory::default();
    let mut r = request();
    let raw = r.cache_key().unwrap();
    r.adjustment = Adjustment::Qfq;
    let qfq = r.cache_key().unwrap();
    let result = client
        .load(&r, CachePolicy::ForceRefresh, &cache, budget(), now())
        .await
        .unwrap();
    assert_eq!(result.bars[0].close().value().to_string(), "5.18");
    r.adjustment = Adjustment::Hfq;
    let hfq = r.cache_key().unwrap();
    let result = client
        .load(&r, CachePolicy::ForceRefresh, &cache, budget(), now())
        .await
        .unwrap();
    assert_eq!(result.bars[0].close().value().to_string(), "20.70");
    assert_ne!(raw, qfq);
    assert_ne!(qfq, hfq);
    r.adjustment = Adjustment::Qfq;
    r.end = "2025-01-05T16:00:00Z".parse().unwrap();
    assert_ne!(r.cache_key().unwrap(), qfq);
    let mut r = request();
    r.adjustment = Adjustment::Qfq;
    let missing_anchor = Fixture::new(vec![
        daily(vec![row("20250103")]),
        table(
            &["ts_code", "trade_date", "adj_factor"],
            vec![json!(["600000.SH", "20250103", "2"])],
        ),
    ]);
    assert!(matches!(
        DailyClient::new(missing_anchor)
            .load(&r, CachePolicy::ForceRefresh, &cache, budget(), now())
            .await,
        Err(Error::Evidence)
    ));
    let invalid_calendar = Fixture::new(vec![
        daily(vec![row("20250103")]),
        table(
            &["ts_code", "trade_date", "adj_factor"],
            vec![
                json!(["600000.SH", "20250103", "2"]),
                json!(["600000.SH", "20250104", "4"]),
                json!(["600000.SH", "20250106", "4"]),
            ],
        ),
    ]);
    assert!(matches!(
        DailyClient::new(invalid_calendar)
            .load(&r, CachePolicy::ForceRefresh, &cache, budget(), now())
            .await,
        Err(Error::Calendar)
    ));
}
#[tokio::test]
async fn invalid_ohlc_volume_amount_symbol_dates_and_conflicts_fail_closed() {
    let cases = [
        (2, json!("NaN")),
        (3, json!("9")),
        (4, json!("11")),
        (6, json!("-1")),
        (7, json!("-1")),
        (0, json!("000001.SZ")),
        (1, json!("20250230")),
        (1, json!("20250104")),
        (1, json!("20250102")),
        (2, json!("10.00001")),
    ];
    for (index, value) in cases {
        let mut v = row("20250103");
        v[index] = value;
        let fixture = Fixture::new(vec![daily(vec![v])]);
        let result = DailyClient::new(fixture)
            .load(
                &request(),
                CachePolicy::ForceRefresh,
                &Memory::default(),
                budget(),
                now(),
            )
            .await;
        assert!(result.is_err(), "{index}")
    }
    let mut different = row("20250103");
    different[5] = json!("10.36");
    let fixture = Fixture::new(vec![daily(vec![row("20250103"), different])]);
    assert!(matches!(
        DailyClient::new(fixture)
            .load(
                &request(),
                CachePolicy::ForceRefresh,
                &Memory::default(),
                budget(),
                now()
            )
            .await,
        Err(Error::Conflict)
    ));
}
#[tokio::test]
async fn empty_open_days_missing_factors_unclosed_session_and_cache_miss_are_errors() {
    let cache = Memory::default();
    let fixture = Fixture::new(vec![]);
    let client = DailyClient::new(fixture.clone());
    assert!(matches!(
        client
            .load(&request(), CachePolicy::CacheOnly, &cache, budget(), now())
            .await,
        Err(Error::CacheMiss)
    ));
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 0);
    let fixture = Fixture::new(vec![daily(vec![])]);
    assert!(matches!(
        DailyClient::new(fixture)
            .load(
                &request(),
                CachePolicy::ForceRefresh,
                &cache,
                budget(),
                now()
            )
            .await,
        Err(Error::Empty)
    ));
    let mut weekend = request();
    weekend.start = "2025-01-03T16:00:00Z".parse().unwrap();
    weekend.end = "2025-01-05T16:00:00Z".parse().unwrap();
    let fixture = Fixture::new(vec![daily(vec![])]);
    assert!(
        DailyClient::new(fixture)
            .load(&weekend, CachePolicy::ForceRefresh, &cache, budget(), now())
            .await
            .unwrap()
            .bars
            .is_empty()
    );
    let fixture = Fixture::new(vec![
        daily(vec![row("20250103")]),
        table(&["ts_code", "trade_date", "adj_factor"], vec![]),
    ]);
    let mut r = request();
    r.adjustment = Adjustment::Qfq;
    assert!(
        DailyClient::new(fixture)
            .load(&r, CachePolicy::ForceRefresh, &cache, budget(), now())
            .await
            .is_err()
    );
    let fixture = Fixture::new(vec![daily(vec![row("20250103")])]);
    assert!(matches!(
        DailyClient::new(fixture)
            .load(
                &request(),
                CachePolicy::ForceRefresh,
                &cache,
                budget(),
                "2025-01-03T06:59:00Z".parse().unwrap()
            )
            .await,
        Err(Error::Calendar)
    ));
}
#[tokio::test]
async fn cache_replays_evidence_and_rejects_wrong_association() {
    let cache = Memory::default();
    let fixture = Fixture::new(vec![daily(vec![row("20250103")])]);
    let client = DailyClient::new(fixture.clone());
    let r = request();
    client
        .load(&r, CachePolicy::PreferCache, &cache, budget(), now())
        .await
        .unwrap();
    cache
        .data
        .lock()
        .unwrap()
        .get_mut(&r.cache_key().unwrap())
        .unwrap()[0]
        .query
        .parameters
        .insert("ts_code".into(), "000001.SZ".into());
    assert!(matches!(
        client
            .load(&r, CachePolicy::CacheOnly, &cache, budget(), now())
            .await,
        Err(Error::Evidence)
    ));
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn malformed_daily_prices_and_required_columns_never_populate_cache() {
    let fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ];
    let mut bad_high = row("20250103");
    bad_high[3] = json!("Infinity");
    let mut cases = vec![("nonfinite high", daily(vec![bad_high]))];
    for (index, name) in fields[..7].iter().enumerate() {
        let mut columns = fields.to_vec();
        columns.remove(index);
        let mut values = row("20250103");
        values.as_array_mut().unwrap().remove(index);
        cases.push((*name, table(&columns, vec![values])));
    }
    for (case, response) in cases {
        let cache = Memory::default();
        let fixture = Fixture::new(vec![response]);
        let result = DailyClient::new(fixture.clone())
            .load(
                &request(),
                CachePolicy::ForceRefresh,
                &cache,
                budget(),
                now(),
            )
            .await;
        assert!(matches!(result, Err(Error::Shape)), "{case}");
        assert!(cache.data.lock().unwrap().is_empty(), "{case}");
        assert_eq!(fixture.calls.load(Ordering::SeqCst), 1, "{case}");
    }
}

async fn replay_reopened_cache(
    directory: &CacheDirectory,
    request: &DailyRequest,
    first: &DailyResult,
    as_of: onlyalpha_domain::time::OnlyUtcDateTime,
) {
    let offline = Fixture::new(vec![]);
    let replay = DailyClient::new(offline.clone())
        .load(
            request,
            CachePolicy::CacheOnly,
            &FileCache(&directory.0),
            budget(),
            as_of,
        )
        .await
        .unwrap();
    assert_eq!(offline.calls.load(Ordering::SeqCst), 0);
    assert!(!first.cache_hit && replay.cache_hit);
    assert!(!first.bars.is_empty());
    assert!(
        first
            .bars
            .windows(2)
            .all(|bars| bars[0].ts_event() < bars[1].ts_event())
    );
    assert_eq!(first.bars, replay.bars);
    assert_eq!(first.cache_key, request.cache_key().unwrap());
    assert_eq!(first.cache_key, replay.cache_key);
    assert!(first.evidence == replay.evidence);
    assert_eq!(first.factor_basis, replay.factor_basis);
    assert_eq!(
        first.normalized_daily_fingerprint,
        replay.normalized_daily_fingerprint
    );
}

#[tokio::test]
async fn reopened_cache_replays_complete_evidence_and_fails_closed_on_misassociation() {
    let directory = CacheDirectory::new();
    let mut r = request();
    r.adjustment = Adjustment::Qfq;
    let prices = daily(vec![row("20250106"), row("20250103")]);
    let factors = table(
        &["ts_code", "trade_date", "adj_factor"],
        vec![
            json!(["600000.SH", "20250103", 2]),
            json!(["600000.SH", "20250106", 4]),
        ],
    );
    let fixture = Fixture::new(vec![prices.clone(), factors.clone()]);
    let first = DailyClient::new(fixture.clone())
        .load(
            &r,
            CachePolicy::PreferCache,
            &FileCache(&directory.0),
            budget(),
            now(),
        )
        .await
        .unwrap();
    assert_eq!(fixture.calls.load(Ordering::SeqCst), 2);
    assert_eq!(first.evidence.len(), 2);
    assert_eq!(first.evidence[0].response, prices);
    assert_eq!(first.evidence[1].response, factors);
    assert_eq!(first.bars.len(), 2);
    replay_reopened_cache(&directory, &r, &first, now()).await;

    let offline = Fixture::new(vec![]);
    let client = DailyClient::new(offline.clone());
    let cache = FileCache(&directory.0);
    let key = r.cache_key().unwrap();
    let path = directory.0.join(&key);
    let mut other = r.clone();
    other.source_id.push_str("-other");
    let other_key = other.cache_key().unwrap();
    assert_ne!(key, other_key);
    let offline_load = |r| client.load(r, CachePolicy::CacheOnly, &cache, budget(), now());
    assert!(matches!(offline_load(&other).await, Err(Error::CacheMiss)));
    std::fs::copy(&path, directory.0.join(other_key)).unwrap();
    assert!(matches!(offline_load(&other).await, Err(Error::Evidence)));
    std::fs::write(&path, b"{").unwrap();
    assert!(matches!(offline_load(&r).await, Err(Error::Evidence)));
    let mut wrong_query = first.evidence.clone();
    wrong_query[1]
        .query
        .parameters
        .insert("ts_code".into(), "000001.SZ".into());
    cache.write(&key, &wrong_query).unwrap();
    assert!(matches!(offline_load(&r).await, Err(Error::Evidence)));
    assert_eq!(offline.calls.load(Ordering::SeqCst), 0);
}

#[tokio::test]
#[ignore = "真实 Tushare 日线与缓存专项，需显式授权和专用凭据"]
async fn authorized_real_daily_cache_roundtrip() {
    use onlyalpha_integration_contract::source::Trust;
    use std::sync::{Arc, Mutex};
    struct ObservedHttp {
        transport: HttpTransport,
        calls: Mutex<Vec<String>>,
    }
    impl Transport for ObservedHttp {
        fn post<'a>(&'a self, query: &'a Query, deadline: Instant) -> ResponseFuture<'a> {
            self.calls.lock().unwrap().push(query.api.clone());
            self.transport.post(query, deadline)
        }
    }
    assert_eq!(
        std::env::var("ONLYALPHA_TUSHARE_DAILY_TEST_AUTHORIZED").as_deref(),
        Ok("1")
    );
    let token = zeroize::Zeroizing::new(
        std::env::var("ONLYALPHA_TUSHARE_DAILY_TEST_TOKEN").expect("需要专项 token"),
    );
    let ca = std::env::var_os("ONLYALPHA_TUSHARE_DAILY_TEST_CA_PEM").expect("需要专用信任根路径");
    let trust = Trust::explicit_roots(vec![std::fs::read(ca).expect("读取专项信任根")]).unwrap();
    let http = Arc::new(ObservedHttp {
        transport: HttpTransport::new(&token, &trust).unwrap(),
        calls: Mutex::new(vec![]),
    });
    drop(token);
    let client = DailyClient::new(http.clone());
    let mut r = request();
    r.start = "2025-01-01T00:00:00Z".parse().unwrap();
    r.end = "2025-01-11T00:00:00Z".parse().unwrap();
    let as_of = "2025-01-12T00:00:00Z".parse().unwrap();
    let external_budget = Budget::from_millis(30_000).unwrap();
    r.calendar = client
        .calendar(
            &r.calendar,
            date("20250101").unwrap(),
            date("20250111").unwrap(),
            external_budget,
        )
        .await
        .unwrap()
        .calendar;
    let directory = CacheDirectory::new();
    let first = client
        .load(
            &r,
            CachePolicy::PreferCache,
            &FileCache(&directory.0),
            external_budget,
            as_of,
        )
        .await
        .unwrap();
    drop(client);
    assert_eq!(*http.calls.lock().unwrap(), ["trade_cal", "daily"]);
    drop(http);
    replay_reopened_cache(&directory, &r, &first, as_of).await;
}
#[tokio::test]
async fn provider_calendar_requires_complete_finite_dates_and_freezes_holidays() {
    let body = table(
        &["exchange", "cal_date", "is_open"],
        vec![
            json!(["SSE", "20250104", 0]),
            json!(["SSE", "20250103", 1]),
            json!(["SSE", "20250102", 0]),
        ],
    );
    let fixture = Fixture::new(vec![body]);
    let client = DailyClient::new(fixture);
    let r = request();
    let result = client
        .calendar(
            &r.calendar,
            date("20250102").unwrap(),
            date("20250104").unwrap(),
            budget(),
        )
        .await
        .unwrap();
    assert!(
        !result
            .calendar
            .is_trading_day(OnlyTradingDay::new(date("20250102").unwrap()).unwrap())
    );
    assert!(
        result
            .calendar
            .is_trading_day(OnlyTradingDay::new(date("20250103").unwrap()).unwrap())
    );
    assert_eq!(
        result.calendar.effective_to().unwrap().to_string(),
        "2025-01-05"
    );
    let fixture = Fixture::new(vec![table(
        &["exchange", "cal_date", "is_open"],
        vec![json!(["SSE", "20250103", 1])],
    )]);
    assert!(matches!(
        DailyClient::new(fixture)
            .calendar(
                &r.calendar,
                date("20250102").unwrap(),
                date("20250104").unwrap(),
                budget()
            )
            .await,
        Err(Error::Calendar)
    ));
}
#[tokio::test]
async fn securities_are_not_fabricated_historical_references() {
    let fixture = Fixture::new(vec![table(
        &[
            "ts_code",
            "name",
            "market",
            "exchange",
            "list_date",
            "delist_date",
        ],
        vec![json!([
            "600000.SH",
            "浦发银行",
            "主板",
            "SSE",
            "19991110",
            null
        ])],
    )]);
    let result = DailyClient::new(fixture)
        .securities("SSE", Asset::Equity, budget())
        .await
        .unwrap();
    assert_eq!(result.evidence.query.api, "stock_basic");
    assert_eq!(result.scope, SecurityScope::ListedEquities);
    assert_eq!(result.exchange, "SSE");
    assert_eq!(result.rows.len(), 1);
    let table = Table::decode(&result.evidence.response).unwrap();
    let value = serde_json::to_value(&table.rows[0]).unwrap();
    assert!(mapping::ashare_reference(&value).is_err());
}
struct Pending;
impl Transport for Pending {
    fn post<'a>(&'a self, _: &'a Query, _: Instant) -> ResponseFuture<'a> {
        Box::pin(std::future::pending())
    }
}
#[tokio::test]
async fn one_absolute_budget_bounds_noncooperative_transport() {
    let result = DailyClient::new(std::sync::Arc::new(Pending))
        .load(
            &request(),
            CachePolicy::ForceRefresh,
            &Memory::default(),
            Budget::from_millis(1).unwrap(),
            now(),
        )
        .await;
    assert!(matches!(result, Err(Error::Deadline)));
}
struct CancelObserved(std::sync::Arc<std::sync::atomic::AtomicUsize>);
impl Transport for CancelObserved {
    fn post<'a>(&'a self, _: &'a Query, _: Instant) -> ResponseFuture<'a> {
        struct Active(std::sync::Arc<std::sync::atomic::AtomicUsize>);
        impl Drop for Active {
            fn drop(&mut self) {
                self.0.fetch_sub(1, Ordering::SeqCst);
            }
        }
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
            let _active = Active(self.0.clone());
            std::future::pending().await
        })
    }
}
#[tokio::test]
async fn cancellation_drops_original_io_and_never_writes_cache() {
    use std::{
        future::Future,
        task::{Context, Poll, Waker},
    };
    let active = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let client = DailyClient::new(std::sync::Arc::new(CancelObserved(active.clone())));
    let request = request();
    let cache = Memory::default();
    let mut operation =
        Box::pin(client.load(&request, CachePolicy::ForceRefresh, &cache, budget(), now()));
    let mut context = Context::from_waker(Waker::noop());
    assert!(matches!(
        operation.as_mut().poll(&mut context),
        Poll::Pending
    ));
    assert_eq!(active.load(Ordering::SeqCst), 1);
    drop(operation);
    assert_eq!(active.load(Ordering::SeqCst), 0);
    assert!(cache.data.lock().unwrap().is_empty());
}

#[tokio::test]
async fn listed_fund_candidates_filter_exchange_without_rewriting_original_evidence() {
    let raw = table(
        &["ts_code", "name", "market", "list_date", "delist_date"],
        vec![
            json!(["510300.SH", "沪深300ETF", "E", "20120528", null]),
            json!(["159919.SZ", "沪深300ETF", "E", "20120528", null]),
            json!(["501001.SH", "示例LOF", "E", "20150101", null]),
        ],
    );
    let fixture = Fixture::new(vec![raw.clone(), raw.clone(), raw.clone()]);
    let client = DailyClient::new(fixture);
    for (exchange, expected) in [
        ("SSE", vec!["501001.SH", "510300.SH"]),
        ("SZSE", vec!["159919.SZ"]),
        ("BSE", vec![]),
    ] {
        let result = client
            .securities(exchange, Asset::Etf, budget())
            .await
            .unwrap();
        assert_eq!(result.scope, SecurityScope::ListedFundCandidates);
        assert_eq!(result.exchange, exchange);
        assert_eq!(
            result
                .rows
                .iter()
                .map(|row| row["ts_code"].as_str().unwrap())
                .collect::<Vec<_>>(),
            expected
        );
        assert_eq!(result.evidence.response, raw);
        assert_eq!(
            Table::decode(&result.evidence.response).unwrap().rows.len(),
            3
        );
        assert_eq!(result.evidence.query.parameters["market"], "E");
    }
    let wrong_market = Fixture::new(vec![table(
        &["ts_code", "name", "market", "list_date", "delist_date"],
        vec![json!(["510300.SH", "错误市场", "O", "20120528", null])],
    )]);
    assert!(matches!(
        DailyClient::new(wrong_market)
            .securities("SSE", Asset::Etf, budget())
            .await,
        Err(Error::Shape)
    ));
}

#[test]
fn immutable_day_replay_binds_real_anchor_and_all_price_inputs() {
    let original = request();
    let instrument = original.instrument.specification();
    let mut request = HistoricalDay {
        instrument: instrument.instrument_id(),
        currency: instrument.quote_currency(),
        price_precision: 18,
        quantity_precision: 0,
        calendar: &original.calendar,
        start: original.start,
        end: original.end,
        asset: Asset::Equity,
        adjustment: Adjustment::Qfq,
        anchor: Some(date("20250103").unwrap()),
    };
    let replay = |request: &HistoricalDay<'_>, prices, factors| {
        let queries = request.queries().unwrap();
        request.replay(
            vec![
                Evidence {
                    query: queries[0].clone(),
                    response: daily(prices),
                },
                Evidence {
                    query: queries[1].clone(),
                    response: table(&["ts_code", "trade_date", "adj_factor"], factors),
                },
            ],
            now(),
            budget(),
        )
    };
    let prices = vec![row("20250103"), row("20250106")];
    let factors = vec![
        json!(["600000.SH", "20250103", 2]),
        json!(["600000.SH", "20250106", 4]),
    ];
    let first = replay(&request, prices.clone(), factors.clone()).unwrap();
    let mut reversed = prices.clone();
    reversed.reverse();
    let second = replay(&request, reversed, factors.iter().rev().cloned().collect()).unwrap();
    assert_eq!(
        first.normalized_daily_fingerprint,
        second.normalized_daily_fingerprint
    );
    assert_eq!(first.factor_basis, second.factor_basis);
    assert_eq!(first.factor_basis.as_ref().unwrap()["anchor_factor"], "2");
    let mut corrected = prices.clone();
    corrected[0][5] = json!(10.34);
    let correction = replay(&request, corrected, factors.clone()).unwrap();
    assert_ne!(
        first.normalized_daily_fingerprint,
        correction.normalized_daily_fingerprint
    );
    assert_eq!(first.factor_basis, correction.factor_basis);
    request.anchor = Some(date("20250106").unwrap());
    let adjusted = replay(&request, prices.clone(), factors.clone()).unwrap();
    assert_ne!(first.factor_basis, adjusted.factor_basis);
    assert_ne!(first.bars[0].close(), adjusted.bars[0].close());
    assert_eq!(adjusted.factor_basis.unwrap()["anchor_factor"], "4");
    assert!(replay(&request, prices.clone(), factors[..1].to_vec()).is_err());
    request.end = "2025-01-06T00:00:00Z".parse().unwrap();
    let outside_anchor = replay(&request, prices.clone(), factors.clone()).unwrap();
    assert_eq!(outside_anchor.bars.len(), 1);
    assert_eq!(outside_anchor.factor_basis.unwrap()["anchor_factor"], "4");
    request.anchor = Some(date("20250103").unwrap());
    let selected = replay(&request, prices.clone(), factors.clone()).unwrap();
    let mut outside = prices.clone();
    outside[1][5] = json!(10.34);
    let mut changed_factors = factors.clone();
    changed_factors[1][2] = json!(5);
    let changed = replay(&request, outside, changed_factors).unwrap();
    assert_eq!(
        selected.normalized_daily_fingerprint,
        changed.normalized_daily_fingerprint
    );
    assert_eq!(selected.factor_basis, changed.factor_basis);
    assert_ne!(selected.evidence, changed.evidence);
    request.end = "2025-01-06T03:00:00Z".parse().unwrap();
    assert!(replay(&request, prices.clone(), factors.clone()).is_err());
    request.start = "2025-01-03T03:00:00Z".parse().unwrap();
    request.end = original.end;
    assert!(replay(&request, prices.clone(), factors.clone()).is_err());
    request.start = original.start;
    request.anchor = Some(date("20250105").unwrap());
    assert!(replay(&request, prices, factors).is_err());
}
