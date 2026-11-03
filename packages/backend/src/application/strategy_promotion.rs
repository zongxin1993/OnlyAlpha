//! Public append-only Promotion values. Reading a stage grants no execution right.
use crate::application::factor_content::hash;
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PROMOTION_LEDGER_CORRUPT";
const LIMIT: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PromotionRecord(Value);
impl PromotionRecord {
    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > LIMIT { return Err("PROMOTION_LEDGER_UNAVAILABLE"); }
        let version=value["schema_version"].as_u64().ok_or(INVALID)?;
        let mut fields=vec!["schema_version","strategy_fingerprint","from_stage","to_stage","evidence_fingerprints","decision","reason","actor","recorded_at","previous_record_fingerprint","record_fingerprint"];
        if version>=2 { fields.push("qualification_decision_fingerprint"); }
        if version==3 {fields.push("origin");}
        if !matches!(version,1|2|3) || value.as_object().is_none_or(|m|m.len()!=fields.len() || fields.iter().any(|k|!m.contains_key(*k))) { return Err(INVALID); }
        for key in ["strategy_fingerprint","record_fingerprint"] { pin(&value[key])?; }
        if !value["previous_record_fingerprint"].is_null() { pin(&value["previous_record_fingerprint"])?; }
        if version==3 {
            let origin=value["origin"].as_object().ok_or(INVALID)?;
            if origin.len()!=2 || !origin.contains_key("kind") || !origin.contains_key("strategy_validation_fingerprint")
                || value["origin"]["kind"]!="MANUAL_BACKTEST" || value["from_stage"]!="FROZEN" || value["to_stage"]!="BACKTEST" {return Err(INVALID);}
            pin(&value["origin"]["strategy_validation_fingerprint"])?;
        }else if value["from_stage"]=="FROZEN" {return Err(INVALID);}
        if next(text(&value["from_stage"])?) != Some(text(&value["to_stage"])?)
            || !matches!(text(&value["decision"])?,"APPROVED"|"REJECTED") { return Err(INVALID); }
        for key in ["actor","reason"] { if text(&value[key])?.trim().is_empty() {return Err(INVALID);} }
        text(&value["recorded_at"])?.parse::<OnlyUtcDateTime>().map_err(|_|INVALID)?;
        let evidence=value["evidence_fingerprints"].as_array().filter(|a|!a.is_empty() && a.len()<=8192).ok_or(INVALID)?;
        let mut previous=None;
        for item in evidence {
            let current=pin(item)?;
            if previous.is_some_and(|p|p>=current) { return Err(INVALID); }
            previous=Some(current);
        }
        if version>=2 { pin(&value["qualification_decision_fingerprint"])?; if !evidence.contains(&value["qualification_decision_fingerprint"]) { return Err(INVALID); } }
        if version==3&&!evidence.contains(&value["origin"]["strategy_validation_fingerprint"]) {return Err(INVALID);}
        let mut identity=value.clone(); identity.as_object_mut().ok_or(INVALID)?.remove("record_fingerprint");
        if value["record_fingerprint"] != hash(&identity)? {return Err(INVALID);}
        Ok(Self(value.clone()))
    }
    pub fn record(&self)->&Value {&self.0}
    pub fn fingerprint(&self)->&str {self.0["record_fingerprint"].as_str().expect("validated Promotion identity")}
}
fn text(value:&Value)->Result<&str> {value.as_str().ok_or(INVALID)}
fn pin(value:&Value)->Result<&str> {
    let value=text(value)?;
    if crate::is_sha256_hex(value) {Ok(value)} else {Err(INVALID)}
}
fn next(stage:&str)->Option<&'static str> {match stage {"FROZEN"|"RESEARCH"=>Some("BACKTEST"),"BACKTEST"=>Some("SIM"),"SIM"=>Some("LIVE_ELIGIBLE"),_=>None}}

pub struct PromotionChain {records:Vec<PromotionRecord>, stage:&'static str}
impl PromotionChain {
    pub fn from_records(strategy:&str,records:Vec<PromotionRecord>)->Result<Self> {
        if !crate::is_sha256_hex(strategy) || records.len()>8192 {return Err(INVALID);}
        if records.is_empty() {return Ok(Self{records,stage:"FROZEN"});}
        let mut children=BTreeMap::new(); let mut identities=BTreeSet::new();
        for row in records {
            if row.record()["strategy_fingerprint"]!=strategy || !identities.insert(row.fingerprint().to_owned()) {return Err(INVALID);}
            let parent=row.record()["previous_record_fingerprint"].as_str().map(str::to_owned);
            if children.insert(parent,row).is_some() {return Err(INVALID);}
        }
        let mut current=children.remove(&None).ok_or(INVALID)?;
        let manual=current.record()["schema_version"]==3;
        let mut ordered=Vec::new(); let mut stage=if manual {"FROZEN"}else{"RESEARCH"};
        loop {
            if manual&&(current.record()["schema_version"]!=3 || current.record()["to_stage"]!="BACKTEST") {return Err(INVALID);}
            if !manual&&current.record()["schema_version"]==3 {return Err(INVALID);}
            if current.record()["from_stage"] != stage {return Err(INVALID);}
            if current.record()["decision"]=="APPROVED" {stage=next(stage).ok_or(INVALID)?;}
            let next=children.remove(&Some(current.fingerprint().to_owned())); ordered.push(current);
            match next {Some(row)=>current=row,None=>break}
        }
        if !children.is_empty() || ordered.len()!=identities.len() {return Err(INVALID);}
        Ok(Self{records:ordered,stage})
    }
    pub fn stage(&self)->&str {self.stage}
    pub fn records(&self)->&[PromotionRecord] {&self.records}
    pub fn head_fingerprint(&self)->Option<&str> {self.records.last().map(PromotionRecord::fingerprint)}
}

// These public value vectors grant no progression or Runtime admission.
#[cfg(test)]
mod tests {
    use super::{PromotionChain, PromotionRecord};
    use serde_json::{Value, json};
    fn signed(mut value: Value) -> Value {
        value.as_object_mut().unwrap().remove("record_fingerprint");
        value["record_fingerprint"] = json!(crate::application::factor_content::hash(&value).unwrap());
        value
    }
    fn record() -> Value {
        signed(json!({"schema_version":2,"strategy_fingerprint":"a".repeat(64),"from_stage":"RESEARCH","to_stage":"BACKTEST",
            "evidence_fingerprints":["b".repeat(64),"c".repeat(64)],"decision":"APPROVED","reason":"实验性回测；仅检查证据完整性",
            "actor":"local-developer","recorded_at":"2026-11-02T00:00:00+00:00","previous_record_fingerprint":null,
            "qualification_decision_fingerprint":"b".repeat(64)}))
    }
    #[test]
    fn public_promotion2_identity_has_no_added_domain_and_includes_original_audit() {
        let value = record();
        let parsed = PromotionRecord::from_record(&value).unwrap();
        assert_eq!(parsed.record(), &value);
        let mut identity = value.clone();
        identity.as_object_mut().unwrap().remove("record_fingerprint");
        assert_eq!(parsed.fingerprint(), crate::application::factor_content::hash(&identity).unwrap());
        identity["actor"] = json!("another-owner");
        let changed = signed(identity);
        assert_ne!(PromotionRecord::from_record(&changed).unwrap().fingerprint(), parsed.fingerprint());
        assert_eq!(PromotionChain::from_records(&"a".repeat(64), vec![parsed]).unwrap().stage(), "BACKTEST");
    }
    #[test]
    fn promotion_history_is_an_exact_chain_independent_of_input_order_or_clock_order() {
        let head = record();
        let mut rejected = head.clone();
        rejected["from_stage"] = json!("BACKTEST"); rejected["to_stage"] = json!("SIM");
        rejected["previous_record_fingerprint"] = head["record_fingerprint"].clone();
        rejected["decision"] = json!("REJECTED"); rejected["recorded_at"] = json!("2026-11-01T00:00:00+00:00");
        let rejected = signed(rejected);
        let mut approved = rejected.clone();
        approved["previous_record_fingerprint"] = rejected["record_fingerprint"].clone();
        approved["decision"] = json!("APPROVED"); let approved = signed(approved);
        let chain = PromotionChain::from_records(&"a".repeat(64), vec![PromotionRecord::from_record(&approved).unwrap(), PromotionRecord::from_record(&head).unwrap(), PromotionRecord::from_record(&rejected).unwrap()]).unwrap();
        assert_eq!(chain.stage(), "SIM"); assert_eq!(chain.head_fingerprint(), Some(approved["record_fingerprint"].as_str().unwrap()));
        assert_eq!(chain.records().len(), 3);
    }
    #[test]
    fn current_public_legacy1_remains_readable_without_fabricated_qualification() {
        let mut value = record(); value["schema_version"] = json!(1);
        value.as_object_mut().unwrap().remove("qualification_decision_fingerprint");
        let value = signed(value); let parsed = PromotionRecord::from_record(&value).unwrap();
        assert!(parsed.record().get("qualification_decision_fingerprint").is_none());
        assert_eq!(PromotionChain::from_records(&"a".repeat(64), vec![parsed]).unwrap().stage(), "BACKTEST");
        // A readable historical stage is deliberately not an admission handle.
    }
    #[test]
    fn public_record_rejects_rehashed_invalid_semantics_and_schema_confusion() {
        for index in 0..12 {
            let mut value=record();
            match index {
                0 => value["schema_version"] = json!(true), 1 => value["schema_version"] = json!(3),
                2 => value["to_stage"] = json!("LIVE"), 3 => value["to_stage"] = json!("SIM"),
                4 => value["reason"] = json!(" "), 5 => value["actor"] = json!(""),
                6 => value["qualification_decision_fingerprint"] = Value::Null,
                7 => value["qualification_decision_fingerprint"] = json!("d".repeat(64)),
                8 => value["evidence_fingerprints"] = json!(["c".repeat(64),"b".repeat(64)]),
                9 => value["evidence_fingerprints"] = json!(["b".repeat(64),"b".repeat(64)]),
                10 => value["strategy_fingerprint"] = json!("A".repeat(64)),
                _ => value["granted"] = json!(true),
            }
            assert!(PromotionRecord::from_record(&signed(value)).is_err(), "mutation {index}");
        }
    }
    #[test]
    fn duplicate_head_branch_orphan_cycle_and_wrong_strategy_fail_closed() {
        let head=record();
        for index in 0..5 {
            let mut other=head.clone(); other["actor"]=json!("second");
            match index {
                0 => other=head.clone(),
                1 => {},
                2 => other["previous_record_fingerprint"]=json!("d".repeat(64)),
                3 => other["strategy_fingerprint"]=json!("e".repeat(64)),
                _ => other["previous_record_fingerprint"]=head["record_fingerprint"].clone(),
            }
            let other=if index==0 {other} else {signed(other)};
            let values=vec![PromotionRecord::from_record(&head).unwrap(),PromotionRecord::from_record(&other).unwrap()];
            assert!(PromotionChain::from_records(&"a".repeat(64),values).is_err(),"mutation {index}");
        }
    }
}

#[cfg(test)]
mod manual_promotion_tests {
    use super::*;
    use serde_json::json;
    fn sign(mut value:Value)->Value {
        value.as_object_mut().unwrap().remove("record_fingerprint");
        value["record_fingerprint"]=json!(hash(&value).unwrap());value
    }
    fn manual()->Value {
        sign(json!({"schema_version":3,"strategy_fingerprint":"a".repeat(64),"from_stage":"FROZEN","to_stage":"BACKTEST",
            "origin":{"kind":"MANUAL_BACKTEST","strategy_validation_fingerprint":"e".repeat(64)},
            "evidence_fingerprints":["b".repeat(64),"c".repeat(64),"e".repeat(64)],"decision":"APPROVED",
            "reason":"执行校验通过，仅允许实验回测","actor":"local-developer","recorded_at":"2026-11-02T00:00:00+00:00",
            "previous_record_fingerprint":null,"qualification_decision_fingerprint":"b".repeat(64)}))
    }
    #[test]
    fn an_unpromoted_strategy_is_frozen_without_inventing_research() {
        assert_eq!(PromotionChain::from_records(&"a".repeat(64),vec![]).unwrap().stage(),"FROZEN");
    }
    #[test]
    fn identical_strategy_cannot_be_promoted_to_backtest_a_second_time() {
        let raw=manual();let first=PromotionRecord::from_record(&raw).unwrap();
        let mut second=raw.clone();second["previous_record_fingerprint"]=raw["record_fingerprint"].clone();
        second["origin"]["strategy_validation_fingerprint"]=json!("f".repeat(64));
        second["evidence_fingerprints"]=json!(["b".repeat(64),"c".repeat(64),"f".repeat(64)]);
        let second=PromotionRecord::from_record(&sign(second)).unwrap();
        assert!(PromotionChain::from_records(&"a".repeat(64),vec![first.clone(),second]).is_err());
        assert!(PromotionChain::from_records(&"a".repeat(64),vec![first.clone(),first]).is_err());
    }
    #[test]
    fn explicit_manual_promotion_has_one_exact_backtest_only_origin() {
        let raw=manual();let parsed=PromotionRecord::from_record(&raw).unwrap();
        assert_eq!(parsed.record(),&raw);
        assert_eq!(PromotionChain::from_records(&"a".repeat(64),vec![parsed.clone()]).unwrap().stage(),"BACKTEST");
        let mut descendant=raw.clone();descendant["schema_version"]=json!(2);descendant.as_object_mut().unwrap().remove("origin");
        descendant["from_stage"]=json!("BACKTEST");descendant["to_stage"]=json!("SIM");
        descendant["previous_record_fingerprint"]=raw["record_fingerprint"].clone();
        let descendant=PromotionRecord::from_record(&sign(descendant)).unwrap();
        assert!(PromotionChain::from_records(&"a".repeat(64),vec![parsed,descendant]).is_err(),"a manual root cannot acquire SIM/LIVE by a later row");
        for mutation in 0..6 {
            let mut wrong=raw.clone();
            match mutation {
                0=>wrong["from_stage"]=json!("RESEARCH"),
                1=>wrong["to_stage"]=json!("SIM"),
                2=>{wrong.as_object_mut().unwrap().remove("origin");},
                3=>wrong["origin"]["kind"]=json!("RESEARCH"),
                4=>wrong["origin"]["strategy_validation_fingerprint"]=json!("bad"),
                _=>wrong["origin"]["approved"]=json!(true),
            }
            assert!(PromotionRecord::from_record(&sign(wrong)).is_err(),"mutation {mutation}");
        }
    }
}
