//! Strict source-row validation, independent of cross-row occurrence/lineage proof.
use super::{Failure, FailurePhase, RunState};
use crate::application::command::{
    Admission, CommandId, CommandKind, Outcome, OutcomeKind, Receipt,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::Value;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "NOVELTY_SOURCE_PROOF_INVALID";
const UNAVAILABLE: &str = "NOVELTY_PROOF_UNAVAILABLE";

pub fn validate_source_history_event(family: &str, event: &Value) -> Result<()> {
    match family {
        "RESEARCH_RUN" => run(event),
        "RESEARCH_ATTEMPT" => attempt(event),
        "PRODUCT_COMMAND_ADMISSION" => {
            fields(
                event,
                &[
                    "command_id",
                    "command_kind",
                    "command_fingerprint",
                    "schema_version",
                ],
            )?;
            command(event).map(|_| ())
        }
        "PRODUCT_COMMAND_RECEIPT" => {
            fields(
                event,
                &[
                    "command_id",
                    "command_kind",
                    "command_fingerprint",
                    "schema_version",
                    "outcome_kind",
                    "outcome_id",
                    "accepted_at",
                ],
            )?;
            let admission = command(event)?;
            let outcome = Outcome::new(
                text(event, "outcome_kind")?
                    .parse::<OutcomeKind>()
                    .map_err(|_| INVALID)?,
                text(event, "outcome_id")?,
            )
            .map_err(|_| INVALID)?;
            Receipt::new(
                admission,
                outcome,
                &timestamp(event, "accepted_at")?.to_string(),
            )
            .map_err(|_| INVALID)?;
            Ok(())
        }
        _ => Err(INVALID),
    }
}
fn fields(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        Err(INVALID)
    } else {
        Ok(())
    }
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(INVALID)
}
fn sha(v: &Value, k: &str) -> Result<()> {
    if crate::is_sha256_hex(text(v, k)?) {
        Ok(())
    } else {
        Err(INVALID)
    }
}
fn optional_sha(v: &Value, k: &str) -> Result<bool> {
    if v[k].is_null() {
        Ok(false)
    } else {
        sha(v, k)?;
        Ok(true)
    }
}
fn uuid(v: &Value, k: &str) -> Result<()> {
    if crate::application::command::uuid4(text(v, k)?) {
        Ok(())
    } else {
        Err(INVALID)
    }
}
fn timestamp(v: &Value, k: &str) -> Result<OnlyUtcDateTime> {
    text(v, k)?.parse().map_err(|_| INVALID)
}
fn optional_time(v: &Value, k: &str) -> Result<Option<OnlyUtcDateTime>> {
    if v[k].is_null() {
        Ok(None)
    } else {
        timestamp(v, k).map(Some)
    }
}
fn command(v: &Value) -> Result<Admission> {
    if v["schema_version"].as_u64() != Some(1) {
        return Err(INVALID);
    }
    Admission::new(
        CommandId::new(text(v, "command_id")?).map_err(|_| INVALID)?,
        text(v, "command_kind")?
            .parse::<CommandKind>()
            .map_err(|_| INVALID)?,
        text(v, "command_fingerprint")?,
    )
    .map_err(|_| INVALID)
}
fn failure(v: &Value) -> Result<bool> {
    let keys = ["failure_phase", "failure_code", "failure_detail"];
    if keys.iter().all(|k| v[*k].is_null()) {
        return Ok(false);
    }
    let phase = match text(v, "failure_phase")? {
        "ADMISSION" => FailurePhase::Admission,
        "EXECUTION" => FailurePhase::Execution,
        "RESULT_COMMIT" => FailurePhase::ResultCommit,
        "ARTIFACT_COMMIT" => FailurePhase::ArtifactCommit,
        "OPERATIONAL" => FailurePhase::Operational,
        _ => return Err(INVALID),
    };
    Failure::new(phase, text(v, "failure_code")?, text(v, "failure_detail")?)
        .map_err(|_| INVALID)?;
    Ok(true)
}
fn attempt(v: &Value) -> Result<()> {
    fields(
        v,
        &[
            "attempt_id",
            "run_id",
            "attempt_number",
            "state",
            "worker_instance_id",
            "claimed_at",
            "last_heartbeat_at",
            "lease_expires_at",
            "finished_at",
            "failure_phase",
            "failure_code",
            "failure_detail",
        ],
    )?;
    for k in ["attempt_id", "run_id", "worker_instance_id"] {
        uuid(v, k)?;
    }
    if v["attempt_number"]
        .as_i64()
        .is_none_or(|n| n < 1 || n > i64::from(i32::MAX))
    {
        return Err(INVALID);
    }
    let claimed = timestamp(v, "claimed_at")?;
    let heartbeat = timestamp(v, "last_heartbeat_at")?;
    let lease = timestamp(v, "lease_expires_at")?;
    let finished = optional_time(v, "finished_at")?;
    let failure = failure(v)?;
    if heartbeat < claimed || lease < heartbeat || finished.is_some_and(|t| t < claimed) {
        return Err(INVALID);
    }
    match text(v, "state")? {
        "ACTIVE" if finished.is_none() && !failure => Ok(()),
        "SUCCEEDED" | "CANCELLED" if finished.is_some() && !failure => Ok(()),
        "FAILED" if finished.is_some() && failure => Ok(()),
        "EXPIRED" if finished.is_some_and(|at| at >= lease) && failure => Ok(()),
        _ => Err(INVALID),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn research_expired_attempt_requires_the_lease_fencing_boundary() {
        let mut event = json!({"attempt_id":"00000000-0000-4000-8000-000000000921","run_id":"00000000-0000-4000-8000-000000000922","attempt_number":1,"state":"EXPIRED","worker_instance_id":"00000000-0000-4000-8000-000000000923","claimed_at":"2026-10-29T03:00:00Z","last_heartbeat_at":"2026-10-29T03:00:00Z","lease_expires_at":"2026-10-29T03:02:00Z","finished_at":"2026-10-29T03:02:00Z","failure_phase":"OPERATIONAL","failure_code":"LEASE_EXPIRED","failure_detail":"controlled expiry"});
        attempt(&event).unwrap();
        event["finished_at"] = json!("2026-10-29T03:01:59.999999Z");
        assert_eq!(attempt(&event), Err(INVALID));
    }
}
fn run(v: &Value) -> Result<()> {
    fields(
        v,
        &[
            "run_id",
            "revision",
            "state",
            "specification_schema_version",
            "specification_fingerprint",
            "specification_payload",
            "admission_resolution_fingerprint",
            "queued_at",
            "started_at",
            "cancel_requested_at",
            "finished_at",
            "research_result_fingerprint",
            "artifact_content_fingerprint",
            "calculation_execution_evidence_fingerprints",
            "failure_phase",
            "failure_code",
            "failure_detail",
            "authoring_provenance",
            "strategy_research_composition_fingerprint",
            "origin_kind",
        ],
    )?;
    uuid(v, "run_id")?;
    let revision = v["revision"].as_i64().filter(|r| *r >= 0).ok_or(INVALID)?;
    let state = RunState::parse(text(v, "state")?).map_err(|_| INVALID)?;
    for k in [
        "specification_fingerprint",
        "admission_resolution_fingerprint",
    ] {
        sha(v, k)?;
    }
    let schema = v["specification_schema_version"].as_u64().ok_or(INVALID)?;
    if matches!(schema, 1..=3) {
        return Err(UNAVAILABLE);
    }
    if schema != 4
        || text(v, "origin_kind")? != "GENERAL"
        || !v["strategy_research_composition_fingerprint"].is_null()
    {
        return Err(INVALID);
    }
    let payload = text(v, "specification_payload")?;
    let canonical =
        onlyalpha_metadata_json::canonical_json(payload, 8 * 1024 * 1024).map_err(|_| INVALID)?;
    if canonical != payload {
        return Err(INVALID);
    }
    let spec: Value = serde_json::from_str(payload).map_err(|_| INVALID)?;
    crate::application::research_run::verify_native_spec_record(&spec).map_err(|_| INVALID)?;
    if crate::application::factor_content::hash(&spec).map_err(|_| INVALID)?
        != text(v, "specification_fingerprint")?
    {
        return Err(INVALID);
    }
    if !v["authoring_provenance"].is_null() {
        return Err(UNAVAILABLE);
    }
    let queued = timestamp(v, "queued_at")?;
    let started = optional_time(v, "started_at")?;
    let cancel = optional_time(v, "cancel_requested_at")?;
    let finished = optional_time(v, "finished_at")?;
    let result = optional_sha(v, "research_result_fingerprint")?;
    let artifact = optional_sha(v, "artifact_content_fingerprint")?;
    let failure = failure(v)?;
    let evidence = v["calculation_execution_evidence_fingerprints"]
        .as_array()
        .ok_or(INVALID)?
        .as_slice();
    if evidence
        .iter()
        .any(|f| !f.as_str().is_some_and(crate::is_sha256_hex))
        || evidence.windows(2).any(|w| w[0].as_str() >= w[1].as_str())
        || (!evidence.is_empty() && !result)
        || (artifact && !result)
    {
        return Err(INVALID);
    }
    if started.is_some_and(|t| t < queued)
        || cancel.is_some_and(|t| started.is_none_or(|s| t < s))
        || finished.is_some_and(|t| {
            t < queued || started.is_some_and(|s| t < s) || cancel.is_some_and(|c| t < c)
        })
        || state.terminal() != finished.is_some()
        || (state == RunState::Failed) != failure
    {
        return Err(INVALID);
    }
    match state {
        RunState::Queued
            if started.is_none()
                && cancel.is_none()
                && !result
                && !artifact
                && evidence.is_empty()
                && revision == 0 => {}
        RunState::Running
            if started.is_some() && cancel.is_none() && evidence.is_empty() && revision == 1 => {}
        RunState::CancelRequested
            if started.is_some() && cancel.is_some() && evidence.is_empty() && revision == 2 => {}
        RunState::Completed
            if started.is_some()
                && result
                && artifact
                && !evidence.is_empty()
                && revision == if cancel.is_some() { 3 } else { 2 } => {}
        RunState::Failed
            if started.is_some() && revision == if cancel.is_some() { 3 } else { 2 } => {}
        RunState::Cancelled if started.is_none() && cancel.is_none() && revision == 1 => {}
        RunState::Cancelled if started.is_some() && cancel.is_some() && revision == 3 => {}
        _ => return Err(INVALID),
    }
    Ok(())
}
