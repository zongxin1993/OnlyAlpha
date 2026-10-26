//! Bounded synchronous ClickHouse HTTP protocol and all-column physical proof.
use super::*;
use onlyalpha_domain::base::OnlyDomainModel;
use reqwest::{Client, Url, redirect, retry};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PhysicalState {
    Absent,
    Exact,
    Partial,
    Conflict,
}
/// Explicit Host-selected endpoint, semantic database, credentials and finite budgets.
/// The owning builder disables redirects, proxies and automatic retry.
pub struct ClickHouseConfig {
    pub url: String,
    pub database: String,
    pub user: String,
    pub password: String,
    pub timeout: Duration,
    pub tls_roots_pem: Vec<Vec<u8>>,
    pub max_bytes: usize,
    pub max_rows: usize,
}
pub struct ClickHouse {
    client: Client,
    url: Url,
    database: String,
    user: String,
    password: zeroize::Zeroizing<String>,
    max_bytes: usize,
    max_rows: usize,
}
impl ClickHouse {
    pub fn new(config: ClickHouseConfig) -> Result<Self> {
        let url = Url::parse(&config.url).map_err(|_| Error::Invalid)?;
        if !matches!(url.scheme(), "http" | "https")
            || url.host_str().is_none()
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || url.path() != "/"
            || config.timeout.is_zero()
            || config.timeout > Duration::from_secs(60)
            || config.max_bytes == 0
            || config.max_bytes > MAX_BYTES
            || config.max_rows == 0
            || config.max_rows > 1_000_000
            || config.user.is_empty()
        {
            return Err(Error::Invalid);
        }
        identifier(&config.database)?;
        if (url.scheme() == "https") != !config.tls_roots_pem.is_empty() {
            return Err(Error::Invalid);
        }
        let certs = config
            .tls_roots_pem
            .iter()
            .map(|pem| reqwest::Certificate::from_pem(pem).map_err(|_| Error::Invalid))
            .collect::<Result<Vec<_>>>()?;
        let client = Client::builder()
            .redirect(redirect::Policy::none())
            .retry(retry::never())
            .no_proxy()
            .http1_only()
            .tls_certs_only(certs)
            .tls_sslkeylogfile(false)
            .timeout(config.timeout)
            .connect_timeout(config.timeout)
            .build()
            .map_err(|_| Error::Unavailable)?;
        Ok(Self {
            client,
            url,
            database: config.database,
            user: config.user,
            password: zeroize::Zeroizing::new(config.password),
            max_bytes: config.max_bytes,
            max_rows: config.max_rows,
        })
    }
    async fn request(&self, sql: String, params: &[(&str, String)]) -> Result<String> {
        if sql.len() > self.max_bytes {
            return Err(Error::Unavailable);
        }
        let mut url = self.url.clone();
        {
            let mut pairs = url.query_pairs_mut();
            pairs.append_pair("database", &self.database);
            for (key, value) in params {
                pairs.append_pair(key, value);
            }
        }
        let mut request = self
            .client
            .post(url)
            .basic_auth(&self.user, Some(self.password.as_str()))
            .body(sql);
        request = request.header("Content-Type", "text/plain; charset=utf-8");
        let mut response = request.send().await.map_err(|_| Error::Unknown)?;
        if !response.status().is_success() {
            return Err(Error::Unavailable);
        }
        if response
            .content_length()
            .is_some_and(|n| n > self.max_bytes as u64)
        {
            return Err(Error::Unavailable);
        }
        let mut bytes = vec![];
        while let Some(chunk) = response.chunk().await.map_err(|_| Error::Unknown)? {
            if bytes
                .len()
                .checked_add(chunk.len())
                .is_none_or(|n| n > self.max_bytes)
            {
                return Err(Error::Unavailable);
            }
            bytes.extend_from_slice(&chunk);
        }
        String::from_utf8(bytes).map_err(|_| Error::Unprovable)
    }
    async fn rows(&self, sql: String, params: &[(&str, String)]) -> Result<Vec<Value>> {
        let raw = self
            .request(format!("{sql} FORMAT JSONEachRow"), params)
            .await?;
        let rows = raw
            .lines()
            .filter(|s| !s.is_empty())
            .map(decode)
            .collect::<Result<Vec<_>>>()?;
        if rows.len() > self.max_rows {
            return Err(Error::Unavailable);
        }
        Ok(rows)
    }
    pub async fn assert_server(&self) -> Result<()> {
        let rows = self.rows("SELECT version() AS version".into(), &[]).await?;
        if rows.len() != 1 || !text(&rows[0]["version"])?.starts_with("26.3.") {
            return Err(Error::Unavailable);
        }
        Ok(())
    }
    pub(super) async fn snapshot(&self, segment: &Segment) -> Result<Rows> {
        let mut result = BTreeMap::new();
        let mut bytes = 0usize;
        let mut count = 0usize;
        for table in TABLES {
            // Return primitive physical values as unambiguous textual SQL values. Decimal
            // and integer columns do not pass through JSON floats or payload hashes.
            let select = columns(table)?
                .iter()
                .map(|(name, _)| format!("if(isNull({name}),NULL,toString({name})) AS {name}"))
                .collect::<Vec<_>>()
                .join(",");
            let rows = self
                .rows(
                    format!(
                        "SELECT {select} FROM {table} WHERE segment_id={{segment:String}} LIMIT {}",
                        self.max_rows + 1
                    ),
                    &[("param_segment", segment.id().into())],
                )
                .await?;
            count = count.checked_add(rows.len()).ok_or(Error::Unavailable)?;
            bytes = bytes
                .checked_add(rows.iter().map(|r| r.to_string().len()).sum::<usize>())
                .ok_or(Error::Unavailable)?;
            if count > self.max_rows || bytes > self.max_bytes {
                return Err(Error::Unavailable);
            }
            result.insert(table.to_owned(), rows);
        }
        Ok(result)
    }
    pub(super) async fn insert(&self, table: &str, rows: &[Value]) -> Result<()> {
        if !TABLES.contains(&table) || rows.is_empty() || rows.len() > self.max_rows {
            return Err(Error::Invalid);
        }
        let body = rows
            .iter()
            .map(canonical)
            .collect::<Result<Vec<_>>>()?
            .join("\n");
        // No splitting/retries: witness binds this single frozen table submission.
        self.request(format!("INSERT INTO {table} SETTINGS async_insert=0, wait_for_async_insert=1, insert_deduplicate=1 FORMAT JSONEachRow\n{body}"),&[]).await?;
        Ok(())
    }
}
impl std::fmt::Debug for ClickHouseConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("ClickHouseConfig(<explicit endpoint; credentials redacted>)")
    }
}
fn identifier(v: &str) -> Result<()> {
    if v.is_empty()
        || !v
            .bytes()
            .enumerate()
            .all(|(i, b)| b.is_ascii_alphabetic() || b == b'_' || i > 0 && b.is_ascii_digit())
    {
        Err(Error::Invalid)
    } else {
        Ok(())
    }
}
pub(super) type Rows = BTreeMap<String, Vec<Value>>;
fn table(kind: &str) -> Result<&'static str> {
    match kind {
        "TRADE" => Ok(TABLES[1]),
        "BAR" => Ok(TABLES[2]),
        "MARKET_REFERENCE" => Ok(TABLES[3]),
        _ => Err(Error::Unprovable),
    }
}
fn columns(table: &str) -> Result<Vec<(&'static str, char)>> {
    let names = match table {
        "market_raw_event" => {
            "raw_event_id source_id provider venue market stream capture_session_id segment_id segment_content_hash record_ordinal provider_event_type provider_event_id provider_sequence ts_event_ns ts_receive_ns ts_ingest_ns payload_codec provider_schema integration_binding_fingerprint provenance raw_payload_base64 raw_sha256 record_hash"
        }
        "market_trade" => {
            "canonical_fact_id source_id instrument_id segment_id segment_content_hash capture_session_id raw_event_id provider_event_id provider_sequence ts_event_ns ts_receive_ns ts_ingest_ns price price_precision quantity quantity_precision aggressor_side provenance quality_state canonical_payload_json canonical_payload_hash normalizer_id normalizer_version record_hash"
        }
        "market_bar" => {
            "canonical_fact_id source_id instrument_id segment_id segment_content_hash capture_session_id raw_event_id ts_event_ns ts_receive_ns ts_ingest_ns bar_start_ns bar_end_ns bar_type_json open high low close price_precision volume quantity_precision quote_volume trade_count provenance quality_state canonical_payload_json canonical_payload_hash normalizer_id normalizer_version record_hash"
        }
        "market_reference_price" => {
            "canonical_fact_id source_id instrument_id segment_id segment_content_hash capture_session_id raw_event_id ts_event_ns ts_receive_ns ts_ingest_ns reference_kind price price_precision provenance quality_state canonical_payload_json canonical_payload_hash normalizer_id normalizer_version record_hash"
        }
        _ => return Err(Error::Invalid),
    };
    Ok(names
        .split_whitespace()
        .map(|name| {
            (
                name,
                if [
                    "price",
                    "quantity",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "quote_volume",
                ]
                .contains(&name)
                {
                    'D'
                } else if [
                    "record_ordinal",
                    "provider_sequence",
                    "ts_event_ns",
                    "ts_receive_ns",
                    "ts_ingest_ns",
                    "bar_start_ns",
                    "bar_end_ns",
                    "price_precision",
                    "quantity_precision",
                    "trade_count",
                ]
                .contains(&name)
                {
                    'I'
                } else {
                    'S'
                },
            )
        })
        .collect())
}
fn decimal(s: &str) -> Result<String> {
    // Physical Decimal256(18) has fixed precision. Reject rounding or expansion
    // beyond that representation instead of accepting a lossy insert.
    if s.len() > 100 || s.is_empty() {
        return Err(Error::Unprovable);
    }
    let (negative, s) = s.strip_prefix('-').map_or((false, s), |s| (true, s));
    let mut pieces = s.split('.');
    let whole = pieces.next().ok_or(Error::Unprovable)?;
    let fraction = pieces.next().unwrap_or("");
    if pieces.next().is_some()
        || whole.is_empty()
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || !fraction.bytes().all(|b| b.is_ascii_digit())
    {
        return Err(Error::Unprovable);
    }
    let whole = whole.trim_start_matches('0');
    let whole = if whole.is_empty() { "0" } else { whole };
    let fraction = fraction.trim_end_matches('0');
    if fraction.len() > 18 || whole.len() + 18 > 76 {
        return Err(Error::Unprovable);
    }
    let sign = if negative && (whole != "0" || !fraction.is_empty()) {
        "-"
    } else {
        ""
    };
    Ok(if fraction.is_empty() {
        format!("{sign}{whole}")
    } else {
        format!("{sign}{whole}.{fraction}")
    })
}
fn render(v: &Value, tag: char, stored: bool) -> Result<Option<String>> {
    if v.is_null() {
        return Ok(None);
    }
    let s = if stored {
        v.as_str().ok_or(Error::Unprovable)?.to_owned()
    } else if tag == 'I' {
        integer(v)?.to_string()
    } else {
        v.as_str().ok_or(Error::Unprovable)?.to_owned()
    };
    Ok(Some(match tag {
        'D' => decimal(&s)?,
        'I' => s
            .parse::<i128>()
            .map_err(|_| Error::Unprovable)?
            .to_string(),
        _ => s,
    }))
}
fn row_proof(table: &str, row: &Value, stored: bool) -> Result<String> {
    let mut proof = String::new();
    for (name, tag) in columns(table)? {
        let v = row.get(name).unwrap_or(&Value::Null);
        if let Some(s) = render(v, tag, stored)? {
            proof.push_str(&format!("{tag}V{}:{s}", s.len()));
        } else {
            proof.push_str(&format!("{tag}N"));
        }
    }
    Ok(proof)
}
fn part(table: &str, rows: &[Value], stored: bool) -> Result<Value> {
    let mut proofs = rows
        .iter()
        .map(|r| row_proof(table, r, stored))
        .collect::<Result<Vec<_>>>()?;
    proofs.sort();
    Ok(
        json!({"table":table,"row_count":rows.len(),"row_set_digest":hash(proofs.concat().as_bytes())}),
    )
}
pub(super) fn proof(segment: &Segment, rows: &Rows, stored: bool) -> Result<PhysicalProof> {
    PhysicalProof::build(
        segment,
        TABLES
            .iter()
            .map(|t| part(t, rows.get(*t).ok_or(Error::Unprovable)?, stored))
            .collect::<Result<Vec<_>>>()?,
    )
}
pub(super) fn classify(expected: &Rows, actual: &Rows) -> Result<PhysicalState> {
    if actual.values().all(Vec::is_empty) {
        return Ok(PhysicalState::Absent);
    }
    let mut partial = false;
    for table in TABLES {
        let wanted = expected.get(table).ok_or(Error::Unprovable)?;
        let actual = actual.get(table).ok_or(Error::Unprovable)?;
        let desired = wanted
            .iter()
            .map(|r| row_proof(table, r, false))
            .collect::<Result<BTreeSet<_>>>()?;
        if desired.len() != wanted.len() {
            return Err(Error::Conflict);
        }
        let observed = actual
            .iter()
            .map(|r| row_proof(table, r, true))
            .collect::<Result<BTreeSet<_>>>()?;
        if observed.len() != actual.len() || !observed.is_subset(&desired) {
            return Ok(PhysicalState::Conflict);
        }
        partial |= observed != desired;
    }
    Ok(if partial {
        PhysicalState::Partial
    } else {
        PhysicalState::Exact
    })
}
pub(super) fn expected(segment: &Segment, bundles: &[Value]) -> Result<Rows> {
    if bundles.len()
        != usize::try_from(integer(&segment.record["record_count"])?).map_err(|_| Error::Invalid)?
    {
        return Err(Error::Unprovable);
    }
    let mut rows: Rows = TABLES.iter().map(|t| ((*t).into(), vec![])).collect();
    let mut canonical_count = 0;
    let mut raw_ids = BTreeSet::new();
    let mut fact_ids = BTreeSet::new();
    for (ordinal, bundle) in bundles.iter().enumerate() {
        // Reuse the owning WAL validator, not another record codec.
        let bundle = crate::persistence::market_data_wal::validate_bundle(
            &bundle.to_string(),
            segment.id(),
        )?;
        let evidence = &bundle["evidence"];
        if !raw_ids.insert(text(&evidence["raw_event_id"])?.to_owned()) {
            return Err(Error::Conflict);
        }
        for (e, s) in [
            ("source_id", "source_id"),
            ("capture_session_id", "capture_session_id"),
            ("provider", "provider"),
            ("venue", "venue"),
            ("market", "market"),
            ("stream", "stream"),
            ("provenance", "capture_mode"),
            ("provider_schema", "provider_schema"),
            ("payload_codec", "codec"),
            (
                "integration_binding_fingerprint",
                "integration_binding_fingerprint",
            ),
            ("bar_construction", "bar_construction"),
        ] {
            if evidence[e] != segment.record[s] {
                return Err(Error::Unprovable);
            }
        }
        let facts = array(&bundle["canonical_facts"])?;
        let ingest = facts
            .iter()
            .map(|f| integer(&f["ts_ingest_ns"]))
            .collect::<Result<Vec<_>>>()?
            .into_iter()
            .min()
            .unwrap_or(integer(&evidence["ts_receive_ns"])?);
        let mut raw = json!({});
        for k in [
            "raw_event_id",
            "source_id",
            "provider",
            "venue",
            "market",
            "stream",
            "capture_session_id",
            "provider_event_type",
            "provider_event_id",
            "provider_sequence",
            "ts_event_ns",
            "ts_receive_ns",
            "payload_codec",
            "provider_schema",
            "provenance",
            "raw_sha256",
        ] {
            raw[k] = evidence[k].clone();
        }
        raw["segment_id"] = segment.id().into();
        raw["segment_content_hash"] = segment.content_hash().into();
        raw["record_ordinal"] = ordinal.into();
        raw["ts_ingest_ns"] = ingest.into();
        raw["raw_payload_base64"] = evidence["payload_base64"].clone();
        if !evidence["integration_binding_fingerprint"].is_null() {
            raw["integration_binding_fingerprint"] =
                evidence["integration_binding_fingerprint"].clone();
        }
        raw["record_hash"] = fingerprint(&raw)?.into();
        rows.get_mut(TABLES[0]).ok_or(Error::Invalid)?.push(raw);
        for fact in facts {
            canonical_count += 1;
            if !fact_ids.insert((
                text(&fact["canonical_fact_id"])?.to_owned(),
                text(&fact["raw_event_id"])?.to_owned(),
            )) {
                return Err(Error::Conflict);
            }
            for k in ["instrument_id", "data_kind"] {
                if fact[k] != segment.record[k] {
                    return Err(Error::Unprovable);
                }
            }
            if fact["canonical_payload"]["data_version"] != segment.record["data_version"] {
                return Err(Error::Unprovable);
            }
            let mut row = json!({});
            for k in [
                "canonical_fact_id",
                "source_id",
                "instrument_id",
                "segment_id",
                "capture_session_id",
                "raw_event_id",
                "ts_event_ns",
                "ts_receive_ns",
                "ts_ingest_ns",
                "provenance",
                "quality_state",
                "canonical_payload_hash",
                "normalizer_id",
                "normalizer_version",
            ] {
                row[k] = fact[k].clone();
            }
            row["segment_content_hash"] = segment.content_hash().into();
            row["canonical_payload_json"] = canonical(&fact["canonical_payload"])?.into();
            let payload = &fact["canonical_payload"]["payload"]["value"];
            match text(&fact["data_kind"])? {
                "BAR" => {
                    for k in ["open", "high", "low", "close", "volume", "quote_volume"] {
                        row[k] = if payload[k].is_null() {
                            Value::Null
                        } else {
                            decimal(text(&payload[k]["value"])?)?;
                            payload[k]["value"].clone()
                        };
                    }
                    row["price_precision"] = payload["open"]["precision"].clone();
                    row["quantity_precision"] = payload["volume"]["precision"].clone();
                    row["trade_count"] = payload["trade_count"].clone();
                    row["bar_type_json"] = canonical(&payload["bar_type"])?.into();
                    row["bar_start_ns"] = time_ns(&payload["bar_start"])?.into();
                    row["bar_end_ns"] = time_ns(&payload["bar_end"])?.into();
                }
                "TRADE" => {
                    for k in ["price", "quantity"] {
                        decimal(text(&payload[k]["value"])?)?;
                        row[k] = payload[k]["value"].clone();
                    }
                    row["price_precision"] = payload["price"]["precision"].clone();
                    row["quantity_precision"] = payload["quantity"]["precision"].clone();
                    let typed = onlyalpha_domain::market::OnlyTradeTick::from_record(payload)
                        .map_err(|_| Error::Unprovable)?;
                    if typed.instrument_id().to_string() != text(&fact["instrument_id"])?
                        || typed.source() != text(&fact["source_id"])?
                        || time_ns(&payload["ts_event"])? != integer(&fact["ts_event_ns"])?
                    {
                        return Err(Error::Unprovable);
                    }
                    row["provider_event_id"] = text(&payload["trade_id"]["value"])?.into();
                    row["provider_sequence"] = integer(&payload["sequence"])?.into();
                    row["aggressor_side"] = payload["aggressor_side"].clone();
                }
                "MARKET_REFERENCE" => {
                    row["reference_kind"] = text(&payload["reference_kind"])?.into();
                    row["price"] = if payload["price"].is_null() {
                        Value::Null
                    } else {
                        decimal(text(&payload["price"]["value"])?)?;
                        payload["price"]["value"].clone()
                    };
                    row["price_precision"] = if payload["price"].is_null() {
                        Value::Null
                    } else {
                        payload["price"]["precision"].clone()
                    };
                }
                _ => return Err(Error::Unprovable),
            }
            row["record_hash"] = fingerprint(&row)?.into();
            rows.get_mut(table(text(&fact["data_kind"])?)?)
                .ok_or(Error::Invalid)?
                .push(row);
        }
    }
    if canonical_count != integer(&segment.record["canonical_count"])? {
        return Err(Error::Unprovable);
    }
    Ok(rows)
}
fn time_ns(v: &Value) -> Result<i64> {
    utc(text(v)?)?
        .0
        .timestamp()
        .total_nanoseconds()
        .try_into()
        .map_err(|_| Error::Unavailable)
}
pub(super) fn facts(segment: &Segment, rows: &Rows) -> Result<Vec<Value>> {
    let mut facts = vec![];
    for (table_name, rows) in rows {
        if table_name == TABLES[0] {
            continue;
        }
        let kind = match table_name.as_str() {
            "market_trade" => "TRADE",
            "market_bar" => "BAR",
            "market_reference_price" => "MARKET_REFERENCE",
            _ => return Err(Error::Unprovable),
        };
        for row in rows {
            let payload = decode(text(&row["canonical_payload_json"])?)?;
            let mut fact = json!({"data_kind":kind,"canonical_payload":payload});
            for key in [
                "canonical_fact_id",
                "raw_event_id",
                "source_id",
                "instrument_id",
                "segment_id",
                "capture_session_id",
                "canonical_payload_hash",
                "normalizer_id",
                "normalizer_version",
                "quality_state",
                "provenance",
            ] {
                fact[key] = text(&row[key])?.into();
            }
            for key in ["ts_event_ns", "ts_receive_ns", "ts_ingest_ns"] {
                fact[key] = text(&row[key])?
                    .parse::<i64>()
                    .map_err(|_| Error::Unprovable)?
                    .into();
            }
            if fact["segment_id"] != segment.id()
                || fact["source_id"] != segment.record["source_id"]
                || fact["capture_session_id"] != segment.record["capture_session_id"]
                || payload_relation(&fact).is_err()
            {
                return Err(Error::Unprovable);
            }
            facts.push(fact);
        }
    }
    Ok(facts)
}
fn payload_relation(f: &Value) -> Result<()> {
    let p = &f["canonical_payload"];
    for (a, b) in [
        ("canonical_fact_id", "update_id"),
        ("source_id", "source_id"),
        ("data_kind", "data_type"),
        ("ts_event_ns", "ts_event"),
    ] {
        if f[a] != p[b] {
            return Err(Error::Unprovable);
        }
    }
    if fingerprint(p)? != text(&f["canonical_payload_hash"])? {
        return Err(Error::Unprovable);
    }
    Ok(())
}

/// Original immutable PG proof and every current WAL-derived physical column
/// must both agree. A historical producer defect is not a supported projection.
pub(super) fn verify_published(
    segment: &Segment,
    expected: &Rows,
    actual: &Rows,
    original: &PhysicalProof,
) -> Result<()> {
    original.validate(segment)?;
    if proof(segment, actual, true)? != *original
        || classify(expected, actual)? != PhysicalState::Exact
    {
        return Err(Error::Unprovable);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_physical_column_and_utf8_byte_length_participates_in_the_digest() {
        for table in TABLES {
            let mut row = json!({});
            for (name, tag) in columns(table).unwrap() {
                row[name] = match tag {
                    'I' => json!(1),
                    'D' => json!("-123.450000000000000001"),
                    _ => json!("值:😀"),
                };
            }
            let original = row_proof(table, &row, false).unwrap();
            assert!(original.contains("SV8:值:😀"));
            for (name, tag) in columns(table).unwrap() {
                let mut changed = row.clone();
                changed[name] = match tag {
                    'I' => json!(-2),
                    'D' => json!("0.000000000000000001"),
                    _ => json!("different"),
                };
                assert_ne!(
                    row_proof(table, &changed, false).unwrap(),
                    original,
                    "{table}.{name}"
                );
                changed[name] = Value::Null;
                assert_ne!(row_proof(table, &changed, false).unwrap(), original);
            }
        }
        assert_eq!(decimal("-0.000000000000000000").unwrap(), "0");
        assert_eq!(decimal("000123.4500").unwrap(), "123.45");
        assert!(decimal("1.0000000000000000001").is_err());
        assert!(decimal("1e3").is_err());
    }
}

#[cfg(test)]
mod empty_physical_strings {
    use super::*;
    #[test]
    fn empty_strings_remain_values_distinct_from_null() {
        assert_eq!(render(&json!(""), 'S', false).unwrap(), Some(String::new()));
        assert_eq!(render(&json!(""), 'S', true).unwrap(), Some(String::new()));
        assert_eq!(render(&Value::Null, 'S', false).unwrap(), None);
        assert!(render(&json!(0), 'S', false).is_err());
    }
}
