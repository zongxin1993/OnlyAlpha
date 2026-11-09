//! 正式历史日线数据源。Host 持有凭据准入、原始输入封存与结果发布权限。
use crate::{
    daily::{self, Adjustment, Asset, DailyClient, Evidence, HistoricalDay},
    http::{self, Query, Transport},
};
use jiff::{Span, civil::Date};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::{OnlySessionProfile, OnlyTradingCalendar, OnlyTradingCalendarInput},
    enums::OnlyCurrencyType,
    identifiers::OnlyInstrumentId,
    instrument::OnlyInstrument,
    market::{OnlyBar, OnlyBarSemantic},
    time::{OnlyTimeZone, OnlyTimestamp, OnlyTradingDay},
    value::OnlyCurrency,
};
use onlyalpha_integration_contract::{
    Category, Descriptor, Error,
    authoring::{PluginProjection, Registration},
    source::*,
};
use serde_json::{Value, json, value::RawValue};
use std::sync::Arc;

const WORK: usize = 16 * 1024 * 1024;
const NORMALIZER: &str = "tushare.daily.native";

fn native_error(e: http::Error) -> SourceError {
    match e {
        http::Error::Configuration => SourceError::Invalid,
        http::Error::Deadline => SourceError::Timeout,
        http::Error::Calendar | http::Error::Empty => SourceError::Gap,
        http::Error::Conflict => SourceError::Conflict,
        http::Error::Shape | http::Error::Evidence => SourceError::Evidence,
        _ => SourceError::Unavailable,
    }
}
fn public_config(config: &RawValue, work: usize) -> Result<(), Error> {
    let mut value: Value = serde_json::from_str(config.get()).map_err(|_| Error::Configuration)?;
    let venue = value
        .as_object_mut()
        .ok_or(Error::Configuration)?
        .remove("venue");
    if venue.is_some_and(|v| !matches!(v.as_str(), Some("XSHG" | "XSHE"))) {
        return Err(Error::Configuration);
    }
    crate::validate_daily(
        &RawValue::from_string(value.to_string()).map_err(|_| Error::Configuration)?,
        work,
    )
}
/// 新运行描述与旧 wheel 的 authoring 有不同实现、配置及探测身份。
pub fn native_authoring(work: usize) -> Result<Registration, Error> {
    let mut doc: Value = serde_json::from_str(crate::DAILY_DESCRIPTOR).map_err(|_| Error::Type)?;
    doc["display_name"] = "Tushare 沪深股票历史日线".into();
    doc["description"] = "沪市或深市上市股票的封存日线。每个配置选择一个交易所。".into();
    let cfg = &mut doc["configuration_contract"];
    let fields = cfg["fields"].as_array_mut().ok_or(Error::Type)?;
    fields.retain(|f| f["field_id"] != "strict_validation");
    fields.push(json!({"advanced":false,"default":"XSHG","description":"该配置的历史证券交易所",
        "display_name":"交易所","enum_values":["XSHE","XSHG"],"exclusive_minimum":false,"field_id":"venue",
        "maximum":null,"minimum":null,"required":false,"secret":false,"value_kind":"ENUM"}));
    cfg.as_object_mut()
        .ok_or(Error::Type)?
        .remove("fingerprint");
    cfg["fingerprint"] = onlyalpha_metadata_json::fingerprint(&cfg.to_string(), work)
        .map_err(|_| Error::Type)?
        .into();
    let probe = &mut doc["probe_contract"];
    probe["probe_version"] = 2.into();
    probe["configured_instruments"] =
        json!({"field_id":"venue","instruments":{"XSHG":"600000.XSHG","XSHE":"000001.XSHE"}});
    probe["default_probe_instrument"] = "600000.XSHG".into();
    probe
        .as_object_mut()
        .ok_or(Error::Type)?
        .remove("fingerprint");
    probe["fingerprint"] = onlyalpha_metadata_json::fingerprint(&probe.to_string(), work)
        .map_err(|_| Error::Probe)?
        .into();
    doc["public_api_version"] = "1.2".into();
    doc["implementation_id"] = "tushare-native".into();
    doc["implementation_version"] = env!("CARGO_PKG_VERSION").into();
    let capabilities =
        serde_json::from_value(doc["capabilities"].clone()).map_err(|_| Error::Type)?;
    Registration::new(
        PluginProjection::new(
            Category::DataSource,
            "tushare-native",
            env!("CARGO_PKG_VERSION"),
            "1.2",
            capabilities,
        )?,
        Descriptor::from_json(&doc.to_string(), work)?,
        public_config,
    )
}
pub fn history_identity(
    descriptor: &Descriptor,
    config: &RawValue,
) -> Result<MarketIdentity, SourceError> {
    let doc: Value =
        serde_json::from_str(descriptor.document().get()).map_err(|_| SourceError::Evidence)?;
    if doc["type_id"] != "tushare.daily.market_data"
        || doc["provider_id"] != "tushare"
        || doc["implementation_id"] != "tushare-native"
    {
        return Err(SourceError::Unsupported);
    }
    let config: Value = serde_json::from_str(config.get()).map_err(|_| SourceError::Invalid)?;
    let venue = match config.get("venue") {
        None => "XSHG",
        Some(v) => v
            .as_str()
            .filter(|s| matches!(*s, "XSHG" | "XSHE"))
            .ok_or(SourceError::Invalid)?,
    };
    Ok(MarketIdentity {
        provider: "tushare".into(),
        venue: venue.into(),
        market: "CN_EQUITY".into(),
        environment: "CN".into(),
        source_id: format!("tushare.daily.{}", venue.to_ascii_lowercase()),
    })
}

/// 由原公开配置恢复日线语义，用于只读能力投影，无需凭据或网络。
pub fn day_semantic(config: &RawValue) -> Result<(Adjustment, OnlyBarSemantic), SourceError> {
    let params: Value = serde_json::from_str(config.get()).map_err(|_| SourceError::Invalid)?;
    let adjustment = match params["adjustment"].as_str().unwrap_or("none") {
        "none" => Adjustment::None,
        "qfq" => Adjustment::Qfq,
        "hfq" => Adjustment::Hfq,
        _ => return Err(SourceError::Invalid),
    };
    let semantic=OnlyBarSemantic::from_record(&json!({"schema_version":3,"formation":{"schema_version":1,"kind":"CALENDAR_PERIOD","unit":"DAY","count":1,"alignment":"SESSION_START"},
            "price_type":"LAST","adjustment_policy":match adjustment {Adjustment::None=>"RAW",Adjustment::Qfq=>"FORWARD",Adjustment::Hfq=>"BACKWARD"}}))
                .map_err(|_|SourceError::Invalid)?;
    Ok((adjustment, semantic))
}

pub struct DailyFactory {
    descriptor: Descriptor,
    implementation: String,
}
impl DailyFactory {
    pub fn installed() -> Result<Self, SourceError> {
        let registration = native_authoring(WORK).map_err(|_| SourceError::Unavailable)?;
        Ok(Self {
            descriptor: Descriptor::from_json(registration.descriptor().document().get(), WORK)
                .map_err(|_| SourceError::Unavailable)?,
            implementation: onlyalpha_metadata_json::fingerprint(
                &json!({"implementation":NORMALIZER,"protocol":1}).to_string(),
                WORK,
            )
            .map_err(|_| SourceError::Unavailable)?,
        })
    }
}
impl Factory for DailyFactory {
    fn descriptor(&self) -> &Descriptor {
        &self.descriptor
    }
    fn implementation_fingerprint(&self) -> &str {
        &self.implementation
    }
    fn validate_configuration(&self, config: &RawValue) -> Result<(), SourceError> {
        native_authoring(WORK)
            .and_then(|r| r.validate_public_configuration(config, WORK))
            .map_err(|_| SourceError::Invalid)
    }
    fn create(
        &self,
        _: &RawValue,
        _: &Trust,
        _: Arc<dyn Clock>,
    ) -> Result<Arc<dyn Resource>, SourceError> {
        Err(SourceError::Unavailable)
    }
    fn create_with_credentials(
        &self,
        config: &RawValue,
        trust: &Trust,
        clock: Arc<dyn Clock>,
        credentials: &[(&str, &str)],
    ) -> Result<Arc<dyn Resource>, SourceError> {
        self.validate_configuration(config)?;
        let [("token", secret)] = credentials else {
            return Err(SourceError::Unavailable);
        };
        let identity = history_identity(&self.descriptor, config)?;
        let params: Value = serde_json::from_str(config.get()).map_err(|_| SourceError::Invalid)?;
        let (adjustment, semantic) = day_semantic(config)?;
        let policy = match params["cache_policy"].as_str().unwrap_or("prefer_cache") {
            "cache_only" => HistoryInputPolicy::CacheOnly,
            "prefer_cache" => HistoryInputPolicy::PreferCache,
            "force_refresh" => HistoryInputPolicy::ForceRefresh,
            _ => return Err(SourceError::Invalid),
        };
        let transport = Arc::new(http::HttpTransport::new(secret, trust).map_err(native_error)?);
        Ok(Arc::new(DailyResource {
            identity,
            transport,
            clock,
            semantic,
            adjustment,
            policy,
        }))
    }
}

struct DailyResource {
    identity: MarketIdentity,
    transport: Arc<dyn Transport>,
    clock: Arc<dyn Clock>,
    semantic: OnlyBarSemantic,
    adjustment: Adjustment,
    policy: HistoryInputPolicy,
}

struct Period {
    start: Date,
    end: Date,
    calendar_start: Date,
    calendar_end: Date,
    profile: &'static str,
}
impl DailyResource {
    fn exchange(&self) -> &str {
        if self.identity.venue == "XSHG" {
            "SSE"
        } else {
            "SZSE"
        }
    }
    fn period(&self, r: &HistoricalDayRequest) -> Result<Period, SourceError> {
        if r.semantic != self.semantic
            || r.instrument.venue().value() != self.identity.venue
            || r.start >= r.end
            || (self.adjustment == Adjustment::Qfq) != r.anchor.is_some()
        {
            return Err(SourceError::Invalid);
        }
        let tz = OnlyTimeZone::new("Asia/Shanghai").map_err(|_| SourceError::Invalid)?;
        let start = tz
            .to_civil(r.start)
            .map_err(|_| SourceError::Invalid)?
            .date();
        let last_us = r
            .end
            .timestamp()
            .total_nanoseconds()
            .checked_sub(1000)
            .ok_or(SourceError::Invalid)?;
        let last = OnlyTimestamp::from_unix_nanos(last_us.into())
            .to_datetime_exact()
            .map_err(|_| SourceError::Invalid)?;
        let end = tz.to_civil(last).map_err(|_| SourceError::Invalid)?.date();
        let anchor = r.anchor.map_or(end, |day| day.value());
        let calendar_start = start.min(anchor);
        let calendar_end = end.max(anchor);
        let version = |date| {
            onlyalpha_market_cn_ashare::PolicyCompiler::version_for(
                OnlyTradingDay::new(date).map_err(|_| SourceError::Invalid)?,
            )
            .map_err(|_| SourceError::Unsupported)
        };
        let profile = version(calendar_start)?;
        if version(calendar_end)? != profile {
            return Err(SourceError::Unsupported);
        }
        if calendar_start
            .checked_add(Span::new().days(5000))
            .map_err(|_| SourceError::Invalid)?
            < calendar_end
        {
            return Err(SourceError::Invalid);
        }
        Ok(Period {
            start,
            end,
            calendar_start,
            calendar_end,
            profile,
        })
    }
    fn plan(&self, r: &HistoricalDayRequest) -> Result<Vec<Query>, SourceError> {
        let p = self.period(r)?;
        let mut queries = vec![
            daily::calendar_query(&self.identity.venue, p.calendar_start, p.calendar_end)
                .map_err(native_error)?,
            daily::securities_query(self.exchange(), Asset::Equity).map_err(native_error)?,
        ];
        queries.extend(
            daily::equity_queries(
                &r.instrument,
                self.adjustment,
                p.start,
                p.end,
                r.anchor.map(|d| d.value()),
            )
            .map_err(native_error)?,
        );
        Ok(queries)
    }
    fn metadata(
        &self,
        row: &std::collections::BTreeMap<String, Value>,
    ) -> Result<Value, SourceError> {
        let code = row
            .get("symbol")
            .and_then(Value::as_str)
            .ok_or(SourceError::Evidence)?;
        let id = format!("{code}.{}", self.identity.venue);
        if row.get("ts_code").and_then(Value::as_str)
            != Some(crate::mapping::symbol(&id).map_err(native_error)?.as_str())
        {
            return Err(SourceError::Evidence);
        }
        Ok(
            json!({"instrument_id":id,"display_symbol":code,"venue":self.identity.venue,"market":self.identity.market,
            "asset_class":"EQUITY","instrument_type":"EQUITY","status":"UNKNOWN","market_data_capabilities":["HISTORICAL_BARS"]}),
        )
    }
    fn prepared(
        &self,
        r: &HistoricalDayRequest,
        observations: Vec<HistoricalObservation>,
        budget: Budget,
    ) -> Result<HistoricalDayResult, SourceError> {
        let deadline = http::deadline(budget).map_err(native_error)?;
        let expected = self.plan(r)?;
        if observations.len() != expected.len()
            || observations
                .iter()
                .zip(&expected)
                .any(|(o, q)| o.query != q.record() || o.received_at < o.producer_started_at)
        {
            return Err(SourceError::Evidence);
        }
        // plan 固定为日历、证券、日线和可选复权因子。只有参与计算的价格/因子限制作价时刻。
        let daily_at = observations
            .get(2)
            .ok_or(SourceError::Evidence)?
            .producer_started_at;
        let factor_at = observations.get(3).map(|o| o.producer_started_at);
        let closed_through = factor_at.map_or(daily_at, |at| daily_at.min(at));
        let mut evidence = observations
            .into_iter()
            .zip(expected)
            .map(|(o, query)| Evidence {
                query,
                response: o.bytes,
            });
        let p = self.period(r)?;
        let policy = onlyalpha_market_cn_ashare::PolicyCompiler::new(p.profile)
            .map_err(|_| SourceError::Unsupported)?;
        let profile = OnlySessionProfile::from_record(&policy.record()["session"])
            .map_err(|_| SourceError::Evidence)?;
        let input = OnlyTradingCalendarInput {
            calendar_id: format!("CN_{}", self.identity.venue)
                .parse()
                .map_err(|_| SourceError::Invalid)?,
            venue_id: r.instrument.venue().clone(),
            timezone: OnlyTimeZone::new("Asia/Shanghai").map_err(|_| SourceError::Invalid)?,
            sessions: profile.sessions().clone(),
            holidays: vec![],
            weekend_days: vec![],
            session_profile_id: Some(profile.profile_id().clone()),
            special_schedules: vec![],
            calendar_version: 1.into(),
            effective_from: Some(p.calendar_start),
            effective_to: Some(
                p.calendar_end
                    .checked_add(Span::new().days(1))
                    .map_err(|_| SourceError::Invalid)?,
            ),
        };
        let calendar = daily::frozen_calendar(
            input,
            p.calendar_start,
            p.calendar_end,
            evidence.next().ok_or(SourceError::Evidence)?,
            deadline,
        )
        .map_err(native_error)?
        .calendar;
        if let Some(day) = r.anchor
            && !calendar
                .session_intervals_for_trading_day(day)
                .map_err(|_| SourceError::Evidence)?
                .iter()
                .map(|(_, close)| *close)
                .max()
                .is_some_and(|close| factor_at.is_some_and(|at| close <= at))
        {
            return Err(SourceError::Gap);
        }
        let securities = daily::frozen_securities(
            self.exchange(),
            Asset::Equity,
            evidence.next().ok_or(SourceError::Evidence)?,
            deadline,
        )
        .map_err(native_error)?;
        let symbol = crate::mapping::symbol(&r.instrument.to_string()).map_err(native_error)?;
        let row = securities
            .rows
            .iter()
            .find(|row| row.get("ts_code").and_then(Value::as_str) == Some(&symbol))
            .ok_or(SourceError::Gap)?;
        let first = daily::date(
            row.get("list_date")
                .and_then(Value::as_str)
                .ok_or(SourceError::Evidence)?,
        )
        .map_err(native_error)?;
        if first > p.start {
            return Err(SourceError::Gap);
        }
        let currency = OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat)
            .map_err(|_| SourceError::Evidence)?;
        let product = HistoricalDay {
            instrument: &r.instrument,
            currency: &currency,
            price_precision: 18,
            quantity_precision: 0,
            calendar: &calendar,
            start: r.start,
            end: r.end,
            adjustment: self.adjustment,
            asset: Asset::Equity,
            anchor: r.anchor.map(|d| d.value()),
        };
        let prices: Vec<_> = evidence.collect();
        let bar_query = prices.first().ok_or(SourceError::Evidence)?.query.record();
        let result = product
            .replay(prices, closed_through, budget)
            .map_err(native_error)?;
        let security = json!({"instrument_id":r.instrument.to_string(),"asset":"EQUITY","currency":"CNY",
            "price_precision":18,"quantity_precision":0,"volume_unit":"SHARE","turnover_unit":"CNY",
            "provider_volume_multiple":100,"provider_amount_multiple":1000,"session_profile":p.profile,
            "display":self.metadata(row)?});
        http::success(
            deadline,
            HistoricalDayResult {
                bars: result.bars,
                calendar,
                security,
                factor_basis: result.factor_basis,
                normalized_daily_fingerprint: result.normalized_daily_fingerprint,
                bar_query,
            },
        )
        .map_err(native_error)
    }
}
impl HistoricalDays for DailyResource {
    fn semantic(&self) -> &OnlyBarSemantic {
        &self.semantic
    }
    fn input_policy(&self) -> HistoryInputPolicy {
        self.policy
    }
    fn inputs(&self, r: &HistoricalDayRequest) -> Result<Vec<Value>, SourceError> {
        Ok(self.plan(r)?.iter().map(Query::record).collect())
    }
    fn fetch<'a>(&'a self, q: &'a Value, b: Budget) -> FutureResult<'a, Vec<u8>> {
        Box::pin(async move {
            let deadline = http::deadline(b).map_err(native_error)?;
            let query = Query::restore(q).map_err(native_error)?;
            let response = self
                .transport
                .post(&query, deadline)
                .await
                .map_err(native_error)?;
            http::success(deadline, response).map_err(native_error)
        })
    }
    fn replay<'a>(
        &'a self,
        r: &'a HistoricalDayRequest,
        observations: Vec<HistoricalObservation>,
        b: Budget,
    ) -> FutureResult<'a, HistoricalDayResult> {
        Box::pin(async move { self.prepared(r, observations, b) })
    }
    fn instruments<'a>(&'a self, b: Budget) -> FutureResult<'a, Vec<Value>> {
        Box::pin(async move {
            let deadline = http::deadline(b).map_err(native_error)?;
            let result = DailyClient::new(Arc::clone(&self.transport))
                .securities(self.exchange(), Asset::Equity, b)
                .await
                .map_err(native_error)?;
            let records = result
                .rows
                .iter()
                .map(|row| self.metadata(row))
                .collect::<Result<Vec<_>, _>>()?;
            http::success(deadline, records).map_err(native_error)
        })
    }
}
impl Resource for DailyResource {
    fn identity(&self) -> &MarketIdentity {
        &self.identity
    }
    fn normalizer_id(&self) -> &str {
        NORMALIZER
    }
    fn calendar(&self) -> Option<&OnlyTradingCalendar> {
        None
    }
    fn historical_days(&self) -> Option<&dyn HistoricalDays> {
        Some(self)
    }
    fn capabilities(&self) -> &[OnlyConstructionCapability] {
        &[]
    }
    fn resume_max_bars(&self) -> u16 {
        0
    }
    fn instruments<'a>(
        &'a self,
        _: &'a [String],
        _: Budget,
    ) -> FutureResult<'a, Vec<OnlyInstrument>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn quotes<'a>(&'a self, _: &'a [String], _: Budget) -> FutureResult<'a, Vec<Quote>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn history<'a>(
        &'a self,
        _: &'a HistoryRequest,
        _: Budget,
        _: &'a mut dyn Recorder,
    ) -> FutureResult<'a, Vec<OnlyBar>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn stream<'a>(
        &'a self,
        _: HistoryRequest,
        _: Option<i64>,
        _: Budget,
    ) -> FutureResult<'a, Box<dyn Stream>> {
        Box::pin(async { Err(SourceError::Unsupported) })
    }
    fn probe<'a>(&'a self, symbol: &'a str, b: Budget) -> FutureResult<'a, Value> {
        Box::pin(async move {
            let deadline = http::deadline(b).map_err(native_error)?;
            let instrument: OnlyInstrumentId = symbol.parse().map_err(|_| SourceError::Invalid)?;
            if instrument.venue().value() != self.identity.venue {
                return Err(SourceError::Invalid);
            }
            let start_ns = self.clock.now_ns()?;
            let today = OnlyTimeZone::new("Asia/Shanghai")
                .map_err(|_| SourceError::Invalid)?
                .to_civil(
                    OnlyTimestamp::from_unix_nanos(start_ns.into())
                        .to_datetime()
                        .map_err(|_| SourceError::Invalid)?,
                )
                .map_err(|_| SourceError::Invalid)?
                .date();
            let last = today
                .checked_sub(Span::new().days(1))
                .map_err(|_| SourceError::Invalid)?;
            let first = last
                .checked_sub(Span::new().days(14))
                .map_err(|_| SourceError::Invalid)?;
            let query = daily::equity_queries(&instrument, Adjustment::None, first, last, None)
                .map_err(native_error)?
                .remove(0);
            let bytes = self.transport.post(&query, deadline).await;
            let end_ns = self.clock.now_ns()?;
            let table = bytes.and_then(|v| http::Table::decode(&v));
            let expected = crate::mapping::symbol(symbol).map_err(native_error)?;
            let history = table
                .as_ref()
                .is_ok_and(|t| daily::probe_bars(t, &expected, first, last, deadline).is_ok());
            let checks=[("AUTHENTICATION",table.is_ok()),("CONNECTIVITY",table.is_ok()||matches!(table,Err(http::Error::Permission))),("HISTORICAL_DATA",history)]
                .map(|(name,ok)|json!({"check":name,"started_at_ns":start_ns,"completed_at_ns":end_ns,"status":if ok{"READY"}else{"FAILED"},
                    "detail":if ok{None}else{Some(table.as_ref().err().map_or("TUSHARE_EMPTY_RESPONSE",|e|e.code()))}}));
            http::success(
                deadline,
                json!({"started_at_ns":start_ns,"completed_at_ns":end_ns,"checks":checks}),
            )
            .map_err(native_error)
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicI64, Ordering};

    struct ConsumerClock(AtomicI64);
    impl Clock for ConsumerClock {
        fn now_ns(&self) -> Result<i64, SourceError> {
            Ok(self.0.load(Ordering::Relaxed))
        }
    }
    #[test]
    fn closed_bars_and_outside_anchor_use_original_producer_time() {
        let config = RawValue::from_string(r#"{"adjustment":"qfq"}"#.into()).unwrap();
        let descriptor = native_authoring(WORK).unwrap();
        let (adjustment, semantic) = day_semantic(&config).unwrap();
        let clock = Arc::new(ConsumerClock(AtomicI64::new(0)));
        let source = DailyResource {
            identity: history_identity(descriptor.descriptor(), &config).unwrap(),
            transport: Arc::new(http::Offline),
            clock: clock.clone(),
            semantic: semantic.clone(),
            adjustment,
            policy: HistoryInputPolicy::CacheOnly,
        };
        let mut request = HistoricalDayRequest {
            instrument: "600000.XSHG".parse().unwrap(),
            semantic,
            start: "2025-01-03T00:00:00Z".parse().unwrap(),
            end: "2025-01-06T00:00:00Z".parse().unwrap(),
            anchor: Some(OnlyTradingDay::new("2025-01-03".parse().unwrap()).unwrap()),
        };
        let before = "2025-01-06T06:59:59Z".parse().unwrap();
        let close = "2025-01-06T07:00:00Z".parse().unwrap();
        let after = "2025-01-06T07:00:01Z".parse().unwrap();
        let replay = |r: &HistoricalDayRequest, daily_start, factor_start, received| {
            let rows = [
                json!([
                    ["SSE", "20250103", 1, null],
                    ["SSE", "20250104", 0, null],
                    ["SSE", "20250105", 0, null],
                    ["SSE", "20250106", 1, null]
                ]),
                json!([[
                    "600000.SH",
                    "600000",
                    "浦发银行",
                    "主板",
                    "SSE",
                    "19991110",
                    null
                ]]),
                json!([
                    ["600000.SH", "20250103", 10, 11, 9, 10, 1, 2],
                    ["600000.SH", "20250106", 12, 13, 11, 12, 1, 2]
                ]),
                json!([["600000.SH", "20250103", 2], ["600000.SH", "20250106", 4]]),
            ];
            let obs = source
                .plan(r)
                .unwrap()
                .into_iter()
                .zip(rows)
                .zip([daily_start, daily_start, daily_start, factor_start])
                .map(|((q, rows), producer_started_at)| {
                    let fields: Vec<_> = q.fields.split(',').collect();
                    let bytes = serde_json::to_vec(
                        &json!({"code":0,"data":{"fields":fields,"items":rows}}),
                    )
                    .unwrap();
                    HistoricalObservation {
                        query: q.record(),
                        bytes,
                        producer_started_at,
                        received_at: received,
                    }
                })
                .collect();
            source.prepared(r, obs, Budget::from_millis(5000).unwrap())
        };
        // 原响应的区间外日线完整保留；消费时钟前移或后移只影响该资源的探测。
        for consume_time in [i64::MAX, 0] {
            clock.0.store(consume_time, Ordering::Relaxed);
            assert_eq!(
                replay(&request, before, before, after).unwrap().bars.len(),
                1
            );
        }
        request.anchor = Some(OnlyTradingDay::new("2025-01-06".parse().unwrap()).unwrap());
        assert!(matches!(
            replay(&request, before, before, after),
            Err(SourceError::Gap)
        ));
        assert!(replay(&request, before, close, after).is_ok());
        request.end = "2025-01-06T07:30:00Z".parse().unwrap();
        for consume_time in [0, i64::MAX] {
            clock.0.store(consume_time, Ordering::Relaxed);
            assert!(matches!(
                replay(&request, before, close, after),
                Err(SourceError::Gap)
            ));
            assert!(matches!(
                replay(&request, close, before, after),
                Err(SourceError::Gap)
            ));
            assert_eq!(replay(&request, close, close, after).unwrap().bars.len(), 2);
        }
        assert!(matches!(
            replay(&request, close, close, before),
            Err(SourceError::Evidence)
        ));
    }
}
