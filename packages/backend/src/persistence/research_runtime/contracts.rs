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
    let schema = v["schema_version"].as_u64();
    let mut fields = vec![
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
    ];
    if matches!(schema, Some(2 | 3)) {
        fields.push("execution_capabilities");
    } else if schema != Some(1) {
        return Err(INVALID);
    }
    exact(v, &fields)?;
    if v["artifact_size"].as_u64().is_none_or(|n| n == 0) {
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
    if (schema == Some(1)
        && !matches!(
            role,
            "CORE"
                | "SUPPORT"
                | "QUANT_ASSET"
                | "CALCULATION"
                | "BACKTEST_RUNTIME"
                | "RESEARCH_RUNTIME"
        ))
        || (matches!(schema, Some(2 | 3)) && role != "BACKEND_RUNTIME")
    {
        return Err(INVALID);
    }
    // Old Research-only V2 manifests remain exact immutable history. Current
    // images may also declare the concrete, separately admitted Backtest owner.
    if matches!(schema, Some(2 | 3))
        && v["execution_capabilities"]
            != json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"}])
        && v["execution_capabilities"]
            != json!([
                {"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"},
                {"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}
            ])
    {
        return Err(INVALID);
    }
    if matches!(
        role,
        "BACKTEST_RUNTIME" | "RESEARCH_RUNTIME" | "BACKEND_RUNTIME"
    ) {
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
    if role == "QUANT_ASSET" || schema == Some(3) {
        if assets.is_empty()
            || provider.iter().any(|k| v[*k].is_null())
            || v["tested_core_execution_fingerprint"].is_null()
        {
            return Err(INVALID);
        }
    } else if provider.iter().any(|k| !v[*k].is_null())
        || !assets.is_empty()
        || (matches!(role, "CALCULATION" | "BACKEND_RUNTIME")
            && (empty || v["tested_core_execution_fingerprint"].is_null()))
        || (!matches!(role, "CALCULATION" | "BACKEND_RUNTIME") && !empty)
    {
        return Err(INVALID);
    }
    if role == "BACKEND_RUNTIME" && schema == Some(3) {
        let image = text(v, "artifact_sha256")?;
        let provider = onlyalpha_calculation_bridge::native_operators::provider_record(
            image,
            text(v, "distribution_version")?,
        )
        .map_err(|_| INVALID)?;
        if v["provider_id"] != provider["manifest"]["provider_id"]
            || v["provider_version"] != provider["manifest"]["provider_version"]
            || v["provider_content_fingerprint"] != provider["content_fingerprint"]
        {
            return Err(INVALID);
        }
        let mut expected_assets = std::collections::BTreeMap::new();
        for calculation in provider["calculations"].as_array().ok_or(INVALID)? {
            let reference = &calculation["type"];
            let key = ["kind", "type_id", "semantic_version"]
                .map(|k| reference[k].as_str().unwrap_or("").to_owned());
            expected_assets.insert(key,json!({"kind":reference["kind"],"asset_id":reference["type_id"],"semantic_version":reference["semantic_version"],"content_fingerprint":crate::application::factor_content::hash(reference).map_err(|_|INVALID)?}));
        }
        if v["assets"] != json!(expected_assets.into_values().collect::<Vec<_>>()) {
            return Err(INVALID);
        }
        let mut native =
            onlyalpha_calculation_bridge::native_predicates::implementation_manifests(image)
                .map_err(|_| INVALID)?;
        native.extend(
            onlyalpha_calculation_bridge::native_operators::implementation_manifests(image)
                .map_err(|_| INVALID)?,
        );
        let mut summaries = native
            .iter()
            .map(crate::application::research_admission::implementation_projection)
            .collect::<Result<Vec<_>>>()?;
        summaries.sort_by_key(|r| {
            [
                "kind",
                "type_id",
                "semantic_version",
                "backend",
                "implementation_fingerprint",
            ]
            .map(|k| r[k].as_str().unwrap_or("").to_owned())
        });
        if v["implementations"] != json!(summaries) {
            return Err(INVALID);
        }
    } else if role == "BACKEND_RUNTIME" {
        for row in v["implementations"].as_array().ok_or(INVALID)? {
            if row["kind"] != "PREDICATE"
                || !matches!(row["backend"].as_str(), Some("RESEARCH" | "TRADING"))
            {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod native_artifact_v2_tests {
    use super::*;

    fn manifest1() -> Value {
        json!({"schema_version":1,"role":"RESEARCH_RUNTIME","source_provenance_authority":"ONLYALPHA_GIT",
            "source_repository":"OnlyAlpha","source_revision":"a".repeat(40),"distribution_name":"onlyalpha-backend",
            "distribution_version":"0.11.1","artifact_logical_name":"onlyalpha_backend-0.11.1-x86_64-unknown-linux-gnu.elf",
            "artifact_sha256":"b".repeat(64),"artifact_size":1024,"tested_core_execution_fingerprint":"c".repeat(64),
            "provider_id":null,"provider_version":null,"provider_content_fingerprint":null,
            "assets":[],"implementations":[],"manifest_fingerprint":"d".repeat(64)})
    }
    fn manifest2() -> Value {
        let mut m = manifest1();
        m["schema_version"] = json!(2);
        m["role"] = json!("BACKEND_RUNTIME");
        m["execution_capabilities"] =
            json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"}]);
        let mut rows = onlyalpha_calculation_bridge::native_predicates::implementation_manifests(&"b".repeat(64))
            .unwrap().into_iter().map(|row| {
                let reference = &row["calculation_type_reference"];
                json!({"kind":reference["kind"],"type_id":reference["type_id"],"semantic_version":reference["semantic_version"],
                    "backend":row["backend_kind"],"implementation_fingerprint":row["implementation_fingerprint"]})
            }).collect::<Vec<_>>();
        rows.sort_by_key(|row| {
            [
                "kind",
                "type_id",
                "semantic_version",
                "backend",
                "implementation_fingerprint",
            ]
            .map(|key| row[key].as_str().unwrap().to_owned())
        });
        m["implementations"] = json!(rows);
        m
    }
    #[test]
    fn manifest1_history_is_unchanged_and_cannot_gain_native_capabilities() {
        let m = manifest1();
        assert!(artifact(&m).is_ok());
        let mut changed = m.clone();
        changed["implementations"] = manifest2()["implementations"].clone();
        assert!(artifact(&changed).is_err());
        let mut changed = m.clone();
        changed["execution_capabilities"] = json!([]);
        assert!(artifact(&changed).is_err());
        let mut changed = m;
        changed["role"] = json!("BACKEND_RUNTIME");
        assert!(artifact(&changed).is_err());
    }
    #[test]
    fn one_backend_artifact_has_typed_research_capability_and_finite_calculations() {
        assert!(artifact(&manifest2()).is_ok());
        assert_eq!(
            manifest2()["artifact_sha256"],
            manifest1()["artifact_sha256"]
        );
        // A value parser is no Store replacement or permission to rewrite an
        // existing SHA-bound Manifest1. Put-once identity remains separate.
    }
    #[test]
    fn manifest2_accepts_exact_backtest_capability_and_preserves_research_only_history() {
        let old = manifest2();
        assert!(artifact(&old).is_ok());
        let mut current = old.clone();
        current["execution_capabilities"] = json!([
            {"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"},
            {"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}
        ]);
        assert!(artifact(&current).is_ok());
        for additional in [
            json!({"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}),
            json!({"kind":"LIVE","contract":"onlyalpha.live.executor/1"}),
        ] {
            let mut corrupt = current.clone();
            corrupt["execution_capabilities"]
                .as_array_mut()
                .unwrap()
                .push(additional);
            assert!(artifact(&corrupt).is_err());
        }
        assert_eq!(
            old,
            manifest2(),
            "old immutable manifests are never upgraded"
        );
    }
    #[test]
    fn manifest2_rejects_empty_duplicate_corrupt_or_unimplemented_execution_capability() {
        for capabilities in [
            json!([]),
            json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"},{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"}]),
            json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/2"}]),
            json!([{"kind":"BACKTEST","contract":"onlyalpha.backtest.driver/1"}]),
            json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1","extra":true}]),
        ] {
            let mut m = manifest2();
            m["execution_capabilities"] = capabilities;
            assert!(artifact(&m).is_err());
        }
        for attack in 0..7 {
            let mut m = manifest2();
            match attack {
                0 => m["implementations"] = json!([]),
                1 => m["role"] = json!("RESEARCH_RUNTIME"),
                2 => {
                    m["artifact_logical_name"] = json!("onlyalpha_backend-0.11.1-py3-none-any.whl")
                }
                3 => m["provider_id"] = json!("fake.provider"),
                4 => m["tested_core_execution_fingerprint"] = Value::Null,
                5 => m["implementations"].as_array_mut().unwrap().reverse(),
                _ => {
                    let row = m["implementations"][0].clone();
                    m["implementations"].as_array_mut().unwrap().insert(0, row);
                }
            }
            assert!(artifact(&m).is_err(), "attack {attack}");
        }
    }

    #[test]
    fn manifest3_binds_the_complete_native_operator_provider_to_one_original_image() {
        let mut manifest = manifest2();
        manifest["schema_version"] = json!(3);
        let image = manifest["artifact_sha256"].as_str().unwrap().to_owned();
        let provider = onlyalpha_calculation_bridge::native_operators::provider_record(
            &image,
            manifest["distribution_version"].as_str().unwrap(),
        )
        .unwrap();
        for key in ["provider_id", "provider_version"] {
            manifest[key] = provider["manifest"][key].clone();
        }
        manifest["provider_content_fingerprint"] = provider["content_fingerprint"].clone();
        let mut assets = std::collections::BTreeMap::new();
        for row in provider["calculations"].as_array().unwrap() {
            let reference = &row["type"];
            let key = ["kind", "type_id", "semantic_version"]
                .map(|k| reference[k].as_str().unwrap().to_owned());
            assets.insert(key,json!({"kind":reference["kind"],"asset_id":reference["type_id"],"semantic_version":reference["semantic_version"],"content_fingerprint":crate::application::factor_content::hash(reference).unwrap()}));
        }
        manifest["assets"] = json!(assets.into_values().collect::<Vec<_>>());
        let mut implementations =
            onlyalpha_calculation_bridge::native_predicates::implementation_manifests(&image)
                .unwrap();
        implementations.extend(
            onlyalpha_calculation_bridge::native_operators::implementation_manifests(&image)
                .unwrap(),
        );
        let mut implementations = implementations
            .iter()
            .map(crate::application::research_admission::implementation_projection)
            .collect::<Result<Vec<_>>>()
            .unwrap();
        implementations.sort_by_key(|r| {
            [
                "kind",
                "type_id",
                "semantic_version",
                "backend",
                "implementation_fingerprint",
            ]
            .map(|k| r[k].as_str().unwrap().to_owned())
        });
        manifest["implementations"] = json!(implementations);
        assert!(artifact(&manifest).is_ok());
        assert_eq!(manifest["assets"].as_array().unwrap().len(), 24);
        assert_eq!(manifest["implementations"].as_array().unwrap().len(), 80);
        for attack in 0..7 {
            let mut changed = manifest.clone();
            match attack {
                0 => changed["provider_id"] = json!("foreign.provider"),
                1 => changed["provider_version"] = json!("6"),
                2 => changed["provider_content_fingerprint"] = json!("0".repeat(64)),
                3 => changed["assets"] = json!([]),
                4 => changed["implementations"] = json!([]),
                5 => {
                    changed["implementations"].as_array_mut().unwrap().pop();
                }
                _ => changed["schema_version"] = json!(2),
            }
            assert!(artifact(&changed).is_err(), "attack {attack}");
        }
        assert!(artifact(&manifest2()).is_ok());
    }
}
