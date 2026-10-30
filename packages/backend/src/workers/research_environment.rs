//! Exact installed Research inputs, reconstructed by the native backend.
//! No Human consent, activation or Run is inferred from mathematical ABI observations.
use crate::{
    application::{
        factor_content::hash,
        research_admission::{PreparationError, check_binding},
        research_factor::CompiledFactor,
    },
    persistence::research_runtime::Registry,
    security::{
        immutable_json::Directory,
        protected_files::{self, FilePolicy},
    },
    workers::algorithm::{AlgorithmProcess, describe_research_runtime},
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path},
    time::Duration,
};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_ENVIRONMENT_INPUT_MISMATCH";
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
    runtime: Value,
    vectors: Value,
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
    pub fn publish(
        &self,
        registry: &mut Registry,
        source: &[u8],
        actor: &str,
        at: OnlyUtcDateTime,
    ) -> Result<()> {
        for (manifest, bytes) in &self.artifacts {
            registry.install_artifact(manifest, bytes)?;
        }
        registry.install_private_factor(&self.runtime, source)?;
        registry.retain_abi_vectors(
            &self.vectors,
            &self.runtime["equivalence_evidence"]["test_vector_set_fingerprint"],
        )?;
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
    factor: &CompiledFactor,
    revision: &Value,
    version: &str,
) -> std::result::Result<PreparedGeneration, PreparationError> {
    crate::application::private_assets::authoring::validate_revision(revision)
        .map_err(|_| INVALID)?;
    if revision["revision_fingerprint"] != factor.revision_fingerprint() {
        return Err(INVALID.into());
    }
    installation.verify().map_err(|_| INVALID)?;
    let release = Release::open(release_root, installation, version)?;
    let provenance: Value = serde_json::from_slice(&release.read("source-provenance.json", false)?)
        .map_err(|_| INVALID)?;
    if provenance["schema_version"] != 1
        || provenance["source_provenance_authority"] != "ONLYALPHA_GIT"
        || provenance["source_repository"] != "OnlyAlpha"
    {
        return Err(INVALID.into());
    }
    let core_version = installation
        .installed_distribution_version("onlyalpha")
        .map_err(|_| INVALID)?;
    let provider_version = installation
        .installed_distribution_version("onlyalpha-plugin-operators")
        .map_err(|_| INVALID)?;
    let (core_name, core_bytes) = release.wheel("onlyalpha", &core_version)?;
    let (provider_name, provider_bytes) =
        release.wheel("onlyalpha-plugin-operators", &provider_version)?;
    let native = release.read("bin/onlyalpha-backend", true)?;
    let descriptor = describe_research_runtime(version).map_err(|_| INVALID)?;
    if descriptor["artifact"] != sha(&native)
        || descriptor["version"] != version
        || descriptor["protocol"] != "onlyalpha.research.executor/1"
    {
        return Err(INVALID.into());
    }
    let core = json!({"schema_version":1,"distribution_name":"onlyalpha","distribution_version":core_version,"artifact_sha256":sha(&core_bytes)});
    let core_pin = hash(&core).map_err(|_| INVALID)?;
    let source = revision
        .as_object()
        .ok_or(INVALID)?
        .iter()
        .filter(|(k, _)| {
            [
                "factor_id",
                "semantic_version",
                "revision_fingerprint",
                "source_text",
                "source_sha256",
                "factor_api_version",
                "factor_api_contract_fingerprint",
                "input_contract",
                "parameter_contract",
                "output_contract",
            ]
            .contains(&k.as_str())
        })
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect::<serde_json::Map<_, _>>();
    let artifact = |name: &str, bytes: &[u8], version: &str| json!({"path":release_root.join("wheels").join(name),"sha256":sha(bytes),"size":bytes.len(),"distribution_version":version});
    let request = json!({"schema_version":1,"source":source,"graph":factor.graph().to_record(),"core_artifact":artifact(&core_name,&core_bytes,&core_version),"operator_artifact":artifact(&provider_name,&provider_bytes,&provider_version)});
    let mut worker =
        AlgorithmProcess::research_resolution(installation, factor.fingerprint(), Box::new(()))
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    let owner = worker
        .cancellation()
        .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    let deadline = Duration::from_secs(10);
    worker
        .handshake_research(deadline)
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    let observation = worker
        .prepare_research(request.clone(), deadline)
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    worker
        .terminate()
        .map_err(|e| PreparationError::worker(e, owner))?;
    installation.verify().map_err(|_| INVALID)?;
    release.verify()?;
    if observation["schema_version"] != 1
        || observation["contract"] != "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
        || observation["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
        || observation["algorithm_artifact"] != installation.artifact_fingerprint()
        || observation["source_projection_fingerprint"]
            != hash(&request["source"]).map_err(|_| INVALID)?
        || observation["graph"] != request["graph"]
        || observation["factor_revision_fingerprint"] != revision["revision_fingerprint"]
        || observation["core_artifact_sha256"] != core["artifact_sha256"]
        || observation["operator_artifact_sha256"] != sha(&provider_bytes)
        || observation["certification_policy"] != "ONLYALPHA_PRIVATE_FACTOR_ABI_VECTORS_V1"
    {
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
    let vectors = observation["certification_vectors"].clone();
    if hash(&vectors).map_err(|_| INVALID)?
        != observation["equivalence_evidence"]["test_vector_set_fingerprint"]
        || vectors["vectors"].as_array().map(Vec::len) != Some(8)
    {
        return Err(INVALID.into());
    }
    let base = provider(
        &observation["operator_provider_manifest"],
        &observation["operator_calculations"],
        Value::Null,
    )?;
    if base["manifest"]["source"]
        != json!({"kind":"DISTRIBUTION","distribution_name":"onlyalpha-plugin-operators","distribution_version":provider_version})
    {
        return Err(INVALID.into());
    }
    let snapshot = &observation["provider_snapshot"];
    let private_manifest = json!({"schema_version":1,"provider_id":format!("private.research.{}",sha(revision["factor_id"].as_str().ok_or(INVALID)?.as_bytes())),"provider_version":revision["revision_fingerprint"],"kind":"FACTOR","source":{"kind":"PRIVATE_FACTOR_SNAPSHOT","private_factor_provider_snapshot_fingerprint":snapshot["snapshot_fingerprint"]}});
    let private = provider(
        &private_manifest,
        &observation["private_calculations"],
        snapshot.clone(),
    )?;
    let mut metadata = revision.clone();
    metadata
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("source_text");
    let mut runtime = json!({"schema_version":1,"revision_metadata":metadata,"source_artifact":observation["source_artifact"],"equivalence_evidence":observation["equivalence_evidence"],"provider_snapshot":snapshot,"provider":private});
    runtime["runtime_artifact_fingerprint"] = hash(&runtime).map_err(|_| INVALID)?.into();
    let binding = json!({"provider_snapshot_fingerprint":snapshot["snapshot_fingerprint"],"runtime_artifact_fingerprint":runtime["runtime_artifact_fingerprint"],"entry":snapshot["entries"][0]});
    let core_artifact = distribution(
        "CORE",
        ("onlyalpha", &core_version),
        &core_name,
        &core_bytes,
        &provenance,
        Value::Null,
        None,
    )?;
    let provider_artifact = distribution(
        "QUANT_ASSET",
        ("onlyalpha-plugin-operators", &provider_version),
        &provider_name,
        &provider_bytes,
        &provenance,
        core_pin.clone().into(),
        Some(&base),
    )?;
    let target = descriptor["target"].as_str().ok_or(INVALID)?;
    let native_artifact = distribution(
        "RESEARCH_RUNTIME",
        ("onlyalpha-backend", version),
        &format!("onlyalpha_backend-{version}-{target}.elf"),
        &native,
        &provenance,
        core_pin.into(),
        None,
    )?;
    let artifacts = vec![
        (core_artifact, core_bytes),
        (provider_artifact, provider_bytes),
        (native_artifact, native),
    ];
    let mut all_implementations = implementations(&observation["operator_calculations"])?;
    all_implementations.extend(implementations(&observation["private_calculations"])?);
    sort_implementations(&mut all_implementations);
    let mut providers = vec![base.clone(), private];
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
    let mut manifest = json!({"schema_version":1,"core_execution":core,"artifact_manifest_fingerprints":artifacts.iter().map(|(m,_)|m["manifest_fingerprint"].as_str().unwrap_or("").to_owned()).collect::<BTreeSet<_>>(),"artifact_sha256s":artifacts.iter().map(|(m,_)|m["artifact_sha256"].as_str().unwrap_or("").to_owned()).collect::<BTreeSet<_>>(),"providers":[{"provider_id":base["manifest"]["provider_id"],"provider_version":base["manifest"]["provider_version"],"provider_content_fingerprint":base["content_fingerprint"],"artifact_sha256":artifacts[1].0["artifact_sha256"]}],"catalog_generation_fingerprint":hash(&catalog).map_err(|_|INVALID)?,"implementations":all_implementations,"private_factor_bindings":[binding]});
    manifest["runtime_generation_fingerprint"] = hash(&manifest).map_err(|_| INVALID)?.into();
    check_binding(&observation, &runtime, &binding, &manifest)?;
    let mut proof = json!({"schema_version":1,"contract":"ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V1","runtime_generation_fingerprint":manifest["runtime_generation_fingerprint"],"algorithm_artifact":installation.artifact_fingerprint(),"release_manifest_sha256":sha(&release.raw),"source_inputs":release.manifest["source_inputs"],"source_provenance":provenance,"native_descriptor":descriptor,"algorithm_observation":observation,"catalog":catalog});
    proof["installed_proof_fingerprint"] = hash(&proof).map_err(|_| INVALID)?.into();
    Ok(PreparedGeneration {
        manifest,
        runtime,
        vectors,
        artifacts,
        proof,
    })
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
