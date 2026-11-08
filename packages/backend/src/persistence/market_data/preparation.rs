//! 原始请求先入库，执行 occurrence 的输入证明最后一次性绑定到具体 Scope。
use super::*;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::{OnlyAdjustmentType, OnlyPriceType},
    identifiers::OnlyInstrumentId,
    market::{OnlyBarAlignment, OnlyBarFormation, OnlyBarSemantic, OnlyCalendarPeriodUnit},
    time::OnlyTradingDay,
};

pub(super) fn request_fingerprint(intent: &Value) -> Result<String> {
    let r = &intent["requested_scope"];
    exact_keys(
        r,
        &[
            "original_request_id",
            "source_id",
            "provider",
            "venue",
            "market",
            "environment",
            "integration_id",
            "integration_revision_fingerprint",
            "artifact_fingerprint",
            "implementation_fingerprint",
            "instrument_id",
            "bar_semantic",
            "start_ns",
            "end_ns",
            "adjustment_anchor",
        ],
    )?;
    for field in [
        "source_id",
        "provider",
        "market",
        "environment",
        "integration_id",
    ] {
        text(&r[field])?;
    }
    for field in [
        "integration_revision_fingerprint",
        "artifact_fingerprint",
        "implementation_fingerprint",
    ] {
        if !crate::is_sha256_hex(text(&r[field])?) {
            return Err(Error::Invalid);
        }
    }
    let instrument: OnlyInstrumentId = text(&r["instrument_id"])?
        .parse()
        .map_err(|_| Error::Invalid)?;
    let semantic = OnlyBarSemantic::from_record(&r["bar_semantic"]).map_err(|_| Error::Invalid)?;
    let start = integer(&r["start_ns"])?;
    let end = integer(&r["end_ns"])?;
    if instrument.venue().value() != text(&r["venue"])?
        || !crate::application::command::uuid4(text(&r["original_request_id"])?)
        || intent["source_id"] != r["source_id"]
        || intent["provenance"] != "REST_BACKFILL"
        || !crate::is_sha256_hex(text(&intent["integration_binding_fingerprint"])?)
        || start < 0
        || end <= start
        || semantic.price_type() != &OnlyPriceType::Last
        || !matches!(semantic.formation(), OnlyBarFormation::CalendarPeriod(f)
            if *f.unit()==OnlyCalendarPeriodUnit::Day && *f.alignment()==OnlyBarAlignment::SessionStart && f.count()==&1.into())
    {
        return Err(Error::Invalid);
    }
    if semantic.adjustment_policy() == &OnlyAdjustmentType::Forward {
        let anchor =
            OnlyTradingDay::from_record(&r["adjustment_anchor"]).map_err(|_| Error::Invalid)?;
        if anchor.to_record() != r["adjustment_anchor"] {
            return Err(Error::Invalid);
        }
    } else if !r["adjustment_anchor"].is_null() {
        return Err(Error::Invalid);
    }
    fingerprint(&json!({"identity_version":3,"requested_scope":r,
        "integration_binding_fingerprint":intent["integration_binding_fingerprint"],
        "provenance":intent["provenance"]}))
}

pub(super) fn bound_scope(
    intent: &AcquisitionIntent,
    attempt: &AcquisitionAttempt,
    record: &Value,
) -> Result<Scope> {
    use onlyalpha_domain::calendar::OnlyTradingCalendar;
    use std::collections::BTreeSet;
    exact_keys(
        record,
        &[
            "attempt_id",
            "input_manifest",
            "input_fingerprint",
            "requested_scope",
        ],
    )?;
    let i = intent.to_record();
    let r = &i["requested_scope"];
    let m = &record["input_manifest"];
    exact_keys(
        m,
        &[
            "acquisition_id",
            "attempt_id",
            "inputs",
            "calendar",
            "security",
            "factor_basis",
            "normalized_daily_fingerprint",
            "bar_query_fingerprint",
            "candidate_refs",
        ],
    )?;
    let scope = Scope::from_record(&record["requested_scope"])?;
    let s = &scope.record;
    let construction = &s["bar_construction"];
    let plan = &construction["plan"];
    let calendar =
        OnlyTradingCalendar::from_record(&m["calendar"]).map_err(|_| Error::Unprovable)?;
    let digest = fingerprint(m)?;
    if i["identity_version"] != 3
        || record["attempt_id"] != attempt.id()
        || record["input_fingerprint"] != digest
        || m["attempt_id"] != attempt.id()
        || m["acquisition_id"] != intent.id()
        || attempt.record["acquisition_id"] != intent.id()
        || ["source_id", "market", "instrument_id", "start_ns", "end_ns"]
            .iter()
            .any(|k| s[k] != r[k])
        || plan["integration_revision_fingerprint"] != r["integration_revision_fingerprint"]
        || plan["target_semantic"] != r["bar_semantic"]
        || calendar.to_record() != m["calendar"]
        || calendar.venue_id().value() != text(&r["venue"])?
        || plan["calendar_fingerprint"] != fingerprint(&m["calendar"])?
        || m["security"]["instrument_id"] != r["instrument_id"]
        || construction["provider_semantic"] != fingerprint(&m["security"])?
    {
        return Err(Error::Unprovable);
    }
    let mut queries = BTreeSet::new();
    let inputs = array(&m["inputs"])?;
    if inputs.is_empty() {
        return Err(Error::Unprovable);
    }
    for input in inputs {
        validate_input(input, attempt.id())?;
        if !queries.insert(text(&input["query_fingerprint"])?) {
            return Err(Error::Conflict);
        }
    }
    let candidates = refs(&m["candidate_refs"])?;
    if candidates.len() != 1 || !queries.contains(text(&m["bar_query_fingerprint"])?) {
        return Err(Error::Unprovable);
    }
    let factor = &m["factor_basis"];
    let raw = r["bar_semantic"]["adjustment_policy"] == "RAW";
    if raw != factor.is_null() || raw != construction["adjustment_evidence"].is_null() {
        return Err(Error::Unprovable);
    }
    if !raw
        && (construction["adjustment_evidence"] != fingerprint(factor)?
            || factor["anchor"] != r["adjustment_anchor"]
            || factor["instrument_id"] != r["instrument_id"])
    {
        return Err(Error::Unprovable);
    }
    if !crate::is_sha256_hex(text(&m["normalized_daily_fingerprint"])?) {
        return Err(Error::Unprovable);
    }
    let version = day_data_version(
        r,
        plan["calendar_fingerprint"].clone(),
        m["normalized_daily_fingerprint"].clone(),
        construction["provider_semantic"].clone(),
        construction["adjustment_evidence"].clone(),
    )?;
    if s["data_version"] != version {
        return Err(Error::Unprovable);
    }
    Ok(scope)
}

pub(super) fn validate_input(input: &Value, attempt: &str) -> Result<()> {
    let mut keys = vec![
        "attempt_id",
        "query_fingerprint",
        "query_document",
        "segment_id",
        "segment_content_hash",
        "raw_event_id",
        "raw_sha256",
    ];
    if let Some(producer) = input.get("producer_attempt_id") {
        if text(producer)? == attempt {
            return Err(Error::Conflict);
        }
        keys.push("producer_attempt_id");
    }
    exact_keys(input, &keys)?;
    if input["attempt_id"] != attempt
        || !input["query_document"].is_object()
        || input["query_fingerprint"] != fingerprint(&input["query_document"])?
        || !crate::is_sha256_hex(text(&input["segment_content_hash"])?)
        || !crate::is_sha256_hex(text(&input["raw_sha256"])?)
    {
        return Err(Error::Unprovable);
    }
    text(&input["segment_id"])?;
    text(&input["raw_event_id"])?;
    Ok(())
}

pub fn day_data_version(
    request: &Value,
    calendar: Value,
    daily: Value,
    security: Value,
    adjustment: Value,
) -> Result<String> {
    let basis = json!({"schema_version":1,"implementation":request["implementation_fingerprint"],"artifact":request["artifact_fingerprint"],
        "calendar_fingerprint":calendar,"normalized_daily_fingerprint":daily,
        "provider_semantic":security,"adjustment_evidence":adjustment,
        "adjustment_policy":request["bar_semantic"]["adjustment_policy"]});
    Ok(format!("history-day:{}", fingerprint(&basis)?))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn financial_day_identity_binds_actual_artifact_but_not_original_operation() {
        let mut r = json!({"artifact_fingerprint":"a".repeat(64),"implementation_fingerprint":"b".repeat(64),
            "bar_semantic":{"adjustment_policy":"RAW"},"original_request_id":"first"});
        let version = |r: &Value| {
            day_data_version(
                r,
                json!("calendar"),
                json!("daily"),
                json!("security"),
                Value::Null,
            )
            .unwrap()
        };
        let first = version(&r);
        r["original_request_id"] = "second".into();
        assert_eq!(first, version(&r));
        r["artifact_fingerprint"] = "c".repeat(64).into();
        assert_ne!(first, version(&r));
    }
}
