//! 离线规则资源的语义身份、原始文档校验和按时点精确查询。
use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{
    identifiers::OnlyInstrumentId, numeric::OnlyDecimal, time::OnlyUtcDateTime,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, str::FromStr};

pub type Result<T> = std::result::Result<T, &'static str>;
const WORK: usize = 64 * 1024 * 1024;
pub(crate) fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 1024)
        .ok_or("REFERENCE_TEXT_INVALID")
}
pub(crate) fn items(v: &Value) -> Result<&Vec<Value>> {
    v.as_array()
        .filter(|a| a.len() <= 65536)
        .ok_or("REFERENCE_LIST_INVALID")
}
pub(crate) fn fields(v: &Value, keys: &[&str]) -> Result<()> {
    if v.as_object()
        .is_some_and(|m| m.len() == keys.len() && keys.iter().all(|k| m.contains_key(*k)))
    {
        Ok(())
    } else {
        Err("REFERENCE_FIELDS_INVALID")
    }
}
pub fn raw_sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
pub fn read_json(bytes: &[u8]) -> Result<Value> {
    let raw = std::str::from_utf8(bytes).map_err(|_| "REFERENCE_JSON_INVALID")?;
    let canonical = onlyalpha_metadata_json::python_json(raw, WORK).map_err(|e| e.code())?;
    serde_json::from_str(&canonical).map_err(|_| "REFERENCE_JSON_INVALID")
}
pub fn fingerprint(v: &Value) -> Result<String> {
    let canonical =
        onlyalpha_metadata_json::python_json(&v.to_string(), WORK).map_err(|e| e.code())?;
    Ok(raw_sha256(canonical.as_bytes()))
}
pub(crate) fn decimal(v: &Value) -> Result<BigDecimal> {
    let s = text(v)?;
    if s.len() > 128 {
        return Err("REFERENCE_DECIMAL_BOUND");
    }
    let n = BigDecimal::from_str(s).map_err(|_| "REFERENCE_DECIMAL_INVALID")?;
    if n.as_bigint_and_exponent().1.unsigned_abs() > 128 {
        return Err("REFERENCE_DECIMAL_BOUND");
    }
    Ok(n)
}
fn plain(v: &Value) -> Result<Value> {
    if v.is_null() {
        return Ok(Value::Null);
    }
    let n = decimal(v)?;
    let value = n.to_plain_string();
    Ok(json!(if n.is_zero() && text(v)?.starts_with('-') {
        format!("-{value}")
    } else {
        value
    }))
}
pub(crate) fn instant(v: &Value) -> Result<OnlyUtcDateTime> {
    text(v)?.parse().map_err(|_| "REFERENCE_TIME_INVALID")
}
fn sha(v: &Value) -> Result<&str> {
    text(v)?
        .bytes()
        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        .then_some(())
        .filter(|_| v.as_str().is_some_and(|s| s.len() == 64))
        .ok_or("REFERENCE_DIGEST_INVALID")?;
    text(v)
}
const SPOT: &[&str] = &[
    "instrument_id",
    "raw_symbol",
    "base_currency",
    "quote_currency",
    "provider_status",
    "spot_trading_allowed",
    "price_tick",
    "minimum_price",
    "maximum_price",
    "quantity_step",
    "minimum_quantity",
    "maximum_quantity",
    "market_quantity_step",
    "market_minimum_quantity",
    "market_maximum_quantity",
    "minimum_notional",
    "maximum_notional",
    "minimum_notional_applies_to_market",
    "maximum_notional_applies_to_market",
    "notional_reference_window_minutes",
    "venue_order_types",
    "time_in_force",
    "order_group_capabilities",
    "default_stp_mode",
    "allowed_stp_modes",
    "permission_sets",
    "capabilities",
    "rules",
    "compatibility_status",
];
const PUBLIC: &[&str] = &[
    "instrument_id",
    "raw_symbol",
    "provider_status",
    "settlement_currency",
    "contract_multiplier",
    "price_tick",
    "minimum_price",
    "maximum_price",
    "quantity_step",
    "minimum_quantity",
    "maximum_quantity",
    "minimum_notional",
    "funding_schedule",
];
const ACCOUNT: &[&str] = &["instrument_id", "effective_inputs", "margin_segments"];
const PROVENANCE: &[&str] = &[
    "coverage_start",
    "coverage_end",
    "observed_at",
    "provider_revision",
    "normalizer_semantic_version",
    "provider_schema_semantic_version",
    "source_raw_fingerprints",
];
const NUMBERS: &[&str] = &[
    "contract_multiplier",
    "price_tick",
    "minimum_price",
    "maximum_price",
    "quantity_step",
    "minimum_quantity",
    "maximum_quantity",
    "market_quantity_step",
    "market_minimum_quantity",
    "market_maximum_quantity",
    "minimum_notional",
    "maximum_notional",
];
pub(crate) const SEGMENT: &[&str] = &[
    "lower_bound",
    "upper_bound",
    "initial_slope",
    "initial_intercept",
    "maintenance_slope",
    "maintenance_intercept",
];
fn strings(v: &Value) -> Result<()> {
    items(v)?.iter().try_for_each(|x| text(x).map(|_| ()))
}
fn rules(raw: &Value) -> Result<Vec<Value>> {
    items(raw)?
        .iter()
        .map(|r| {
            fields(r, &["rule_type", "category", "values"])?;
            for pair in items(&r["values"])? {
                if items(pair)?.len() != 2
                    || !(pair[1].is_string()
                        || pair[1].is_boolean()
                        || pair[1].is_i64()
                        || pair[1].is_u64())
                {
                    return Err("REFERENCE_RULE_VALUE");
                }
                text(&pair[0])?;
            }
            Ok(json!([
                text(&r["rule_type"])?,
                text(&r["category"])?,
                r["values"]
            ]))
        })
        .collect()
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Spot,
    Public,
    Account,
}
#[derive(Clone, Debug)]
pub struct Reference {
    kind: Kind,
    payload: Value,
    id: String,
}
fn segment_identity(v: &Value) -> Result<Value> {
    fields(v, SEGMENT)?;
    if SEGMENT
        .iter()
        .any(|k| *k != "upper_bound" && v[k].is_null())
    {
        return Err("REFERENCE_MARGIN_SEGMENT");
    }
    Ok(Value::Array(
        SEGMENT
            .iter()
            .map(|k| plain(&v[k]))
            .collect::<Result<_>>()?,
    ))
}
fn content(row: &Value, kind: Kind) -> Result<String> {
    let semantic = match kind {
        Kind::Spot => SPOT,
        Kind::Public => PUBLIC,
        Kind::Account => ACCOUNT,
    };
    let mut keys = semantic.to_vec();
    if kind != Kind::Spot {
        keys.extend(PROVENANCE);
        if kind == Kind::Public {
            keys.push("published_at");
            instant(&row["published_at"])?;
        }
        instant(&row["observed_at"])?;
        let start = instant(&row["coverage_start"])?;
        if !row["coverage_end"].is_null() && instant(&row["coverage_end"])? <= start {
            return Err("REFERENCE_COVERAGE_INVALID");
        }
        for k in [
            "provider_revision",
            "normalizer_semantic_version",
            "provider_schema_semantic_version",
        ] {
            text(&row[k])?;
        }
        let raw = items(&row["source_raw_fingerprints"])?;
        if raw.len() != 2 {
            return Err("REFERENCE_EVIDENCE_INCOMPLETE");
        }
        for r in raw {
            sha(r)?;
        }
    }
    fields(row, &keys)?;
    let id = text(&row["instrument_id"])?;
    if id.parse::<OnlyInstrumentId>().is_err() {
        return Err("REFERENCE_INSTRUMENT_INVALID");
    }
    if kind == Kind::Account {
        let e = &row["effective_inputs"];
        fields(
            e,
            &[
                "position_mode",
                "margin_mode",
                "leverage",
                "source_fingerprint",
            ],
        )?;
        if !matches!(text(&e["position_mode"])?, "NETTING" | "HEDGING")
            || !matches!(text(&e["margin_mode"])?, "CROSS" | "ISOLATED")
            || decimal(&e["leverage"])? < 1
            || sha(&e["source_fingerprint"])? != fingerprint(&row["source_raw_fingerprints"])?
        {
            return Err("REFERENCE_ACCOUNT_PROFILE_INVALID");
        }
        let segments = items(&row["margin_segments"])?;
        if segments.is_empty() {
            return Err("REFERENCE_MARGIN_SEGMENTS_REQUIRED");
        }
        return fingerprint(&json!([
            id,
            [
                e["position_mode"],
                e["margin_mode"],
                plain(&e["leverage"])?,
                e["source_fingerprint"]
            ],
            segments
                .iter()
                .map(segment_identity)
                .collect::<Result<Vec<_>>>()?
        ]));
    }
    let raw = text(&row["raw_symbol"])?;
    if id
        != format!(
            "{raw}{}.BINANCE",
            if kind == Kind::Public { "-PERP" } else { "" }
        )
    {
        return Err("REFERENCE_INSTRUMENT_RELATION");
    }
    for k in ["quantity_step", "minimum_quantity", "price_tick"] {
        if decimal(&row[k])? <= BigDecimal::zero() {
            return Err("REFERENCE_STATIC_RULE_INVALID");
        }
    }
    let mut pairs = Vec::new();
    for &k in semantic {
        let v = &row[k];
        let value = if NUMBERS.contains(&k) {
            if !v.is_null() && decimal(v)? < BigDecimal::zero() {
                return Err("REFERENCE_STATIC_RULE_INVALID");
            }
            plain(v)?
        } else {
            match k {
                "funding_schedule" => {
                    fields(
                        v,
                        &[
                            "interval_seconds",
                            "boundary_offset_seconds",
                            "valuation_price_kind",
                            "provider_semantic_version",
                        ],
                    )?;
                    let interval = v["interval_seconds"]
                        .as_u64()
                        .ok_or("REFERENCE_FUNDING_INTERVAL")?;
                    if v["boundary_offset_seconds"]
                        .as_u64()
                        .is_none_or(|n| n >= interval)
                        || v["valuation_price_kind"] != "MARK"
                    {
                        return Err("REFERENCE_FUNDING_SCHEDULE");
                    }
                    json!([
                        interval,
                        v["boundary_offset_seconds"],
                        "MARK",
                        text(&v["provider_semantic_version"])?
                    ])
                }
                "rules" => json!(rules(v)?),
                "spot_trading_allowed"
                | "minimum_notional_applies_to_market"
                | "maximum_notional_applies_to_market" => {
                    json!(v.as_bool().ok_or("REFERENCE_BOOLEAN")?)
                }
                "notional_reference_window_minutes" => json!(v.as_u64().ok_or("REFERENCE_WINDOW")?),
                "permission_sets" => {
                    for a in items(v)? {
                        strings(a)?;
                    }
                    v.clone()
                }
                "capabilities" => {
                    for a in items(v)? {
                        if items(a)?.len() != 2 || !a[1].is_boolean() {
                            return Err("REFERENCE_CAPABILITY");
                        }
                        text(&a[0])?;
                    }
                    v.clone()
                }
                "order_group_capabilities"
                | "venue_order_types"
                | "time_in_force"
                | "allowed_stp_modes" => {
                    strings(v)?;
                    v.clone()
                }
                "compatibility_status" if v != "COMPATIBLE" && v != "INCOMPATIBLE" => {
                    return Err("REFERENCE_COMPATIBILITY");
                }
                _ => json!(text(v)?),
            }
        };
        pairs.push((k, value));
    }
    if kind == Kind::Public && decimal(&row["contract_multiplier"])? <= BigDecimal::zero() {
        return Err("REFERENCE_MULTIPLIER");
    }
    pairs.sort_by_key(|p| p.0);
    fingerprint(&json!(pairs))
}
impl Reference {
    pub fn kind(&self) -> Kind {
        self.kind
    }
    pub fn payload(&self) -> &Value {
        &self.payload
    }
    pub fn fingerprint(&self) -> &str {
        &self.id
    }
    fn rows(&self) -> &Value {
        if self.kind == Kind::Spot {
            &self.payload["authority"]["references"]
        } else {
            &self.payload["references"]
        }
    }
    pub fn resolve(&self, instrument: &str, at: OnlyUtcDateTime) -> Result<&Value> {
        if self.kind == Kind::Spot
            && (self.payload["authority"]["compatibility_status"] != "COMPATIBLE"
                || at < instant(&self.payload["observed_at"])?)
        {
            return Err("REFERENCE_HISTORICAL_COVERAGE_UNPROVEN");
        }
        for row in items(self.rows())? {
            if row["instrument_id"] == instrument
                && (self.kind == Kind::Spot
                    || (instant(&row["coverage_start"])? <= at
                        && (row["coverage_end"].is_null() || at < instant(&row["coverage_end"])?)))
            {
                return Ok(row);
            }
        }
        Err("REFERENCE_NOT_FOUND_AT_TIME")
    }
    pub fn document(bytes: &[u8], expected_sha256: &str, resource_id: &str) -> Result<Self> {
        if raw_sha256(bytes) != expected_sha256 {
            return Err("REFERENCE_BLOB_MISMATCH");
        }
        let v = read_json(bytes)?;
        fields(
            &v,
            &["schema_version", "resource_id", "provider_id", "payload"],
        )?;
        if v["schema_version"] != 1 || text(&v["resource_id"])? != resource_id {
            return Err("REFERENCE_DOCUMENT_IDENTITY");
        }
        let r = Self::load(&v["payload"])?;
        let provider = if r.kind == Kind::Spot {
            "onlyalpha-plugin-binance-spot/reference@1"
        } else {
            "onlyalpha-plugin-binance-usdm/reference@1"
        };
        if v["provider_id"] != provider {
            return Err("REFERENCE_PROVIDER_MISMATCH");
        }
        Ok(r)
    }
    pub fn load(payload: &Value) -> Result<Self> {
        let rebuilt = if payload.get("authority").is_some() {
            fields(payload, &["authority", "observed_at"])?;
            let a = &payload["authority"];
            fields(
                a,
                &[
                    "semantic_schema_version",
                    "authority_fingerprint",
                    "authority_version",
                    "compatibility_status",
                    "exchange_rules",
                    "references",
                ],
            )?;
            Self::spot(
                instant(&payload["observed_at"])?,
                a["exchange_rules"].clone(),
                items(&a["references"])?.clone(),
            )?
        } else {
            fields(payload, &["kind", "authority_fingerprint", "references"])?;
            let kind = match text(&payload["kind"])? {
                "PUBLIC" => Kind::Public,
                "ACCOUNT" => Kind::Account,
                _ => return Err("REFERENCE_KIND"),
            };
            Self::usdm(kind, items(&payload["references"])?.clone())?
        };
        if rebuilt.payload != *payload {
            return Err("REFERENCE_FINGERPRINT_CONFLICT");
        }
        Ok(rebuilt)
    }
    pub fn spot(at: OnlyUtcDateTime, exchange: Value, mut rows: Vec<Value>) -> Result<Self> {
        if rows.is_empty() {
            return Err("REFERENCE_EMPTY");
        }
        let identities = rules(&exchange)?;
        let mut seen = BTreeSet::new();
        for row in &mut rows {
            let object = row.as_object_mut().ok_or("REFERENCE_RECORD")?;
            object.remove("content_fingerprint");
            let fp = content(row, Kind::Spot)?;
            if !seen.insert(text(&row["instrument_id"])?.to_owned()) {
                return Err("REFERENCE_DUPLICATE_INSTRUMENT");
            }
            row["content_fingerprint"] = json!(fp);
        }
        rows.sort_by(|a, b| {
            a["instrument_id"]
                .as_str()
                .cmp(&b["instrument_id"].as_str())
        });
        let id = fingerprint(&json!([
            identities,
            rows.iter()
                .map(|r| &r["content_fingerprint"])
                .collect::<Vec<_>>()
        ]))?;
        let status = if identities.iter().any(|r| r[1] == "UNKNOWN_CRITICAL") {
            "INCOMPATIBLE"
        } else {
            "COMPATIBLE"
        };
        let payload = json!({"observed_at":iso(at),"authority":{"semantic_schema_version":1,"authority_version":"2","authority_fingerprint":id,"compatibility_status":status,"exchange_rules":exchange,"references":rows}});
        Ok(Self {
            kind: Kind::Spot,
            payload,
            id,
        })
    }
    pub fn usdm(kind: Kind, mut rows: Vec<Value>) -> Result<Self> {
        if rows.is_empty() || kind == Kind::Spot {
            return Err("REFERENCE_USDM_KIND");
        }
        let mut profile = None;
        for row in &mut rows {
            row.as_object_mut()
                .ok_or("REFERENCE_RECORD")?
                .remove("content_fingerprint");
            let fp = content(row, kind)?;
            if kind == Kind::Account
                && profile
                    .replace(row["effective_inputs"].clone())
                    .is_some_and(|p| p != row["effective_inputs"])
            {
                return Err("REFERENCE_PROFILE_AMBIGUOUS");
            }
            row["content_fingerprint"] = json!(fp);
        }
        // Times have been validated; use absolute time rather than lexical ordering.
        rows.sort_by(|a, b| {
            a["instrument_id"]
                .as_str()
                .cmp(&b["instrument_id"].as_str())
                .then_with(|| instant(&a["coverage_start"]).cmp(&instant(&b["coverage_start"])))
        });
        for window in rows.windows(2) {
            if window[0]["instrument_id"] == window[1]["instrument_id"]
                && (window[0]["coverage_end"].is_null()
                    || instant(&window[0]["coverage_end"])?
                        > instant(&window[1]["coverage_start"])?)
            {
                return Err("REFERENCE_COVERAGE_AMBIGUOUS");
            }
        }
        let mut identities = Vec::new();
        for row in &rows {
            let mut id = vec![row["content_fingerprint"].clone()];
            for k in [
                "coverage_start",
                "coverage_end",
                "observed_at",
                "published_at",
            ] {
                if let Some(value) = row.get(k) {
                    id.push(if value.is_null() {
                        Value::Null
                    } else {
                        json!(instant(value)?.to_string())
                    });
                }
            }
            for k in [
                "provider_revision",
                "normalizer_semantic_version",
                "provider_schema_semantic_version",
                "source_raw_fingerprints",
            ] {
                id.push(row[k].clone());
            }
            identities.push(id);
        }
        let id = fingerprint(&json!(identities))?;
        let name = if kind == Kind::Public {
            "PUBLIC"
        } else {
            "ACCOUNT"
        };
        Ok(Self {
            kind,
            payload: json!({"kind":name,"authority_fingerprint":id,"references":rows}),
            id,
        })
    }
}
pub fn iso(at: OnlyUtcDateTime) -> String {
    at.to_string().replace('Z', "+00:00")
}
pub fn decimal_text(v: &Value) -> Result<String> {
    decimal(v)?;
    Ok(text(v)?
        .parse::<OnlyDecimal>()
        .map_err(|_| "REFERENCE_DECIMAL_INVALID")?
        .to_string())
}
