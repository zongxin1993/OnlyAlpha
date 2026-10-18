use crate::{OnlyDeliveryError, OnlyDeliveryResult};
use onlyalpha_domain::identifiers::OnlyIdentifier;
use serde_json::{Map, Value};
pub(crate) fn invalid(message: impl ToString) -> OnlyDeliveryError {
    OnlyDeliveryError::Record(message.to_string())
}
pub(crate) fn fields<'a>(
    value: &'a Value,
    names: &[&str],
) -> OnlyDeliveryResult<&'a Map<String, Value>> {
    let row = value.as_object().ok_or_else(|| invalid("OBJECT"))?;
    if row.len() != names.len() || names.iter().any(|key| !row.contains_key(*key)) {
        return Err(invalid("FIELDS"));
    }
    Ok(row)
}
pub(crate) fn object<'a>(
    value: &'a Value,
    names: &[&str],
) -> OnlyDeliveryResult<&'a Map<String, Value>> {
    let row = fields(value, names)?;
    if row["schema_version"].as_u64() != Some(1) {
        return Err(invalid("SCHEMA"));
    }
    Ok(row)
}
pub(crate) fn text(value: &Value) -> OnlyDeliveryResult<&str> {
    value.as_str().ok_or_else(|| invalid("TEXT"))
}
pub(crate) fn array(value: &Value) -> OnlyDeliveryResult<&Vec<Value>> {
    value.as_array().ok_or_else(|| invalid("ARRAY"))
}
pub(crate) fn identifier(raw: &str) -> OnlyDeliveryResult<OnlyIdentifier> {
    let id = OnlyIdentifier::new(raw).map_err(invalid)?;
    if id.value() != raw {
        return Err(invalid("NONCANONICAL_ID"));
    }
    Ok(id)
}
