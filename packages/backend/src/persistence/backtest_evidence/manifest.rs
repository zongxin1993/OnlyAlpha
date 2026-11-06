//! Strict public Evidence1 and explicit fixed-native Evidence2 values.
//! A parsed manifest is neither a producer nor a CompletionProof.
use crate::application::{command, factor_content::hash};
use serde_json::Value;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "BACKTEST_EVIDENCE_CORRUPT";
const LIMIT: usize = 8 * 1024 * 1024;
const COMMON: [&str; 7] = [
    "schema_version",
    "backtest_run_id",
    "specification_fingerprint",
    "admission_resolution_fingerprint",
    "strategy_fingerprint",
    "result_fingerprint",
    "determinism_fingerprint",
];
const LEGACY: [&str; 10] = [
    "dataset_binding_fingerprint",
    "base_dataset_snapshot_fingerprint",
    "market_product_composition_fingerprint",
    "portfolio_profile_fingerprint",
    "risk_profile_fingerprint",
    "execution_profile_fingerprint",
    "kernel_semantics_version",
    "implementation_fingerprints",
    "artifacts",
    "evidence_fingerprint",
];
const NATIVE: [&str; 7] = [
    "kind",
    "dataset_snapshot_fingerprint",
    "dataset_binding_fingerprint",
    "runtime_generation_fingerprint",
    "preparation_fingerprint",
    "artifacts",
    "evidence_fingerprint",
];
const STREAMED: [&str; 9] = [
    "kind",
    "dataset_snapshot_fingerprint",
    "dataset_binding_fingerprint",
    "runtime_generation_fingerprint",
    "preparation_fingerprint",
    "artifacts",
    "evidence_fingerprint",
    "trace_format",
    "logical_trace_fingerprint",
];
pub(super) const NAMES: [&str; 5] = [
    "observation.json",
    "replay-proof.json",
    "replay-trace.json",
    "result.json",
    "runtime.json",
];
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key].as_str().ok_or(INVALID)
}
fn fields<'a>(value: &Value, names: impl IntoIterator<Item = &'a str>) -> Result<()> {
    let names = names.into_iter().collect::<std::collections::BTreeSet<_>>();
    let object = value.as_object().ok_or(INVALID)?;
    if object.len() != names.len() || object.keys().any(|k| !names.contains(k.as_str())) {
        return Err(INVALID);
    }
    Ok(())
}
fn pin(value: &Value, key: &str) -> Result<()> {
    if crate::is_sha256_hex(text(value, key)?) {
        Ok(())
    } else {
        Err(INVALID)
    }
}
pub(super) fn artifact_name(value: &str) -> Result<()> {
    if value.is_empty()
        || value.starts_with('/')
        || value.contains('\\')
        || value.contains('\0')
        || value
            .split('/')
            .any(|p| p.is_empty() || p == "." || p == "..")
        || value.rsplit('/').next() == Some("manifest.json")
    {
        return Err(INVALID);
    }
    Ok(())
}
#[derive(Clone)]
pub struct Manifest(Value);
impl Manifest {
    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > LIMIT {
            return Err("BACKTEST_EVIDENCE_UNAVAILABLE");
        }
        let version = value["schema_version"].as_u64().ok_or(INVALID)?;
        let extension = match version {
            1 => LEGACY.as_slice(),
            2 => NATIVE.as_slice(),
            3 => STREAMED.as_slice(),
            _ => return Err(INVALID),
        };
        fields(value, COMMON.into_iter().chain(extension.iter().copied()))?;
        if text(value, "backtest_run_id")?.is_empty() {
            return Err(INVALID);
        }
        for key in [
            "specification_fingerprint",
            "admission_resolution_fingerprint",
            "strategy_fingerprint",
            "result_fingerprint",
            "determinism_fingerprint",
            "dataset_binding_fingerprint",
        ] {
            pin(value, key)?;
        }
        if version == 1 {
            for key in [
                "base_dataset_snapshot_fingerprint",
                "market_product_composition_fingerprint",
                "portfolio_profile_fingerprint",
                "risk_profile_fingerprint",
                "execution_profile_fingerprint",
            ] {
                pin(value, key)?;
            }
            if text(value, "kernel_semantics_version")?.trim().is_empty() {
                return Err(INVALID);
            }
            let implementations = value["implementation_fingerprints"]
                .as_array()
                .ok_or(INVALID)?;
            let mut previous = None;
            for implementation in implementations {
                let identity = implementation
                    .as_str()
                    .filter(|s| crate::is_sha256_hex(s))
                    .ok_or(INVALID)?;
                if previous.is_some_and(|p| p >= identity) {
                    return Err(INVALID);
                }
                previous = Some(identity);
            }
        } else {
            if value["kind"] != "NATIVE_BTC_SPOT_NEXT_OPEN_EVIDENCE"
                || !command::uuid4(text(value, "backtest_run_id")?)
            {
                return Err(INVALID);
            }
            for key in [
                "dataset_snapshot_fingerprint",
                "runtime_generation_fingerprint",
                "preparation_fingerprint",
            ] {
                pin(value, key)?;
            }
        }
        if version == 3 {
            if value["trace_format"] != "RUNTIME_ENCODED_REPLAY_TRACE@2" {
                return Err(INVALID);
            }
            pin(value, "logical_trace_fingerprint")?;
        }
        let artifacts = value["artifacts"].as_array().ok_or(INVALID)?;
        if version >= 2 && artifacts.len() != NAMES.len() {
            return Err(INVALID);
        }
        let mut previous = None;
        for (index, artifact) in artifacts.iter().enumerate() {
            fields(artifact, ["name", "sha256", "size", "media_type"])?;
            let name = text(artifact, "name")?;
            artifact_name(name)?;
            if previous.is_some_and(|p| p >= name) {
                return Err(INVALID);
            }
            previous = Some(name);
            pin(artifact, "sha256")?;
            artifact["size"].as_u64().ok_or(INVALID)?;
            let media = text(artifact, "media_type")?;
            if media.is_empty()
                || (version >= 2 && (name != NAMES[index] || media != "application/json"))
            {
                return Err(INVALID);
            }
        }
        pin(value, "evidence_fingerprint")?;
        let mut body = value.clone();
        body.as_object_mut()
            .ok_or(INVALID)?
            .remove("evidence_fingerprint");
        if hash(&body)? != value["evidence_fingerprint"] {
            return Err(INVALID);
        }
        Ok(Self(value.clone()))
    }
    pub fn schema_version(&self) -> u64 {
        self.0["schema_version"].as_u64().expect("verified version")
    }
    pub fn fingerprint(&self) -> &str {
        self.0["evidence_fingerprint"]
            .as_str()
            .expect("verified identity")
    }
    pub fn record(&self) -> &Value {
        &self.0
    }
}
