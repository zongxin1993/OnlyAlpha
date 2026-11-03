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
const SOURCE_WORK: usize = 8 * 1024 * 1024;
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_DEFINITION_UNAVAILABLE";
pub(crate) fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        return Err(INVALID);
    }
    Ok(())
}
pub(crate) fn name(v: &Value) -> Result<&str> {
    let value = v.as_str().ok_or(INVALID)?;
    if value.len() > 4096 {
        return Err(UNAVAILABLE);
    }
    if value.is_empty() || value.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return Err(INVALID);
    }
    Ok(value)
}
pub(crate) fn rows(v: &Value) -> Result<&Vec<Value>> {
    let values = v.as_array().ok_or(INVALID)?;
    if values.len() > 4096 {
        return Err(UNAVAILABLE);
    }
    Ok(values)
}
pub(crate) fn scalar(v: &Value, work: &mut usize) -> Result<Value> {
    let normalized = onlyalpha_calculation::product::normalize_scalar(v, *work).map_err(|e| {
        if e == onlyalpha_calculation::product::Error::Unavailable {
            UNAVAILABLE
        } else {
            INVALID
        }
    })?;
    let cost = v
        .to_string()
        .len()
        .checked_add(normalized.to_string().len())
        .ok_or(UNAVAILABLE)?;
    *work = work.checked_sub(cost).ok_or(UNAVAILABLE)?;
    Ok(normalized)
}
pub(crate) type Variables = BTreeMap<String, BTreeSet<String>>;
pub(crate) fn variable(v: &Value, variables: &Variables) -> Result<()> {
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
fn operand(v: &mut Value, variables: &Variables, work: &mut usize) -> Result<()> {
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
            v["value"] = scalar(&v["value"], work)?;
            Ok(())
        }
        _ => Err(INVALID),
    }
}
fn expression(v: &mut Value, variables: &Variables, depth: usize, work: &mut usize) -> Result<()> {
    if depth > 32 {
        return Err(UNAVAILABLE);
    }
    match v["kind"].as_str() {
        Some("COMPARISON") => {
            exact(v, &["kind", "operator", "left", "right"])?;
            if !["==", "!=", "<", "<=", ">", ">="].contains(&name(&v["operator"])?) {
                return Err(INVALID);
            }
            operand(&mut v["left"], variables, work)?;
            operand(&mut v["right"], variables, work)
        }
        Some("NOT") => {
            exact(v, &["kind", "operand"])?;
            expression(&mut v["operand"], variables, depth + 1, work)
        }
        Some("AND" | "OR") => {
            exact(v, &["kind", "operands"])?;
            if rows(&v["operands"])?.len() < 2 {
                return Err(INVALID);
            }
            for child in v["operands"].as_array_mut().ok_or(INVALID)? {
                expression(child, variables, depth + 1, work)?;
            }
            Ok(())
        }
        _ => Err(INVALID),
    }
}
pub(crate) fn normalize_instances(
    values: &mut Value,
    kinds: &[&str],
    work: &mut usize,
) -> Result<(Variables, BTreeSet<String>)> {
    let calculations = values.as_array_mut().ok_or(INVALID)?;
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
        let instance_key = name(&c["instance_key"])?.to_owned();
        if !instance_key
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_lowercase)
            || !instance_key
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
        {
            return Err(INVALID);
        }
        let t = &c["type_reference"];
        let reference = TypeReference::new(
            name(&t["kind"])?,
            name(&t["type_id"])?,
            name(&t["semantic_version"])?,
        )
        .map_err(|_| INVALID)?;
        if !kinds.contains(&reference.kind()) {
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
        let parameters = c["parameters"].as_object_mut().ok_or(INVALID)?;
        for (key, p) in parameters {
            name(&json!(key))?;
            exact(p, &["kind", "value"])?;
            if p["kind"] != "FIXED" {
                return Err(INVALID);
            }
            p["value"] = scalar(&p["value"], work)?;
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
            || variables.insert(instance_key, unique).is_some()
        {
            return Err(INVALID);
        }
    }
    let calculations = values.as_array_mut().ok_or(INVALID)?;
    calculations.sort_by(|a, b| a["instance_key"].as_str().cmp(&b["instance_key"].as_str()));
    for c in calculations {
        let mut inputs = BTreeSet::new();
        for binding in rows(&c["input_bindings"])? {
            exact(binding, &["input_name", "source"])?;
            if !inputs.insert(name(&binding["input_name"])?) {
                return Err(INVALID);
            }
            if binding["source"].is_string() {
                name(&binding["source"])?;
            } else {
                let source = &binding["source"];
                exact(source, &["kind", "instance_key", "output_name"])?;
                if source["kind"] != "VARIABLE" {
                    return Err(INVALID);
                }
                name(&source["instance_key"])?;
                name(&source["output_name"])?;
            }
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
    Ok((variables, private))
}
pub(crate) fn validate_instances(calculations: &[Value], variables: &Variables) -> Result<()> {
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
                variable(&binding["source"], variables)?;
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
    Ok(())
}
#[derive(Clone, Debug)]
pub struct Definition(Value);
impl Definition {
    /// Derive authoring defaults from the exact compiled Factor graph. This
    /// value carries no Human confirmation, publication or execution grant.
    pub(crate) fn from_compiled_factor(
        factor: &crate::application::research_factor::CompiledFactor,
        universe: Value,
        market_input: Value,
    ) -> Result<Self> {
        let nodes=factor.graph().ordered_nodes().collect::<Vec<_>>();
        let names=nodes.iter().enumerate().map(|(index,node)| {
            let id=node.fingerprint();
            let key=if id==factor.root_fingerprint() {"momentum".to_owned()} else {format!("input_{index}")};
            (id,key)
        }).collect::<BTreeMap<_,_>>();
        let mut calculations=Vec::with_capacity(nodes.len());
        let mut dependency=None;
        for node in nodes {
            let record=node.to_record();
            let id=node.fingerprint();
            let mut bindings=Vec::new();
            for (input,binding) in record["input_bindings"].as_object().ok_or(INVALID)? {
                let source=if let Some(parent)=binding["node_fingerprint"].as_str() {
                    if !binding["source"].is_null() {return Err(INVALID);}
                    json!({"kind":"VARIABLE","instance_key":names.get(parent).ok_or(INVALID)?,"output_name":binding["output_name"]})
                } else {
                    let field=binding["source"].as_str().ok_or(INVALID)?;
                    if !["open","high","low","close","volume"].contains(&field) {return Err(INVALID);}
                    json!(format!("bar.{field}"))
                };
                bindings.push(json!({"input_name":input,"source":source}));
            }
            let parameters=record["parameters"].as_object().ok_or(INVALID)?.iter()
                .map(|(key,value)|(key.clone(),json!({"kind":"FIXED","value":value}))).collect::<BTreeMap<_,_>>();
            let outputs=record["outputs"].as_array().ok_or(INVALID)?.iter()
                .map(|output|output["name"].clone()).collect::<Vec<_>>();
            if id==factor.root_fingerprint() {
                if record["kind"]!="FACTOR" || outputs!=vec![json!("value")] {return Err(INVALID);}
                dependency=Some(json!({"factor_id":record["type_id"],"revision_fingerprint":factor.revision_fingerprint()}));
            } else if record["kind"]!="INDICATOR" {return Err(INVALID);}
            calculations.push(json!({"instance_key":names.get(&id).ok_or(INVALID)?,
                "type_reference":{"kind":record["kind"],"type_id":record["type_id"],"semantic_version":record["semantic_version"]},
                "parameters":parameters,"published_outputs":outputs,"primary_output":"value","input_bindings":bindings}));
        }
        let literal=|value|json!({"kind":"LITERAL","data_type":"DECIMAL","value":{"type":"DECIMAL","value":value}});
        let variable=json!({"kind":"VARIABLE","instance_key":"momentum","output_name":"value"});
        Self::from_record(&json!({"schema_version":1,"universe":universe,"market_input":market_input,
            "calculations":calculations,"factor_revision_dependencies":[dependency.ok_or(INVALID)?],
            "eligibility":{"kind":"COMPARISON","operator":">","left":{"kind":"DATASET_FIELD","field_name":"close"},"right":literal("0")},
            "signals":{"entry":{"kind":"COMPARISON","operator":">=","left":variable,"right":literal("0.001")},
                "exit":{"kind":"COMPARISON","operator":"<=","left":variable,"right":literal("0")}}}))
    }
    pub fn from_record(v: &Value) -> Result<Self> {
        if v.to_string().len() > SOURCE_WORK {
            return Err(UNAVAILABLE);
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
        if rows(&record["calculations"])?.is_empty() {
            return Err(INVALID);
        }
        let mut work = SOURCE_WORK;
        let (variables, private) = normalize_instances(
            &mut record["calculations"],
            &["INDICATOR", "FACTOR"],
            &mut work,
        )?;
        validate_instances(rows(&record["calculations"])?, &variables)?;
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
        expression(&mut record["eligibility"], &variables, 0, &mut work)?;
        exact(&record["signals"], &["entry", "exit"])?;
        for role in ["entry", "exit"] {
            expression(&mut record["signals"][role], &variables, 0, &mut work)?;
        }
        record["factor_revision_dependencies"] = json!(dependencies.values().collect::<Vec<_>>());
        if record.to_string().len() > SOURCE_WORK {
            return Err(UNAVAILABLE);
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
        if value.to_string().len() > LIMIT {
            return Err(INVALID);
        }
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
    #[test]
    fn strategy_draft_derivation_uses_exact_compiled_factor_dependencies_and_periods() {
        let fixture:Value=serde_json::from_str(include_str!("../../tests/application/fixtures/research_factor.json")).unwrap();
        let compiled=crate::application::research_factor::compile(&fixture["candidate"],&fixture["draft"],&fixture["revision"]).unwrap();
        let reference=definition();
        let derived=Definition::from_compiled_factor(&compiled,reference["universe"].clone(),reference["market_input"].clone()).unwrap().to_record();
        assert_eq!(derived["factor_revision_dependencies"],json!([{"factor_id":fixture["revision"]["factor_id"],"revision_fingerprint":fixture["revision"]["revision_fingerprint"]}]));
        let instances=derived["calculations"].as_array().unwrap();
        assert_eq!(instances.len(),compiled.graph().ordered_nodes().count());
        let root=instances.iter().find(|v|v["instance_key"]=="momentum").unwrap();
        assert_eq!(root["type_reference"]["type_id"],fixture["revision"]["factor_id"]);
        assert_eq!(root["parameters"]["literal_1"],json!({"kind":"FIXED","value":{"type":"DECIMAL","value":"1"}}));
        assert_eq!(root["input_bindings"].as_array().unwrap().len(),4);
        for name in ["onlyalpha.operator.delay","onlyalpha.operator.rolling_mean"] {
            let dependency=instances.iter().find(|v|v["type_reference"]["type_id"]==name).unwrap();
            assert_eq!(dependency["parameters"]["period"],json!({"kind":"FIXED","value":{"type":"INTEGER","value":20}}));
        }
        assert_eq!(derived["signals"]["entry"]["left"],json!({"kind":"VARIABLE","instance_key":"momentum","output_name":"value"}));
        assert_eq!(derived["signals"]["entry"]["right"]["value"]["value"],"0.001");
        assert_eq!(derived["signals"]["exit"]["right"]["value"]["value"],"0");
        assert!(derived.get("quantity").is_none());
        let mut candidate=fixture["candidate"].clone();
        candidate["expression"]["left"]["left"]["right"]["lag"]=json!(7);
        candidate["expression"]["right"]["right"]["mean"]=json!(9);
        let preview=crate::application::factor_content::preview(&candidate,"private.factor.exact_periods").unwrap();
        let revision=crate::application::private_assets::authoring::Draft::new(preview["draft"].clone()).unwrap().revision().unwrap();
        let changed=crate::application::research_factor::compile(&candidate,&preview["draft"],&revision).unwrap();
        let derived=Definition::from_compiled_factor(&changed,reference["universe"].clone(),reference["market_input"].clone()).unwrap().to_record();
        for (name,period) in [("onlyalpha.operator.delay",7),("onlyalpha.operator.rolling_mean",9)] {
            let row=derived["calculations"].as_array().unwrap().iter().find(|v|v["type_reference"]["type_id"]==name).unwrap();
            assert_eq!(row["parameters"]["period"]["value"]["value"],period);
        }
    }
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
    fn strategy_calculation_instance_names_follow_the_public_authoring_contract() {
        for bad in ["Momentum", "1momentum", "with.dot", "量"] {
            let mut value = definition();
            value["calculations"][0]["instance_key"] = json!(bad);
            for role in ["entry", "exit"] {
                value["signals"][role]["left"]["instance_key"] = json!(bad);
            }
            assert!(Definition::from_record(&value).is_err(), "accepted {bad}");
        }
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
    #[test]
    fn private_strategy_source_capacity_is_not_corruption_or_runtime_admission() {
        let mut wide = definition();
        let original = wide["calculations"][0].clone();
        for i in 0..256 {
            let mut row = original.clone();
            row["instance_key"] = json!(format!("node_{i}"));
            wide["calculations"].as_array_mut().unwrap().push(row);
        }
        assert!(Definition::from_record(&wide).is_ok());
        let mut large = definition();
        let key = "x".repeat(4097);
        large["calculations"][0]["instance_key"] = json!(key);
        for role in ["entry", "exit"] {
            large["signals"][role]["left"]["instance_key"] = json!(key);
        }
        assert_eq!(
            Definition::from_record(&large).err(),
            Some("PRIVATE_STRATEGY_DEFINITION_UNAVAILABLE")
        );
    }
    #[test]
    fn public_strategy_seed_uses_the_same_native_authoring_contract() {
        let seed: Value = serde_json::from_str(include_str!(
            "../../../../examples/private-assets/strategy/simple_momentum/strategy.json"
        ))
        .unwrap();
        let mut value = seed["strategy"].clone();
        value["definition"]["factor_revision_dependencies"] = json!([{"factor_id":"private.factor.simple_momentum","revision_fingerprint":"a".repeat(64)}]);
        value["schema_version"] = json!(1);
        value["base_revision_fingerprint"] = Value::Null;
        value["description"] = seed["description"].clone();
        let draft = Draft::new(value).unwrap();
        let revision = draft.revision().unwrap();
        crate::application::private_assets::revision("STRATEGY", &revision).unwrap();
        assert_eq!(revision["strategy_id"], "private.strategy.simple_momentum");
        assert!(revision.get("strategy_fingerprint").is_none());
    }
    #[test]
    fn strategy_authoring_api_has_closed_dtos_and_implemented_human_routes() {
        use crate::transport::{
            routes::{Operation, operation},
            wire::{PrivateStrategyRevisionDto, SavePrivateStrategyDraftDto},
        };
        let draft = json!({"schema_version":1,"strategy_id":"private.strategy.btc","semantic_version":"1","base_revision_fingerprint":null,"definition":definition(),"description":"BTC momentum","tags":[]});
        let body = json!({"draft":draft,"expected_draft_fingerprint":null});
        assert!(serde_json::from_value::<SavePrivateStrategyDraftDto>(body.clone()).is_ok());
        let mut missing = body.clone();
        missing
            .as_object_mut()
            .unwrap()
            .remove("expected_draft_fingerprint");
        assert!(serde_json::from_value::<SavePrivateStrategyDraftDto>(missing).is_err());
        let mut extra = body.clone();
        extra["draft"]["account"] = json!("cash");
        assert!(serde_json::from_value::<SavePrivateStrategyDraftDto>(extra).is_err());
        let revision = Draft::new(draft).unwrap().revision().unwrap();
        assert!(serde_json::from_value::<PrivateStrategyRevisionDto>(revision.clone()).is_ok());
        let mut extra = revision;
        extra["runtime"] = json!("BACKTEST");
        assert!(serde_json::from_value::<PrivateStrategyRevisionDto>(extra).is_err());
        for (method, path) in [
            (http::Method::GET, "/api/v2/private-assets/strategies"),
            (
                http::Method::GET,
                "/api/v2/private-assets/strategies/private.strategy.btc",
            ),
            (
                http::Method::PUT,
                "/api/v2/private-assets/strategies/private.strategy.btc/draft",
            ),
            (
                http::Method::POST,
                "/api/v2/private-assets/strategies/private.strategy.btc/revisions",
            ),
            (
                http::Method::GET,
                "/api/v2/private-assets/strategies/private.strategy.btc/commands/id",
            ),
            (
                http::Method::GET,
                "/api/v2/private-assets/strategies/private.strategy.btc/revisions/exact",
            ),
        ] {
            assert_eq!(
                operation(&method, path),
                Some(Operation::Implemented),
                "{path}"
            );
        }
    }
}
