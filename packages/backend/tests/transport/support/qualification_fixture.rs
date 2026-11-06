//! Test data/reads through current immutable Policy and Store owners only.
//! No PG connection, publication, admission, evaluator support or product route.
use onlyalpha_backend::application::qualification_policy::{Policy, Store};
use onlyalpha_backend::security::protected_files;
use onlyalpha_strategy::record_fingerprint;
use serde_json::{Value, json};
use std::{error::Error, os::fd::AsFd, path::Path};

pub fn produce(input: &Value) -> Result<Value, Box<dyn Error>> {
    let action = input["action"].as_str().ok_or("fixture action")?;
    if matches!(action, "model" | "validate") {
        let record = if action == "validate" {
            input["document"].clone()
        } else {
            let mut record = json!({"schema_version":1,
                "policy_id":input["policy_id"].as_str().unwrap_or("research"),
                "policy_version":input["version"].as_str().unwrap_or("1"),
                "gate":"RESEARCH_TO_BACKTEST", "missing_evidence_behavior":"FAIL", "aggregation":"ALL",
                "criteria":[{"criterion_id":"count","evidence_kind":"RESEARCH_RESULT",
                    "metric":"artifact_count","comparison":"GE",
                    "threshold":input["threshold"].as_str().unwrap_or("-0.000001")}]});
            let mut identity = record.clone();
            identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
            record["policy_fingerprint"] = json!(record_fingerprint(&identity));
            record
        };
        return Ok(
            match Policy::from_json(&record.to_string(), 8 * 1024 * 1024) {
                Ok(policy) => json!({"policy":policy.to_record(),"error":null}),
                Err(error) => json!({"error":error.code()}),
            },
        );
    }
    let root =
        protected_files::open_directory(Path::new(input["root"].as_str().ok_or("fixture root")?))
            .map_err(|_| "controlled fixture root unavailable")?;
    let store = Store::open(root.as_fd())?;
    match action {
        "policies" => Ok(match store.policies(64 * 1024 * 1024) {
            Ok(policies) => {
                json!({"policies":policies.iter().map(Policy::to_record).collect::<Vec<_>>(),"error":null})
            }
            Err(error) => json!({"error":error.code()}),
        }),
        "load" => Ok(
            match store.load_exact(
                input["policy_id"].as_str().ok_or("fixture id")?,
                input["version"].as_str().ok_or("fixture version")?,
                64 * 1024 * 1024,
            ) {
                Ok(policy) => json!({"policy":policy.to_record(),"error":null}),
                Err(error) => json!({"error":error.code()}),
            },
        ),
        _ => Err("unknown qualification fixture action".into()),
    }
}
