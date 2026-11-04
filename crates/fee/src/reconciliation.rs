use crate::{
    manager::{Manager, validate_query},
    model::*,
};
use bigdecimal::{BigDecimal, Zero};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    str::FromStr,
};
fn signed_number(v: &Value) -> Result<BigDecimal, Error> {
    let s = text(v)?;
    if let Some(s) = s.strip_prefix('-') {
        Ok(-num(&json!(s))?)
    } else {
        num(v)
    }
}
fn component_key(v: &Value) -> Result<String, Error> {
    fields(v, &["type", "authority", "direction", "component"])?;
    text(&v["component"])?;
    use onlyalpha_domain::fee::{OnlyFeeAuthority, OnlyFeeType};
    OnlyFeeType::from_str(text(&v["type"])?).map_err(|e| Error(e.to_string()))?;
    OnlyFeeAuthority::from_str(text(&v["authority"])?).map_err(|e| Error(e.to_string()))?;
    one(&v["direction"], &["CHARGE", "REBATE"])?;
    Ok(digest(v))
}
fn signed(amount: &Value, identity: &Value) -> Result<BigDecimal, Error> {
    let n = num(amount)?;
    Ok(if identity["direction"] == "REBATE" {
        -n
    } else {
        n
    })
}
impl Manager {
    pub fn reconcile(&mut self, evidence: Value, policy: Value) -> Result<Value, Error> {
        let input = json!({"evidence":evidence,"policy":policy});
        let key = digest(&input);
        if let Some(decision) = self.decisions.get(&key) {
            return Ok(decision.clone());
        }
        self.append(json!({"kind":"RECONCILE","input":input}))
    }
    pub(crate) fn reconcile_inner(&mut self, input: &Value) -> Result<Value, Error> {
        fields(input, &["evidence", "policy"])?;
        let e = &input["evidence"];
        let p = &input["policy"];
        fields(
            e,
            &[
                "id",
                "reference",
                "revision",
                "supersedes",
                "scope",
                "mode",
                "complete",
                "components",
                "total",
            ],
        )?;
        for k in ["id", "reference"] {
            text(&e[k])?;
        }
        let sequence = unsigned(&e["revision"])?;
        if sequence == 0 {
            return Err(err("FEE_EVIDENCE_REVISION"));
        }
        if !e["supersedes"].is_null() {
            text(&e["supersedes"])?;
        }
        validate_query(&e["scope"])?;
        one(
            &e["mode"],
            &[
                "DETAILED",
                "COMMISSION_ONLY",
                "ALL_IN",
                "ORDER_CUMULATIVE",
                "DEFERRED_STATEMENT",
            ],
        )?;
        let complete = e["complete"]
            .as_bool()
            .ok_or_else(|| err("FEE_EVIDENCE_COMPLETE"))?;
        fields(
            p,
            &[
                "id",
                "version",
                "currency",
                "precision",
                "threshold",
                "unknown_action",
                "incomplete_action",
                "component_action",
            ],
        )?;
        text(&p["id"])?;
        text(&p["version"])?;
        if p["currency"] != e["scope"]["currency"]
            || e["scope"]["account"] != self.config["account"]
        {
            return Err(err("FEE_RECONCILIATION_SCOPE"));
        }
        let precision =
            u8::try_from(unsigned(&p["precision"])?).map_err(|_| err("FEE_PRECISION"))?;
        if precision > 18 {
            return Err(err("FEE_PRECISION"));
        }
        let threshold = num(&p["threshold"])?;
        for k in ["unknown_action", "incomplete_action", "component_action"] {
            one(&p[k], &["BLOCK", "ADJUST"])?;
        }
        let family = digest(&json!([e["reference"], e["scope"]]));
        let prior_head = self.heads.get(&family).cloned();
        let mut conflict = false;
        if let Some(head) = &prior_head {
            let current = unsigned(&head["revision"])?;
            if sequence == current && *head != *e {
                conflict = true;
            } else if sequence != current + 1 || e["supersedes"] != head["id"] {
                return Err(err("FEE_EVIDENCE_LINEAGE"));
            }
        } else if sequence != 1 || !e["supersedes"].is_null() {
            return Err(err("FEE_EVIDENCE_PREDECESSOR"));
        }
        if self
            .evidence
            .get(text(&e["id"])?)
            .is_some_and(|old| *old != *e)
        {
            conflict = true;
        }
        let local = self.query(&e["scope"])?;
        let mut local_values: BTreeMap<String, BigDecimal> = BTreeMap::new();
        let mut identities = BTreeMap::new();
        let mut unavailable = !complete || local.is_empty();
        for a in &local {
            if a["detail_available"] != true {
                unavailable = true;
            }
            if a["subject"]["currency"]["precision"] != precision {
                return Err(err("FEE_POLICY_PRECISION_CONFLICT"));
            }
            for c in array(&a["components"])? {
                let i = &c["identity"];
                let identity = json!({"type":i["type"],"authority":i["authority"],"direction":i["direction"],"component":format!("{}:{}:{}",i["namespace"].as_str().unwrap_or(""),i["family"].as_str().unwrap_or(""),i["rule"].as_str().unwrap_or(""))});
                let k = component_key(&identity)?;
                *local_values.entry(k.clone()).or_default() += signed(&c["amount"], &identity)?;
                identities.insert(k, identity);
            }
        }
        if e["mode"] != "DETAILED" {
            let total: BigDecimal = local_values
                .iter()
                .filter(|(k, _)| {
                    e["mode"] != "COMMISSION_ONLY" || identities[*k]["type"] == "BROKER_COMMISSION"
                })
                .map(|(_, v)| v.clone())
                .sum();
            let i = json!({"type":if e["mode"]=="COMMISSION_ONLY"{"BROKER_COMMISSION"}else{"PLATFORM_FEE"},"authority":"BROKER","direction":"CHARGE","component":if e["mode"]=="COMMISSION_ONLY"{"COMMISSION"}else{"ALL_IN"}});
            let key = component_key(&i)?;
            local_values.clear();
            identities.clear();
            if !local.is_empty() {
                local_values.insert(key.clone(), total);
            }
            identities.insert(key, i);
        }
        let mut reported = BTreeMap::new();
        for c in array(&e["components"])? {
            fields(c, &["identity", "amount"])?;
            exact_amount(&num(&c["amount"])?, precision)?;
            let key = component_key(&c["identity"])?;
            if reported
                .insert(key.clone(), signed(&c["amount"], &c["identity"])?)
                .is_some()
            {
                return Err(err("FEE_EXTERNAL_COMPONENT_DUPLICATE"));
            }
            identities.insert(key, c["identity"].clone());
        }
        if e["mode"] != "DETAILED" {
            if !reported.is_empty() || e["total"].is_null() {
                return Err(err("FEE_EVIDENCE_MODE"));
            }
            let total = signed_number(&e["total"])?;
            exact_amount(&total, precision)?;
            let key = identities
                .keys()
                .next()
                .ok_or_else(|| err("FEE_AGGREGATE_IDENTITY"))?
                .clone();
            reported.insert(key, total);
        }
        if !e["total"].is_null() {
            let total = signed_number(&e["total"])?;
            exact_amount(&total, precision)?;
            if e["mode"] == "DETAILED" && reported.values().cloned().sum::<BigDecimal>() != total {
                return Err(err("FEE_EXTERNAL_TOTAL_CONFLICT"));
            }
        }
        let mut prior: BTreeMap<String, BigDecimal> = BTreeMap::new();
        let mut prior_inputs = Vec::new();
        for a in &self.adjustments {
            if a["scope"] == e["scope"] {
                let key = component_key(&a["identity"])?;
                let n = signed_number(&a["signed_amount"])?;
                *prior.entry(key.clone()).or_default() += n;
                identities.insert(key, a["identity"].clone());
                prior_inputs.push(a.clone());
            } else {
                let previous = self.query(&a["scope"])?;
                if previous
                    .iter()
                    .any(|x| local.iter().any(|l| l["id"] == x["id"]))
                {
                    return Err(err("FEE_ADJUSTMENT_SCOPE_OVERLAP_UNPROVEN"));
                }
            }
        }
        let keys: BTreeSet<_> = local_values
            .keys()
            .chain(reported.keys())
            .chain(prior.keys())
            .cloned()
            .collect();
        let mut rows = Vec::new();
        let mut proposed = Vec::new();
        let mut blocked = conflict;
        let mut different = false;
        let mut incomplete = unavailable;
        for key in keys {
            let l = local_values.get(&key);
            let r = reported.get(&key);
            let before = prior.get(&key).cloned().unwrap_or_default();
            let effective = l.cloned().unwrap_or_default() + &before;
            let difference = r.cloned().unwrap_or_default() - &effective;
            let missing = l.is_none() || r.is_none();
            let status = if r.is_none() {
                "MISSING_EXTERNAL"
            } else if l.is_none() {
                "MISSING_LOCAL"
            } else if difference.is_zero() {
                "MATCHED"
            } else {
                "DIFFERENT"
            };
            if missing {
                incomplete = true;
            }
            if !difference.is_zero() {
                different = true;
            }
            let action = if missing || incomplete {
                &p["incomplete_action"]
            } else if matches!(e["mode"].as_str(), Some("ALL_IN" | "DEFERRED_STATEMENT"))
                && sequence == 1
            {
                &p["unknown_action"]
            } else {
                &p["component_action"]
            };
            let absolute = if difference < BigDecimal::zero() {
                -&difference
            } else {
                difference.clone()
            };
            if (missing || incomplete || absolute > threshold) && action == "BLOCK" {
                blocked = true;
            }
            rows.push(json!({"identity":identities[&key],"local":l.map(|n|n.to_string()),"external":r.map(|n|n.to_string()),"prior":before.to_string(),"difference":difference.to_string(),"status":status}));
            if !difference.is_zero() && !missing && !unavailable && !conflict {
                proposed.push(json!({"id":format!("FADJ-{}",digest(&json!([e,p,&key,difference.to_string(),&prior_inputs]))),"evidence":e["id"],"family":family,"scope":e["scope"],"identity":identities[&key],"signed_amount":difference.to_string(),"amount":exact_amount(&absolute,precision)?,"direction":if difference<BigDecimal::zero(){"REFUND"}else{"SUPPLEMENTAL_CHARGE"},"cluster":if e["scope"]["kind"]=="STATEMENT"{Value::Null}else{local.first().map(|a|a["subject"]["cluster"].clone()).unwrap_or(Value::Null)}}));
            }
        }
        if incomplete && p["incomplete_action"] == "BLOCK" {
            blocked = true;
        }
        let status = if conflict {
            "EVIDENCE_CONFLICT"
        } else if blocked {
            "TRADING_BLOCKED"
        } else if incomplete {
            "INCOMPLETE_EXTERNAL_DATA"
        } else if different {
            "RECONCILED_WITH_ADJUSTMENT"
        } else {
            "MATCHED"
        };
        if blocked || incomplete {
            proposed.clear();
        }
        let decision = json!({"id":format!("FREC-{}",digest(input)),"evidence":e["id"],"family":family,"scope":e["scope"],"policy":digest(p),"local_facts":digest(&json!(local)),"prior_adjustments":digest(&json!(prior_inputs)),"components":rows,"status":status,"adjustments":proposed});
        if blocked {
            self.blockers.insert(family.clone(),json!({"family":family,"evidence":e["id"],"decision":decision["id"],"scope":e["scope"],"policy":digest(p)}));
        } else if !incomplete && !conflict {
            self.blockers.remove(&family);
        }
        if !conflict {
            self.heads.insert(family, e.clone());
            self.evidence.insert(text(&e["id"])?.into(), e.clone());
        }
        self.adjustments.extend(proposed);
        self.decisions.insert(digest(input), decision.clone());
        Ok(decision)
    }
}
