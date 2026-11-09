//! Calendar DAY acquisition and exact dynamic adjustment. No Product storage or
//! grant authority. Raw responses must be durably recorded by the caller before
//! publishing the returned canonical Bars.
use crate::{
    http::{self, Error, Query, Result, Table, Transport},
    mapping,
};
use bigdecimal::{BigDecimal, num_bigint::BigInt};
use jiff::{Span, civil::Date};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::{OnlyTradingCalendar, OnlyTradingCalendarInput},
    identifiers::OnlyInstrumentId,
    instrument::OnlyInstrument,
    market::OnlyBar,
    time::{OnlyTradingDay, OnlyUtcDateTime},
    value::{OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity},
};
use onlyalpha_integration_contract::source::Budget;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, str::FromStr, sync::Arc, time::Instant};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Adjustment {
    None,
    Qfq,
    Hfq,
}
impl Adjustment {
    fn canonical(self) -> &'static str {
        match self {
            Self::None => "RAW",
            Self::Qfq => "FORWARD",
            Self::Hfq => "BACKWARD",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Asset {
    Equity,
    Etf,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CachePolicy {
    PreferCache,
    ForceRefresh,
    CacheOnly,
}
/// Explicit immutable request. End is exclusive; qfq anchor is the inclusive
/// provider end_date, independent of missing final-day Bars (e.g. suspension).
#[derive(Clone)]
pub struct DailyRequest {
    pub source_id: String,
    pub instrument: OnlyInstrument,
    pub calendar: OnlyTradingCalendar,
    pub start: OnlyUtcDateTime,
    pub end: OnlyUtcDateTime,
    pub adjustment: Adjustment,
    pub asset: Asset,
}
/// 已确定单位的行情输入。历史行情无须构造交易 tick、交易状态或可下单数量。
pub struct HistoricalDay<'a> {
    pub instrument: &'a OnlyInstrumentId,
    pub currency: &'a OnlyCurrency,
    pub price_precision: u8,
    pub quantity_precision: u8,
    pub calendar: &'a OnlyTradingCalendar,
    pub start: OnlyUtcDateTime,
    pub end: OnlyUtcDateTime,
    pub adjustment: Adjustment,
    pub asset: Asset,
    /// 显式前复权基准必须是冻结日历内的交易日。旧 SDK 接口按原 end_date 规则取值。
    pub anchor: Option<Date>,
}
impl HistoricalDay<'_> {
    pub fn queries(&self) -> Result<Vec<Query>> {
        Ok(Plan::new(self)?.queries)
    }
    /// 精确重放关联到同一请求的原始响应；不构造 Transport 或解密凭据。
    pub fn replay(
        &self,
        evidence: Vec<Evidence>,
        now: OnlyUtcDateTime,
        budget: Budget,
    ) -> Result<DailyResult> {
        let deadline = http::deadline(budget)?;
        let plan = Plan::new(self)?;
        if (self.adjustment == Adjustment::Qfq) != self.anchor.is_some() {
            return Err(Error::Configuration);
        }
        normalize(self, &plan, evidence, None, now, deadline)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Evidence {
    pub query: Query,
    pub response: Vec<u8>,
}
#[derive(Clone)]
pub struct DailyResult {
    pub bars: Vec<OnlyBar>,
    pub evidence: Vec<Evidence>,
    pub cache_key: String,
    pub identical_duplicates: usize,
    pub cache_hit: bool,
    /// 规范化因子表，独立保留实际 anchor 数值与原始响应。
    pub factor_basis: Option<Value>,
    pub normalized_daily_fingerprint: String,
}
/// Selection is separate from immutable provider evidence. A fund_basic
/// response identifies listed funds, including non-ETF products; no completeness
/// or ETF classification is inferred from its market=E flag.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SecurityScope {
    ListedEquities,
    ListedFundCandidates,
}
#[derive(Clone)]
pub struct SecuritiesResult {
    pub evidence: Evidence,
    pub rows: Vec<BTreeMap<String, Value>>,
    pub exchange: String,
    pub scope: SecurityScope,
}
#[derive(Clone)]
pub struct CalendarResult {
    pub calendar: OnlyTradingCalendar,
    pub evidence: Evidence,
}
/// Cache owns reusable provider observations only, never official trading facts.
/// Implementations must atomically store a complete bundle and retain exact key.
/// Every hit is replayed through the same validation; errors never trigger an
/// implicit network fallback in CACHE_ONLY.
pub trait Cache: Send + Sync {
    fn read(&self, key: &str) -> Result<Option<Vec<Evidence>>>;
    fn write(&self, key: &str, evidence: &[Evidence]) -> Result<()>;
}
pub struct DailyClient {
    transport: Arc<dyn Transport>,
}
impl DailyClient {
    pub fn new(transport: Arc<dyn Transport>) -> Self {
        Self { transport }
    }
    /// Freeze every provider date in an explicit finite interval. The caller's
    /// versioned session template owns open/close times; trade_cal owns open days.
    /// No weekday guess or current machine calendar is used as provider evidence.
    pub async fn calendar(
        &self,
        template: &OnlyTradingCalendar,
        start: Date,
        end: Date,
        budget: Budget,
    ) -> Result<CalendarResult> {
        let deadline = http::deadline(budget)?;
        if start > end
            || template.timezone().name() != "Asia/Shanghai"
            || start
                .checked_add(Span::new().days(5000))
                .map_err(|_| Error::Calendar)?
                < end
        {
            return Err(Error::Configuration);
        }
        let query = calendar_query(template.venue_id().value(), start, end)?;
        let response = self.post(&query, deadline).await?;
        frozen_calendar(
            template.input(),
            start,
            end,
            Evidence { query, response },
            deadline,
        )
    }
    pub async fn load(
        &self,
        request: &DailyRequest,
        policy: CachePolicy,
        cache: &dyn Cache,
        budget: Budget,
        now: OnlyUtcDateTime,
    ) -> Result<DailyResult> {
        let deadline = http::deadline(budget)?;
        let data = request.market_input()?;
        let plan = Plan::new(&data)?;
        let key = request.cache_key()?;
        if policy != CachePolicy::ForceRefresh {
            if let Some(evidence) = cache.read(&key)? {
                ensure_time(deadline)?;
                let result = normalize(&data, &plan, evidence, Some((key, true)), now, deadline)?;
                return http::success(deadline, result);
            }
            if policy == CachePolicy::CacheOnly {
                return Err(Error::CacheMiss);
            }
        }
        ensure_time(deadline)?;
        let mut evidence = Vec::new();
        for query in &plan.queries {
            let response = self.post(query, deadline).await?;
            ensure_time(deadline)?;
            evidence.push(Evidence {
                query: query.clone(),
                response,
            });
        }
        let result = normalize(&data, &plan, evidence, Some((key, false)), now, deadline)?;
        ensure_time(deadline)?;
        cache.write(&result.cache_key, &result.evidence)?;
        ensure_time(deadline)?;
        http::success(deadline, result)
    }
    async fn post(&self, query: &Query, deadline: Instant) -> Result<Vec<u8>> {
        ensure_time(deadline)?;
        let response = tokio::time::timeout_at(
            tokio::time::Instant::from_std(deadline),
            self.transport.post(query, deadline),
        )
        .await
        .map_err(|_| Error::Deadline)??;
        http::success(deadline, response)
    }
    /// Provider security metadata is not a historical market-rule Reference.
    pub async fn securities(
        &self,
        exchange: &str,
        asset: Asset,
        budget: Budget,
    ) -> Result<SecuritiesResult> {
        let deadline = http::deadline(budget)?;
        let query = securities_query(exchange, asset)?;
        let response = self.post(&query, deadline).await?;
        frozen_securities(exchange, asset, Evidence { query, response }, deadline)
    }
}

pub(crate) fn securities_query(exchange: &str, asset: Asset) -> Result<Query> {
    if !matches!(exchange, "SSE" | "SZSE" | "BSE") {
        return Err(Error::Configuration);
    }
    let (api, params, fields) = match asset {
        Asset::Equity => (
            "stock_basic",
            BTreeMap::from([
                ("exchange".into(), exchange.into()),
                ("list_status".into(), "L".into()),
            ]),
            "ts_code,symbol,name,market,exchange,list_date,delist_date",
        ),
        Asset::Etf => (
            "fund_basic",
            BTreeMap::from([("market".into(), "E".into())]),
            "ts_code,name,market,list_date,delist_date",
        ),
    };
    Query::new(api, params, fields)
}

pub(crate) fn frozen_securities(
    exchange: &str,
    asset: Asset,
    evidence: Evidence,
    deadline: Instant,
) -> Result<SecuritiesResult> {
    if evidence.query != securities_query(exchange, asset)? {
        return Err(Error::Evidence);
    }
    let table = Table::decode(&evidence.response)?;
    table.require(&["ts_code", "name", "market", "list_date", "delist_date"])?;
    let mut by_symbol = BTreeMap::new();
    let expected_suffix = match exchange {
        "SSE" => "SH",
        "SZSE" => "SZ",
        _ => "BJ",
    };
    for row in &table.rows {
        ensure_time(deadline)?;
        let code = text(row, "ts_code")?;
        let (n, suffix) = code.split_once('.').ok_or(Error::Shape)?;
        let venue = match suffix {
            "SH" => "XSHG",
            "SZ" => "XSHE",
            "BJ" => "XBSE",
            _ => return Err(Error::Shape),
        };
        mapping::symbol(&format!("{n}.{venue}"))?;
        if asset == Asset::Equity
            && (text(row, "exchange")? != exchange
                || suffix
                    != match exchange {
                        "SSE" => "SH",
                        "SZSE" => "SZ",
                        _ => "BJ",
                    })
        {
            return Err(Error::Shape);
        }
        text(row, "name")?;
        let market = text(row, "market")?;
        if asset == Asset::Etf && market != "E" {
            return Err(Error::Shape);
        }
        date(text(row, "list_date")?)?;
        if let Some(Value::String(d)) = row.get("delist_date")
            && !d.is_empty()
        {
            date(d)?;
        }
        if suffix != expected_suffix {
            continue;
        }
        if let Some(previous) = by_symbol.insert(code, row)
            && previous != row
        {
            return Err(Error::Conflict);
        }
    }
    let rows = by_symbol.into_values().cloned().collect();
    http::success(
        deadline,
        SecuritiesResult {
            evidence,
            rows,
            exchange: exchange.into(),
            scope: match asset {
                Asset::Equity => SecurityScope::ListedEquities,
                Asset::Etf => SecurityScope::ListedFundCandidates,
            },
        },
    )
}

pub(crate) fn calendar_query(venue: &str, start: Date, end: Date) -> Result<Query> {
    let exchange = match venue {
        "XSHG" => "SSE",
        "XSHE" => "SZSE",
        "XBSE" => "SSE",
        _ => return Err(Error::Calendar),
    };
    Query::new(
        "trade_cal",
        BTreeMap::from([
            ("exchange".into(), exchange.into()),
            ("start_date".into(), format_date(start)),
            ("end_date".into(), format_date(end)),
        ]),
        "exchange,cal_date,is_open,pretrade_date",
    )
}
pub(crate) fn frozen_calendar(
    mut input: OnlyTradingCalendarInput,
    start: Date,
    end: Date,
    evidence: Evidence,
    deadline: Instant,
) -> Result<CalendarResult> {
    let query = calendar_query(input.venue_id.value(), start, end)?;
    if query != evidence.query
        || start > end
        || start
            .checked_add(Span::new().days(5000))
            .map_err(|_| Error::Calendar)?
            < end
    {
        return Err(Error::Evidence);
    }
    let response = &evidence.response;
    let table = Table::decode(response)?;
    table.require(&["exchange", "cal_date", "is_open"])?;
    let mut days = BTreeMap::new();
    for row in &table.rows {
        ensure_time(deadline)?;
        if text(row, "exchange")? != query.parameters.get("exchange").ok_or(Error::Calendar)? {
            return Err(Error::Calendar);
        }
        let day = date(text(row, "cal_date")?)?;
        if day < start || day > end {
            return Err(Error::Calendar);
        }
        let open = match row.get("is_open") {
            Some(Value::String(v)) if v == "1" => true,
            Some(Value::String(v)) if v == "0" => false,
            Some(Value::Number(n)) if n.as_i64() == Some(1) => true,
            Some(Value::Number(n)) if n.as_i64() == Some(0) => false,
            _ => return Err(Error::Calendar),
        };
        if let Some(previous) = days.insert(day, open)
            && previous != open
        {
            return Err(Error::Conflict);
        }
    }
    let mut holidays = Vec::new();
    let mut day = start;
    while day <= end {
        ensure_time(deadline)?;
        let open = *days.get(&day).ok_or(Error::Calendar)?;
        if !open {
            holidays.push(day)
        }
        day = day
            .checked_add(Span::new().days(1))
            .map_err(|_| Error::Calendar)?;
    }

    input.holidays = holidays;
    input.weekend_days.clear();
    input.special_schedules.retain(|schedule| {
        schedule.trading_day().value() >= start && schedule.trading_day().value() <= end
    });
    for schedule in &input.special_schedules {
        ensure_time(deadline)?;
        if days.get(&schedule.trading_day().value()) != Some(&!schedule.is_closed()) {
            return Err(Error::Calendar);
        }
    }
    input.effective_from = Some(start);
    input.effective_to = Some(day);
    let calendar = OnlyTradingCalendar::new(input).map_err(|_| Error::Calendar)?;
    http::success(deadline, CalendarResult { calendar, evidence })
}

fn ensure_time(deadline: Instant) -> Result<()> {
    http::success(deadline, ())
}
impl DailyRequest {
    fn market_input(&self) -> Result<HistoricalDay<'_>> {
        let spec = self.instrument.specification();
        if self.source_id.is_empty()
            || self.source_id.len() > 128
            || spec.trading_calendar_id().as_ref() != Some(self.calendar.calendar_id())
            || !matches!(
                (self.asset, spec.instrument_type().as_str()),
                (Asset::Equity, "EQUITY") | (Asset::Etf, "ETF")
            )
        {
            return Err(Error::Configuration);
        }
        Ok(HistoricalDay {
            instrument: spec.instrument_id(),
            currency: spec.quote_currency(),
            price_precision: *spec.price_precision(),
            quantity_precision: *spec.quantity_precision(),
            calendar: &self.calendar,
            start: self.start,
            end: self.end,
            adjustment: self.adjustment,
            asset: self.asset,
            anchor: None,
        })
    }
    pub fn cache_key(&self) -> Result<String> {
        let plan = Plan::new(&self.market_input()?)?;
        let record = json!({"schema_version":1,"time_semantics_version":2,"source_id":self.source_id,"instrument":self.instrument.to_record(),"calendar":self.calendar.to_record(),"start":self.start.to_string(),"end":self.end.to_string(),"adjustment":self.adjustment.canonical(),"qfq_anchor":if self.adjustment==Adjustment::Qfq{Some(format_date(plan.end))}else{None},"asset":if self.asset==Asset::Equity{"E"}else{"FD"}});
        let canonical =
            onlyalpha_metadata_json::canonical_json(&record.to_string(), http::MAX_RESPONSE)
                .map_err(|_| Error::Shape)?;
        Ok(Sha256::digest(canonical.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect())
    }
}
struct Plan {
    start: Date,
    end: Date,
    factor_start: Date,
    factor_end: Date,
    queries: Vec<Query>,
}
impl Plan {
    fn new(request: &HistoricalDay<'_>) -> Result<Self> {
        if request.start >= request.end
            || request.calendar.timezone().name() != "Asia/Shanghai"
            || request.instrument.venue() != request.calendar.venue_id()
            || request.currency.code() != "CNY"
            || request.anchor.is_some() && request.adjustment != Adjustment::Qfq
        {
            return Err(Error::Configuration);
        }
        if request.asset == Asset::Etf && request.adjustment != Adjustment::None {
            return Err(Error::Configuration);
        }
        let start = request
            .calendar
            .timezone()
            .to_civil(request.start)
            .map_err(|_| Error::Calendar)?
            .date();
        let end_ns = request
            .end
            .timestamp()
            .total_nanoseconds()
            .checked_sub(1000)
            .ok_or(Error::Calendar)?;
        let end = onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(end_ns.into())
            .to_datetime_exact()
            .map_err(|_| Error::Calendar)?;
        let end = request
            .calendar
            .timezone()
            .to_civil(end)
            .map_err(|_| Error::Calendar)?
            .date();
        if start > end
            || start
                .checked_add(Span::new().days(5000))
                .map_err(|_| Error::Calendar)?
                < end
        {
            return Err(Error::Configuration);
        }
        day_plan(
            request.instrument,
            request.asset,
            request.adjustment,
            start,
            end,
            request.anchor,
        )
    }
}

fn day_plan(
    instrument: &OnlyInstrumentId,
    asset: Asset,
    adjustment: Adjustment,
    start: Date,
    end: Date,
    explicit_anchor: Option<Date>,
) -> Result<Plan> {
    let code = mapping::symbol(&instrument.to_string())?;
    let parameters = BTreeMap::from([
        ("ts_code".into(), code),
        ("start_date".into(), format_date(start)),
        ("end_date".into(), format_date(end)),
    ]);
    let api = match asset {
        Asset::Equity => "daily",
        Asset::Etf => "fund_daily",
    };
    let mut queries = vec![Query::new(
        api,
        parameters.clone(),
        "ts_code,trade_date,open,high,low,close,vol,amount",
    )?];
    let anchor = explicit_anchor.unwrap_or(end);
    let factor_start = start.min(anchor);
    let factor_end = end.max(anchor);
    if factor_start
        .checked_add(Span::new().days(5000))
        .map_err(|_| Error::Calendar)?
        < factor_end
    {
        return Err(Error::Configuration);
    }
    if adjustment != Adjustment::None {
        let mut parameters = parameters;
        parameters.insert("start_date".into(), format_date(factor_start));
        parameters.insert("end_date".into(), format_date(factor_end));
        queries.push(Query::new(
            "adj_factor",
            parameters,
            "ts_code,trade_date,adj_factor",
        )?)
    }
    Ok(Plan {
        start,
        end,
        queries,
        factor_start,
        factor_end,
    })
}

pub(crate) fn equity_queries(
    instrument: &OnlyInstrumentId,
    adjustment: Adjustment,
    start: Date,
    end: Date,
    anchor: Option<Date>,
) -> Result<Vec<Query>> {
    Ok(day_plan(instrument, Asset::Equity, adjustment, start, end, anchor)?.queries)
}
fn text<'a>(row: &'a BTreeMap<String, Value>, field: &str) -> Result<&'a str> {
    row.get(field)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= 128)
        .ok_or(Error::Shape)
}
pub fn date(raw: &str) -> Result<Date> {
    if raw.len() != 8 || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return Err(Error::Shape);
    }
    let year = raw[0..4].parse::<i16>().map_err(|_| Error::Shape)?;
    if year < 1 {
        return Err(Error::Shape);
    }
    Date::new(
        year,
        raw[4..6].parse().map_err(|_| Error::Shape)?,
        raw[6..8].parse().map_err(|_| Error::Shape)?,
    )
    .map_err(|_| Error::Shape)
}
fn format_date(day: Date) -> String {
    format!("{:04}{:02}{:02}", day.year(), day.month(), day.day())
}
fn decimal(value: &Value) -> Result<BigDecimal> {
    let raw = match value {
        Value::String(v) => v.clone(),
        Value::Number(v) => v.to_string(),
        _ => return Err(Error::Shape),
    };
    if raw.len() > 128 {
        return Err(Error::TooLarge);
    }
    let number = BigDecimal::from_str(&raw).map_err(|_| Error::Shape)?;
    let (n, scale) = number.as_bigint_and_exponent();
    if scale.unsigned_abs() > 128 || n.to_string().len() > 128 {
        return Err(Error::TooLarge);
    }
    Ok(number)
}
/// Exact rational rounding to cents with ties to even. Never use f64 or a
/// precision-limited intermediate divide before final provider price rounding.
pub fn adjusted_price(price: &str, factor: &str, anchor: &str) -> Result<String> {
    let numerator =
        decimal(&Value::String(price.into()))? * decimal(&Value::String(factor.into()))?;
    let denominator = decimal(&Value::String(anchor.into()))?;
    if numerator <= 0 || denominator <= 0 {
        return Err(Error::Shape);
    }
    let (mut n, ns) = numerator.as_bigint_and_exponent();
    let (mut d, ds) = denominator.as_bigint_and_exponent();
    let shift = ds - ns + 2;
    if shift >= 0 {
        n *= BigInt::from(10).pow(shift as u32)
    } else {
        d *= BigInt::from(10).pow((-shift) as u32)
    }
    let mut quotient = &n / &d;
    let remainder = &n % &d;
    let twice = &remainder * BigInt::from(2);
    if twice > d || (twice == d && &quotient % 2 != BigInt::from(0)) {
        quotient += 1
    }
    Ok(BigDecimal::new(quotient, 2).to_string())
}
fn prices(row: &BTreeMap<String, Value>) -> Result<Vec<BigDecimal>> {
    let raw_prices = ["open", "high", "low", "close"]
        .map(|f| decimal(row.get(f).unwrap_or(&Value::Null)))
        .into_iter()
        .collect::<Result<Vec<_>>>()?;
    if raw_prices.iter().any(|p| p <= &BigDecimal::from(0))
        || raw_prices[1] < raw_prices[0]
        || raw_prices[1] < raw_prices[3]
        || raw_prices[2] > raw_prices[0]
        || raw_prices[2] > raw_prices[3]
        || raw_prices[1] < raw_prices[2]
    {
        return Err(Error::Shape);
    }
    Ok(raw_prices)
}

pub(crate) fn probe_bars(
    t: &Table,
    code: &str,
    start: Date,
    end: Date,
    deadline: Instant,
) -> Result<()> {
    t.require(&[
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
    ])?;
    let (rows, _) = by_day(t, code, start, end, deadline)?;
    if rows.is_empty() {
        return Err(Error::Empty);
    }
    for row in rows.values() {
        prices(row)?;
        let volume = decimal(row.get("vol").ok_or(Error::Shape)?)?;
        let amount = row
            .get("amount")
            .filter(|v| !v.is_null())
            .map(decimal)
            .transpose()?;
        if volume < 0 || amount.is_some_and(|n| n < 0) {
            return Err(Error::Shape);
        }
    }
    Ok(())
}

fn normalize(
    request: &HistoricalDay<'_>,
    plan: &Plan,
    evidence: Vec<Evidence>,
    sdk_cache: Option<(String, bool)>,
    now: OnlyUtcDateTime,
    deadline: Instant,
) -> Result<DailyResult> {
    ensure_time(deadline)?;
    if evidence.len() != plan.queries.len()
        || evidence
            .iter()
            .zip(&plan.queries)
            .any(|(e, q)| &e.query != q)
    {
        return Err(Error::Evidence);
    }
    let code = mapping::symbol(&request.instrument.to_string())?;
    let table = Table::decode(&evidence[0].response)?;
    table.require(&[
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "vol",
    ])?;
    let (rows, duplicates) = by_day(&table, &code, plan.start, plan.end, deadline)?;
    let factors = if request.adjustment != Adjustment::None {
        let table = Table::decode(&evidence[1].response)?;
        table.require(&["ts_code", "trade_date", "adj_factor"])?;
        let (rows, _) = by_day(&table, &code, plan.factor_start, plan.factor_end, deadline)?;
        let mut out = BTreeMap::new();
        for (day, row) in rows {
            ensure_time(deadline)?;
            let trading_day = OnlyTradingDay::new(day).map_err(|_| Error::Calendar)?;
            if !request.calendar.is_effective_on(trading_day)
                || !request.calendar.is_trading_day(trading_day)
            {
                return Err(Error::Calendar);
            }
            let n = decimal(row.get("adj_factor").ok_or(Error::Shape)?)?;
            if n <= 0 {
                return Err(Error::Shape);
            }
            out.insert(day, n);
        }
        out
    } else {
        BTreeMap::new()
    };
    let anchor = if request.adjustment == Adjustment::Qfq {
        let mut anchor_day = request.anchor.unwrap_or(plan.end);
        if request.anchor.is_some()
            && !request
                .calendar
                .is_trading_day(OnlyTradingDay::new(anchor_day).map_err(|_| Error::Calendar)?)
        {
            return Err(Error::Calendar);
        }
        loop {
            ensure_time(deadline)?;
            let trading_day = OnlyTradingDay::new(anchor_day).map_err(|_| Error::Calendar)?;
            if !request.calendar.is_effective_on(trading_day) {
                return Err(Error::Calendar);
            }
            if request.calendar.is_trading_day(trading_day) {
                break;
            }
            if anchor_day <= plan.start {
                return Err(Error::Empty);
            }
            anchor_day = anchor_day
                .checked_sub(Span::new().days(1))
                .map_err(|_| Error::Calendar)?;
        }
        factors.get(&anchor_day).cloned().ok_or(Error::Evidence)?
    } else {
        BigDecimal::from(1)
    };
    let mut used_factors = BTreeMap::new();
    if let Some(day) = request.anchor {
        used_factors.insert(day, anchor.clone());
    }
    let mut daily_digest = Sha256::new();
    let mut bars = Vec::new();
    for (day, row) in rows {
        ensure_time(deadline)?;
        let day_value = OnlyTradingDay::new(day).map_err(|_| Error::Calendar)?;
        if !request.calendar.is_effective_on(day_value) {
            return Err(Error::Calendar);
        }
        let intervals = request
            .calendar
            .session_intervals_for_trading_day(day_value)
            .map_err(|_| Error::Calendar)?;
        let start = intervals.iter().map(|v| v.0).min().ok_or(Error::Calendar)?;
        let end = intervals.iter().map(|v| v.1).max().ok_or(Error::Calendar)?;
        let raw_prices = prices(&row)?;
        let vol = decimal(row.get("vol").ok_or(Error::Shape)?)?;
        if vol < 0 {
            return Err(Error::Shape);
        }
        let volume = OnlyQuantity::new(
            (&vol * BigDecimal::from(100))
                .normalized()
                .to_string()
                .parse()
                .map_err(|_| Error::Shape)?,
            request.quantity_precision,
        )
        .map_err(|_| Error::Shape)?;
        let turnover = match row.get("amount") {
            None | Some(Value::Null) => None,
            Some(v) => {
                let amount = decimal(v)?;
                if amount < 0 {
                    return Err(Error::Shape);
                }
                Some(
                    OnlyMoney::new(
                        (amount * BigDecimal::from(1000))
                            .normalized()
                            .to_string()
                            .parse()
                            .map_err(|_| Error::Shape)?,
                        request.currency.clone(),
                    )
                    .map_err(|_| Error::Shape)?
                    .to_record(),
                )
            }
        };
        // 民用日期查询可返回 UTC 窗口两端外的整个交易日；原响应保留，域值仍逐行验证。
        if sdk_cache.is_none() && (end <= request.start || start >= request.end) {
            continue;
        }
        if start < request.start || end > request.end || end > now {
            return Err(Error::Calendar);
        }
        let factor = if request.adjustment == Adjustment::None {
            BigDecimal::from(1)
        } else {
            factors.get(&day).cloned().ok_or(Error::Shape)?
        };
        let price = |index: usize| -> Result<Value> {
            let spelling = if request.adjustment == Adjustment::None {
                raw_prices[index].normalized().to_string()
            } else {
                adjusted_price(
                    &raw_prices[index].to_string(),
                    &factor.to_string(),
                    &anchor.to_string(),
                )?
            };
            OnlyPrice::new(
                spelling.parse().map_err(|_| Error::Shape)?,
                request.price_precision,
            )
            .map(|v| v.to_record())
            .map_err(|_| Error::Shape)
        };
        if request.adjustment != Adjustment::None {
            used_factors.insert(day, factor.clone());
        }
        // 价格、量、成交额逐交易日排序，规范数值后散列；表内行顺序不影响身份。
        let normalized = json!([
            day.to_string(),
            raw_prices
                .iter()
                .map(|n| n.normalized().to_string())
                .collect::<Vec<_>>(),
            vol.normalized().to_string(),
            row.get("amount")
                .filter(|n| !n.is_null())
                .map(decimal)
                .transpose()?
                .map(|n| n.normalized().to_string())
        ]);
        daily_digest.update(normalized.to_string().as_bytes());
        let raw = json!({"schema_version":1,"bar_type":{"schema_version":2,"instrument_id":request.instrument.to_record(),"semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"CALENDAR_PERIOD","unit":"DAY","count":1,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":request.adjustment.canonical()}},"open":price(0)?,"high":price(1)?,"low":price(2)?,"close":price(3)?,"volume":volume.to_record(),"quote_volume":null,"turnover":turnover,"trade_count":null,"open_interest":null,"bar_start":start.to_string(),"bar_end":end.to_string(),"ts_event":end.to_string(),"ts_init":end.to_string(),"is_closed":true,"revision":0,"adjustment_type":request.adjustment.canonical(),"trading_day":day.to_string(),"session_type":"REGULAR"});
        bars.push(OnlyBar::from_record(&raw).map_err(|_| Error::Shape)?);
    }
    if bars.is_empty() {
        let mut day = plan.start;
        while day <= plan.end {
            ensure_time(deadline)?;
            let trading_day = OnlyTradingDay::new(day).map_err(|_| Error::Calendar)?;
            if !request.calendar.is_effective_on(trading_day)
                || request.calendar.is_trading_day(trading_day)
            {
                return Err(Error::Empty);
            }
            day = day
                .checked_add(Span::new().days(1))
                .map_err(|_| Error::Calendar)?;
        }
    }
    let factors = if sdk_cache.is_some() {
        factors
    } else {
        used_factors
    };
    let (key, cache_hit) = sdk_cache.unwrap_or_default();
    let factor_basis = (request.adjustment != Adjustment::None).then(|| json!({
        "instrument_id":request.instrument.to_string(),
        "anchor":request.anchor.map(|d|json!({"schema_version":1,"value":d.to_string()})),
        "anchor_factor":anchor.normalized().to_string(),
        "factors":factors.iter().map(|(d,n)| (d.to_string(), n.normalized().to_string())).collect::<BTreeMap<_,_>>()
    }));
    http::success(
        deadline,
        DailyResult {
            bars,
            evidence,
            cache_key: key,
            factor_basis,
            normalized_daily_fingerprint: daily_digest
                .finalize()
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect(),
            identical_duplicates: duplicates,
            cache_hit,
        },
    )
}
type RowsByDay = BTreeMap<Date, BTreeMap<String, Value>>;

fn by_day(
    table: &Table,
    code: &str,
    start: Date,
    end: Date,
    deadline: Instant,
) -> Result<(RowsByDay, usize)> {
    let mut rows = BTreeMap::new();
    let mut duplicates = 0;
    for row in &table.rows {
        ensure_time(deadline)?;
        if text(row, "ts_code")? != code {
            return Err(Error::Shape);
        }
        let day = date(text(row, "trade_date")?)?;
        if day < start || day > end {
            return Err(Error::Shape);
        }
        if let Some(previous) = rows.insert(day, row.clone()) {
            if previous != *row {
                return Err(Error::Conflict);
            }
            duplicates += 1;
        }
    }
    Ok((rows, duplicates))
}
