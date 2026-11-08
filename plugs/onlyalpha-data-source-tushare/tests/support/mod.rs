use onlyalpha_data_source_tushare::{daily::*, http::*};
use onlyalpha_domain::{calendar::*, enums::*, instrument::*, time::OnlyTimeZone, value::*};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::Instant,
};
pub fn request() -> DailyRequest {
    let currency = OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat).unwrap();
    let spec = OnlyInstrumentSpecification::new(OnlyInstrumentSpecificationInput {
        instrument_id: "600000.XSHG".parse().unwrap(),
        raw_symbol: "600000".parse().unwrap(),
        asset_class: OnlyAssetClass::Equity,
        instrument_type: OnlyInstrumentType::Equity,
        market_type: OnlyMarketType::Cash,
        quote_currency: currency.clone(),
        settlement_currency: currency,
        price_precision: 4,
        quantity_precision: 0,
        tick_size: OnlyPrice::new("0.0001".parse().unwrap(), 4).unwrap(),
        step_size: OnlyQuantity::new("1".parse().unwrap(), 0).unwrap(),
        contract_multiplier: OnlyMultiplier::new("1".parse().unwrap(), 0).unwrap(),
        base_currency: None,
        margin_currency: None,
        minimum_quantity: None,
        maximum_quantity: None,
        minimum_notional: None,
        maximum_notional: None,
        minimum_price: None,
        maximum_price: None,
        lot_size: None,
        instrument_version: 1.into(),
        activation_time: None,
        effective_from: None,
        effective_to: None,
        timezone: "Asia/Shanghai".into(),
        trading_calendar_id: Some("CN_XSHG".parse().unwrap()),
        session_profile_id: None,
        status: OnlySecurityStatus::Active,
    })
    .unwrap();
    let sessions = [
        ("morning", "09:30:00", "11:30:00"),
        ("afternoon", "13:00:00", "15:00:00"),
    ]
    .into_iter()
    .map(|(name, open, close)| {
        OnlyTradingSession::new(OnlyTradingSessionInput {
            name: name.into(),
            opens_at: open.parse().unwrap(),
            closes_at: close.parse().unwrap(),
            session_type: OnlySessionType::Regular,
            belongs_to_trading_day_offset: 0,
            allows_orders: true,
            allows_market_data: true,
        })
        .unwrap()
    })
    .collect();
    let calendar = OnlyTradingCalendar::new(OnlyTradingCalendarInput {
        calendar_id: "CN_XSHG".parse().unwrap(),
        venue_id: "XSHG".parse().unwrap(),
        timezone: OnlyTimeZone::new("Asia/Shanghai").unwrap(),
        sessions,
        holidays: vec![],
        weekend_days: vec![5, 6],
        session_profile_id: None,
        special_schedules: vec![],
        calendar_version: 1.into(),
        effective_from: None,
        effective_to: None,
    })
    .unwrap();
    DailyRequest {
        source_id: "tushare-history".into(),
        instrument: OnlyInstrument::new(spec, OnlyInstrumentKind::Equity).unwrap(),
        calendar,
        start: "2025-01-02T16:00:00Z".parse().unwrap(),
        end: "2025-01-06T16:00:00Z".parse().unwrap(),
        adjustment: Adjustment::None,
        asset: Asset::Equity,
    }
}
pub fn table(fields: &[&str], rows: Vec<Value>) -> Vec<u8> {
    json!({"code":0,"msg":null,"data":{"fields":fields,"items":rows}})
        .to_string()
        .into_bytes()
}
pub fn daily(rows: Vec<Value>) -> Vec<u8> {
    table(
        &[
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
        ],
        rows,
    )
}
pub fn row(day: &str) -> Value {
    json!(["600000.SH", day, 10.00, 10.50, 9.50, 10.35, 123.45, 127.777])
}
#[derive(Default)]
pub struct Memory {
    pub data: Mutex<BTreeMap<String, Vec<Evidence>>>,
}
impl Cache for Memory {
    fn read(&self, key: &str) -> Result<Option<Vec<Evidence>>> {
        Ok(self.data.lock().unwrap().get(key).cloned())
    }
    fn write(&self, key: &str, e: &[Evidence]) -> Result<()> {
        self.data.lock().unwrap().insert(key.into(), e.to_vec());
        Ok(())
    }
}

/// 各测试独占一个目录；文件只保存 provider Query 和原始响应。
pub struct CacheDirectory(pub std::path::PathBuf);
impl CacheDirectory {
    pub fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        loop {
            let path = std::env::temp_dir().join(format!(
                "onlyalpha-tushare-evidence-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            let mut builder = std::fs::DirBuilder::new();
            #[cfg(unix)]
            std::os::unix::fs::DirBuilderExt::mode(&mut builder, 0o700);
            match builder.create(&path) {
                Ok(()) => return Self(path),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!("无法建立测试缓存目录: {error}"),
            }
        }
    }
}
impl Drop for CacheDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

pub struct FileCache<'a>(pub &'a std::path::Path);
impl Cache for FileCache<'_> {
    fn read(&self, key: &str) -> Result<Option<Vec<Evidence>>> {
        let bytes = match std::fs::read(self.0.join(key)) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(Error::Evidence),
        };
        type StoredObservation = (String, BTreeMap<String, String>, String, Vec<u8>);
        let (stored_key, rows): (String, Vec<StoredObservation>) =
            serde_json::from_slice(&bytes).map_err(|_| Error::Evidence)?;
        if stored_key != key {
            return Err(Error::Evidence);
        }
        let evidence = rows
            .into_iter()
            .map(|(api, parameters, fields, response)| {
                Ok(Evidence {
                    query: Query::new(&api, parameters, &fields)?,
                    response,
                })
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(Some(evidence))
    }
    fn write(&self, key: &str, evidence: &[Evidence]) -> Result<()> {
        let rows: Vec<_> = evidence
            .iter()
            .map(|e| {
                (
                    &e.query.api,
                    &e.query.parameters,
                    &e.query.fields,
                    &e.response,
                )
            })
            .collect();
        let bytes = serde_json::to_vec(&(key, rows)).map_err(|_| Error::Evidence)?;
        let destination = self.0.join(key);
        let staging = destination.with_extension("stage");
        std::fs::write(&staging, bytes).map_err(|_| Error::Evidence)?;
        std::fs::rename(staging, destination).map_err(|_| Error::Evidence)
    }
}
pub struct Fixture {
    pub responses: Mutex<Vec<Vec<u8>>>,
    pub queries: Mutex<Vec<Query>>,
    pub calls: AtomicUsize,
}
impl Fixture {
    pub fn new(responses: Vec<Vec<u8>>) -> Arc<Self> {
        Arc::new(Self {
            responses: Mutex::new(responses.into_iter().rev().collect()),
            queries: Mutex::new(vec![]),
            calls: AtomicUsize::new(0),
        })
    }
}
impl Transport for Fixture {
    fn post<'a>(&'a self, q: &'a Query, _: Instant) -> ResponseFuture<'a> {
        Box::pin(async move {
            self.calls.fetch_add(1, Ordering::SeqCst);
            self.queries.lock().unwrap().push(q.clone());
            self.responses.lock().unwrap().pop().ok_or(Error::Request)
        })
    }
}
