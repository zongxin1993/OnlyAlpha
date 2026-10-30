//! The existing Exact Evaluation Subject / Decision Group identity contracts.
//! This module does not accept a claimed ADMIT or certify caller-supplied history.
use crate::application::{command::CommandId, factor_content::hash};
use serde_json::{Value, json};

pub type Result<T> = std::result::Result<T, &'static str>;
pub(crate) const INVALID: &str = "NOVELTY_PROOF_INVALID";
pub(crate) const UNAVAILABLE: &str = "NOVELTY_PROOF_UNAVAILABLE";
pub(crate) const LIMIT: usize = 8 * 1024 * 1024;
pub const FAMILIES: [&str; 11] = [
    "AGENT_PROVENANCE",
    "PRODUCT_COMMAND_ADMISSION",
    "PRODUCT_COMMAND_RECEIPT",
    "QUALIFICATION_DECISION",
    "RESEARCH_ATTEMPT",
    "RESEARCH_FACTOR_PAIR_STATISTICS",
    "RESEARCH_RESULT",
    "RESEARCH_RUN",
    "RESEARCH_STATISTICS",
    "RESEARCH_SUMMARY_STATISTICS",
    "SEARCH_PROVENANCE",
];
pub(crate) fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let object = v.as_object().ok_or(INVALID)?;
    if object.len() != keys.len() || keys.iter().any(|k| !object.contains_key(*k)) {
        return Err(INVALID);
    }
    Ok(())
}
pub(crate) fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(INVALID)
}
pub(crate) fn pin(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| crate::is_sha256_hex(s))
        .ok_or(INVALID)
}
pub(crate) fn fp(v: &Value) -> Result<String> {
    hash(v).map_err(|_| INVALID)
}
pub(crate) fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), LIMIT).map_err(|_| INVALID)
}
pub(crate) fn signed(mut v: Value, key: &str, domain: Option<&str>) -> Result<Value> {
    let mut identity = v.clone();
    if let Some(domain) = domain {
        identity
            .as_object_mut()
            .ok_or(INVALID)?
            .insert("domain".into(), json!(domain));
    }
    let digest = fp(&identity)?;
    v.as_object_mut()
        .ok_or(INVALID)?
        .insert(key.into(), json!(digest));
    Ok(v)
}
pub(crate) fn verify_signed(v: &Value, key: &str, domain: Option<&str>) -> Result<()> {
    let expected = pin(&v[key])?;
    let mut raw = v.clone();
    raw.as_object_mut().ok_or(INVALID)?.remove(key);
    if signed(raw, key, domain)?[key] != expected {
        return Err(INVALID);
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Subject(Value);
impl Subject {
    pub fn new(record: Value) -> Result<Self> {
        exact(
            &record,
            &[
                "schema_version",
                "graph_fingerprint",
                "candidate_node_fingerprint",
                "output_name",
                "candidate_fingerprint",
                "dataset_snapshot_fingerprint",
                "specification_fingerprint",
                "result_plan_fingerprint",
                "statistics_fingerprints",
                "catalog_generation_fingerprint",
                "runtime_generation_fingerprint",
                "authoring_generation_fingerprint",
            ],
        )?;
        if record["schema_version"].as_u64() != Some(1) || text(&record, "output_name")?.is_empty()
        {
            return Err(INVALID);
        }
        for key in [
            "graph_fingerprint",
            "candidate_node_fingerprint",
            "candidate_fingerprint",
            "dataset_snapshot_fingerprint",
            "specification_fingerprint",
            "result_plan_fingerprint",
            "catalog_generation_fingerprint",
            "runtime_generation_fingerprint",
        ] {
            pin(&record[key])?;
        }
        if !record["authoring_generation_fingerprint"].is_null() {
            pin(&record["authoring_generation_fingerprint"])?;
        }
        let statistics = record["statistics_fingerprints"]
            .as_array()
            .ok_or(INVALID)?;
        if statistics.is_empty() || statistics.len() > 32 {
            return Err(INVALID);
        }
        let strings = statistics.iter().map(pin).collect::<Result<Vec<_>>>()?;
        if strings.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(INVALID);
        }
        Ok(Self(record))
    }
    pub fn to_record(&self) -> Value {
        self.0.clone()
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
    pub fn fingerprint(&self) -> Result<String> {
        let mut record = self.0.clone();
        record.as_object_mut().ok_or(INVALID)?.insert(
            "domain".into(),
            json!("ONLYALPHA_EXACT_EVALUATION_INTENT_SUBJECT_V1"),
        );
        fp(&record)
    }
}
pub fn subject_set(subjects: &[Subject]) -> Result<Value> {
    if subjects.is_empty() || subjects.len() > 32 {
        return Err(INVALID);
    }
    let specification = pin(&subjects[0].0["specification_fingerprint"])?;
    let identities = subjects
        .iter()
        .map(Subject::fingerprint)
        .collect::<Result<Vec<_>>>()?;
    if identities.windows(2).any(|pair| pair[0] >= pair[1])
        || subjects
            .iter()
            .any(|s| s.0["specification_fingerprint"] != specification)
    {
        return Err(INVALID);
    }
    Ok(
        json!({"schema_version":1,"specification_fingerprint":specification,"subjects":subjects.iter().map(Subject::to_record).collect::<Vec<_>>()}),
    )
}
pub fn subject_set_fingerprint(subjects: &[Subject]) -> Result<String> {
    let mut v = subject_set(subjects)?;
    v.as_object_mut().ok_or(INVALID)?.insert(
        "domain".into(),
        json!("ONLYALPHA_RESEARCH_EVALUATION_SUBJECT_SET_V1"),
    );
    fp(&v)
}

pub(crate) fn policy(v: &Value, id: &str, version: &str) -> Result<()> {
    exact(
        v,
        &[
            "schema_version",
            "policy_id",
            "policy_version",
            "rules",
            "policy_fingerprint",
        ],
    )?;
    verify_signed(
        v,
        "policy_fingerprint",
        Some("onlyalpha.research.novelty-policy"),
    )?;
    if v["schema_version"].as_u64() != Some(1)
        || v["policy_id"] != id
        || v["policy_version"] != version
    {
        return Err(INVALID);
    }
    let rules = v["rules"].as_array().ok_or(INVALID)?;
    let conditions = [
        "CERTIFIED_NO_MATCH",
        "EXACT_COMPLETED_EVALUATION",
        "EXACT_COMPLETED_NEGATIVE_EVIDENCE",
        "OPERATIONAL_FAILURE",
        "PROOF_INCOMPLETE",
        "PROOF_UNAVAILABLE",
        "SEARCH_OR_BUDGET_STOP",
    ];
    if rules.len() != conditions.len() {
        return Err(INVALID);
    }
    for (rule, condition) in rules.iter().zip(conditions) {
        exact(rule, &["condition", "outcome"])?;
        let outcome = text(rule, "outcome")?;
        let allowed = match condition {
            "CERTIFIED_NO_MATCH" => matches!(outcome, "ADMIT" | "REVIEW" | "FAIL_CLOSED"),
            "EXACT_COMPLETED_EVALUATION" => matches!(outcome, "REUSE" | "ADMIT" | "REVIEW"),
            "EXACT_COMPLETED_NEGATIVE_EVIDENCE" => {
                matches!(outcome, "SUPPRESS" | "REVIEW" | "FAIL_CLOSED")
            }
            _ => matches!(outcome, "REVIEW" | "FAIL_CLOSED"),
        };
        if rule["condition"] != condition || !allowed {
            return Err(INVALID);
        }
    }
    Ok(())
}

pub(crate) fn historical_query(
    subject: &Subject,
    projection: &Value,
    matches: Vec<Value>,
    incomplete: bool,
) -> Result<(Value, Value)> {
    let query = signed(
        json!({"query_schema_version":3,"projection_revision_fingerprint":projection["revision_fingerprint"],"query_kind":"EVALUATION_INTENT_EXACT","exact_selector":{"selector_schema_version":1,"intent_subject":subject.0}}),
        "query_fingerprint",
        None,
    )?;
    let proof = signed(
        json!({"query_fingerprint":query["query_fingerprint"],"projection_revision_fingerprint":projection["revision_fingerprint"],"projection_logical_digest":projection["logical_digest"],"source_manifest_fingerprint":projection["source_manifest"]["manifest_fingerprint"],"proof_status":if incomplete {"PROOF_INCOMPLETE"} else if matches.is_empty() {"CERTIFIED_NO_MATCH"} else {"MATCH"},"ordered_matches":matches,"failure_code":if incomplete {json!("PREDICATE_COMPLETENESS_UNPROVEN")} else {Value::Null}}),
        "result_fingerprint",
        None,
    )?;
    Ok((query, proof))
}

/// One bounded first-slice request: no Qualification or related-failure selector.
/// Future selector support must migrate its actual owning proof, never ignore it.
pub(crate) fn decision_bundle(
    command: &CommandId,
    subject: &Subject,
    policy_record: &Value,
    projection: &Value,
    query: Value,
    proof: Value,
) -> Result<Value> {
    let resolved = json!({"subject_type":"EXACT_EVALUATION","evaluation_subject":subject.0,"qualification_binding":null,"related_failures":[]});
    let intent = fp(
        &json!({"domain":"onlyalpha.research.novelty-decision-intent-v2","request_schema_version":2,"policy_id":policy_record["policy_id"],"policy_version":policy_record["policy_version"],"resolved_subject":resolved}),
    )?;
    let mut subject_identity = resolved.clone();
    subject_identity.as_object_mut().ok_or(INVALID)?.insert(
        "domain".into(),
        json!("onlyalpha.research.novelty-decision-subject-v2"),
    );
    let decision_subject = json!({"product_command_id":command.value(),"canonical_intent_fingerprint":intent,"resolved_subject":resolved,"subject_fingerprint":fp(&subject_identity)?});
    let witness = signed(
        json!({"schema_version":2,"subject":decision_subject,"policy_id":policy_record["policy_id"],"policy_version":policy_record["policy_version"],"policy_fingerprint":policy_record["policy_fingerprint"],"projection_schema_version":projection["projection_schema_version"],"projector_algorithm_version":projection["projector_algorithm_version"],"projection_revision_fingerprint":projection["revision_fingerprint"],"projection_logical_digest":projection["logical_digest"],"source_manifest":projection["source_manifest"],"proofs":[{"role":"EVALUATION","query":query,"proof":proof}],"negative_evidence":null,"negative_evidence_failure_code":null}),
        "witness_fingerprint",
        Some("onlyalpha.research.novelty-decision-witness-v2"),
    )?;
    let (condition, reason) = match text(&proof, "proof_status")? {
        "CERTIFIED_NO_MATCH" => ("CERTIFIED_NO_MATCH", "CERTIFIED_EVALUATION_ABSENCE"),
        "MATCH" => ("EXACT_COMPLETED_EVALUATION", "EXACT_EVALUATION_MATCH"),
        "PROOF_INCOMPLETE" => ("PROOF_INCOMPLETE", "HISTORICAL_PROOF_INCOMPLETE"),
        "PROOF_UNAVAILABLE" => ("PROOF_UNAVAILABLE", "HISTORICAL_PROOF_UNAVAILABLE"),
        _ => return Err(INVALID),
    };
    let rule = policy_record["rules"]
        .as_array()
        .ok_or(INVALID)?
        .iter()
        .find(|r| r["condition"] == condition)
        .ok_or(INVALID)?;
    let decision = signed(
        json!({"schema_version":2,"product_command_id":command.value(),"canonical_intent_fingerprint":intent,"subject_type":"EXACT_EVALUATION","subject_fingerprint":decision_subject["subject_fingerprint"],"policy_id":policy_record["policy_id"],"policy_version":policy_record["policy_version"],"policy_fingerprint":policy_record["policy_fingerprint"],"witness_fingerprint":witness["witness_fingerprint"],"derived_policy_condition":condition,"outcome":rule["outcome"],"reason_codes":[reason],"ordered_proof_references":[proof["result_fingerprint"]]}),
        "decision_fingerprint",
        Some("onlyalpha.research.novelty-decision-v2"),
    )?;
    Ok(json!({"decision":decision,"witness":witness}))
}
pub(crate) fn group(
    command: &CommandId,
    subjects: &[Subject],
    members: Vec<Value>,
) -> Result<Value> {
    let set = subject_set(subjects)?;
    if members.len() != subjects.len() {
        return Err(INVALID);
    }
    let actionable = members.iter().all(|m| m["decision"]["outcome"] == "ADMIT");
    signed(
        json!({"schema_version":1,"product_command_id":command.value(),"specification_fingerprint":set["specification_fingerprint"],"subject_set_fingerprint":subject_set_fingerprint(subjects)?,"members":members,"disposition":if actionable {"ACTIONABLE"} else {"BLOCKED"}}),
        "group_fingerprint",
        Some("onlyalpha.research.novelty-decision-group-v1"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn subject() -> Value {
        json!({"schema_version":1,"graph_fingerprint":"1".repeat(64),"candidate_node_fingerprint":"2".repeat(64),"output_name":"value","candidate_fingerprint":"3".repeat(64),"dataset_snapshot_fingerprint":"4".repeat(64),"specification_fingerprint":"5".repeat(64),"result_plan_fingerprint":"6".repeat(64),"statistics_fingerprints":["7".repeat(64)],"catalog_generation_fingerprint":"8".repeat(64),"runtime_generation_fingerprint":"9".repeat(64),"authoring_generation_fingerprint":null})
    }
    #[test]
    fn subject_requires_complete_original_identity_not_partial_or_duplicate_statistics() {
        let good = Subject::new(subject()).unwrap();
        for key in subject().as_object().unwrap().keys() {
            let mut broken = subject();
            broken.as_object_mut().unwrap().remove(key);
            assert!(Subject::new(broken).is_err(), "missing {key}");
        }
        let mut broken = subject();
        broken["statistics_fingerprints"] = json!(["7".repeat(64), "7".repeat(64)]);
        assert!(Subject::new(broken).is_err());
        let mut changed = subject();
        changed["runtime_generation_fingerprint"] = json!("a".repeat(64));
        assert_ne!(
            good.fingerprint().unwrap(),
            Subject::new(changed).unwrap().fingerprint().unwrap()
        );
    }
    #[test]
    fn incomplete_proof_can_never_select_an_admit_rule() {
        let mut p =
            json!({"schema_version":1,"policy_id":"native","policy_version":"1","rules":[]});
        p["rules"] = json!([{"condition":"CERTIFIED_NO_MATCH","outcome":"ADMIT"},{"condition":"EXACT_COMPLETED_EVALUATION","outcome":"REUSE"},{"condition":"EXACT_COMPLETED_NEGATIVE_EVIDENCE","outcome":"SUPPRESS"},{"condition":"OPERATIONAL_FAILURE","outcome":"REVIEW"},{"condition":"PROOF_INCOMPLETE","outcome":"ADMIT"},{"condition":"PROOF_UNAVAILABLE","outcome":"FAIL_CLOSED"},{"condition":"SEARCH_OR_BUDGET_STOP","outcome":"REVIEW"}]);
        p = signed(
            p,
            "policy_fingerprint",
            Some("onlyalpha.research.novelty-policy"),
        )
        .unwrap();
        assert!(policy(&p, "native", "1").is_err());
    }
    #[test]
    fn subject_and_complete_group_match_independent_original_authority_vectors() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_novelty.json"
        ))
        .unwrap();
        let s = Subject::new(fixture["subject"].clone()).unwrap();
        assert_eq!(s.fingerprint().unwrap(), fixture["subject_fingerprint"]);
        policy(&fixture["policy"], "native", "1").unwrap();
        let command = CommandId::new(fixture["command_id"].as_str().unwrap()).unwrap();
        let (q, p) = historical_query(&s, &fixture["projection"], vec![], false).unwrap();
        let bundle = decision_bundle(
            &command,
            &s,
            &fixture["policy"],
            &fixture["projection"],
            q,
            p,
        )
        .unwrap();
        assert_eq!(
            group(&command, &[s], vec![bundle]).unwrap(),
            fixture["group"]
        );
    }
}
