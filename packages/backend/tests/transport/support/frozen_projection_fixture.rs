//! Pure fixture documents from current Rust value owners, never publication or admission.
use onlyalpha_backend::application::frozen_strategy::FreezeRelation;
use onlyalpha_strategy::{SourceRevision, record_fingerprint};
use serde_json::{Value, json};

pub(crate) fn produce(input: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    const WORK: usize = 1024 * 1024;
    let source = input
        .get("source")
        .map(|v| SourceRevision::from_json(&v.to_string(), WORK))
        .transpose()?;
    let mut relation = match input.get("relation") {
        Some(value) => value.clone(),
        None => json!({"schema_version":1,
            "strategy_fingerprint":source.as_ref().ok_or("source required")?.fingerprint(),
            "candidate_fingerprint":"a".repeat(64),"research_result_fingerprint":"b".repeat(64),
            "research_execution_evidence_fingerprints":["c".repeat(64),"d".repeat(64)],
            "admission_evidence_fingerprint":"e".repeat(64),"equivalence_evidence_fingerprints":["f".repeat(64)]}),
    };
    let mut identity = relation.clone();
    identity
        .as_object_mut()
        .ok_or("relation object")?
        .remove("relation_fingerprint");
    identity["domain"] = json!("onlyalpha.strategy.freeze-relation");
    relation["relation_fingerprint"] = json!(record_fingerprint(&identity));
    let relation = FreezeRelation::from_json(&relation.to_string(), WORK)?;
    Ok(match source {
        Some(source) => {
            if relation.strategy_fingerprint() != source.fingerprint() {
                return Err("fixture relation mismatch".into());
            }
            json!({"strategy_fingerprint":source.fingerprint(),
                "frozen":{"schema_version":1,"strategy_fingerprint":source.fingerprint(),"revision":source.to_record()},
                "relation":relation.to_record()})
        }
        None => json!({"relation":relation.to_record()}),
    })
}
