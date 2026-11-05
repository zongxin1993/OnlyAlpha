//! Controlled storage-only generation fixtures. These bytes are never executed
//! and certify neither an installed Python distribution nor a native ABI.
use onlyalpha_backend::{
    application::{command::CommandId, factor_content::hash},
    persistence::research_runtime::Registry,
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;

fn seal(mut value: Value, key: &str) -> Value {
    value[key] = hash(&value).unwrap().into();
    value
}
fn artifact(
    role: &str,
    distribution: &str,
    logical: &str,
    bytes: &[u8],
    core: Option<&str>,
) -> Value {
    let sha = Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let mut value = json!({"schema_version":1,"role":role,"source_provenance_authority":"ONLYALPHA_GIT",
        "source_repository":"OnlyAlpha","source_revision":"1".repeat(40),"distribution_name":distribution,
        "distribution_version":"0.11.1","artifact_logical_name":logical,"artifact_sha256":sha,"artifact_size":bytes.len(),
        "tested_core_execution_fingerprint":core,"provider_id":null,"provider_version":null,"provider_content_fingerprint":null,
        "assets":[],"implementations":[]});
    if role == "QUANT_ASSET" {
        value["provider_id"] = json!("fixture.storage.reference");
        value["provider_version"] = json!("1");
        value["provider_content_fingerprint"] = json!("2".repeat(64));
        value["assets"] = json!([{"kind":"INDICATOR","asset_id":"fixture.storage.value","semantic_version":"1","content_fingerprint":"3".repeat(64)}]);
        value["implementations"] = json!([{"kind":"INDICATOR","type_id":"fixture.storage.value","semantic_version":"1","backend":"RESEARCH","implementation_fingerprint":"4".repeat(64)}]);
    }
    seal(value, "manifest_fingerprint")
}
/// Create ACTIVE original work and optionally a second READY generation solely
/// through the existing owner. All storage metadata uses real Manifest1 DTOs.
pub fn fixture(root: &Path, ready: bool) -> (String, String) {
    let core_bytes = b"controlled core bytes; storage evidence only";
    let core_artifact = artifact(
        "CORE",
        "onlyalpha",
        "onlyalpha-0.11.1-py3-none-any.whl",
        core_bytes,
        None,
    );
    let core = json!({"schema_version":1,"distribution_name":"onlyalpha","distribution_version":"0.11.1","artifact_sha256":core_artifact["artifact_sha256"]});
    let core_id = hash(&core).unwrap();
    let provider_bytes = b"controlled reference distribution bytes; not installed operators";
    let provider = artifact(
        "QUANT_ASSET",
        "onlyalpha-storage-reference",
        "onlyalpha_storage_reference-0.11.1-py3-none-any.whl",
        provider_bytes,
        Some(&core_id),
    );
    let (target, machine) = if cfg!(target_arch = "aarch64") {
        ("aarch64-unknown-linux-gnu", 183u16)
    } else {
        ("x86_64-unknown-linux-gnu", 62u16)
    };
    let mut native_bytes = [0u8; 64];
    native_bytes[..7].copy_from_slice(b"\x7fELF\x02\x01\x01");
    native_bytes[16..18].copy_from_slice(&3u16.to_le_bytes());
    native_bytes[18..20].copy_from_slice(&machine.to_le_bytes());
    native_bytes[20..24].copy_from_slice(&1u32.to_le_bytes());
    native_bytes[52..54].copy_from_slice(&64u16.to_le_bytes());
    let native = artifact(
        "RESEARCH_RUNTIME",
        "onlyalpha-backend",
        &format!("onlyalpha_backend-0.11.1-{target}.elf"),
        &native_bytes,
        Some(&core_id),
    );
    let mut registry = Registry::initialize_fresh(root).unwrap();
    for (manifest, bytes) in [
        (&core_artifact, core_bytes.as_slice()),
        (&provider, provider_bytes.as_slice()),
        (&native, native_bytes.as_slice()),
    ] {
        registry.install_artifact(manifest, bytes).unwrap();
    }
    let mut manifests = vec![
        core_artifact["manifest_fingerprint"].clone(),
        provider["manifest_fingerprint"].clone(),
        native["manifest_fingerprint"].clone(),
    ];
    manifests.sort_by_key(|v| v.as_str().unwrap().to_owned());
    let mut artifacts = vec![
        core_artifact["artifact_sha256"].clone(),
        provider["artifact_sha256"].clone(),
        native["artifact_sha256"].clone(),
    ];
    artifacts.sort_by_key(|v| v.as_str().unwrap().to_owned());
    let manifest = seal(
        json!({"schema_version":1,"core_execution":core,"artifact_manifest_fingerprints":manifests,"artifact_sha256s":artifacts,
        "providers":[{"provider_id":provider["provider_id"],"provider_version":provider["provider_version"],"provider_content_fingerprint":provider["provider_content_fingerprint"],"artifact_sha256":provider["artifact_sha256"]}],
        "catalog_generation_fingerprint":"4".repeat(64),"implementations":provider["implementations"],"private_factor_bindings":[]}),
        "runtime_generation_fingerprint",
    );
    let generation = manifest["runtime_generation_fingerprint"]
        .as_str()
        .unwrap()
        .to_owned();
    let at: OnlyUtcDateTime = "2026-10-29T00:00:00Z".parse().unwrap();
    registry
        .prepare_generation(&manifest, "fixture", at)
        .unwrap();
    registry
        .activate(
            &CommandId::new("00000000-0000-4000-8000-000000000101").unwrap(),
            &generation,
            None,
            "fixture",
            at,
        )
        .unwrap();
    registry
        .bind_new_work_exact("work", &generation, "research", "fixture", at)
        .unwrap();
    let target = if ready {
        let next = variant(&manifest, '5');
        registry.prepare_generation(&next, "fixture", at).unwrap();
        next["runtime_generation_fingerprint"]
            .as_str()
            .unwrap()
            .to_owned()
    } else {
        String::new()
    };
    (generation, target)
}
/// A distinct immutable candidate with the same exact retained artifacts.
pub fn variant(manifest: &Value, digit: char) -> Value {
    let mut next = manifest.clone();
    next.as_object_mut()
        .unwrap()
        .remove("runtime_generation_fingerprint");
    next["catalog_generation_fingerprint"] = digit.to_string().repeat(64).into();
    seal(next, "runtime_generation_fingerprint")
}
