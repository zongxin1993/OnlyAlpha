//! Named workspace presentation library. No market values or scientific evidence.
use crate::application::command::CommandId;
use crate::application::source_access::Reference;
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, market::OnlyBarSemantic,
    numeric::OnlyDecimal,
};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, fmt};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    HistoryCorrupt,
    CommandConflict,
    CommandUnknown,
    VersionConflict,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "WORKSPACE_INVALID",
            Self::HistoryCorrupt => "WORKSPACE_HISTORY_CORRUPT",
            Self::CommandConflict => "WORKSPACE_COMMAND_CONFLICT",
            Self::CommandUnknown => "WORKSPACE_COMMAND_UNKNOWN",
            Self::VersionConflict => "WORKSPACE_VERSION_CONFLICT",
            Self::Unavailable => "WORKSPACE_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Book {
    version: u64,
    active_workspace_id: Option<String>,
    workspaces: Vec<Value>,
}
impl Book {
    pub fn new(
        version: u64,
        active_workspace_id: Option<String>,
        workspaces: Vec<Value>,
    ) -> Result<Self, Error> {
        if version > i64::MAX as u64
            || workspaces.len() > 32
            || (version > 0 && workspaces.is_empty())
        {
            return Err(Error::Invalid);
        }
        let mut ids = BTreeSet::new();
        for workspace in &workspaces {
            let row = object(workspace, &["workspace_id", "name", "configuration"])?;
            let id = text(&row["workspace_id"])?;
            namespace_id(id)?;
            if !ids.insert(id) {
                return Err(Error::Invalid);
            }
            let name = text(&row["name"])?;
            if name.trim() != name || name.trim().is_empty() || name.chars().count() > 120 {
                return Err(Error::Invalid);
            }
            validate_configuration(&row["configuration"])?;
        }
        if workspaces.is_empty() {
            if active_workspace_id.is_some() {
                return Err(Error::Invalid);
            }
        } else if !active_workspace_id
            .as_deref()
            .is_some_and(|id| ids.contains(id))
        {
            return Err(Error::Invalid);
        }
        let book = Self {
            version,
            active_workspace_id,
            workspaces,
        };
        if book.to_record().to_string().len() > 65536 {
            return Err(Error::Invalid);
        }
        Ok(book)
    }
    pub fn version(&self) -> u64 {
        self.version
    }
    pub fn with_version(&self, version: u64) -> Result<Self, Error> {
        Self::new(
            version,
            self.active_workspace_id.clone(),
            self.workspaces.clone(),
        )
    }
    pub fn to_record(&self) -> Value {
        json!({"version":self.version,"active_workspace_id":self.active_workspace_id,"workspaces":self.workspaces})
    }
    pub fn from_record(value: &Value) -> Result<Self, Error> {
        let row = object(value, &["version", "active_workspace_id", "workspaces"])?;
        let active = if row["active_workspace_id"].is_null() {
            None
        } else {
            Some(text(&row["active_workspace_id"])?.to_owned())
        };
        Self::new(
            row["version"].as_u64().ok_or(Error::Invalid)?,
            active,
            array(&row["workspaces"], 32)?.to_vec(),
        )
    }
    pub fn fingerprint(&self, namespace: &str) -> Result<String, Error> {
        Self::record_fingerprint(namespace, &self.to_record())
    }
    pub fn record_fingerprint(namespace: &str, record: &Value) -> Result<String, Error> {
        namespace_id(namespace)?;
        fingerprint(&json!({"namespace_id":namespace,"workspace_library":record}))
    }
    pub fn intent_fingerprint(&self, namespace: &str) -> Result<String, Error> {
        namespace_id(namespace)?;
        fingerprint(
            &json!({"namespace_id":namespace,"expected_version":self.version,"active_workspace_id":self.active_workspace_id,"workspaces":self.workspaces}),
        )
    }
}
pub(crate) fn namespace_id(value: &str) -> Result<(), Error> {
    CommandId::new(value)
        .map(|_| ())
        .map_err(|_| Error::Invalid)
}
fn fingerprint(value: &Value) -> Result<String, Error> {
    let canonical = onlyalpha_metadata_json::integral_float_json(&value.to_string(), 1024 * 1024)
        .map_err(|_| Error::Invalid)?;
    Ok(Sha256::digest(canonical.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
fn object<'a>(v: &'a Value, keys: &[&str]) -> Result<&'a Map<String, Value>, Error> {
    let row = v.as_object().ok_or(Error::Invalid)?;
    if row.len() != keys.len() || keys.iter().any(|k| !row.contains_key(*k)) {
        return Err(Error::Invalid);
    }
    Ok(row)
}
fn text(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 1024 && !s.chars().any(char::is_control))
        .ok_or(Error::Invalid)
}
fn array(v: &Value, max: usize) -> Result<&[Value], Error> {
    v.as_array()
        .filter(|a| a.len() <= max)
        .map(Vec::as_slice)
        .ok_or(Error::Invalid)
}
fn names(v: &Value) -> Result<BTreeSet<&str>, Error> {
    let a = array(v, 32)?;
    let set = a.iter().map(text).collect::<Result<BTreeSet<_>, _>>()?;
    if a.is_empty() || a.len() != set.len() {
        return Err(Error::Invalid);
    }
    Ok(set)
}
fn scalar(v: &Value) -> Result<(), Error> {
    let row = object(v, &["type", "value"])?;
    let value = &row["value"];
    let valid = match row["type"].as_str() {
        Some("NULL") => value.is_null(),
        Some("BOOLEAN") => value.is_boolean(),
        Some("INTEGER") => value
            .as_i64()
            .is_some_and(|n| n.unsigned_abs() <= 9_007_199_254_740_991),
        Some("DECIMAL") => text(value).is_ok_and(|s| s.parse::<OnlyDecimal>().is_ok()),
        Some("STRING") => text(value).is_ok(),
        _ => false,
    };
    if !valid {
        return Err(Error::Invalid);
    }
    Ok(())
}
fn color(v: &Value) -> Result<(), Error> {
    let s = text(v)?;
    if s.len() != 7 || !s.starts_with('#') || !s[1..].bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(Error::Invalid);
    }
    Ok(())
}
fn validate_configuration(v: &Value) -> Result<(), Error> {
    let row = object(v, &["source", "instrument_id", "bar_semantic", "studies"])?;
    let source = object(
        &row["source"],
        &[
            "integration_id",
            "integration_revision_fingerprint",
            "expected_type_id",
        ],
    )?;
    Reference::new(
        text(&source["integration_id"])?,
        text(&source["integration_revision_fingerprint"])?,
        Some(text(&source["expected_type_id"])?),
    )
    .map_err(|_| Error::Invalid)?;
    let instrument = text(&row["instrument_id"])?;
    if !instrument
        .parse::<OnlyInstrumentId>()
        .is_ok_and(|id| id.to_string() == instrument)
    {
        return Err(Error::Invalid);
    }
    let semantic =
        OnlyBarSemantic::from_record(&row["bar_semantic"]).map_err(|_| Error::Invalid)?;
    if !semantic.is_fixed_duration() {
        return Err(Error::Invalid);
    }
    for study in array(&row["studies"], 32)? {
        let s = object(
            study,
            &[
                "kind",
                "type_id",
                "semantic_version",
                "parameters",
                "output_names",
                "presentation",
            ],
        )?;
        onlyalpha_calculation::TypeReference::new(
            text(&s["kind"])?,
            text(&s["type_id"])?,
            text(&s["semantic_version"])?,
        )
        .map_err(|_| Error::Invalid)?;
        let parameters = s["parameters"]
            .as_object()
            .filter(|m| m.len() <= 32)
            .ok_or(Error::Invalid)?;
        for (key, value) in parameters {
            text(&json!(key))?;
            scalar(value)?;
        }
        names(&s["output_names"])?;
        let p = object(
            &s["presentation"],
            &[
                "placement",
                "color",
                "line_width",
                "opacity",
                "visible",
                "series_styles",
            ],
        )?;
        if !matches!(
            p["placement"].as_str(),
            Some("PRICE_OVERLAY" | "SEPARATE_PANE")
        ) || !p["visible"].is_boolean()
            || !p["line_width"]
                .as_f64()
                .is_some_and(|n| n.is_finite() && (1.0..=5.0).contains(&n))
            || !p["opacity"]
                .as_f64()
                .is_some_and(|n| (0.0..=1.0).contains(&n))
        {
            return Err(Error::Invalid);
        }
        color(&p["color"])?;
        let styles = p["series_styles"]
            .as_object()
            .filter(|m| m.len() <= 32)
            .ok_or(Error::Invalid)?;
        for (key, style) in styles {
            text(&json!(key))?;
            let st = object(style, &["color", "visible"])?;
            color(&st["color"])?;
            if !st["visible"].is_boolean() {
                return Err(Error::Invalid);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn single_book(version: u64, configuration: Option<Value>) -> Result<Book, Error> {
        let id = "00000000-0000-4000-8000-000000000002";
        Book::new(version, configuration.as_ref().map(|_| id.to_owned()), configuration.into_iter().map(|configuration|json!({"workspace_id":id,"name":"观察工作区","configuration":configuration})).collect())
    }
    fn configuration() -> serde_json::Value {
        json!({"source":{"integration_id":"binance","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"onlyalpha.source.binance.spot"},"instrument_id":"BTCUSDT.BINANCE","bar_semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":7,"stride_minutes":7,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"},"studies":[{"kind":"INDICATOR","type_id":"test.sma","semantic_version":"1.0.0","parameters":{"period":{"type":"INTEGER","value":20}},"output_names":["SMA"],"presentation":{"placement":"PRICE_OVERLAY","color":"#abcdef","line_width":2,"opacity":1,"visible":true,"series_styles":{}}}]})
    }
    #[test]
    fn workspace_intent_roundtrips_without_prices_or_authority() {
        let config = configuration();
        let book = single_book(0, Some(config.clone())).unwrap();
        assert_eq!(Book::from_record(&book.to_record()).unwrap(), book);
        let namespace = "00000000-0000-4000-8000-000000000001";
        assert_ne!(
            book.fingerprint(namespace).unwrap(),
            single_book(1, Some(config.clone()))
                .unwrap()
                .fingerprint(namespace)
                .unwrap()
        );
        assert_ne!(
            single_book(0, Some(config.clone()))
                .unwrap()
                .intent_fingerprint(namespace)
                .unwrap(),
            single_book(1, Some(config.clone()))
                .unwrap()
                .intent_fingerprint(namespace)
                .unwrap()
        );
        assert!(single_book(0, None).is_ok());
        assert!(single_book(1, None).is_err());
        assert!(single_book(i64::MAX as u64 + 1, Some(config)).is_err());
    }
    #[test]
    fn library_names_are_labels_and_selection_is_an_exact_bounded_id() {
        let first = "00000000-0000-4000-8000-000000000002";
        let second = "00000000-0000-4000-8000-000000000003";
        let entry = |id: &str, name: &str| json!({"workspace_id":id,"name":name,"configuration":configuration()});
        let items = vec![entry(first, "同名"), entry(second, "同名")];
        assert!(Book::new(1, Some(second.to_owned()), items.clone()).is_ok());
        assert!(Book::new(1, None, items.clone()).is_err());
        assert!(
            Book::new(
                1,
                Some("00000000-0000-4000-8000-000000000004".to_owned()),
                items
            )
            .is_err()
        );
        for name in ["", " 空白 ", "bad\nname", &"字".repeat(121)] {
            assert!(Book::new(1, Some(first.to_owned()), vec![entry(first, name)]).is_err());
        }
        assert!(
            Book::new(
                1,
                Some(first.to_owned()),
                vec![entry(first, "同名"), entry(first, "另一个名称")]
            )
            .is_err()
        );
        let oversized = (1..=33)
            .map(|n| entry(&format!("00000000-0000-4000-8000-{n:012}"), "工作区"))
            .collect();
        assert!(Book::new(1, Some(first.to_owned()), oversized).is_err());
    }
    #[test]
    fn workspace_preserves_fractional_width_and_canonical_presentation_numbers() {
        let mut config = configuration();
        config["studies"][0]["presentation"]["line_width"] = json!(2.5);
        assert!(single_book(0, Some(config)).is_ok());
    }
    #[test]
    fn workspace_canonical_presentation_numbers_ignore_equivalent_json_spelling() {
        let first = configuration();
        let mut second = first.clone();
        second["studies"][0]["presentation"]["opacity"] = json!(1.0);
        let namespace = "00000000-0000-4000-8000-000000000001";
        assert_eq!(
            single_book(0, Some(first))
                .unwrap()
                .fingerprint(namespace)
                .unwrap(),
            single_book(0, Some(second))
                .unwrap()
                .fingerprint(namespace)
                .unwrap()
        );
    }
    #[test]
    fn workspace_keeps_styles_for_currently_unselected_outputs() {
        let mut config = configuration();
        config["studies"][0]["presentation"]["series_styles"] =
            json!({"another_official_output":{"color":"#123456","visible":false}});
        assert!(single_book(0, Some(config)).is_ok());
    }
    #[test]
    fn workspace_rejects_values_grants_fallback_and_unsafe_scalars() {
        for field in [
            "bars",
            "results",
            "viewport",
            "token",
            "latest",
            "revision_evidence",
        ] {
            let mut bad = configuration();
            bad[field] = json!([]);
            assert!(single_book(0, Some(bad)).is_err(), "{field}");
        }
        for (path, value) in [
            (
                "source",
                json!({"integration_id":"binance","integration_revision_fingerprint":"latest","expected_type_id":"source"}),
            ),
            ("instrument_id", json!("bad")),
            ("bar_semantic", json!({})),
            ("studies", json!([{"capability":{}}])),
        ] {
            let mut bad = configuration();
            bad[path] = value;
            assert!(single_book(0, Some(bad)).is_err(), "{path}");
        }
        for value in [
            json!(1.5),
            json!(9007199254740992_u64),
            json!("20"),
            json!(null),
        ] {
            let mut bad = configuration();
            bad["studies"][0]["parameters"]["period"]["value"] = value;
            assert!(single_book(0, Some(bad)).is_err());
        }
        let mut bad = configuration();
        bad["studies"][0]["presentation"]["opacity"] = json!(1.1);
        assert!(single_book(0, Some(bad)).is_err());
        let mut bad = configuration();
        bad["studies"][0]["output_names"] = json!(["SMA", "SMA"]);
        assert!(single_book(0, Some(bad)).is_err());
        let mut bad = configuration();
        bad["studies"][0]["parameters"]["period"]["value"] =
            json!({"$serde_json::private::Number":"20"});
        assert!(single_book(0, Some(bad)).is_err());
    }
}
