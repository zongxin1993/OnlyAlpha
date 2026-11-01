//! Strict ADR 0133 authoring values. Parsing is not Freeze or Runtime admission.
use crate::application::factor_content::hash;
use onlyalpha_calculation::TypeReference;
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyInstrumentId, market::OnlyBarSemantic,
};
use onlyalpha_market_data_construction::OnlyConstructionRecipe;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_DEFINITION_INVALID";
const LIMIT: usize = 262144;
fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(INVALID);
    }
    Ok(())
}
fn name(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| {
            !s.is_empty()
                && s.len() <= 512
                && !s.chars().any(|c| c.is_whitespace() || c.is_control())
        })
        .ok_or(INVALID)
}
fn rows(v: &Value) -> Result<&Vec<Value>> {
    v.as_array().filter(|a| a.len() <= 256).ok_or(INVALID)
}
fn scalar(v: &Value) -> Result<Value> {
    onlyalpha_calculation::product::normalize_scalar(v, 16384).map_err(|_| INVALID)
}
// Only called after the bounded structural parser has checked this tree.
fn normalize_expression(v: &mut Value) -> Result<()> {
    match v["kind"].as_str() {
        Some("COMPARISON") => {
            for side in ["left", "right"] {
                if v[side]["kind"] == "LITERAL" {
                    v[side]["value"] = scalar(&v[side]["value"])?;
                }
            }
        }
        Some("NOT") => normalize_expression(&mut v["operand"])?,
        Some("AND" | "OR") => {
            for child in v["operands"].as_array_mut().ok_or(INVALID)? {
                normalize_expression(child)?;
            }
        }
        _ => return Err(INVALID),
    }
    Ok(())
}
type Variables = BTreeMap<String, BTreeSet<String>>;
fn variable(v: &Value, variables: &Variables) -> Result<()> {
    exact(v, &["kind", "instance_key", "output_name"])?;
    if v["kind"] != "VARIABLE"
        || !variables
            .get(name(&v["instance_key"])?)
            .is_some_and(|outputs| {
                v["output_name"]
                    .as_str()
                    .is_some_and(|s| outputs.contains(s))
            })
    {
        return Err(INVALID);
    }
    Ok(())
}
fn operand(v: &Value, variables: &Variables) -> Result<()> {
    match v["kind"].as_str() {
        Some("VARIABLE") => variable(v, variables),
        Some("DATASET_FIELD") => {
            exact(v, &["kind", "field_name"])?;
            // Dataset types are checked by the exact research resolver before execution.
            name(&v["field_name"])?;
            Ok(())
        }
        Some("LITERAL") => {
            exact(v, &["kind", "data_type", "value"])?;
            if !["DECIMAL", "INTEGER", "BOOLEAN", "STRING"].contains(&name(&v["data_type"])?)
                || v["data_type"] != v["value"]["type"]
            {
                return Err(INVALID);
            }
            scalar(&v["value"]).map(|_| ())
        }
        _ => Err(INVALID),
    }
}
fn expression(v: &Value, variables: &Variables, depth: usize) -> Result<()> {
    if depth > 32 {
        return Err(INVALID);
    }
    match v["kind"].as_str() {
        Some("COMPARISON") => {
            exact(v, &["kind", "operator", "left", "right"])?;
            if !["==", "!=", "<", "<=", ">", ">="].contains(&name(&v["operator"])?) {
                return Err(INVALID);
            }
            operand(&v["left"], variables)?;
            operand(&v["right"], variables)
        }
        Some("NOT") => {
            exact(v, &["kind", "operand"])?;
            expression(&v["operand"], variables, depth + 1)
        }
        Some("AND" | "OR") => {
            exact(v, &["kind", "operands"])?;
            let operands = rows(&v["operands"])?;
            if operands.len() < 2 {
                return Err(INVALID);
            }
            for child in operands {
                expression(child, variables, depth + 1)?;
            }
            Ok(())
        }
        _ => Err(INVALID),
    }
}
#[derive(Clone, Debug)]
pub struct Definition(Value);
impl Definition {
    pub fn from_record(v: &Value) -> Result<Self> {
        if v.to_string().len() > LIMIT {
            return Err(INVALID);
        }
        exact(
            v,
            &[
                "schema_version",
                "universe",
                "market_input",
                "calculations",
                "factor_revision_dependencies",
                "eligibility",
                "signals",
            ],
        )?;
        if v["schema_version"] != 1 {
            return Err(INVALID);
        }
        let mut record = v.clone();
        exact(&record["universe"], &["kind", "instruments"])?;
        let universe = rows(&record["universe"]["instruments"])?;
        let mut instruments = BTreeSet::new();
        for id in universe {
            let parsed: OnlyInstrumentId = name(id)?.parse().map_err(|_| INVALID)?;
            if !instruments.insert(parsed.to_string()) {
                return Err(INVALID);
            }
        }
        if instruments.is_empty()
            || record["universe"]["kind"]
                != if instruments.len() == 1 {
                    "SINGLE_INSTRUMENT"
                } else {
                    "EXPLICIT_INSTRUMENT_SET"
                }
        {
            return Err(INVALID);
        }
        record["universe"]["instruments"] = json!(instruments);
        let market = &record["market_input"];
        exact(
            market,
            &[
                "schema_version",
                "data_kind",
                "bar_semantic",
                "construction_requirement",
                "observation_admission",
            ],
        )?;
        if market["schema_version"] != 2
            || market["data_kind"] != "BAR"
            || market["observation_admission"] != "FINAL_ONLY"
        {
            return Err(INVALID);
        }
        let semantic =
            OnlyBarSemantic::from_record(&market["bar_semantic"]).map_err(|_| INVALID)?;
        let requirement = &market["construction_requirement"];
        exact(requirement, &["schema_version", "kind", "policy", "recipe"])?;
        if requirement["schema_version"] != 1
            || requirement["kind"] != "EXACT_RECIPE"
            || !requirement["policy"].is_null()
        {
            return Err(INVALID);
        }
        let recipe =
            OnlyConstructionRecipe::from_record(&requirement["recipe"]).map_err(|_| INVALID)?;
        if recipe.target() != &semantic {
            return Err(INVALID);
        }
        let calculations = rows(&record["calculations"])?;
        if calculations.is_empty() {
            return Err(INVALID);
        }
        let mut variables = Variables::new();
        let mut private = BTreeSet::new();
        for c in calculations {
            exact(
                c,
                &[
                    "instance_key",
                    "type_reference",
                    "parameters",
                    "published_outputs",
                    "input_bindings",
                    "primary_output",
                ],
            )?;
            exact(
                &c["type_reference"],
                &["kind", "type_id", "semantic_version"],
            )?;
            let t = &c["type_reference"];
            let reference = TypeReference::new(
                name(&t["kind"])?,
                name(&t["type_id"])?,
                name(&t["semantic_version"])?,
            )
            .map_err(|_| INVALID)?;
            if !["INDICATOR", "FACTOR"].contains(&reference.kind()) {
                return Err(INVALID);
            }
            if reference.type_id().starts_with("private.factor.") {
                if reference.kind() != "FACTOR" {
                    return Err(INVALID);
                }
                crate::application::private_assets::authoring::validate_id(reference.type_id())
                    .map_err(|_| INVALID)?;
                private.insert(reference.type_id().to_owned());
            }
            let parameters = c["parameters"].as_object().ok_or(INVALID)?;
            for (key, p) in parameters {
                name(&json!(key))?;
                exact(p, &["kind", "value"])?;
                if p["kind"] != "FIXED" {
                    return Err(INVALID);
                }
                scalar(&p["value"])?;
            }
            let outputs = rows(&c["published_outputs"])?;
            let mut unique = BTreeSet::new();
            for output in outputs {
                if !unique.insert(name(output)?.to_owned()) {
                    return Err(INVALID);
                }
            }
            if unique.is_empty()
                || (!c["primary_output"].is_null() && !unique.contains(name(&c["primary_output"])?))
                || variables
                    .insert(name(&c["instance_key"])?.to_owned(), unique)
                    .is_some()
            {
                return Err(INVALID);
            }
        }
        // Exact reference closure is checked before any resolver/algorithm is selected.
        let mut edges = BTreeMap::<String, BTreeSet<String>>::new();
        for c in calculations {
            let mut input_names = BTreeSet::new();
            let mut parents = BTreeSet::new();
            for binding in rows(&c["input_bindings"])? {
                exact(binding, &["input_name", "source"])?;
                if !input_names.insert(name(&binding["input_name"])?) {
                    return Err(INVALID);
                }
                if binding["source"].is_string() {
                    name(&binding["source"])?;
                } else {
                    variable(&binding["source"], &variables)?;
                    parents.insert(name(&binding["source"]["instance_key"])?.to_owned());
                }
            }
            edges.insert(name(&c["instance_key"])?.to_owned(), parents);
        }
        while !edges.is_empty() {
            let ready: BTreeSet<_> = edges
                .iter()
                .filter(|(_, p)| p.is_empty())
                .map(|(id, _)| id.clone())
                .collect();
            if ready.is_empty() {
                return Err(INVALID);
            }
            edges.retain(|id, _| !ready.contains(id));
            for parents in edges.values_mut() {
                parents.retain(|id| !ready.contains(id));
            }
        }
        let mut dependencies = BTreeMap::new();
        for d in rows(&record["factor_revision_dependencies"])? {
            exact(d, &["factor_id", "revision_fingerprint"])?;
            let id = name(&d["factor_id"])?;
            crate::application::private_assets::authoring::validate_id(id).map_err(|_| INVALID)?;
            if !name(&d["revision_fingerprint"]).is_ok_and(crate::is_sha256_hex)
                || dependencies.insert(id.to_owned(), d.clone()).is_some()
            {
                return Err(INVALID);
            }
        }
        if dependencies.keys().ne(private.iter()) {
            return Err(INVALID);
        }
        expression(&record["eligibility"], &variables, 0)?;
        exact(&record["signals"], &["entry", "exit"])?;
        for role in ["entry", "exit"] {
            expression(&record["signals"][role], &variables, 0)?;
        }
        normalize_expression(&mut record["eligibility"])?;
        for role in ["entry", "exit"] {
            normalize_expression(&mut record["signals"][role])?;
        }
        record["factor_revision_dependencies"] = json!(dependencies.values().collect::<Vec<_>>());
        let calculations = record["calculations"].as_array_mut().ok_or(INVALID)?;
        calculations.sort_by(|a, b| a["instance_key"].as_str().cmp(&b["instance_key"].as_str()));
        for c in calculations {
            for p in c["parameters"].as_object_mut().ok_or(INVALID)?.values_mut() {
                p["value"] = scalar(&p["value"])?;
            }
            c["published_outputs"]
                .as_array_mut()
                .ok_or(INVALID)?
                .sort_by(|a, b| a.as_str().cmp(&b.as_str()));
            c["input_bindings"]
                .as_array_mut()
                .ok_or(INVALID)?
                .sort_by(|a, b| a["input_name"].as_str().cmp(&b["input_name"].as_str()));
        }
        if record.to_string().len() > LIMIT {
            return Err(INVALID);
        }
        Ok(Self(record))
    }
    pub fn to_record(&self) -> Value {
        self.0.clone()
    }
    pub fn fingerprint(&self) -> Result<String> {
        let mut record = self.0.clone();
        record["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_DEFINITION_V1");
        hash(&record)
    }
}
/// Mutable authoring input; its published Revision is not a frozen trading Strategy.
#[derive(Clone, Debug)]
pub struct Draft(Value);
impl Draft {
    pub fn new(mut value: Value) -> Result<Self> {
        if value.to_string().len() > LIMIT {
            return Err(INVALID);
        }
        exact(
            &value,
            &[
                "schema_version",
                "strategy_id",
                "semantic_version",
                "base_revision_fingerprint",
                "definition",
                "description",
                "tags",
            ],
        )?;
        if value["schema_version"] != 1 {
            return Err(INVALID);
        }
        crate::application::private_assets::id(name(&value["strategy_id"])?, "STRATEGY")
            .map_err(|_| INVALID)?;
        let version = name(&value["semantic_version"])?;
        if version.starts_with('0') || !version.bytes().all(|b| b.is_ascii_digit()) {
            return Err(INVALID);
        }
        if !value["base_revision_fingerprint"].is_null()
            && !name(&value["base_revision_fingerprint"]).is_ok_and(crate::is_sha256_hex)
        {
            return Err(INVALID);
        }
        if value["description"]
            .as_str()
            .is_none_or(|s| s.len() > 8000 || s.contains('\0'))
        {
            return Err(INVALID);
        }
        value["definition"] = Definition::from_record(&value["definition"])?.to_record();
        let mut tags = BTreeSet::new();
        for tag in rows(&value["tags"])? {
            if !tags.insert(name(tag)?.to_owned()) {
                return Err(INVALID);
            }
        }
        value["tags"] = json!(tags);
        let draft = Self(value);
        draft.revision()?;
        Ok(draft)
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn strategy_id(&self) -> &str {
        self.0["strategy_id"]
            .as_str()
            .expect("validated strategy draft")
    }
    pub fn base(&self) -> Option<&str> {
        self.0["base_revision_fingerprint"].as_str()
    }
    pub fn fingerprint(&self) -> Result<String> {
        hash(&json!({"contract":"ONLYALPHA_PRIVATE_STRATEGY_DRAFT_V1","draft":self.0}))
    }
    pub fn revision(&self) -> Result<Value> {
        let mut record = self.0.clone();
        let parent = record
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("base_revision_fingerprint")
            .ok_or(INVALID)?;
        record["parent_revision_fingerprint"] = parent;
        record["definition_fingerprint"] =
            json!(Definition::from_record(&record["definition"])?.fingerprint()?);
        record["contract"] = json!("ONLYALPHA_PRIVATE_STRATEGY_REVISION_V1");
        let fingerprint = hash(&record)?;
        record.as_object_mut().ok_or(INVALID)?.remove("contract");
        record["revision_fingerprint"] = json!(fingerprint);
        crate::application::private_assets::revision("STRATEGY", &record).map_err(|_| INVALID)?;
        Ok(record)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};
    fn definition() -> Value {
        let source: Value = serde_json::from_str(
            include_str!("../../../../test-data/strategy/product-sources-v1.jsonl")
                .lines()
                .next()
                .unwrap(),
        )
        .unwrap();
        let variable = json!({"kind":"VARIABLE","instance_key":"momentum","output_name":"value"});
        let decimal = |n| json!({"kind":"LITERAL","data_type":"DECIMAL","value":{"type":"DECIMAL","value":n}});
        json!({"schema_version":1,"universe":source["record"]["universe"],"market_input":source["record"]["market_input_contract"],
            "calculations":[{"instance_key":"momentum","type_reference":{"kind":"FACTOR","type_id":"private.factor.price_volume","semantic_version":"1"},"parameters":{},"published_outputs":["value"],"input_bindings":[],"primary_output":"value"}],
            "factor_revision_dependencies":[{"factor_id":"private.factor.price_volume","revision_fingerprint":"a".repeat(64)}],
            "eligibility":{"kind":"COMPARISON","operator":">","left":{"kind":"DATASET_FIELD","field_name":"close"},"right":decimal("0")},
            "signals":{"entry":{"kind":"COMPARISON","operator":">=","left":variable,"right":decimal("0.001")},"exit":{"kind":"COMPARISON","operator":"<=","left":variable,"right":decimal("0")}}})
    }
    #[test]
    fn private_strategy_definition_keeps_exact_factor_and_excludes_execution_configuration() {
        let v = definition();
        let parsed = Definition::from_record(&v).unwrap();
        assert_eq!(parsed.to_record(), v);
        let fingerprint = parsed.fingerprint().unwrap();
        let mut changed = v.clone();
        changed["factor_revision_dependencies"][0]["revision_fingerprint"] = json!("b".repeat(64));
        assert_ne!(
            Definition::from_record(&changed)
                .unwrap()
                .fingerprint()
                .unwrap(),
            fingerprint
        );
        for key in ["capital", "fee", "execution", "account"] {
            let mut wrong = v.clone();
            wrong[key] = json!({});
            assert!(Definition::from_record(&wrong).is_err(), "{key}");
        }
    }
    #[test]
    fn private_strategy_definition_rejects_incomplete_or_unbound_decisions() {
        for mode in [
            "empty",
            "sweep",
            "dependency",
            "duplicate-dependency",
            "missing-exit",
            "unknown-variable",
            "unknown-output",
            "literal-type",
            "nonfinite",
            "nonfinal",
            "recipe",
            "extra-signal",
        ] {
            let mut v = definition();
            match mode {
                "empty" => v["calculations"] = json!([]),
                "sweep" => {
                    v["calculations"][0]["parameters"]["window"] =
                        json!({"kind":"SWEEP","values":[20,30]})
                }
                "dependency" => v["factor_revision_dependencies"] = json!([]),
                "duplicate-dependency" => {
                    let row = v["factor_revision_dependencies"][0].clone();
                    v["factor_revision_dependencies"]
                        .as_array_mut()
                        .unwrap()
                        .push(row);
                }
                "missing-exit" => v["signals"]["exit"] = Value::Null,
                "unknown-variable" => {
                    v["signals"]["entry"]["left"]["instance_key"] = json!("unknown")
                }
                "unknown-output" => v["signals"]["entry"]["left"]["output_name"] = json!("absent"),
                "literal-type" => {
                    v["signals"]["entry"]["right"]["value"]["type"] = json!("BOOLEAN")
                }
                "nonfinite" => v["signals"]["entry"]["right"]["value"]["value"] = json!("NaN"),
                "nonfinal" => v["market_input"]["observation_admission"] = json!("PREVIEW"),
                "recipe" => {
                    v["market_input"]["construction_requirement"]["recipe"]["target_semantic"]["price_type"] =
                        json!("MID")
                }
                _ => v["signals"]["unexpected"] = json!(true),
            }
            assert!(Definition::from_record(&v).is_err(), "{mode}");
        }
    }
    #[test]
    fn private_strategy_draft_publishes_only_a_canonical_authoring_revision() {
        let raw = json!({"schema_version":1,"strategy_id":"private.strategy.btc_momentum","semantic_version":"1","base_revision_fingerprint":null,"definition":definition(),"description":"BTC 1 minute momentum","tags":["volume","momentum"]});
        let draft = Draft::new(raw.clone()).unwrap();
        let revision = draft.revision().unwrap();
        assert_eq!(
            revision["definition_fingerprint"],
            Definition::from_record(&definition())
                .unwrap()
                .fingerprint()
                .unwrap()
        );
        assert_eq!(revision["tags"], json!(["momentum", "volume"]));
        assert!(revision.get("base_revision_fingerprint").is_none());
        assert_eq!(revision["parent_revision_fingerprint"], Value::Null);
        assert_ne!(
            draft.fingerprint().unwrap(),
            revision["revision_fingerprint"].as_str().unwrap()
        );
        for (field, value) in [
            ("strategy_id", json!("private.factor.wrong")),
            ("semantic_version", json!("01")),
            ("tags", json!(["a", "a"])),
            ("account", json!("cash")),
            ("description", json!("bad\u{0000}")),
            ("base_revision_fingerprint", json!("missing")),
        ] {
            let mut wrong = raw.clone();
            wrong[field] = value;
            assert!(Draft::new(wrong).is_err(), "{field}");
        }
        let mut next = raw;
        next["base_revision_fingerprint"] = revision["revision_fingerprint"].clone();
        next["semantic_version"] = json!("2");
        assert_eq!(
            Draft::new(next).unwrap().revision().unwrap()["parent_revision_fingerprint"],
            revision["revision_fingerprint"]
        );
    }
    #[test]
    fn private_strategy_definition_rejects_cycles_and_canonicalizes_collection_order() {
        let mut v = definition();
        v["calculations"][0]["input_bindings"] = json!([{"input_name":"close","source":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"}}]);
        assert!(Definition::from_record(&v).is_err());
        let mut v = definition();
        let mut second = v["calculations"][0].clone();
        second["instance_key"] = json!("another");
        v["calculations"].as_array_mut().unwrap().push(second);
        let pin = Definition::from_record(&v).unwrap().fingerprint().unwrap();
        v["calculations"].as_array_mut().unwrap().reverse();
        assert_eq!(
            Definition::from_record(&v).unwrap().fingerprint().unwrap(),
            pin
        );
        v["calculations"][0]["input_bindings"] = json!([{"input_name":"close","source":{"kind":"VARIABLE","instance_key":"unknown","output_name":"value"}}]);
        assert!(Definition::from_record(&v).is_err());
    }
    #[test]
    fn private_strategy_uses_the_calculation_scalar_canonical_identity() {
        for (spelling, expected) in [("1e-3", "0.001"), ("-0.00", "-0.00"), ("0E+2", "0")] {
            let mut v = definition();
            v["signals"]["entry"]["right"]["value"]["value"] = json!(spelling);
            let scalar = onlyalpha_calculation::product::normalize_scalar(
                &v["signals"]["entry"]["right"]["value"],
                4096,
            )
            .unwrap();
            assert_eq!(scalar["value"], expected);
            assert_eq!(
                Definition::from_record(&v).unwrap().to_record()["signals"]["entry"]["right"]["value"],
                scalar
            );
        }
    }
}
