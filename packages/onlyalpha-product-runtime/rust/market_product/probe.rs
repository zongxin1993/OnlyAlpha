//! Exact native Probe execution and append-only owning PostgreSQL projection.
use super::*;
use crate::{market_product::queries::Application, source_access::Selection};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio_postgres::{Client, IsolationLevel};
pub trait ProbeAdmission: Send + Sync {
    fn require_probe(&self, selection: &Selection, attempt_id: &str) -> Result<()>;
}
pub struct CompletedProbe {
    resolved: Arc<Resolved>,
    admission: Arc<dyn ProbeAdmission>,
    attempt: String,
    document: Value,
    fingerprint: String,
    started: String,
    completed: String,
    status: &'static str,
}
fn utc(ns: i64) -> Result<String> {
    Ok(time(ns.div_euclid(1000) * 1000)?
        .to_string()
        .replace('Z', "+00:00"))
}
impl Application {
    pub async fn execute_probe(
        &self,
        r: Arc<Resolved>,
        admission: Arc<dyn ProbeAdmission>,
        attempt_id: &str,
        deadline: Instant,
    ) -> Result<CompletedProbe> {
        if !crate::command::uuid4(attempt_id) {
            return Err(Error::Invalid);
        }
        admission.require_probe(&r.selection, attempt_id)?;
        let deadline = deadline.min(Instant::now() + Duration::from_secs(15));
        let raw = r.resource.probe(&r.probe_symbol, budget(deadline)?).await?;
        admission.require_probe(&r.selection, attempt_id)?;
        let started = utc(raw["started_at_ns"].as_i64().ok_or(Error::Corrupt)?)?;
        let completed = utc(raw["completed_at_ns"].as_i64().ok_or(Error::Corrupt)?)?;
        let raw_checks = raw["checks"].as_array().ok_or(Error::Corrupt)?;
        let expected = [
            "CONNECTIVITY",
            "HISTORICAL_DATA",
            "REALTIME_DATA",
            "REFERENCE_DATA",
        ];
        let mut checks = vec![];
        for name in expected {
            let rows = raw_checks
                .iter()
                .filter(|c| c["check"] == name)
                .collect::<Vec<_>>();
            if rows.len() != 1 {
                return Err(Error::Corrupt);
            }
            let c = rows[0];
            let start = c["started_at_ns"].as_i64().ok_or(Error::Corrupt)?;
            let end = c["completed_at_ns"]
                .as_i64()
                .filter(|n| *n >= start)
                .ok_or(Error::Corrupt)?;
            let passed = c["status"] == "READY";
            checks.push(json!({"check":name,"status":if passed{"PASS"}else{"FAIL"},"latency_ms":(end-start)/1_000_000,"failure_kind":if passed{None}else{Some(if name=="CONNECTIVITY"{"OFFLINE"}else{"DEGRADED"})},"error_code":if passed{Value::Null}else{c["detail"].clone()},"detail":"","observations":[]}));
        }
        if raw_checks.len() != 4 || completed < started {
            return Err(Error::Corrupt);
        }
        let status = overall(&checks)?;
        let document = json!({"probe_attempt_id":attempt_id,"integration_id":r.selection.reference().integration_id(),"revision_fingerprint":r.selection.reference().revision(),"overall_status":status,"started_at":started,"completed_at":completed,"probe_instrument":r.probe_symbol,"checks":checks});
        validate_document(&document, &r)?;
        let fingerprint = fp(&document)?;
        Ok(CompletedProbe {
            resolved: r,
            admission,
            attempt: attempt_id.into(),
            document,
            fingerprint,
            started,
            completed,
            status,
        })
    }
}
impl CompletedProbe {
    fn check(&self) -> Result<()> {
        self.admission
            .require_probe(&self.resolved.selection, &self.attempt)
    }
    pub fn document(&self) -> &Value {
        &self.document
    }
    pub async fn persist(&self, client: &mut Client) -> Result<Value> {
        self.check()?;
        let r = &self.resolved;
        let b = r.binding.record();
        let tx = client
            .build_transaction()
            .isolation_level(IsolationLevel::ReadCommitted)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        crate::postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        tx.batch_execute("SET LOCAL search_path=pg_catalog,public")
            .await
            .map_err(|_| Error::Unavailable)?;
        // Re-prove the exact original Revision relation in the owning commit. No
        // replacement Revision/current-head/probe readiness policy is inferred here.
        let rows=tx.query("SELECT type_descriptor_fingerprint,runtime_configuration_fingerprint,probe_configuration_fingerprint FROM public.integration_revision WHERE integration_id=$1::text::uuid AND revision_fingerprint=$2 FOR SHARE",&[&b.integration_id.value(),&b.revision_fingerprint]).await.map_err(|_|Error::Unavailable)?;
        if rows.len() != 1
            || rows[0]
                .try_get::<_, String>(0)
                .map_err(|_| Error::Corrupt)?
                != b.type_descriptor_fingerprint
            || rows[0]
                .try_get::<_, String>(1)
                .map_err(|_| Error::Corrupt)?
                != b.runtime_configuration_fingerprint
            || rows[0]
                .try_get::<_, Option<String>>(2)
                .map_err(|_| Error::Corrupt)?
                != r.probe_configuration
        {
            return Err(Error::Corrupt);
        }
        self.check()?;
        let raw = self.document.to_string();
        tx.execute("INSERT INTO public.integration_probe_attempt(probe_attempt_id,integration_id,revision_fingerprint,type_id,type_descriptor_fingerprint,probe_contract_fingerprint,probe_configuration_fingerprint,runtime_configuration_fingerprint,started_at,completed_at,overall_status,result_fingerprint,result_document) VALUES($1::text::uuid,$2::text::uuid,$3,$4,$5,$6,$7,$8,$9::text::timestamptz,$10::text::timestamptz,$11,$12,$13::text::json) ON CONFLICT DO NOTHING",&[&self.attempt,&b.integration_id.value(),&b.revision_fingerprint,&b.type_id.value(),&b.type_descriptor_fingerprint,&r.probe_contract,&r.probe_configuration,&b.runtime_configuration_fingerprint,&self.started,&self.completed,&self.status,&self.fingerprint,&raw]).await.map_err(|_|Error::Unavailable)?;
        let row=tx.query_one("SELECT result_fingerprint,result_document::text FROM public.integration_probe_attempt WHERE probe_attempt_id=$1::text::uuid",&[&self.attempt]).await.map_err(|_|Error::Unavailable)?;
        let stored: String = row.try_get(1).map_err(|_| Error::Corrupt)?;
        let value: Value = serde_json::from_str(&stored).map_err(|_| Error::Corrupt)?;
        if row.try_get::<_, String>(0).map_err(|_| Error::Corrupt)? != self.fingerprint
            || fp(&value)? != self.fingerprint
            || canonical(&value)? != canonical(&self.document)?
        {
            return Err(Error::Conflict);
        }
        self.check()?;
        tx.commit().await.map_err(|_| Error::Unknown)?;
        self.check()?;
        Ok(self.document.clone())
    }
}
/// No attempt stays UNKNOWN; an unavailable/corrupt proof is never UNKNOWN.
pub async fn latest_probe(client: &Client, r: &Resolved) -> Result<Value> {
    let b = r.binding.record();
    let rows=client.query("SELECT result_fingerprint,result_document::text,type_id,type_descriptor_fingerprint,probe_contract_fingerprint,probe_configuration_fingerprint,runtime_configuration_fingerprint,to_char(started_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),to_char(completed_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),overall_status,probe_attempt_id::text FROM public.integration_probe_attempt WHERE integration_id=$1::text::uuid AND revision_fingerprint=$2 ORDER BY completed_at DESC,probe_attempt_id DESC LIMIT 1",&[&b.integration_id.value(),&b.revision_fingerprint]).await.map_err(|_|Error::Unavailable)?;
    let Some(row) = rows.first() else {
        return Ok(json!({"status":"UNKNOWN","latest_attempt":null}));
    };
    let stored = row.try_get::<_, String>(1).map_err(|_| Error::Corrupt)?;
    let value: Value = serde_json::from_str(&stored).map_err(|_| Error::Corrupt)?;
    if onlyalpha_metadata_json::canonical_json(&stored, 1024 * 1024).map_err(|_| Error::Corrupt)?
        != canonical(&value)?
    {
        return Err(Error::Corrupt);
    }
    validate_document(&value, r)?;
    for (index, key) in [(7, "started_at"), (8, "completed_at")] {
        let column: onlyalpha_domain::time::OnlyUtcDateTime = row
            .try_get::<_, String>(index)
            .map_err(|_| Error::Corrupt)?
            .parse()
            .map_err(|_| Error::Corrupt)?;
        let document: onlyalpha_domain::time::OnlyUtcDateTime = value[key]
            .as_str()
            .ok_or(Error::Corrupt)?
            .parse()
            .map_err(|_| Error::Corrupt)?;
        if column != document {
            return Err(Error::Corrupt);
        }
    }
    if fp(&value)? != row.try_get::<_, String>(0).map_err(|_| Error::Corrupt)?
        || row.try_get::<_, String>(2).map_err(|_| Error::Corrupt)? != b.type_id.value()
        || row.try_get::<_, String>(3).map_err(|_| Error::Corrupt)? != b.type_descriptor_fingerprint
        || row.try_get::<_, String>(4).map_err(|_| Error::Corrupt)? != r.probe_contract
        || row
            .try_get::<_, Option<String>>(5)
            .map_err(|_| Error::Corrupt)?
            != r.probe_configuration
        || row.try_get::<_, String>(6).map_err(|_| Error::Corrupt)?
            != b.runtime_configuration_fingerprint
        || value["integration_id"] != b.integration_id.value()
        || value["revision_fingerprint"] != b.revision_fingerprint
        || value["probe_attempt_id"] != row.try_get::<_, String>(10).map_err(|_| Error::Corrupt)?
        || value["overall_status"] != row.try_get::<_, String>(9).map_err(|_| Error::Corrupt)?
    {
        return Err(Error::Corrupt);
    }
    Ok(json!({"status":value["overall_status"],"latest_attempt":value}))
}
fn keys(value: &Value, expected: &[&str]) -> Result<()> {
    let fields = value.as_object().ok_or(Error::Corrupt)?;
    if fields.len() != expected.len() || expected.iter().any(|k| !fields.contains_key(*k)) {
        return Err(Error::Corrupt);
    }
    Ok(())
}
fn overall(checks: &[Value]) -> Result<&'static str> {
    for (kind, status) in [("OFFLINE", "OFFLINE"), ("FAILED", "FAILED")] {
        if checks
            .iter()
            .any(|c| c["status"] == "FAIL" && c["failure_kind"] == kind)
        {
            return Ok(status);
        }
    }
    if checks.iter().any(|c| c["status"] != "PASS") {
        Ok("DEGRADED")
    } else {
        Ok("READY")
    }
}
fn validate_document(value: &Value, r: &Resolved) -> Result<()> {
    validate_original_document(
        value,
        r.selection.reference().integration_id(),
        r.selection.reference().revision(),
        Some(&r.probe_symbol),
        &[
            "CONNECTIVITY".into(),
            "HISTORICAL_DATA".into(),
            "REALTIME_DATA".into(),
            "REFERENCE_DATA".into(),
        ],
    )
}
fn validate_original_document(
    value: &Value,
    integration: &str,
    revision: &str,
    probe_symbol: Option<&str>,
    expected_checks: &[String],
) -> Result<()> {
    keys(
        value,
        &[
            "probe_attempt_id",
            "integration_id",
            "revision_fingerprint",
            "overall_status",
            "started_at",
            "completed_at",
            "probe_instrument",
            "checks",
        ],
    )?;
    if !crate::command::uuid4(value["probe_attempt_id"].as_str().ok_or(Error::Corrupt)?)
        || value["integration_id"] != integration
        || value["revision_fingerprint"] != revision
        || match probe_symbol {
            Some(symbol) => value["probe_instrument"] != symbol,
            None => !value["probe_instrument"].is_null(),
        }
    {
        return Err(Error::Corrupt);
    }
    let start: onlyalpha_domain::time::OnlyUtcDateTime = value["started_at"]
        .as_str()
        .ok_or(Error::Corrupt)?
        .parse()
        .map_err(|_| Error::Corrupt)?;
    let end: onlyalpha_domain::time::OnlyUtcDateTime = value["completed_at"]
        .as_str()
        .ok_or(Error::Corrupt)?
        .parse()
        .map_err(|_| Error::Corrupt)?;
    if end < start {
        return Err(Error::Corrupt);
    }
    let checks = value["checks"]
        .as_array()
        .filter(|v| v.len() == expected_checks.len())
        .ok_or(Error::Corrupt)?;
    let mut count = 0usize;
    for (check, name) in checks.iter().zip(expected_checks) {
        keys(
            check,
            &[
                "check",
                "status",
                "latency_ms",
                "failure_kind",
                "error_code",
                "detail",
                "observations",
            ],
        )?;
        if check["check"].as_str() != Some(name.as_str())
            || check["latency_ms"].as_i64().is_none_or(|n| n < 0)
            || check["detail"]
                .as_str()
                .is_none_or(|v| v.chars().count() > 500)
        {
            return Err(Error::Corrupt);
        }
        let observations = check["observations"].as_array().ok_or(Error::Corrupt)?;
        count = count
            .checked_add(observations.len())
            .ok_or(Error::Corrupt)?;
        if count > 8
            || observations
                .iter()
                .any(|v| v.as_str().is_none_or(|s| s.chars().count() > 200))
        {
            return Err(Error::Corrupt);
        }
        match check["status"].as_str() {
            Some("FAIL") => {
                if !matches!(
                    check["failure_kind"].as_str(),
                    Some("DEGRADED" | "OFFLINE" | "FAILED")
                ) {
                    return Err(Error::Corrupt);
                }
                let code = check["error_code"].as_str().ok_or(Error::Corrupt)?;
                if !code.as_bytes().first().is_some_and(u8::is_ascii_uppercase)
                    || !code
                        .bytes()
                        .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == b'_')
                {
                    return Err(Error::Corrupt);
                }
            }
            Some("PASS" | "SKIPPED") => {
                if !check["failure_kind"].is_null() || !check["error_code"].is_null() {
                    return Err(Error::Corrupt);
                }
            }
            _ => return Err(Error::Corrupt),
        }
    }
    if value["overall_status"] != overall(checks)? {
        return Err(Error::Corrupt);
    }
    Ok(())
}
/// Observe original append-only Probe receipts using their verified original
/// Revision relation. Current executable admission is intentionally irrelevant.
pub async fn probe_attempts(
    client: &mut Client,
    snapshot: &crate::integration_postgres::Snapshot,
    max_rows: usize,
) -> Result<Vec<Value>> {
    if max_rows == 0 || max_rows > 10000 {
        return Err(Error::Invalid);
    }
    let tx = client
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .map_err(|_| Error::Unavailable)?;
    crate::postgres::bounds(&tx)
        .await
        .map_err(|_| Error::Unavailable)?;
    let owner = snapshot.integration().record();
    let bound = i64::try_from(max_rows + 1).map_err(|_| Error::Invalid)?;
    let rows=tx.query("SELECT probe_attempt_id::text,integration_id::text,revision_fingerprint,type_id,type_descriptor_fingerprint,probe_contract_fingerprint,probe_configuration_fingerprint,runtime_configuration_fingerprint,to_char(started_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),to_char(completed_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),overall_status,result_fingerprint,result_document::text FROM public.integration_probe_attempt WHERE integration_id=$1::text::uuid ORDER BY completed_at DESC,probe_attempt_id DESC LIMIT $2",&[&owner.integration_id.value(),&bound]).await.map_err(|_|Error::Unavailable)?;
    if rows.len() > max_rows {
        return Err(Error::Unavailable);
    }
    let mut result = vec![];
    let mut used = 0usize;
    for row in rows {
        let column = |i| row.try_get::<_, String>(i).map_err(|_| Error::Corrupt);
        let pin = column(2)?;
        let (revision, _) = snapshot
            .history()
            .iter()
            .find(|(r, _)| r.record().revision_fingerprint == pin)
            .ok_or(Error::Corrupt)?;
        let r = revision.record();
        let descriptor: Value = serde_json::from_str(r.type_descriptor_document.raw().get())
            .map_err(|_| Error::Corrupt)?;
        let contract = &descriptor["probe_contract"];
        let contract_fp = contract["fingerprint"].as_str().ok_or(Error::Corrupt)?;
        let config = r
            .probe_configuration_document
            .as_ref()
            .map(|d| serde_json::from_str::<Value>(d.raw().get()))
            .transpose()
            .map_err(|_| Error::Corrupt)?;
        let instrument = config
            .as_ref()
            .and_then(|v| v["instrument"].as_str())
            .or_else(|| contract["default_probe_instrument"].as_str());
        let mut checks = contract["probe_checks"]
            .as_array()
            .ok_or(Error::Corrupt)?
            .iter()
            .map(|v| v.as_str().map(String::from).ok_or(Error::Corrupt))
            .collect::<Result<Vec<_>>>()?;
        checks.sort();
        if checks.windows(2).any(|p| p[0] == p[1]) {
            return Err(Error::Corrupt);
        }
        let raw = column(12)?;
        used = used
            .checked_add(raw.len())
            .filter(|n| *n <= 64 * 1024 * 1024)
            .ok_or(Error::Unavailable)?;
        let mut value: Value = serde_json::from_str(&raw).map_err(|_| Error::Corrupt)?;
        if onlyalpha_metadata_json::canonical_json(&raw, 64 * 1024 * 1024)
            .map_err(|_| Error::Corrupt)?
            != canonical(&value)?
            || fp(&value)? != column(11)?
        {
            return Err(Error::Corrupt);
        }
        validate_original_document(
            &value,
            owner.integration_id.value(),
            &pin,
            instrument,
            &checks,
        )?;
        let started: onlyalpha_domain::time::OnlyUtcDateTime =
            column(8)?.parse().map_err(|_| Error::Corrupt)?;
        let completed: onlyalpha_domain::time::OnlyUtcDateTime =
            column(9)?.parse().map_err(|_| Error::Corrupt)?;
        if value["probe_attempt_id"] != column(0)?
            || column(1)? != owner.integration_id.value()
            || column(3)? != r.type_id.value()
            || column(4)? != r.type_descriptor_fingerprint
            || column(5)? != contract_fp
            || row
                .try_get::<_, Option<String>>(6)
                .map_err(|_| Error::Corrupt)?
                != r.probe_configuration_fingerprint
            || column(7)? != r.runtime_configuration_fingerprint
            || value["started_at"]
                .as_str()
                .ok_or(Error::Corrupt)?
                .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()
                .map_err(|_| Error::Corrupt)?
                != started
            || value["completed_at"]
                .as_str()
                .ok_or(Error::Corrupt)?
                .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()
                .map_err(|_| Error::Corrupt)?
                != completed
            || value["overall_status"] != column(10)?
        {
            return Err(Error::Corrupt);
        }
        value["schema_version"] = json!(1);
        value["type_id"] = json!(r.type_id.value());
        value["type_descriptor_fingerprint"] = json!(r.type_descriptor_fingerprint);
        value["probe_contract_fingerprint"] = json!(contract_fp);
        value["probe_configuration_fingerprint"] = json!(r.probe_configuration_fingerprint);
        value["runtime_configuration_fingerprint"] = json!(r.runtime_configuration_fingerprint);
        result.push(value);
    }
    tx.commit().await.map_err(|_| Error::Unavailable)?;
    Ok(result)
}
