//! Mutable Product labels, separate from immutable authoring content.
use super::{Error, Result, fp};
use serde_json::{Value, json};
#[derive(Clone, Debug)]
pub struct Display(Value);
pub fn defaults(number: usize) -> Value {
    json!({"display_name":format!("私有因子 {number}"),"usage_summary":"自定义计算；用途待完善。"})
}
impl Display {
    pub fn new(value: Value) -> Result<Self> {
        super::exact(
            &value,
            &[
                "schema_version",
                "factor_id",
                "display_name",
                "usage_summary",
                "edit_number",
            ],
        )
        .map_err(|_| Error::Invalid)?;
        let id = value["factor_id"].as_str().ok_or(Error::Invalid)?;
        super::id(id, "FACTOR").map_err(|_| Error::Invalid)?;
        if value["schema_version"].as_u64() != Some(1)
            || !value["edit_number"]
                .as_u64()
                .is_some_and(|n| (1..=9_007_199_254_740_991).contains(&n))
        {
            return Err(Error::Invalid);
        }
        fields(&value["display_name"], &value["usage_summary"])?;
        Ok(Self(value))
    }
    pub fn create(id: &str, names: &Value) -> Result<Self> {
        super::exact(names, &["display_name", "usage_summary"]).map_err(|_| Error::Invalid)?;
        Self::new(
            json!({"schema_version":1,"factor_id":id,"display_name":names["display_name"],"usage_summary":names["usage_summary"],"edit_number":1}),
        )
    }
    pub fn update(&self, name: &str, summary: &str) -> Result<Self> {
        let next = self.0["edit_number"]
            .as_u64()
            .ok_or(Error::Invalid)?
            .checked_add(1)
            .ok_or(Error::Invalid)?;
        Self::new(
            json!({"schema_version":1,"factor_id":self.0["factor_id"],"display_name":name,"usage_summary":summary,"edit_number":next}),
        )
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn fingerprint(&self) -> Result<String> {
        fp(&json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_DISPLAY_V1","display":self.0}))
    }
}
fn fields(name: &Value, summary: &Value) -> Result<()> {
    let name = name.as_str().ok_or(Error::Invalid)?;
    let summary = summary.as_str().ok_or(Error::Invalid)?;
    if name.trim().is_empty()
        || name.chars().count() > 100
        || name.len() > 400
        || name.chars().any(char::is_control)
        || summary.trim().is_empty()
        || summary.chars().count() > 1000
        || summary.len() > 4000
        || summary
            .chars()
            .any(|c| c.is_control() && !matches!(c, '\n' | '\t'))
    {
        return Err(Error::Invalid);
    }
    Ok(())
}
