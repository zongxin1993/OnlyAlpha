use bigdecimal::{BigDecimal, Zero};
use onlyalpha_domain::{identifiers::OnlyIdentifier, numeric::OnlyDecimal};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{fmt, str::FromStr};
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error(pub String);
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for Error {}
impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self(e.to_string())
    }
}
impl From<onlyalpha_domain::errors::OnlyDomainError> for Error {
    fn from(e: onlyalpha_domain::errors::OnlyDomainError) -> Self {
        Self(e.to_string())
    }
}
pub(crate) fn err(s: &str) -> Error {
    Error(s.into())
}
pub(crate) fn boundary<T, E: fmt::Display>(r: Result<T, E>) -> Result<T, Error> {
    r.map_err(|e| Error(e.to_string()))
}
pub fn digest(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
#[cfg(test)]
std::thread_local! {
    pub(crate) static HASHED_CANONICAL_WATCH: std::cell::RefCell<Option<(String,u64)>> = const { std::cell::RefCell::new(None) };
}
pub(crate) fn hash(v: &Value) -> String {
    let canonical = v.to_string();
    #[cfg(test)]
    HASHED_CANONICAL_WATCH.with(|watch| {
        if let Some((expected, count)) = watch.borrow_mut().as_mut() {
            if expected.as_str() == canonical.as_str() {
                *count += 1;
            }
        }
    });
    digest(canonical.as_bytes())
}
pub(crate) fn row<'a>(v: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let r = v.as_object().ok_or_else(|| err("EXECUTION_RECORD"))?;
    if r.get("schema_version").and_then(Value::as_u64) != Some(1)
        || r.len() != fields.len() + 1
        || fields.iter().any(|f| !r.contains_key(*f))
    {
        return Err(err("EXECUTION_FIELDS"));
    }
    Ok(r)
}
pub(crate) fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 256)
        .ok_or_else(|| err("EXECUTION_TEXT"))
}
pub(crate) fn id(v: &Value) -> Result<&str, Error> {
    let s = text(v)?;
    if OnlyIdentifier::new(s)?.value() != s {
        return Err(err("EXECUTION_ID"));
    }
    Ok(s)
}
pub(crate) fn uint(v: &Value) -> Result<u64, Error> {
    v.as_u64().ok_or_else(|| err("EXECUTION_UNSIGNED"))
}
pub(crate) fn fp(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(err("EXECUTION_DIGEST"));
    }
    Ok(())
}
pub(crate) fn dec(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    let raw = BigDecimal::from_str(s).map_err(|_| err("EXECUTION_DECIMAL"))?;
    let (c, e) = raw.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&e) {
        return Err(err("EXECUTION_DECIMAL_BOUND"));
    }
    let canonical: OnlyDecimal = s.parse()?;
    let n = BigDecimal::from_str(&canonical.to_string()).map_err(|_| err("EXECUTION_DECIMAL"))?;
    let (c, scale) = n.as_bigint_and_exponent();
    if c.to_string().len() > 128 || !(-64..=18).contains(&scale) {
        return Err(err("EXECUTION_DECIMAL_BOUND"));
    }
    Ok(n)
}
pub(crate) fn exact(v: &Value) -> Result<BigDecimal, Error> {
    let s = v
        .as_str()
        .filter(|s| s.len() <= 1100)
        .ok_or_else(|| err("EXECUTION_EXACT"))?;
    let raw = BigDecimal::from_str(s).map_err(|_| err("EXECUTION_EXACT"))?;
    let (c, e) = raw.as_bigint_and_exponent();
    if c.to_string().len() > 1024 || !(-512..=512).contains(&e) {
        return Err(err("EXECUTION_EXACT_BOUND"));
    }
    let n: OnlyDecimal = s.parse()?;
    let d = BigDecimal::from_str(&n.to_string()).map_err(|_| err("EXECUTION_EXACT"))?;
    let (c, scale) = d.as_bigint_and_exponent();
    if c.to_string().len() > 1024
        || !(-512..=512).contains(&scale)
        || d.normalized().to_plain_string().len() > 1024
    {
        return Err(err("EXECUTION_EXACT_BOUND"));
    }
    Ok(d)
}
pub(crate) fn exact_record(n: &BigDecimal, p: u8) -> String {
    let s = n.normalized().as_bigint_and_exponent().1.max(i64::from(p));
    n.with_scale(s).to_plain_string()
}
pub(crate) fn nonnegative(v: &Value) -> Result<BigDecimal, Error> {
    let n = dec(v)?;
    if n < BigDecimal::zero() {
        return Err(err("EXECUTION_NEGATIVE"));
    }
    Ok(n)
}
pub(crate) fn money(n: &BigDecimal, p: u8) -> Result<String, Error> {
    let v = n.with_scale(i64::from(p));
    if &v != n {
        return Err(err("EXECUTION_MONEY_PRECISION"));
    }
    let s = v.to_plain_string();
    if s.len() > 160 {
        return Err(err("EXECUTION_MONEY_BOUND"));
    }
    Ok(s)
}
pub(crate) const COMPONENTS: [&str; 6] = [
    "ORDER",
    "POSITION",
    "ACCOUNT",
    "LEDGER",
    "RISK",
    "EXECUTION",
];
#[cfg(test)]
std::thread_local! {
    pub(crate) static PREPARED_VALIDATIONS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    pub(crate) static PREPARED_OWNED_BODY_BYTES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
// Pure data derived only after the complete original body verifier succeeds.
// Its encoded body remains the unique representation; headers grant no source,
// planner, Store, Ready or execution authority.
struct CanonicalPreparedData {
    bytes: Vec<u8>,
    transaction: String,
    sequence: u64,
    predecessor: u64,
    configuration: String,
    payload: String,
    input: Value,
    events: Value,
    projections: Vec<(String, String)>,
    account_format: Option<u64>,
    position_order_data: Value,
    order_snapshot_data: Value,
}
/// Constructed only by the pure planner. Store transport must bind its exact encoded digest.
pub struct Prepared {
    value: std::sync::OnceLock<std::sync::Arc<Value>>,
    data: Option<std::sync::Arc<CanonicalPreparedData>>,
    input_fingerprint: std::sync::Arc<std::sync::OnceLock<String>>,
    validated_transition_data: std::sync::Arc<std::sync::OnceLock<()>>,
    planned: bool,
    typed_after: Option<Box<crate::Components>>,
}
impl Clone for Prepared {
    fn clone(&self) -> Self {
        Self {
            value: self.value.clone(),
            data: self.data.clone(),
            input_fingerprint: std::sync::Arc::clone(&self.input_fingerprint),
            validated_transition_data: std::sync::Arc::clone(&self.validated_transition_data),
            planned: self.planned,
            typed_after: None,
        }
    }
}
impl fmt::Debug for Prepared {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Prepared")
            .field("value", self.value())
            .field("planned", &self.planned)
            .finish()
    }
}
impl PartialEq for Prepared {
    fn eq(&self, other: &Self) -> bool {
        match (&self.data, &other.data) {
            (Some(left), Some(right))
                if std::sync::Arc::ptr_eq(left, right) || left.bytes == right.bytes =>
            {
                true
            }
            _ => self.value() == other.value(),
        }
    }
}
impl Eq for Prepared {}

impl Prepared {
    #[cfg(test)]
    pub(crate) fn retained_expansion(&self) -> Option<std::sync::Weak<Value>> {
        self.value.get().map(std::sync::Arc::downgrade)
    }
    #[cfg(test)]
    pub(crate) fn new(v: Value) -> Result<Self, Error> {
        Self::new_local(v, None)
    }
    /// Only the local planner can supply the actual owning post-transition
    /// components. Decoded data never gains this transient representation.
    pub(crate) fn new_with_typed_after(v: Value, after: crate::Components) -> Result<Self, Error> {
        Self::new_local(v, Some(after))
    }
    fn new_local(mut v: Value, after: Option<crate::Components>) -> Result<Self, Error> {
        if v.get("payload_hash").is_some() {
            return Err(err("EXECUTION_PAYLOAD_HASH"));
        }
        let payload_hash = hash(&v);
        v["payload_hash"] = json!(&payload_hash);
        let mut result = Self {
            value: std::sync::OnceLock::from(std::sync::Arc::new(v)),
            data: None,
            input_fingerprint: std::sync::Arc::new(std::sync::OnceLock::new()),
            validated_transition_data: std::sync::Arc::new(std::sync::OnceLock::new()),
            planned: !after.as_ref().is_some_and(|c| c.projection_data),
            typed_after: after.filter(|c| !c.projection_data).map(Box::new),
        };
        result.validate_with_payload_hash(Some(&payload_hash))?;
        let bytes = serde_json::to_vec(result.value())?;
        // Value permits unchecked arbitrary-precision Number construction.
        // Prove this exact representation has the original reader's meaning
        // and depth limits before an observation may release its expanded form.
        if !crate::canonical_roundtrip::matches_value(&bytes, result.value()) {
            return Err(err("EXECUTION_NONCANONICAL"));
        }
        result.retain_canonical_data(bytes);
        Ok(result)
    }
    /// Borrow the complete immutable canonical body as data, never a commit grant.
    /// `record()` remains the detached owned-copy API.
    pub fn value(&self) -> &Value {
        self.value
            .get_or_init(|| {
                let data = self.data.as_ref().expect("validated canonical data");
                std::sync::Arc::new(
                    serde_json::from_slice(&data.bytes)
                        .expect("validated immutable canonical JSON"),
                )
            })
            .as_ref()
    }
    pub(crate) fn is_planned(&self) -> bool {
        self.planned
    }
    /// Same original planner marker and exact data, without optional expanded
    /// or typed acceleration state. Decoded data remains non-planner data.
    pub fn compact_clone(&self) -> Self {
        Self {
            value: std::sync::OnceLock::new(),
            data: self.data.clone(),
            input_fingerprint: std::sync::Arc::clone(&self.input_fingerprint),
            validated_transition_data: std::sync::Arc::clone(&self.validated_transition_data),
            planned: self.planned,
            typed_after: None,
        }
    }
    pub(crate) fn observation(&self) -> Self {
        let mut result = self.compact_clone();
        result.planned = false;
        result
    }
    fn retain_canonical_data(&mut self, bytes: Vec<u8>) {
        let body = self.value();
        let projections = body["projections"]
            .as_array()
            .expect("validated projections");
        let data = CanonicalPreparedData {
            bytes,
            transaction: body["transaction_id"]
                .as_str()
                .expect("validated")
                .to_owned(),
            sequence: body["sequence"].as_u64().expect("validated"),
            predecessor: body["predecessor"].as_u64().expect("validated"),
            configuration: body["config_hash"].as_str().expect("validated").to_owned(),
            payload: body["payload_hash"].as_str().expect("validated").to_owned(),
            input: body["input"].clone(),
            events: body["events"].clone(),
            projections: projections
                .iter()
                .map(|row| {
                    (
                        row["before_hash"].as_str().expect("validated").to_owned(),
                        row["result_hash"].as_str().expect("validated").to_owned(),
                    )
                })
                .collect(),
            account_format: projections[2]["result"]["schema_version"].as_u64(),
            order_snapshot_data: projections[0]["result"]["state"]["orders"].clone(),
            position_order_data: json!({"schema_version":1,"orders":projections[5]["result"]["orders"],
                "position_accounts":projections[1]["result"]["state"]["accounts"],
                "position_allocations":projections[1]["result"]["state"]["allocations"],
                "economic_version":projections[2]["result"]["state"]["snapshot"]["economic_version"],
                "position_checkpoint_fingerprint":projections[1]["result_hash"]}),
        };
        self.data = Some(std::sync::Arc::new(data));
    }
    pub(crate) fn typed_after(&self) -> Option<&crate::Components> {
        self.typed_after.as_deref()
    }
    pub fn record(&self) -> Value {
        let owned = match self.value.get() {
            Some(value) => value.as_ref().clone(),
            None => {
                serde_json::from_slice(&self.data.as_ref().expect("validated canonical data").bytes)
                    .expect("validated immutable canonical JSON")
            }
        };
        #[cfg(test)]
        PREPARED_OWNED_BODY_BYTES
            .with(|count| count.set(count.get() + owned.to_string().len() as u64));
        owned
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(self
            .data
            .as_ref()
            .expect("validated canonical data")
            .bytes
            .clone())
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, Error> {
        let v: Value = serde_json::from_slice(bytes)?;
        if serde_json::to_vec(&v)? != bytes {
            return Err(err("EXECUTION_NONCANONICAL"));
        }
        let mut p = Self {
            value: std::sync::OnceLock::from(std::sync::Arc::new(v)),
            data: None,
            input_fingerprint: std::sync::Arc::new(std::sync::OnceLock::new()),
            validated_transition_data: std::sync::Arc::new(std::sync::OnceLock::new()),
            planned: false,
            typed_after: None,
        };
        p.validate()?;
        p.retain_canonical_data(bytes.to_vec());
        Ok(p)
    }
    pub fn id(&self) -> &str {
        match &self.data {
            Some(data) => &data.transaction,
            None => self.value()["transaction_id"].as_str().expect("validated"),
        }
    }
    pub fn sequence(&self) -> u64 {
        match &self.data {
            Some(data) => data.sequence,
            None => self.value()["sequence"].as_u64().expect("validated"),
        }
    }
    /// Original complete-body fields, derived only after canonical validation.
    /// None of these data reads proves a current Store or Ready source.
    pub fn predecessor_sequence(&self) -> u64 {
        self.data
            .as_ref()
            .expect("validated canonical data")
            .predecessor
    }
    pub fn configuration_fingerprint(&self) -> &str {
        &self
            .data
            .as_ref()
            .expect("validated canonical data")
            .configuration
    }
    pub fn payload_fingerprint(&self) -> &str {
        &self
            .data
            .as_ref()
            .expect("validated canonical data")
            .payload
    }
    pub fn projection_hashes(&self) -> &[(String, String)] {
        &self
            .data
            .as_ref()
            .expect("validated canonical data")
            .projections
    }
    pub fn account_checkpoint_version(&self) -> Option<u64> {
        self.data
            .as_ref()
            .expect("validated canonical data")
            .account_format
    }
    /// Pure fields of these original projections, never an owning current-source view.
    pub fn position_order_data(&self) -> &Value {
        &self
            .data
            .as_ref()
            .expect("validated canonical data")
            .position_order_data
    }
    /// Exact original Order rows only. Consumers still validate complete
    /// Domain snapshots and their owning source; this is no activity proof.
    pub fn order_snapshot_data(&self) -> &Value {
        &self
            .data
            .as_ref()
            .expect("validated canonical data")
            .order_snapshot_data
    }
    pub fn input(&self) -> &Value {
        match &self.data {
            Some(data) => &data.input,
            None => &self.value()["input"],
        }
    }
    /// Canonical data identity of this exact immutable input, never Store freshness or admission.
    pub fn input_fingerprint(&self) -> &str {
        self.input_fingerprint
            .get_or_init(|| hash(self.input()))
            .as_str()
    }
    /// Pure owner-transition data only, never current Store/Ready or planner authority.
    /// Transport decoding always starts without this rebuildable, nonserialized data.
    pub fn has_validated_transition_data(&self) -> bool {
        self.validated_transition_data.get().is_some()
    }
    pub(crate) fn mark_transition_data_valid(&self) {
        let _ = self.validated_transition_data.set(());
    }
    pub fn projection_count(&self) -> usize {
        COMPONENTS.len()
    }
    pub fn events(&self) -> &Value {
        match &self.data {
            Some(data) => &data.events,
            None => &self.value()["events"],
        }
    }
    fn validate(&self) -> Result<(), Error> {
        self.validate_with_payload_hash(None)
    }
    // Only new() supplies the hash it just computed over its owned local body.
    // External bytes always use validate() and recompute their complete hash.
    fn validate_with_payload_hash(&self, local_hash: Option<&str>) -> Result<(), Error> {
        #[cfg(test)]
        PREPARED_VALIDATIONS.with(|count| count.set(count.get() + 1));
        let v = self.value();
        row(
            v,
            &[
                "transaction_id",
                "config_hash",
                "sequence",
                "predecessor",
                "input",
                "projections",
                "events",
                "payload_hash",
            ],
        )?;
        for f in ["config_hash", "payload_hash"] {
            fp(&v[f])?;
        }
        if uint(&v["sequence"])? == 0
            || uint(&v["predecessor"])?.checked_add(1) != Some(uint(&v["sequence"])?)
        {
            return Err(err("EXECUTION_SEQUENCE"));
        }
        if text(&v["transaction_id"])? != format!("ETX-{}", self.input_fingerprint()) {
            return Err(err("EXECUTION_IDENTITY"));
        }
        if let Some(expected) = local_hash {
            if v["payload_hash"].as_str() != Some(expected) {
                return Err(err("EXECUTION_PAYLOAD_HASH"));
            }
        } else {
            let mut content = v.clone();
            let expected = content
                .as_object_mut()
                .expect("row")
                .remove("payload_hash")
                .expect("row");
            if expected != hash(&content) {
                return Err(err("EXECUTION_PAYLOAD_HASH"));
            }
        }
        let ps = v["projections"]
            .as_array()
            .filter(|p| p.len() == COMPONENTS.len())
            .ok_or_else(|| err("EXECUTION_PROJECTIONS"))?;
        for (i, p) in ps.iter().enumerate() {
            row(p, &["component", "before_hash", "result_hash", "result"])?;
            if p["component"] != COMPONENTS[i] {
                return Err(err("EXECUTION_PROJECTION_HASH_OR_ORDER"));
            }
            if i < 5 && self.typed_after.is_some() {
                // The same owner already encoded and hashed these exact bytes.
                // Require its complete JSON value, hash, config, planner origin
                // and Account format, rather than trusting a supplied digest.
                let _ = crate::Components::validated_typed_after(self, i)?;
            } else if p["result_hash"] != hash(&p["result"]) {
                return Err(err("EXECUTION_PROJECTION_HASH_OR_ORDER"));
            }
            fp(&p["before_hash"])?;
        }
        let events = v["events"]
            .as_array()
            .filter(|a| a.len() == 1)
            .ok_or_else(|| err("EXECUTION_EVENTS"))?;
        if events[0]
            != json!({"schema_version":1,"event_id":format!("{}-EVENT-1",self.id()),"transaction_id":self.id(),"sequence":v["sequence"],"input":v["input"]})
        {
            return Err(err("EXECUTION_EVENT_IDENTITY"));
        }
        Ok(())
    }
}

pub(crate) fn settled_money(
    proof: &Value,
    key: &str,
    raw: &BigDecimal,
    currency: &Value,
    p: u8,
) -> Result<String, Error> {
    let v = &proof[key];
    row(v, &["amount", "currency"])?;
    if v["currency"] != *currency || proof["rounding"] != "HALF_EVEN" {
        return Err(err("EXECUTION_SETTLEMENT_ROUNDING"));
    }
    let amount = money(&nonnegative(&v["amount"])?, p)?;
    if v["amount"] != amount
        || nonnegative(&v["amount"])?
            != raw.with_scale_round(i64::from(p), bigdecimal::RoundingMode::HalfEven)
    {
        return Err(err("EXECUTION_SETTLEMENT_NOTIONAL"));
    }
    Ok(amount)
}
// Bound all external decimal leaves before calling typed Domain readers.
pub(crate) fn bound_decimal_leaves(v: &Value) -> Result<(), Error> {
    match v {
        Value::Object(m) => {
            for (k, v) in m {
                if (k == "amount" || (k == "value" && m.contains_key("precision")))
                    && v.as_str().is_some_and(|s| {
                        s.bytes()
                            .next()
                            .is_some_and(|b| b.is_ascii_digit() || b == b'-' || b == b'+')
                    })
                {
                    dec(v)?;
                } else {
                    bound_decimal_leaves(v)?;
                }
            }
        }
        Value::Array(a) => {
            for v in a {
                bound_decimal_leaves(v)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
#[path = "tests/typed_after_tests.rs"]
mod typed_after_tests;

#[cfg(test)]
#[path = "tests/record_observation_tests.rs"]
mod record_observation_tests;

#[cfg(test)]
#[path = "tests/pure_transition_data_tests.rs"]
mod pure_transition_data_tests;
