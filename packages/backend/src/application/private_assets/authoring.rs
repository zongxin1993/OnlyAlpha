//! Authoring content only: a saved Revision never grants execution or admission.
use super::{Error, Result, fp, hash, revision};
use serde_json::{Value, json};
/// Frozen API V1 identity; shared SDK conformance checks bind this exact value.
pub const API_FINGERPRINT: &str =
    "3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9";
#[derive(Clone, Debug)]
pub struct Draft(Value);
impl Draft {
    pub fn new(mut value: Value) -> Result<Self> {
        let object = value.as_object_mut().ok_or(Error::Invalid)?;
        if object.contains_key("revision_fingerprint")
            || object.contains_key("parent_revision_fingerprint")
        {
            return Err(Error::Invalid);
        }
        if value.to_string().len() > 262144
            || value["source_text"]
                .as_str()
                .is_none_or(|s| s.len() > 65536)
            || value["factor_api_contract_fingerprint"] != API_FINGERPRINT
            || !storable(&value)
        {
            return Err(Error::Invalid);
        }
        let tags = value["tags"].as_array_mut().ok_or(Error::Invalid)?;
        if tags.iter().any(|v| v.as_str().is_none_or(str::is_empty)) {
            return Err(Error::Invalid);
        }
        tags.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
        if tags.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(Error::Invalid);
        }
        let draft = Self(value);
        draft.revision().map_err(|_| Error::Invalid)?;
        Ok(draft)
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn factor_id(&self) -> &str {
        self.0["factor_id"].as_str().expect("validated draft")
    }
    pub fn base(&self) -> Option<&str> {
        self.0["base_revision_fingerprint"].as_str()
    }
    pub fn fingerprint(&self) -> Result<String> {
        fp(&json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_DRAFT_V1","draft":self.0}))
    }
    pub fn revision(&self) -> Result<Value> {
        let mut value = self.0.as_object().ok_or(Error::Invalid)?.clone();
        let base = value
            .remove("base_revision_fingerprint")
            .ok_or(Error::Invalid)?;
        value.insert("parent_revision_fingerprint".into(), base);
        let source = value
            .get("source_text")
            .and_then(Value::as_str)
            .ok_or(Error::Invalid)?;
        let sha = hash(source.as_bytes());
        value.insert("source_sha256".into(), json!(sha));
        value.insert(
            "contract".into(),
            json!("ONLYALPHA_PRIVATE_FACTOR_REVISION_V1"),
        );
        let fingerprint = fp(&Value::Object(value.clone()))?;
        value.remove("contract");
        value.insert("revision_fingerprint".into(), json!(fingerprint));
        let result = Value::Object(value);
        revision("FACTOR", &result)?;
        Ok(result)
    }
}
pub fn fingerprint(value: &Value) -> Result<String> {
    fp(value)
}
pub fn validate_revision(value: &Value) -> Result<()> {
    revision("FACTOR", value)
}

pub fn validate_id(value: &str) -> Result<()> {
    super::id(value, "FACTOR")
}

// PostgreSQL TEXT/JSONB cannot represent NUL, including nested object keys.
fn storable(value: &Value) -> bool {
    match value {
        Value::String(text) => !text.contains('\0'),
        Value::Array(items) => items.iter().all(storable),
        Value::Object(items) => items
            .iter()
            .all(|(key, value)| !key.contains('\0') && storable(value)),
        _ => true,
    }
}
