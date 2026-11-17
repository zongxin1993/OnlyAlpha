//! Exact installed Research inputs, reconstructed by the native backend.
//! No Human consent, activation or Run is inferred from mathematical ABI observations.
use crate::{
    application::{factor_content::hash, research_admission::PreparationError},
    persistence::research_runtime::Registry,
    security::{
        immutable_json::Directory,
        protected_files::{self, FilePolicy},
    },
    workers::algorithm::{AlgorithmProcess, describe_native_runtime},
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_observability::{Correlation, measure};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path},
    time::Duration,
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_ENVIRONMENT_INPUT_MISMATCH";

#[cfg(test)]
#[path = "../tests/research_environment_diagnostics_tests.rs"]
mod diagnostics_tests;
fn sha(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
struct Release {
    root: Directory,
    raw: Vec<u8>,
    manifest: Value,
}
impl Release {
    fn open(root: &Path, installation: &ChartInstallation, version: &str) -> Result<Self> {
        let directory = Directory::open(root)?;
        let raw = protected_files::read_file_at(
            &directory.fd,
            "manifest.json".as_ref(),
            FilePolicy::HistoryDocument,
            8 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?
        .to_vec();
        let canonical = onlyalpha_metadata_json::canonical_json(
            std::str::from_utf8(&raw).map_err(|_| INVALID)?,
            8 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?;
        let manifest: Value = serde_json::from_str(&canonical).map_err(|_| INVALID)?;
        if manifest["schema_version"] != 2
            || manifest["runtime_root"] != root.to_str().ok_or(INVALID)?
            || manifest["version"] != version
            || manifest["algorithm_artifact"] != installation.artifact_fingerprint()
            || installation.root() != root.join("algorithms")
        {
            return Err(INVALID);
        }
        Ok(Self {
            root: directory,
            raw,
            manifest,
        })
    }
    fn read(&self, path: &str, executable: bool) -> Result<Vec<u8>> {
        if Path::new(path)
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        {
            return Err(INVALID);
        }
        let parts = path.split('/').collect::<Vec<_>>();
        let (leaf, parents) = parts.split_last().ok_or(INVALID)?;
        let parent = self.root.path(parents, false)?;
        let raw = protected_files::read_file_at(
            &parent.fd,
            (*leaf).as_ref(),
            if executable {
                FilePolicy::Executable
            } else {
                FilePolicy::HistoryDocument
            },
            128 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?
        .to_vec();
        if self.manifest["files"][path] != sha(&raw) {
            return Err(INVALID);
        }
        self.verify()?;
        Ok(raw)
    }
    fn verify(&self) -> Result<()> {
        self.root.verify()?;
        let raw = protected_files::read_file_at(
            &self.root.fd,
            "manifest.json".as_ref(),
            FilePolicy::HistoryDocument,
            8 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?;
        if *raw != self.raw {
            return Err(INVALID);
        }
        Ok(())
    }
    fn wheel(&self, distribution: &str, version: &str) -> Result<(String, Vec<u8>)> {
        let name = format!(
            "{}-{version}-py3-none-any.whl",
            distribution.replace('-', "_")
        );
        Ok((name.clone(), self.read(&format!("wheels/{name}"), false)?))
    }
}
/// Only this actual installed producer constructs the package used by the Product owner.
/// A manifest supplied by a client cannot construct this value.
pub struct PreparedGeneration {
    manifest: Value,
    artifacts: Vec<(Value, Vec<u8>)>,
    proof: Value,
}
impl PreparedGeneration {
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }
    pub fn proof(&self) -> &Value {
        &self.proof
    }
    pub fn publish(&self, registry: &mut Registry, actor: &str, at: OnlyUtcDateTime) -> Result<()> {
        for (manifest, bytes) in &self.artifacts {
            registry.install_artifact(manifest, bytes)?;
        }
        registry.retain_installed_proof(&self.manifest, &self.proof)?;
        registry.prepare_generation(&self.manifest, actor, at)?;
        Ok(())
    }
}
/// The source of all executable metadata is the sealed selected release and its real math child.
/// The owning API must separately retain exact Human preparation intent and expected-current.
pub fn prepare(
    installation: &ChartInstallation,
    release_root: &Path,
    version: &str,
) -> std::result::Result<PreparedGeneration, PreparationError> {
    prepare_installed(installation, release_root, version, false)
}
/// Qualify the actual installed Target library independently of signal programs.
pub fn prepare_strategy(
    installation: &ChartInstallation,
    release_root: &Path,
    version: &str,
) -> std::result::Result<PreparedGeneration, PreparationError> {
    prepare_installed(installation, release_root, version, true)
}
fn prepare_installed(
    installation: &ChartInstallation,
    release_root: &Path,
    version: &str,
    with_targets: bool,
) -> std::result::Result<PreparedGeneration, PreparationError> {
    measure(
        "backend",
        "runtime.prepare.all",
        Correlation::default(),
        || {
            measure(
                "backend",
                "runtime.prepare.installation_verify",
                Correlation::default(),
                || installation.verify(),
            )
            .map_err(|_| INVALID)?;
            let release = measure(
                "backend",
                "runtime.prepare.release_open",
                Correlation::default(),
                || Release::open(release_root, installation, version),
            )?;
            let provenance: Value = measure(
                "backend",
                "runtime.prepare.provenance_read",
                Correlation::default(),
                || {
                    serde_json::from_slice(&release.read("source-provenance.json", false)?)
                        .map_err(|_| INVALID)
                },
            )?;
            if provenance["schema_version"] != 1
                || provenance["source_provenance_authority"] != "ONLYALPHA_GIT"
                || provenance["source_repository"] != "OnlyAlpha"
            {
                return Err(INVALID.into());
            }
            let core_version = measure(
                "backend",
                "runtime.prepare.core_version",
                Correlation::default(),
                || installation.installed_distribution_version("onlyalpha"),
            )
            .map_err(|_| INVALID)?;
            let provider_version = version;
            let (core_name, core_bytes) = measure(
                "backend",
                "runtime.prepare.core_wheel",
                Correlation::default(),
                || release.wheel("onlyalpha", &core_version),
            )?;
            let target_wheel = if with_targets {
                let version = measure(
                    "backend",
                    "runtime.prepare.target_version",
                    Correlation::default(),
                    || installation.installed_distribution_version("onlyalpha-backend-algorithms"),
                )
                .map_err(|_| INVALID)?;
                let (name, bytes) = measure(
                    "backend",
                    "runtime.prepare.target_wheel",
                    Correlation::default(),
                    || release.wheel("onlyalpha-backend-algorithms", &version),
                )?;
                Some((version, name, bytes))
            } else {
                None
            };
            let native = measure(
                "backend",
                "runtime.prepare.native_read",
                Correlation::default(),
                || release.read("bin/onlyalpha-backend", true),
            )?;
            let native_descriptor = measure(
                "backend",
                "runtime.prepare.native_inventory",
                Correlation::default(),
                || describe_native_runtime(version),
            )
            .map_err(|_| INVALID)?;
            let descriptor = native_descriptor["image"].clone();
            measure(
                "backend",
                "runtime.prepare.native_binding",
                Correlation::default(),
                || {
                    if descriptor["artifact"] != sha(&native)
                        || descriptor["version"] != version
                        || descriptor["protocol"] != "onlyalpha.research.executor/1"
                    {
                        Err(INVALID)
                    } else {
                        Ok(())
                    }
                },
            )?;
            let core = json!({"schema_version":1,"distribution_name":"onlyalpha","distribution_version":core_version,"artifact_sha256":sha(&core_bytes)});
            let core_pin = hash(&core).map_err(|_| INVALID)?;
            let artifact = |name: &str, bytes: &[u8], version: &str| json!({"path":release_root.join("wheels").join(name),"sha256":sha(bytes),"size":bytes.len(),"distribution_version":version});
            let mut request = json!({"schema_version":1,"contract":"ONLYALPHA_INSTALLED_CALCULATION_ENVIRONMENT_V1","core_artifact":artifact(&core_name,&core_bytes,&core_version),"operator_artifact":{"sha256":descriptor["artifact"],"distribution_version":version}});
            if let Some((version, name, bytes)) = &target_wheel {
                request["target_artifact"] = artifact(name, bytes, version);
            }
            let preparation_identity = hash(&request).map_err(|_| INVALID)?;
            let mut worker = measure(
                "backend",
                "runtime.prepare.worker_create",
                Correlation::default(),
                || {
                    AlgorithmProcess::research_resolution(
                        installation,
                        &preparation_identity,
                        Box::new(()),
                    )
                },
            )
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
            let owner = worker
                .cancellation()
                .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
            let deadline = Duration::from_secs(10);
            measure(
                "backend",
                "runtime.prepare.worker_handshake",
                Correlation::default(),
                || worker.handshake_research(deadline),
            )
            .map_err(|e| PreparationError::worker(e, owner.clone()))?;
            let observation = measure(
                "backend",
                "runtime.prepare.worker_prepare",
                Correlation::default(),
                || worker.prepare_research(request.clone(), deadline),
            )
            .map_err(|e| PreparationError::worker(e, owner.clone()))?;
            measure(
                "backend",
                "runtime.prepare.worker_drain",
                Correlation::default(),
                || worker.terminate(),
            )
            .map_err(|e| PreparationError::worker(e, owner))?;
            measure(
                "backend",
                "runtime.prepare.installation_verify_final",
                Correlation::default(),
                || installation.verify(),
            )
            .map_err(|_| INVALID)?;
            measure(
                "backend",
                "runtime.prepare.release_verify_final",
                Correlation::default(),
                || release.verify(),
            )?;
            measure(
                "backend",
                "runtime.prepare.proof_build",
                Correlation::default(),
                || {
                    if observation["schema_version"] != 1
                        || observation["contract"]
                            != "ONLYALPHA_INSTALLED_CALCULATION_ENVIRONMENT_V1"
                        || observation["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
                        || observation["algorithm_artifact"] != installation.artifact_fingerprint()
                        || observation["core_artifact_sha256"] != core["artifact_sha256"]
                        || observation["operator_artifact_sha256"] != sha(&native)
                        || observation["implementations"] != json!([])
                    {
                        return Err(INVALID.into());
                    }
                    let mut fields = vec![
                        "schema_version",
                        "contract",
                        "algorithm_artifact",
                        "core_artifact_sha256",
                        "core_resources_fingerprint",
                        "isolation",
                        "implementations",
                        "operator_provider_manifest",
                        "operator_calculations",
                        "operator_artifact_sha256",
                        "operator_resources_fingerprint",
                    ];
                    if target_wheel.is_some() {
                        fields.extend([
                            "target_artifact_sha256",
                            "target_resources_fingerprint",
                            "target_calculations",
                        ]);
                    }
                    if observation.as_object().is_none_or(|record| {
                        record.len() != fields.len()
                            || fields.iter().any(|key| !record.contains_key(*key))
                    }) {
                        return Err(INVALID.into());
                    }
                    for key in [
                        "core_resources_fingerprint",
                        "operator_resources_fingerprint",
                    ] {
                        if !observation[key].as_str().is_some_and(crate::is_sha256_hex) {
                            return Err(INVALID.into());
                        }
                    }
                    let target_implementations = if let Some((_, _, bytes)) = &target_wheel {
                        if observation["target_artifact_sha256"] != sha(bytes)
                            || !observation["target_resources_fingerprint"]
                                .as_str()
                                .is_some_and(crate::is_sha256_hex)
                        {
                            return Err(INVALID.into());
                        }
                        let targets = observation["target_calculations"]
                            .as_array()
                            .filter(|r| !r.is_empty())
                            .ok_or(INVALID)?;
                        let mut identities = BTreeSet::new();
                        for target in targets {
                            let reference = &target["type"];
                            if reference["kind"] != "TARGET"
                                || target["backend"] != "RESEARCH"
                                || !target["state_capability"].is_null()
                                || !target["checkpoint_schema_version"].is_null()
                                || !identities.insert(
                                    ["kind", "type_id", "semantic_version"]
                                        .map(|k| reference[k].as_str().unwrap_or("").to_owned()),
                                )
                            {
                                return Err(INVALID.into());
                            }
                        }
                        let mut projected = implementations(&observation["target_calculations"])?;
                        sort_implementations(&mut projected);
                        projected
                    } else {
                        Vec::new()
                    };
                    let base = provider(
                        &observation["operator_provider_manifest"],
                        &observation["operator_calculations"],
                        Value::Null,
                    )?;
                    if base["manifest"]["source"]
                        != json!({"kind":"DISTRIBUTION","distribution_name":"onlyalpha-backend","distribution_version":provider_version})
                    {
                        return Err(INVALID.into());
                    }
                    let core_artifact = distribution(
                        "CORE",
                        ("onlyalpha", &core_version),
                        &core_name,
                        &core_bytes,
                        &provenance,
                        Value::Null,
                        None,
                    )?;
                    let target = descriptor["target"].as_str().ok_or(INVALID)?;
                    let mut native_implementations = native_descriptor["implementations"]
                        .as_array()
                        .ok_or(INVALID)?
                        .iter()
                        .map(crate::application::research_admission::implementation_projection)
                        .collect::<Result<Vec<_>>>()?;
                    sort_implementations(&mut native_implementations);
                    let mut native_artifact = distribution(
                        "BACKEND_RUNTIME",
                        ("onlyalpha-backend", version),
                        &format!("onlyalpha_backend-{version}-{target}.elf"),
                        &native,
                        &provenance,
                        core_pin.clone().into(),
                        Some(&base),
                    )?;
                    native_artifact
                        .as_object_mut()
                        .ok_or(INVALID)?
                        .remove("manifest_fingerprint");
                    native_artifact["schema_version"] = json!(3);
                    native_artifact["execution_capabilities"] =
                        native_descriptor["execution_capabilities"].clone();
                    native_artifact["implementations"] = json!(native_implementations);
                    native_artifact["manifest_fingerprint"] =
                        hash(&native_artifact).map_err(|_| INVALID)?.into();
                    let mut artifacts =
                        vec![(core_artifact, core_bytes), (native_artifact, native)];
                    if let Some((version, name, bytes)) = target_wheel {
                        let mut target_artifact = distribution(
                            "CALCULATION",
                            ("onlyalpha-backend-algorithms", &version),
                            &name,
                            &bytes,
                            &provenance,
                            core_pin.into(),
                            None,
                        )?;
                        target_artifact
                            .as_object_mut()
                            .ok_or(INVALID)?
                            .remove("manifest_fingerprint");
                        target_artifact["implementations"] = json!(target_implementations);
                        target_artifact["manifest_fingerprint"] =
                            hash(&target_artifact).map_err(|_| INVALID)?.into();
                        artifacts.push((target_artifact, bytes));
                    }
                    let mut all_implementations = native_implementations;
                    all_implementations.extend(target_implementations);
                    sort_implementations(&mut all_implementations);
                    let mut providers = vec![base.clone()];
                    providers.sort_by_key(|p| {
                        (
                            p["manifest"]["kind"].as_str().unwrap_or("").to_owned(),
                            p["manifest"]["provider_id"]
                                .as_str()
                                .unwrap_or("")
                                .to_owned(),
                            p["manifest"]["provider_version"]
                                .as_str()
                                .unwrap_or("")
                                .to_owned(),
                        )
                    });
                    let catalog = json!({"schema_version":1,"providers":providers});
                    let mut manifest = json!({"schema_version":1,"core_execution":core,"artifact_manifest_fingerprints":artifacts.iter().map(|(m,_)|m["manifest_fingerprint"].as_str().unwrap_or("").to_owned()).collect::<BTreeSet<_>>(),"artifact_sha256s":artifacts.iter().map(|(m,_)|m["artifact_sha256"].as_str().unwrap_or("").to_owned()).collect::<BTreeSet<_>>(),"providers":[{"provider_id":base["manifest"]["provider_id"],"provider_version":base["manifest"]["provider_version"],"provider_content_fingerprint":base["content_fingerprint"],"artifact_sha256":artifacts[1].0["artifact_sha256"]}],"catalog_generation_fingerprint":hash(&catalog).map_err(|_|INVALID)?,"implementations":all_implementations,"private_factor_bindings":[]});
                    manifest["runtime_generation_fingerprint"] =
                        hash(&manifest).map_err(|_| INVALID)?.into();
                    let mut proof = json!({"schema_version":2,"contract":"ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V2","runtime_generation_fingerprint":manifest["runtime_generation_fingerprint"],"algorithm_artifact":installation.artifact_fingerprint(),"release_manifest_sha256":sha(&release.raw),"source_inputs":release.manifest["source_inputs"],"source_provenance":provenance,"native_descriptor":native_descriptor,"algorithm_observation":observation,"catalog":catalog});
                    proof["installed_proof_fingerprint"] =
                        hash(&proof).map_err(|_| INVALID)?.into();
                    Ok(PreparedGeneration {
                        manifest,
                        artifacts,
                        proof,
                    })
                },
            )
        },
    )
}

fn provider(manifest: &Value, calculations: &Value, snapshot: Value) -> Result<Value> {
    let content = json!({"kind":manifest["kind"],"calculations":calculations,"private_factor_snapshot":snapshot});
    Ok(
        json!({"manifest":manifest,"content_fingerprint":hash(&content).map_err(|_|INVALID)?,"calculations":calculations,"private_factor_snapshot":snapshot}),
    )
}
fn implementations(calculations: &Value) -> Result<Vec<Value>> {
    calculations.as_array().ok_or(INVALID)?.iter().map(|c| {
  for k in ["kind","type_id","semantic_version"] {if !c["type"][k].is_string(){return Err(INVALID);}}
  if !c["implementation_fingerprint"].as_str().is_some_and(crate::is_sha256_hex) || !matches!(c["backend"].as_str(),Some("RESEARCH"|"TRADING")) {return Err(INVALID);}
  Ok(json!({"kind":c["type"]["kind"],"type_id":c["type"]["type_id"],"semantic_version":c["type"]["semantic_version"],"backend":c["backend"],"implementation_fingerprint":c["implementation_fingerprint"]}))
 }).collect()
}
fn sort_implementations(rows: &mut [Value]) {
    rows.sort_by_key(|r| {
        [
            "kind",
            "type_id",
            "semantic_version",
            "backend",
            "implementation_fingerprint",
        ]
        .map(|k| r[k].as_str().unwrap_or("").to_owned())
    });
}
fn distribution(
    role: &str,
    identity: (&str, &str),
    logical: &str,
    bytes: &[u8],
    provenance: &Value,
    core: Value,
    provider: Option<&Value>,
) -> Result<Value> {
    let (name, version) = identity;
    let mut assets = BTreeMap::new();
    let mut implementation = Vec::new();
    if let Some(p) = provider {
        implementation = implementations(&p["calculations"])?;
        sort_implementations(&mut implementation);
        for c in p["calculations"].as_array().ok_or(INVALID)? {
            let t = &c["type"];
            let key = ["kind", "type_id", "semantic_version"]
                .map(|k| t[k].as_str().unwrap_or("").to_owned());
            let asset = json!({"kind":t["kind"],"asset_id":t["type_id"],"semantic_version":t["semantic_version"],"content_fingerprint":hash(t).map_err(|_|INVALID)?});
            if assets
                .insert(key, asset.clone())
                .is_some_and(|old| old != asset)
            {
                return Err(INVALID);
            }
        }
    }
    let mut m = json!({"schema_version":1,"role":role,"source_provenance_authority":provenance["source_provenance_authority"],"source_repository":provenance["source_repository"],"source_revision":provenance["source_revision"],"distribution_name":name,"distribution_version":version,"artifact_logical_name":logical,"artifact_sha256":sha(bytes),"artifact_size":bytes.len(),"tested_core_execution_fingerprint":core,"provider_id":provider.map(|p|p["manifest"]["provider_id"].clone()),"provider_version":provider.map(|p|p["manifest"]["provider_version"].clone()),"provider_content_fingerprint":provider.map(|p|p["content_fingerprint"].clone()),"assets":assets.into_values().collect::<Vec<_>>(),"implementations":implementation});
    m["manifest_fingerprint"] = hash(&m).map_err(|_| INVALID)?.into();
    Ok(m)
}
