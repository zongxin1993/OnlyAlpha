use crate::model::*;
use bigdecimal::{BigDecimal, Zero};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug)]
pub struct Catalog {
    pub(crate) value: Value,
}
#[derive(Clone, Debug)]
pub struct Binding {
    pub(crate) value: Value,
}
#[derive(Clone, Debug)]
pub struct Assessment {
    pub(crate) value: Value,
}
impl Binding {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.value)
    }
}
impl Assessment {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
}
fn schedule_key(s: &Value) -> String {
    format!(
        "{}:{}",
        s["namespace"].as_str().unwrap_or(""),
        s["family"].as_str().unwrap_or("")
    )
}
fn validate_rule(r: &Value, namespace: &Value) -> Result<(), Error> {
    fields(
        r,
        &[
            "id",
            "type",
            "authority",
            "direction",
            "scope",
            "resolution",
            "terms",
            "minimum",
            "maximum",
            "quantum",
            "rounding",
            "pipeline",
            "side",
            "offset",
            "liquidity",
        ],
    )?;
    text(&r["id"])?;
    use onlyalpha_domain::fee::{OnlyFeeAuthority, OnlyFeeType};
    use std::str::FromStr;
    OnlyFeeType::from_str(text(&r["type"])?).map_err(|e| Error(e.to_string()))?;
    OnlyFeeAuthority::from_str(text(&r["authority"])?).map_err(|e| Error(e.to_string()))?;
    let broker = matches!(text(&r["authority"])?, "BROKER" | "PLATFORM");
    if broker != (namespace == "BROKER") {
        return Err(err("FEE_SCHEDULE_AUTHORITY"));
    }
    one(&r["direction"], &["CHARGE", "REBATE"])?;
    one(&r["scope"], &["FILL", "ORDER_CUMULATIVE"])?;
    one(&r["resolution"], &["ORDER_FIXED", "FILL_EFFECTIVE"])?;
    one(
        &r["rounding"],
        &["HALF_EVEN", "HALF_UP", "CEILING", "FLOOR"],
    )?;
    one(&r["pipeline"], &["BOUNDS_THEN_ROUND", "ROUND_THEN_BOUNDS"])?;
    if num(&r["quantum"])?.is_zero() {
        return Err(err("FEE_QUANTUM"));
    }
    for k in ["minimum", "maximum"] {
        if !r[k].is_null() {
            num(&r[k])?;
        }
    }
    if !r["minimum"].is_null()
        && !r["maximum"].is_null()
        && num(&r["minimum"])? > num(&r["maximum"])?
    {
        return Err(err("FEE_BOUNDS"));
    }
    for (k, allowed) in [
        ("side", &["BUY", "SELL"][..]),
        (
            "offset",
            &["OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"][..],
        ),
        ("liquidity", &["MAKER", "TAKER"][..]),
    ] {
        if !r[k].is_null() {
            one(&r[k], allowed)?;
        }
    }
    let terms = array(&r["terms"])?;
    if terms.is_empty() {
        return Err(err("FEE_FORMULA_EMPTY"));
    }
    for t in terms {
        if t["kind"] == "FIXED" {
            fields(t, &["kind", "amount"])?;
        } else {
            fields(t, &["kind", "basis", "amount"])?;
            one(&t["kind"], &["RATE", "PER_UNIT"])?;
            one(&t["basis"], &["NOTIONAL", "QUANTITY", "CONTRACTS"])?;
        }
        num(&t["amount"])?;
    }
    Ok(())
}
impl Catalog {
    pub fn new(mut value: Value) -> Result<Self, Error> {
        bound(&value, 0)?;
        fields(
            &value,
            &[
                "schema_version",
                "market_pack",
                "broker_contract",
                "schedules",
            ],
        )?;
        if let Some(schedules) = value["schedules"].as_array_mut() {
            for s in schedules.iter_mut() {
                if !s.is_object() {
                    return Err(err("FEE_RECORD"));
                }
                if let Some(rules) = s["rules"].as_array_mut() {
                    for r in rules.iter_mut() {
                        if !r.is_object() {
                            return Err(err("FEE_RECORD"));
                        }
                        for k in ["minimum", "maximum", "quantum"] {
                            if !r[k].is_null() {
                                r[k] = json!(num(&r[k])?.normalized().to_plain_string());
                            }
                        }
                        if let Some(terms) = r["terms"].as_array_mut() {
                            for t in terms.iter_mut() {
                                if !t.is_object() {
                                    return Err(err("FEE_RECORD"));
                                }
                                t["amount"] =
                                    json!(num(&t["amount"])?.normalized().to_plain_string());
                            }
                            terms.sort_by_key(Value::to_string);
                        }
                    }
                    rules.sort_by_key(|r| r["id"].to_string());
                }
            }
            schedules.sort_by_key(|s| format!("{}:{}", schedule_key(s), s["version"]));
        }
        for k in ["market_pack", "broker_contract"] {
            if !value[k].is_object() {
                return Err(err("FEE_RECORD"));
            }
            if let Some(f) = value[k]["families"].as_array_mut() {
                f.sort_by_key(Value::to_string);
            }
        }
        fields(
            &value,
            &[
                "schema_version",
                "market_pack",
                "broker_contract",
                "schedules",
            ],
        )?;
        if value["schema_version"] != 1 {
            return Err(err("FEE_SCHEMA"));
        }
        fields(&value["market_pack"], &["id", "version", "families"])?;
        fields(
            &value["broker_contract"],
            &["id", "version", "broker", "account", "families"],
        )?;
        for source in [&value["market_pack"], &value["broker_contract"]] {
            text(&source["id"])?;
            text(&source["version"])?;
            let a = array(&source["families"])?;
            if a.is_empty() {
                return Err(err("FEE_AUTHORITY_MISSING"));
            }
            let mut ids = BTreeSet::new();
            for x in a {
                if !ids.insert(text(x)?) {
                    return Err(err("FEE_FAMILY_DUPLICATE"));
                }
            }
        }
        text(&value["broker_contract"]["broker"])?;
        text(&value["broker_contract"]["account"])?;
        let mut versions = BTreeSet::new();
        let mut scopes = BTreeMap::new();
        let mut policies = BTreeMap::new();
        for s in array(&value["schedules"])? {
            fields(
                s,
                &[
                    "namespace",
                    "family",
                    "version",
                    "from",
                    "to",
                    "scope",
                    "rules",
                ],
            )?;
            one(&s["namespace"], &["MARKET", "BROKER"])?;
            text(&s["family"])?;
            text(&s["version"])?;
            let start = unsigned(&s["from"])?;
            if !s["to"].is_null() && unsigned(&s["to"])? <= start {
                return Err(err("FEE_EFFECTIVE_RANGE"));
            }
            if s["namespace"] == "MARKET" {
                fields(
                    &s["scope"],
                    &["market", "venue", "instrument_class", "currency"],
                )?;
            } else {
                fields(&s["scope"], &["broker", "account", "currency"])?;
            }
            for x in s["scope"].as_object().expect("object").values() {
                text(x)?;
            }
            let key = schedule_key(s);
            if !versions.insert((key.clone(), text(&s["version"])?)) {
                return Err(err("FEE_VERSION_DUPLICATE"));
            }
            if scopes
                .insert(key.clone(), s["scope"].clone())
                .is_some_and(|old| old != s["scope"])
            {
                return Err(err("FEE_FAMILY_SCOPE_DRIFT"));
            }
            let rules = array(&s["rules"])?;
            if rules.is_empty() {
                return Err(err("FEE_RULES_EMPTY"));
            }
            let mut ids = BTreeSet::new();
            for r in rules {
                validate_rule(r, &s["namespace"])?;
                if !ids.insert(text(&r["id"])?) {
                    return Err(err("FEE_RULE_DUPLICATE"));
                }
                if r["resolution"] != rules[0]["resolution"] {
                    return Err(err("FEE_MIXED_RESOLUTION"));
                }
            }
            if policies
                .insert(key, rules[0]["resolution"].clone())
                .is_some_and(|p| p != rules[0]["resolution"])
            {
                return Err(err("FEE_FAMILY_RESOLUTION_DRIFT"));
            }
        }
        Ok(Self { value })
    }
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    fn selected(&self, scope: &Value, day: u64) -> Result<Vec<Value>, Error> {
        let mut result = Vec::new();
        for (namespace, source) in [
            ("MARKET", &self.value["market_pack"]),
            ("BROKER", &self.value["broker_contract"]),
        ] {
            for family in array(&source["families"])? {
                let mut matches = Vec::new();
                for s in array(&self.value["schedules"])? {
                    if s["namespace"] != namespace || s["family"] != *family {
                        continue;
                    }
                    if s["scope"].as_object().expect("scope").iter().any(|(k, x)| {
                        *x != if k == "currency" {
                            scope["currency"]["code"].clone()
                        } else {
                            scope[k].clone()
                        }
                    }) {
                        continue;
                    }
                    if unsigned(&s["from"])? <= day
                        && (s["to"].is_null() || day < unsigned(&s["to"])?)
                    {
                        matches.push(s.clone());
                    }
                }
                if matches.len() != 1 {
                    return Err(err("FEE_SCHEDULE_NOT_UNIQUE"));
                }
                result.push(matches.remove(0));
            }
        }
        Ok(result)
    }
    pub fn bind(&self, subject: Value, day: u64) -> Result<Binding, Error> {
        scope(&subject)?;
        if subject["account"] != self.value["broker_contract"]["account"]
            || subject["broker"] != self.value["broker_contract"]["broker"]
        {
            return Err(err("FEE_BROKER_ACCOUNT_SCOPE"));
        }
        self.selected(&subject, day)?;
        Ok(Binding {
            value: json!({"schema_version":1,"catalog":self.value,"subject":subject,"day":day}),
        })
    }
    pub(crate) fn read_binding(v: &Value) -> Result<Binding, Error> {
        fields(v, &["schema_version", "catalog", "subject", "day"])?;
        let b =
            Self::new(v["catalog"].clone())?.bind(v["subject"].clone(), unsigned(&v["day"])?)?;
        if b.value != *v {
            return Err(err("FEE_BINDING"));
        }
        Ok(b)
    }
    fn resolved(&self, b: &Binding, day: u64) -> Result<Vec<Value>, Error> {
        let old = Self::new(b.value["catalog"].clone())?;
        for k in ["market_pack", "broker_contract"] {
            if self.value[k] != old.value[k] {
                return Err(err("FEE_BOUND_AUTHORITY_CHANGED"));
            }
        }
        for previous in array(&old.value["schedules"])? {
            if array(&self.value["schedules"])?.iter().any(|current| {
                schedule_key(current) == schedule_key(previous)
                    && current["version"] == previous["version"]
                    && current != previous
            }) {
                return Err(err("FEE_VERSION_CONTENT_CONFLICT"));
            }
        }
        let original = old.selected(&b.value["subject"], unsigned(&b.value["day"])?)?;
        let mut result = Vec::new();
        for s in original {
            let effective = s["rules"][0]["resolution"] == "FILL_EFFECTIVE";
            let selected = if effective {
                let mut single = self.clone();
                for k in ["market_pack", "broker_contract"] {
                    single.value[k]["families"] =
                        if (k == "market_pack") == (s["namespace"] == "MARKET") {
                            json!([s["family"]])
                        } else {
                            json!([])
                        };
                }
                let matches = single.selected(&b.value["subject"], day)?;
                let n = matches.first().ok_or_else(|| err("FEE_FAMILY_MISSING"))?;
                if n["scope"] != s["scope"] || n["rules"][0]["resolution"] != "FILL_EFFECTIVE" {
                    return Err(err("FEE_FAMILY_SCOPE_DRIFT"));
                }
                n.clone()
            } else {
                s
            };
            result.push(selected);
        }
        Ok(result)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn assess(
        &self,
        b: &Binding,
        day: u64,
        trade: &str,
        time: impl Into<bigdecimal::num_bigint::BigInt>,
        fill: Value,
        cumulative: Value,
        liquidity: Option<&str>,
    ) -> Result<Assessment, Error> {
        let time = instant_record(time.into())?;
        text(&json!(trade))?;
        if let Some(l) = liquidity {
            one(&json!(l), &["MAKER", "TAKER"])?;
        }
        let precision = currency(&b.value["subject"]["currency"])?;
        for values in [&fill, &cumulative] {
            fields(values, &["notional", "quantity", "contracts", "currency"])?;
            for k in ["notional", "quantity"] {
                num(&values[k])?;
            }
            if !values["contracts"].is_null() {
                num(&values["contracts"])?;
            }
            if values["currency"] != b.value["subject"]["currency"]["code"] {
                return Err(err("FEE_FX_UNSUPPORTED"));
            }
        }
        let mut components = Vec::new();
        for s in self.resolved(b, day)? {
            for r in array(&s["rules"])? {
                let subject = &b.value["subject"];
                if !applies_to_subject(r, subject) {
                    continue;
                }
                if !r["liquidity"].is_null() {
                    let role = liquidity.ok_or_else(|| err("FEE_LIQUIDITY_REQUIRED"))?;
                    if r["liquidity"] != role {
                        continue;
                    }
                }
                let values = if r["scope"] == "FILL" {
                    &fill
                } else {
                    &cumulative
                };
                let mut raw = BigDecimal::zero();
                for t in array(&r["terms"])? {
                    let base = if t["kind"] == "FIXED" {
                        BigDecimal::from(1)
                    } else {
                        let key = match text(&t["basis"])? {
                            "NOTIONAL" => "notional",
                            "QUANTITY" => "quantity",
                            _ => "contracts",
                        };
                        if values[key].is_null() {
                            return Err(err("FEE_BASIS_UNSUPPORTED"));
                        }
                        num(&values[key])?
                    };
                    raw += base * num(&t["amount"])?;
                }
                let bounds = |mut n: BigDecimal| -> Result<BigDecimal, Error> {
                    if !r["minimum"].is_null() {
                        n = n.max(num(&r["minimum"])?);
                    }
                    if !r["maximum"].is_null() {
                        n = n.min(num(&r["maximum"])?);
                    }
                    Ok(n)
                };
                let q = num(&r["quantum"])?;
                let target = if r["pipeline"] == "BOUNDS_THEN_ROUND" {
                    round(&bounds(raw.clone())?, &q, text(&r["rounding"])?)?
                } else {
                    bounds(round(&raw, &q, text(&r["rounding"])?)?)?
                };
                let monetary = amount(&target, precision)?;
                if num(&monetary)? != target {
                    return Err(err("FEE_MONEY_PRECISION"));
                }
                let identity = json!({"namespace":s["namespace"],"family":s["family"],"version":s["version"],"schedule":digest(&s),"rule":r["id"],"rule_fingerprint":digest(r),"scope":r["scope"],"resolution":r["resolution"],"direction":r["direction"],"type":r["type"],"authority":r["authority"]});
                components.push(
                    json!({"identity":identity,"raw":amount(&raw,precision)?,"target":monetary}),
                );
            }
        }
        if components.is_empty() {
            return Err(err("FEE_NO_MATCHING_RULE"));
        }
        components.sort_by_key(|v| digest(&v["identity"]));
        Ok(Assessment {
            value: json!({"schema_version":1,"catalog":self.value,"binding":b.value,"day":day,"trade":trade,"time":time,"fill":fill,"cumulative":cumulative,"liquidity":liquidity,"components":components}),
        })
    }
    pub(crate) fn read_assessment(v: &Value) -> Result<Assessment, Error> {
        bound(v, 0)?;
        let c = Self::new(v["catalog"].clone())?;
        let b = Self::read_binding(&v["binding"])?;
        let a = c.assess(
            &b,
            unsigned(&v["day"])?,
            text(&v["trade"])?,
            instant(&v["time"])?,
            v["fill"].clone(),
            v["cumulative"].clone(),
            v["liquidity"].as_str(),
        )?;
        if a.value != *v {
            return Err(err("FEE_ASSESSMENT_CONFLICT"));
        }
        Ok(a)
    }
    pub fn estimate(
        &self,
        b: &Binding,
        day: u64,
        expected_basis: Value,
        full_basis: Value,
        expected_count: u64,
        maximum_count: Option<u64>,
    ) -> Result<Value, Error> {
        if expected_count == 0
            || expected_count > 4096
            || maximum_count.is_some_and(|n| n < expected_count || n > 4096)
        {
            return Err(err("FEE_ESTIMATE_COUNT"));
        }
        let schedules = self.resolved(b, day)?;
        if schedules
            .iter()
            .flat_map(|s| s["rules"].as_array().expect("rules"))
            .any(|r| applies_to_subject(r, &b.value["subject"]) && !r["liquidity"].is_null())
        {
            return Err(err("FEE_ESTIMATE_LIQUIDITY_REQUIRED"));
        }
        let split = schedules
            .iter()
            .flat_map(|s| s["rules"].as_array().expect("rules"))
            .any(|r| applies_to_subject(r, &b.value["subject"]) && split_sensitive(r));
        if split && maximum_count.is_none() {
            return Err(err("FEE_ESTIMATE_MAXIMUM_FILL_COUNT_REQUIRED"));
        }
        let evaluate = |count: u64, maximum: bool| -> Result<Value, Error> {
            let a = self.assess(
                b,
                day,
                "estimate",
                0,
                expected_basis.clone(),
                full_basis.clone(),
                None,
            )?;
            let whole = self.assess(
                b,
                day,
                "estimate",
                0,
                full_basis.clone(),
                full_basis.clone(),
                None,
            )?;
            let mut charges = BigDecimal::zero();
            let mut rebates = BigDecimal::zero();
            for c in array(&a.value["components"])? {
                let r = schedules
                    .iter()
                    .find(|s| digest(s) == c["identity"]["schedule"].as_str().unwrap_or(""))
                    .and_then(|s| {
                        s["rules"]
                            .as_array()?
                            .iter()
                            .find(|r| r["id"] == c["identity"]["rule"])
                    })
                    .ok_or_else(|| err("FEE_ESTIMATE_RULE"))?;
                let multiplier = if split_sensitive(r) { count } else { 1 };
                let selected = if split_sensitive(r) && !maximum {
                    c
                } else {
                    whole.value["components"]
                        .as_array()
                        .expect("components")
                        .iter()
                        .find(|x| x["identity"] == c["identity"])
                        .ok_or_else(|| err("FEE_ESTIMATE_RULE"))?
                };
                let n = num(&selected["target"])? * BigDecimal::from(multiplier);
                if c["identity"]["direction"] == "CHARGE" {
                    charges += n;
                } else {
                    rebates += n;
                }
            }
            let p = currency(&b.value["subject"]["currency"])?;
            Ok(json!({"charges":amount(&charges,p)?,"rebates":amount(&rebates,p)?}))
        };
        let expected = evaluate(expected_count, false)?;
        let maximum = evaluate(maximum_count.unwrap_or(expected_count), true)?;
        Ok(
            json!({"schema_version":1,"binding":b.fingerprint(),"expected":expected,"maximum":maximum,"reservation_charge":maximum["charges"],"assumptions":digest(&json!([day,expected_basis,full_basis,expected_count,maximum_count]))}),
        )
    }
}
fn split_sensitive(r: &Value) -> bool {
    let zero = r["terms"].as_array().is_some_and(|terms| {
        terms
            .iter()
            .all(|t| num(&t["amount"]).is_ok_and(|n| n.is_zero()))
    }) && (r["minimum"].is_null() || num(&r["minimum"]).is_ok_and(|n| n.is_zero()));
    !zero
        && r["scope"] == "FILL"
        && (r["rounding"] != "FLOOR"
            || !r["minimum"].is_null()
            || !r["maximum"].is_null()
            || r["terms"]
                .as_array()
                .is_some_and(|a| a.iter().any(|t| t["kind"] == "FIXED")))
}

fn applies_to_subject(r: &Value, subject: &Value) -> bool {
    ["side", "offset"]
        .iter()
        .all(|k| r[k].is_null() || r[k] == subject[k])
}
