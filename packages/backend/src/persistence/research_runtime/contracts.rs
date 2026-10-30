//! Exact DTO invariants of the existing Generation/distribution authority.
use super::{INVALID, Result, exact, sha, text};
use serde_json::{Value, json};
use std::collections::BTreeSet;
fn identity(v: &Value, k: &str) -> Result<()> {
    let s = text(v, k)?;
    if s.len() > 256
        || !s.as_bytes()[0].is_ascii_alphanumeric()
        || !s
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
    {
        return Err(INVALID);
    }
    Ok(())
}
fn sorted<'a>(v: &'a Value, keys: &[&str]) -> Result<&'a [Value]> {
    let rows = v.as_array().ok_or(INVALID)?;
    let mut previous = None;
    for row in rows {
        let key = keys
            .iter()
            .map(|k| text(row, k).map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        if previous.as_ref().is_some_and(|p| p >= &key) {
            return Err(INVALID);
        }
        previous = Some(key);
    }
    Ok(rows)
}
fn implementation(v: &Value) -> Result<()> {
    exact(
        v,
        &[
            "kind",
            "type_id",
            "semantic_version",
            "backend",
            "implementation_fingerprint",
        ],
    )?;
    for k in ["kind", "type_id", "semantic_version", "backend"] {
        identity(v, k)?;
    }
    sha(v, "implementation_fingerprint")?;
    Ok(())
}
fn implementations(v: &Value) -> Result<()> {
    for row in sorted(
        v,
        &[
            "kind",
            "type_id",
            "semantic_version",
            "backend",
            "implementation_fingerprint",
        ],
    )? {
        implementation(row)?;
    }
    Ok(())
}
pub(super) fn generation(v: &Value) -> Result<()> {
    let core = &v["core_execution"];
    exact(
        core,
        &[
            "schema_version",
            "distribution_name",
            "distribution_version",
            "artifact_sha256",
        ],
    )?;
    if core["schema_version"].as_u64() != Some(1) {
        return Err(INVALID);
    }
    identity(core, "distribution_name")?;
    identity(core, "distribution_version")?;
    sha(core, "artifact_sha256")?;
    let providers = sorted(
        &v["providers"],
        &[
            "provider_id",
            "provider_version",
            "provider_content_fingerprint",
            "artifact_sha256",
        ],
    )?;
    if providers.is_empty() {
        return Err(INVALID);
    }
    let artifacts = v["artifact_sha256s"].as_array().ok_or(INVALID)?;
    for p in providers {
        exact(
            p,
            &[
                "provider_id",
                "provider_version",
                "provider_content_fingerprint",
                "artifact_sha256",
            ],
        )?;
        identity(p, "provider_id")?;
        identity(p, "provider_version")?;
        sha(p, "provider_content_fingerprint")?;
        sha(p, "artifact_sha256")?;
        if !artifacts.contains(&p["artifact_sha256"]) {
            return Err(INVALID);
        }
    }
    implementations(&v["implementations"])?;
    let mut previous = None;
    let mut factor_ids = BTreeSet::new();
    for p in v["private_factor_bindings"].as_array().ok_or(INVALID)? {
        exact(
            p,
            &[
                "provider_snapshot_fingerprint",
                "runtime_artifact_fingerprint",
                "entry",
            ],
        )?;
        sha(p, "provider_snapshot_fingerprint")?;
        sha(p, "runtime_artifact_fingerprint")?;
        let e = &p["entry"];
        let fields = [
            "factor_id",
            "semantic_version",
            "revision_fingerprint",
            "source_sha256",
            "source_artifact_fingerprint",
            "factor_api_version",
            "factor_api_contract_fingerprint",
            "research_adapter_fingerprint",
            "trading_adapter_fingerprint",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "equivalence_evidence_fingerprint",
        ];
        exact(e, &fields)?;
        identity(e, "factor_id")?;
        identity(e, "semantic_version")?;
        if e["factor_api_version"].as_u64().is_none_or(|n| n == 0) {
            return Err(INVALID);
        }
        for k in &fields[2..] {
            if *k != "factor_api_version" {
                sha(e, k)?;
            }
        }
        let key = (
            text(p, "provider_snapshot_fingerprint")?,
            text(p, "runtime_artifact_fingerprint")?,
        );
        // A source snapshot has one entry for each Factor, so equal first two keys
        // use the entry's declared dataclass field order, not JSON key order.
        let mut ordering = vec![key.0.to_owned(), key.1.to_owned()];
        ordering.extend(fields.iter().map(|k| e[*k].to_string()));
        if previous.as_ref().is_some_and(|old| old >= &ordering)
            || !factor_ids.insert(text(e, "factor_id")?)
        {
            return Err(INVALID);
        }
        previous = Some(ordering);
        for (backend, key) in [
            ("RESEARCH", "research_implementation_fingerprint"),
            ("TRADING", "trading_implementation_fingerprint"),
        ] {
            let required = json!({"kind":"FACTOR","type_id":e["factor_id"],"semantic_version":e["semantic_version"],"backend":backend,"implementation_fingerprint":e[key]});
            if !v["implementations"]
                .as_array()
                .ok_or(INVALID)?
                .contains(&required)
            {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}
pub(super) fn artifact(v: &Value) -> Result<()> {
    exact(
        v,
        &[
            "schema_version",
            "role",
            "source_provenance_authority",
            "source_repository",
            "source_revision",
            "distribution_name",
            "distribution_version",
            "artifact_logical_name",
            "artifact_sha256",
            "artifact_size",
            "tested_core_execution_fingerprint",
            "provider_id",
            "provider_version",
            "provider_content_fingerprint",
            "assets",
            "implementations",
            "manifest_fingerprint",
        ],
    )?;
    if v["schema_version"].as_u64() != Some(1) || v["artifact_size"].as_u64().is_none_or(|n| n == 0)
    {
        return Err(INVALID);
    }
    for k in [
        "source_repository",
        "source_revision",
        "distribution_name",
        "distribution_version",
        "artifact_logical_name",
    ] {
        identity(v, k)?;
    }
    sha(v, "artifact_sha256")?;
    let authority = text(v, "source_provenance_authority")?;
    if !matches!(authority, "ONLYALPHA_GIT" | "EXTERNAL_RELEASE") {
        return Err(INVALID);
    }
    if authority == "ONLYALPHA_GIT" {
        let r = text(v, "source_revision")?;
        if !matches!(r.len(), 40 | 64)
            || !r
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(INVALID);
        }
    }
    let name = text(v, "distribution_name")?;
    let mut normalized = String::new();
    for b in name.bytes() {
        if b"-_.".contains(&b) {
            if !normalized.ends_with('_') {
                normalized.push('_')
            }
        } else {
            normalized.push((b as char).to_ascii_lowercase())
        }
    }
    let version = text(v, "distribution_version")?
        .replace('-', "_")
        .to_ascii_lowercase();
    let file = text(v, "artifact_logical_name")?;
    if !file
        .to_ascii_lowercase()
        .starts_with(&format!("{normalized}-{version}-"))
    {
        return Err(INVALID);
    }
    let role = text(v, "role")?;
    if !matches!(
        role,
        "CORE"
            | "SUPPORT"
            | "QUANT_ASSET"
            | "CALCULATION"
            | "BACKTEST_RUNTIME"
            | "RESEARCH_RUNTIME"
    ) {
        return Err(INVALID);
    }
    if matches!(role, "BACKTEST_RUNTIME" | "RESEARCH_RUNTIME") {
        let (distribution, prefix) = if role == "BACKTEST_RUNTIME" {
            ("onlyalpha-backtest-driver", "onlyalpha_backtest_driver")
        } else {
            ("onlyalpha-backend", "onlyalpha_backend")
        };
        if name != distribution
            || authority != "ONLYALPHA_GIT"
            || !["aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"]
                .iter()
                .any(|t| file == format!("{prefix}-{version}-{t}.elf"))
            || v["tested_core_execution_fingerprint"].is_null()
        {
            return Err(INVALID);
        }
    } else if !file.to_ascii_lowercase().ends_with(".whl")
        && (name != "onlyalpha-kernel"
            || role != "SUPPORT"
            || authority != "ONLYALPHA_GIT"
            || !v["tested_core_execution_fingerprint"].is_null()
            || !["aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"]
                .iter()
                .any(|t| file == format!("onlyalpha_kernel-{version}-{t}.elf")))
    {
        return Err(INVALID);
    }
    if !v["tested_core_execution_fingerprint"].is_null() {
        sha(v, "tested_core_execution_fingerprint")?;
    }
    for k in ["provider_id", "provider_version"] {
        if !v[k].is_null() {
            identity(v, k)?;
        }
    }
    if !v["provider_content_fingerprint"].is_null() {
        sha(v, "provider_content_fingerprint")?;
    }
    let assets = sorted(
        &v["assets"],
        &[
            "kind",
            "asset_id",
            "semantic_version",
            "content_fingerprint",
        ],
    )?;
    for a in assets {
        exact(
            a,
            &[
                "kind",
                "asset_id",
                "semantic_version",
                "content_fingerprint",
            ],
        )?;
        for k in ["kind", "asset_id", "semantic_version"] {
            identity(a, k)?;
        }
        sha(a, "content_fingerprint")?;
    }
    implementations(&v["implementations"])?;
    let empty = v["implementations"].as_array().ok_or(INVALID)?.is_empty();
    let provider = [
        "provider_id",
        "provider_version",
        "provider_content_fingerprint",
    ];
    if role == "QUANT_ASSET" {
        if assets.is_empty()
            || provider.iter().any(|k| v[*k].is_null())
            || v["tested_core_execution_fingerprint"].is_null()
        {
            return Err(INVALID);
        }
    } else if provider.iter().any(|k| !v[*k].is_null())
        || !assets.is_empty()
        || (role == "CALCULATION" && (empty || v["tested_core_execution_fingerprint"].is_null()))
        || (role != "CALCULATION" && !empty)
    {
        return Err(INVALID);
    }
    Ok(())
}
