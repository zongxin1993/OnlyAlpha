//! Independent factor construction/certification owner. It never prepares market
//! data or runs a Research job. Only this owner and its owning reader mint READY.
use crate::{
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        factor_build::FactorBuildRepository,
        job_publication::{
            PublicationError, bounded, commit, db, deployment_error, digest, durable, encode, role,
        },
    },
};
use onlyalpha_calculation::program::{BoundProgram, NUMERIC_POLICY, Program};
use onlyalpha_calculation_bridge::{ChartInstallation, WorkerError};
use serde_json::{Value, json};
use std::{sync::Arc, time::Duration};
use tokio_postgres::{Client, Transaction};
#[path = "factor_build/certification.rs"]
mod certification;
type Result<T> = std::result::Result<T, BuildError>;
#[derive(Debug)]
pub enum BuildError {
    Storage(PublicationError),
    NotReady,
    Failed(&'static str),
    Invalid,
    Unknown,
}
impl From<PublicationError> for BuildError {
    fn from(v: PublicationError) -> Self {
        Self::Storage(v)
    }
}
impl std::fmt::Display for BuildError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "FACTOR_BUILD_{self:?}")
    }
}
impl std::error::Error for BuildError {}
/// Preserve the owning reader's knowledge state at preparation boundaries.
pub(crate) fn preparation_error(
    error: BuildError,
) -> crate::application::research_admission::PreparationError {
    use crate::application::research_admission::PreparationError;
    use PublicationError as P;
    let code = match error {
        BuildError::NotReady | BuildError::Storage(P::MissingEvidence) => {
            "PRIVATE_STRATEGY_PROGRAM_NOT_READY"
        }
        BuildError::Unknown | BuildError::Storage(P::OutcomeUnknown) => {
            return PreparationError::unknown("PRIVATE_STRATEGY_PROGRAM_OUTCOME_UNKNOWN", None);
        }
        BuildError::Storage(P::Unavailable) => "PRIVATE_STRATEGY_PROGRAM_UNAVAILABLE",
        BuildError::Storage(P::Denied) => "PRIVATE_STRATEGY_PROGRAM_DENIED",
        BuildError::Storage(P::BudgetExceeded) => "PRIVATE_STRATEGY_PROGRAM_BUDGET_EXCEEDED",
        BuildError::Storage(P::OwnershipLost) => "PRIVATE_STRATEGY_PROGRAM_OWNERSHIP_LOST",
        BuildError::Storage(P::Conflict) => "PRIVATE_STRATEGY_PROGRAM_CONFLICT",
        BuildError::Storage(P::Mismatch) => "PRIVATE_STRATEGY_PROGRAM_MISMATCH",
        BuildError::Storage(P::Integrity) | BuildError::Invalid | BuildError::Failed(_) => {
            "PRIVATE_STRATEGY_PROGRAM_INVALID"
        }
    };
    code.into()
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuildStatus {
    Building,
    Ready,
    Failed,
}
#[derive(Debug)]
pub struct BuildReport {
    pub revision: String,
    pub status: BuildStatus,
    pub source_parse_count: Option<u64>,
}
#[derive(Clone)]
pub struct ReadyFactorBinding {
    verified: VerifiedFactorProgram,
}
#[derive(Clone)]
struct VerifiedFactorProgram {
    program: BoundProgram,
    program_fingerprint: String,
    certificate_fingerprint: String,
    revision: String,
    metadata: Value,
    interface: String,
    source_sha: String,
    factor_id: String,
}
/// Only declarations required by native execution. Source and authoring
/// annotations stay in the authoring owner; the exact certificate pins this
/// projection to the fully validated immutable revision at build time.
pub(crate) fn execution_metadata(metadata:&Value)->Value {
    json!({"factor_id":metadata["factor_id"],"semantic_version":metadata["semantic_version"],
        "revision_fingerprint":metadata["revision_fingerprint"],"source_sha256":metadata["source_sha256"],
        "factor_api_version":metadata["factor_api_version"],"factor_api_contract_fingerprint":metadata["factor_api_contract_fingerprint"],
        "input_contract":metadata["input_contract"],"parameter_contract":metadata["parameter_contract"],"output_contract":metadata["output_contract"]})
}
impl VerifiedFactorProgram {
    fn bind_metadata(&mut self, metadata: &Value) -> Result<()> {
        crate::application::private_assets::authoring::validate_revision(metadata)
            .map_err(|_| BuildError::Storage(PublicationError::Integrity))?;
        if metadata["source_text"].as_str().is_none_or(|text|digest(text.as_bytes())!=self.source_sha) {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        self.bind_execution_metadata(&execution_metadata(metadata))
    }
    fn bind_execution_metadata(&mut self, metadata:&Value)->Result<()> {
        if !metadata.is_object() || metadata.as_object().is_none_or(|m|m.len()!=9)
            || execution_metadata(metadata)!=*metadata
            || metadata["revision_fingerprint"]!=self.revision || metadata["factor_id"]!=self.factor_id
            || metadata["source_sha256"]!=self.source_sha
            || metadata["factor_api_version"]!=1
            || metadata["factor_api_contract_fingerprint"]!=crate::application::private_assets::authoring::API_FINGERPRINT
            || metadata["semantic_version"].as_str().is_none_or(str::is_empty)
            || fp(&json!({"api":metadata["factor_api_contract_fingerprint"],"inputs":metadata["input_contract"],"parameters":metadata["parameter_contract"],"outputs":metadata["output_contract"]}))?!=self.interface
            || (!self.metadata.is_null() && self.metadata!=*metadata) {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        certification::signature(metadata,self.program.program())?;
        self.metadata=metadata.clone();
        Ok(())
    }

    fn calculation(
        &self,
        image: &str,
        bindings: &Value,
    ) -> Result<onlyalpha_calculation_bridge::ProgramCalculation> {
        onlyalpha_calculation_bridge::ProgramCalculation::resolve(
            &self.metadata,
            Arc::new(self.program.clone()),
            &self.program_fingerprint,
            image,
            bindings,
        )
        .map_err(calc)
    }
}
impl ReadyFactorBinding {
    pub(crate) fn metadata(&self) -> &Value {
        &self.verified.metadata
    }
    pub(crate) fn calculation(
        &self,
        image: &str,
        bindings: &Value,
    ) -> Result<onlyalpha_calculation_bridge::ProgramCalculation> {
        self.verified.calculation(image, bindings)
    }
    pub fn program(&self) -> &BoundProgram {
        &self.verified.program
    }
    pub fn program_fingerprint(&self) -> &str {
        &self.verified.program_fingerprint
    }
    pub fn certificate_fingerprint(&self) -> &str {
        &self.verified.certificate_fingerprint
    }
    pub fn revision_fingerprint(&self) -> &str {
        &self.verified.revision
    }
}
/// No Deserialize, public constructor, raw-ready flag or arbitrary certificate setter.
pub(crate) struct BuiltFactorProgram {
    record: Value,
}
impl BuiltFactorProgram {
    pub(crate) fn record(&self) -> &Value {
        &self.record
    }
}
pub(crate) struct CertifiedBuild {
    program: Value,
    certificate: Value,
    parameters: Value,
}
impl CertifiedBuild {
    pub(crate) fn records(&self) -> (&Value, &Value, &Value) {
        (&self.program, &self.certificate, &self.parameters)
    }
}
struct Source {
    revision: String,
    sha: String,
    raw: Value,
    signature: String,
}
pub struct FactorBuildService<'a> {
    client: &'a mut Client,
    namespace: SemanticStoreId,
    installation: Arc<ChartInstallation>,
    native: String,
    context: String,
    suite: String,
    writable: bool,
}
fn fp(v: &Value) -> Result<String> {
    Ok(digest(encode(v, 8 * 1024 * 1024)?.as_bytes()))
}
fn calc<T>(_: T) -> BuildError {
    BuildError::Failed("FACTOR_PROGRAM_INVALID")
}
fn worker(e: WorkerError) -> BuildError {
    if matches!(e, WorkerError::Unknown(_)) {
        BuildError::Unknown
    } else {
        BuildError::Failed("FACTOR_COMPILE_REJECTED")
    }
}
async fn source(tx: &Transaction<'_>, revision: &str) -> Result<Source> {
    let row=tx.query_opt("SELECT source_sha256,CASE WHEN octet_length(payload::text)<=8388608 AND octet_length(source_text)<=65536 THEN payload::text END,CASE WHEN octet_length(source_text)<=65536 THEN source_text END FROM public.private_factor_revision WHERE revision_fingerprint=$1",&[&revision]).await.map_err(db)?.ok_or(BuildError::Storage(PublicationError::MissingEvidence))?;
    let raw: String = row
        .get::<_, Option<String>>(1)
        .ok_or(BuildError::Storage(PublicationError::BudgetExceeded))?;
    let v: Value =
        serde_json::from_str(&raw).map_err(|_| BuildError::Storage(PublicationError::Integrity))?;
    crate::application::private_assets::authoring::validate_revision(&v)
        .map_err(|_| BuildError::Storage(PublicationError::Integrity))?;
    let sha: String = row.get(0);
    let text: String = row
        .get::<_, Option<String>>(2)
        .ok_or(BuildError::Storage(PublicationError::BudgetExceeded))?;
    if v["revision_fingerprint"] != revision
        || v["source_sha256"] != sha
        || v["source_text"] != text
        || digest(text.as_bytes()) != sha
    {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    if v["factor_api_version"] != 1
        || v["factor_api_contract_fingerprint"]
            != crate::application::private_assets::authoring::API_FINGERPRINT
    {
        return Err(BuildError::Failed("FACTOR_SOURCE_API_UNSUPPORTED"));
    }
    let signature = fp(
        &json!({"api":v["factor_api_contract_fingerprint"],"inputs":v["input_contract"],"parameters":v["parameter_contract"],"outputs":v["output_contract"]}),
    )?;
    Ok(Source {
        revision: revision.into(),
        sha,
        raw: v,
        signature,
    })
}
impl<'a> FactorBuildService<'a> {
    pub async fn new(
        client: &'a mut Client,
        namespace: &SemanticStoreId,
        installation: Arc<ChartInstallation>,
    ) -> Result<Self> {
        let current = role(
            client,
            &["onlyalpha_factor_builder", "onlyalpha_job_reader"],
        )
        .await?;
        deployment::verify_binding(client, namespace)
            .await
            .map_err(deployment_error)?;
        installation.verify().map_err(worker)?;
        let native =
            crate::workers::algorithm::describe_research_runtime(env!("CARGO_PKG_VERSION"))
                .map_err(worker)?["artifact"]
                .as_str()
                .ok_or(BuildError::Invalid)?
                .to_owned();
        let suite = fp(&certification::policy())?;
        let context = fp(
            &json!({"builder":installation.artifact_fingerprint(),"native":native,"api":crate::application::private_assets::authoring::API_FINGERPRINT,"suite":suite}),
        )?;
        Ok(Self {
            client,
            namespace: namespace.clone(),
            installation,
            native,
            context,
            suite,
            writable: current == "onlyalpha_factor_builder",
        })
    }
    pub fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
    /// Size preflight only, never READY. The immutable exact records are still
    /// fully verified by resolve_frozen_binding before any input is returned.
    pub(crate) async fn read_memory_requirement(
        &mut self,
        binding: &crate::application::job_contract::FactorExecutionBinding,
    ) -> Result<usize> {
        let expected = binding.record();
        let certificate = expected["certificate"]
            .as_str()
            .ok_or(BuildError::Invalid)?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let row = tx.query_opt("SELECT c.revision_fingerprint,c.program_fingerprint,c.parameters_fingerprint,octet_length(p.payload),octet_length(c.payload),octet_length(c.parameters_payload) FROM public.factor_parameter_certificate c JOIN public.factor_built_program p ON p.program_fingerprint=c.program_fingerprint WHERE c.certificate_fingerprint=$1", &[&certificate]).await.map_err(db)?.ok_or(BuildError::Storage(PublicationError::MissingEvidence))?;
        for (index, key) in [(0, "revision"), (1, "program"), (2, "parameters")] {
            if expected[key].as_str() != Some(row.get::<_, String>(index).as_str()) {
                return Err(BuildError::Storage(PublicationError::Mismatch));
            }
        }
        let mut encoded = 0_usize;
        for (index, limit) in [(3, 8 * 1024 * 1024), (4, 8 * 1024 * 1024), (5, 262144)] {
            let bytes = usize::try_from(row.get::<_, i32>(index))
                .map_err(|_| BuildError::Storage(PublicationError::Integrity))?;
            if bytes == 0 || bytes > limit {
                return Err(BuildError::Storage(PublicationError::BudgetExceeded));
            }
            encoded = encoded
                .checked_add(bytes)
                .ok_or(BuildError::Storage(PublicationError::BudgetExceeded))?;
        }
        // Restricted IR contains scalar values and bounded node/port records.
        // Reserve for encoded buffers, JSON trees, decoded and bound copies;
        // execution history belongs to the subsequent Session budget.
        const BUILD_DECODE_RESERVE_FACTOR: usize = 64;
        let bytes = encoded
            .checked_mul(BUILD_DECODE_RESERVE_FACTOR)
            .ok_or(BuildError::Storage(PublicationError::BudgetExceeded))?;
        commit(tx).await?;
        Ok(bytes)
    }
    pub async fn request(
        &mut self,
        factor_id: &str,
        revision: &str,
        parameters: &Value,
    ) -> Result<BuildStatus> {
        if !self.writable {
            return Err(BuildError::Storage(PublicationError::Denied));
        }
        if !parameters.is_object() {
            return Err(BuildError::Invalid);
        }
        match self
            .resolve_ready_binding(factor_id, revision, parameters)
            .await
        {
            Ok(_) => return Ok(BuildStatus::Ready),
            Err(BuildError::NotReady) => {}
            Err(e) => return Err(e),
        }
        let raw = encode(parameters, 262144)?;
        let requested = digest(raw.as_bytes());
        let tx = self.client.transaction().await.map_err(db)?;
        durable(&tx).await?;
        let row=tx.query_opt("SELECT factor_id FROM public.private_factor_revision WHERE revision_fingerprint=$1",&[&revision]).await.map_err(db)?.ok_or(BuildError::Storage(PublicationError::MissingEvidence))?;
        if row.get::<_, String>(0) != factor_id {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        if raw == "{}" && let Some(row)=tx.query_opt("SELECT state,build_environment_fingerprint FROM public.factor_build_request WHERE revision_fingerprint=$1 AND request_context='DEFAULT' AND requested_parameters_payload='{}'",&[&revision]).await.map_err(db)? {
    let state:String=row.get(0);let environment:Option<String>=row.get(1);
    if state=="BUILDING" || state=="FAILED"&&environment.as_deref()==Some(self.context.as_str()) {commit(tx).await?;return Ok(if state=="FAILED"{BuildStatus::Failed}else{BuildStatus::Building});}
   }
        tx.execute("INSERT INTO public.factor_build_request(revision_fingerprint,requested_parameters_fingerprint,requested_parameters_payload,request_context,state) VALUES($1,$2,$3,$4,'BUILDING') ON CONFLICT DO NOTHING",&[&revision,&requested,&raw,&self.context]).await.map_err(db)?;
        let row=tx.query_one("SELECT requested_parameters_payload,state FROM public.factor_build_request WHERE revision_fingerprint=$1 AND requested_parameters_fingerprint=$2 AND request_context=$3",&[&revision,&requested,&self.context]).await.map_err(db)?;
        if row.get::<_, String>(0) != raw {
            return Err(BuildError::Storage(PublicationError::Conflict));
        }
        let status = if row.get::<_, String>(1) == "FAILED" {
            BuildStatus::Failed
        } else {
            BuildStatus::Building
        };
        commit(tx).await?;
        Ok(status)
    }
    pub async fn resolve_ready_binding(
        &mut self,
        factor_id: &str,
        revision: &str,
        parameters: &Value,
    ) -> Result<ReadyFactorBinding> {
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let environment = ReadEnvironment {
            builder: self.installation.artifact_fingerprint().to_owned(),
            native: self.native.clone(),
            suite: self.suite.clone(),
            context: self.context.clone(),
        };
        let ready = read_ready(&tx, &environment, factor_id, revision, parameters).await?;
        commit(tx).await?;
        Ok(ready)
    }
    /// Load only the exact immutable certificate selected by a frozen job.
    /// This operation cannot enqueue work, parse source or certify parameters.
    pub async fn resolve_frozen_binding(
        &mut self,
        binding: &crate::application::job_contract::FactorExecutionBinding,
    ) -> Result<ReadyFactorBinding> {
        let expected = binding.record();
        let certificate = expected["certificate"]
            .as_str()
            .ok_or(BuildError::Invalid)?;
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let row = tx.query_opt(
            "SELECT c.revision_fingerprint,c.program_fingerprint,c.parameters_fingerprint,CASE WHEN octet_length(c.parameters_payload)<=262144 THEN c.parameters_payload END,r.factor_id FROM public.factor_parameter_certificate c JOIN public.private_factor_revision r ON r.revision_fingerprint=c.revision_fingerprint WHERE c.certificate_fingerprint=$1",
            &[&certificate],
        ).await.map_err(db)?.ok_or(BuildError::Storage(PublicationError::MissingEvidence))?;
        for (index, key) in [(0, "revision"), (1, "program"), (2, "parameters")] {
            if expected[key].as_str() != Some(row.get::<_, String>(index).as_str()) {
                return Err(BuildError::Storage(PublicationError::Mismatch));
            }
        }
        let raw = row
            .get::<_, Option<String>>(3)
            .ok_or(BuildError::Storage(PublicationError::BudgetExceeded))?;
        let parameters: Value = serde_json::from_str(&raw).map_err(calc)?;
        if encode(&parameters, 262144)? != raw || digest(raw.as_bytes()) != expected["parameters"] {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        let factor_id: String = row.get(4);
        let revision: String = row.get(0);
        commit(tx).await?;
        let arguments = Value::Object(
            parameters
                .as_object()
                .ok_or(BuildError::Invalid)?
                .iter()
                .map(|(key, value)| (key.clone(), value["value"].clone()))
                .collect(),
        );
        let ready = self
            .resolve_ready_binding(&factor_id, &revision, &arguments)
            .await?;
        if ready.certificate_fingerprint() != certificate
            || Some(ready.program_fingerprint()) != expected["program"].as_str()
            || ready.program().parameters().fingerprint() != expected["parameters"]
        {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        Ok(ready)
    }
    pub async fn run_pending(&mut self) -> Result<Option<BuildReport>> {
        if !self.writable {
            return Err(BuildError::Storage(PublicationError::Denied));
        }
        let installation = self.installation.clone();
        let native = self.native.clone();
        let context = self.context.clone();
        let suite = self.suite.clone();
        let tx = self.client.transaction().await.map_err(db)?;
        durable(&tx).await?;
        let row=tx.query_opt("SELECT revision_fingerprint,requested_parameters_fingerprint,requested_parameters_payload,request_context FROM public.factor_build_request WHERE state='BUILDING' AND request_context IN ('DEFAULT',$1) ORDER BY created_at,revision_fingerprint,requested_parameters_fingerprint FOR UPDATE SKIP LOCKED LIMIT 1",&[&context]).await.map_err(db)?;
        let Some(row) = row else {
            commit(tx).await?;
            return Ok(None);
        };
        let revision: String = row.get(0);
        let requested: String = row.get(1);
        let raw: String = row.get(2);
        let request_context: String = row.get(3);
        let params: Value = serde_json::from_str(&raw).map_err(calc)?;
        if digest(raw.as_bytes()) != requested || encode(&params, 262144)? != raw {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        let mut parse_count = Some(0);
        let result = build(
            &tx,
            &revision,
            &params,
            BuildEnvironment {
                installation: &installation,
                native: &native,
                context: &context,
                suite: &suite,
            },
            &mut parse_count,
        )
        .await;
        let status = match result {
            Ok(proof) => {
                let publication = FactorBuildRepository::from_certified(&proof)?;
                FactorBuildRepository::put_in_transaction(&tx, &publication).await?;
                let p = fp(&proof.program)?;
                let c = fp(&proof.certificate)?;
                tx.execute("UPDATE public.factor_build_request SET state='READY',build_environment_fingerprint=$4,program_fingerprint=$5,certificate_fingerprint=$6,finished_at=clock_timestamp() WHERE revision_fingerprint=$1 AND requested_parameters_fingerprint=$2 AND request_context=$3 AND state='BUILDING'",&[&revision,&requested,&request_context,&context,&p,&c]).await.map_err(db)?;
                BuildStatus::Ready
            }
            Err(BuildError::NotReady) => {
                tx.rollback().await.map_err(db)?;
                return Ok(Some(BuildReport {
                    revision: revision.clone(),
                    status: BuildStatus::Building,
                    source_parse_count: Some(0),
                }));
            }
            Err(BuildError::Failed(code)) => {
                tx.execute("UPDATE public.factor_build_request SET state='FAILED',build_environment_fingerprint=$4,failure_code=$5,finished_at=clock_timestamp() WHERE revision_fingerprint=$1 AND requested_parameters_fingerprint=$2 AND request_context=$3 AND state='BUILDING'",&[&revision,&requested,&request_context,&context,&code]).await.map_err(db)?;
                BuildStatus::Failed
            }
            Err(e) => return Err(e),
        };
        commit(tx).await?;
        Ok(Some(BuildReport {
            revision,
            status,
            source_parse_count: parse_count,
        }))
    }
}
struct BuildEnvironment<'a> {
    installation: &'a Arc<ChartInstallation>,
    native: &'a str,
    context: &'a str,
    suite: &'a str,
}
async fn build(
    tx: &Transaction<'_>,
    revision: &str,
    params: &Value,
    environment: BuildEnvironment<'_>,
    parse_count: &mut Option<u64>,
) -> Result<CertifiedBuild> {
    let BuildEnvironment {
        installation,
        native,
        context,
        suite,
    } = environment;
    let source = source(tx, revision).await?;
    let identity = fp(
        &json!({"source":source.sha,"interface":source.signature,"builder":installation.artifact_fingerprint(),"primitive":native}),
    )?;
    let acquired: bool = tx
        .query_one(
            "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))",
            &[&identity],
        )
        .await
        .map_err(db)?
        .get(0);
    if !acquired {
        return Err(BuildError::NotReady);
    }
    let rows=tx.query("SELECT payload,program_fingerprint FROM public.factor_built_program WHERE source_sha256=$1 AND payload::jsonb->>'interface_fingerprint'=$2 AND payload::jsonb->>'builder_artifact'=$3 AND payload::jsonb->>'primitive_artifact'=$4 LIMIT 2",&[&source.sha,&source.signature,&installation.artifact_fingerprint(),&native]).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    let container = if let Some(row) = rows.first() {
        let raw: String = row.get(0);
        let fp: String = row.get(1);
        let value: Value = serde_json::from_str(&raw).map_err(calc)?;
        if digest(raw.as_bytes()) != fp || encode(&value, 8 * 1024 * 1024)? != raw {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        value
    } else {
        *parse_count = None;
        let mut process = crate::workers::algorithm::AlgorithmProcess::research_resolution(
            installation,
            context,
            Box::new(()),
        )
        .map_err(worker)?;
        let observed = (|| {
            process.handshake_research(Duration::from_secs(5))?;
            process.compile_factor(json!({"schema_version":1,"contract":"ONLYALPHA_FACTOR_PROGRAM_COMPILE_V1","source":source.raw.as_object().ok_or(WorkerError::Invalid)?.iter().filter(|(k,_)|["source_text","source_sha256","factor_api_version","factor_api_contract_fingerprint","input_contract","parameter_contract","output_contract"].contains(&k.as_str())).map(|(k,v)|(k.clone(),v.clone())).collect::<serde_json::Map<_,_>>()}),Duration::from_secs(3))
        })();
        process.terminate().map_err(worker)?;
        let observed = observed.map_err(worker)?;
        if observed["contract"] != "ONLYALPHA_FACTOR_PROGRAM_COMPILED_V1"
            || observed["source_sha256"] != source.sha
            || observed["parse_count"] != 1
            || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
        {
            return Err(BuildError::Failed("FACTOR_COMPILE_BINDING"));
        }
        *parse_count = Some(1);
        json!({"contract":"FACTOR_PROGRAM_CONTAINER_V1","source_sha256":source.sha,"interface_fingerprint":source.signature,"builder_artifact":installation.artifact_fingerprint(),"numeric_policy":NUMERIC_POLICY,"primitive_artifact":native,"program_format":"TYPED_FACTOR_PROGRAM_V1","body":observed["program"]})
    };
    let program =
        Program::decode(encode(&container["body"], 1024 * 1024)?.as_bytes()).map_err(calc)?;
    certification::signature(&source.raw, &program)?;
    let built = BuiltFactorProgram {
        record: container.clone(),
    };
    FactorBuildRepository::put_program_in_transaction(tx, &built).await?;
    let resolved = program.resolve_parameters(params).map_err(calc)?;
    let bound = program.bind(&resolved).map_err(calc)?;
    let evidence = certification::certify(&source.raw, &bound, context)?;
    let program_fp = fp(&container)?;
    let cert = json!({"contract":"FACTOR_PARAMETER_CERTIFICATE_V1","revision_fingerprint":source.revision,"program_fingerprint":program_fp,"parameters_fingerprint":resolved.fingerprint(),"numeric_policy":NUMERIC_POLICY,"certifier_artifact":native,"case_suite_fingerprint":suite,"execution_metadata":execution_metadata(&source.raw),"evidence":evidence});
    Ok(CertifiedBuild {
        program: container,
        certificate: cert,
        parameters: resolved.record().clone(),
    })
}

/// Issuer selection is private data derived from actual installed/loaded artifacts.
/// It cannot be populated from a Source JSON claim or caller-supplied hashes.
pub(crate) struct ReadEnvironment {
    builder: String,
    native: String,
    suite: String,
    context: String,
}
impl ReadEnvironment {
    pub(crate) fn selected(installation: &ChartInstallation) -> Result<Self> {
        installation.verify().map_err(worker)?;
        let native =
            crate::workers::algorithm::describe_research_runtime(env!("CARGO_PKG_VERSION"))
                .map_err(worker)?["artifact"]
                .as_str()
                .ok_or(BuildError::Invalid)?
                .to_owned();
        let suite = fp(&certification::policy())?;
        let context = fp(
            &json!({"builder":installation.artifact_fingerprint(),"native":native,"api":crate::application::private_assets::authoring::API_FINGERPRINT,"suite":suite}),
        )?;
        Ok(Self {
            builder: installation.artifact_fingerprint().to_owned(),
            native,
            suite,
            context,
        })
    }
}
/// Resolve every private instance separately. Two instances of one revision
/// with different parameters must retain two precise certificates.
pub(crate) async fn read_instances(
    tx: &Transaction<'_>,
    environment: &ReadEnvironment,
    strategy: &Value,
    factors: &std::collections::BTreeMap<String, Value>,
) -> Result<std::collections::BTreeMap<String, ReadyFactorBinding>> {
    let definition =
        crate::application::private_strategy::Definition::from_record(&strategy["definition"])
            .map_err(calc)?
            .to_record();
    let mut result = std::collections::BTreeMap::new();
    for instance in definition["calculations"]
        .as_array()
        .ok_or(BuildError::Invalid)?
    {
        let reference = &instance["type_reference"];
        if reference["kind"] != "FACTOR" {
            continue;
        }
        let factor_id = reference["type_id"].as_str().ok_or(BuildError::Invalid)?;
        let factor = factors.get(factor_id).ok_or(BuildError::Invalid)?;
        if factor["semantic_version"] != reference["semantic_version"] {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        let parameters = instance["parameters"]
            .as_object()
            .ok_or(BuildError::Invalid)?
            .iter()
            .map(|(key, value)| {
                if value["kind"] != "FIXED" {
                    return Err(BuildError::Invalid);
                }
                Ok((key.clone(), value["value"]["value"].clone()))
            })
            .collect::<Result<serde_json::Map<_, _>>>()?;
        let mut ready = read_ready(
            tx,
            environment,
            factor_id,
            factor["revision_fingerprint"]
                .as_str()
                .ok_or(BuildError::Invalid)?,
            &Value::Object(parameters),
        )
        .await?;
        ready.verified.bind_metadata(factor)?;
        let key = instance["instance_key"]
            .as_str()
            .ok_or(BuildError::Invalid)?;
        if result.insert(key.to_owned(), ready).is_some() {
            return Err(BuildError::Invalid);
        }
    }
    Ok(result)
}
/// Same owning reader for the public service and the existing admitted
/// preparation owner. This core performs SELECT only in the caller's actual
/// transaction; PG access privileges and the outer owner remain in force.
pub(crate) async fn read_ready(
    tx: &Transaction<'_>,
    environment: &ReadEnvironment,
    factor_id: &str,
    revision: &str,
    parameters: &Value,
) -> Result<ReadyFactorBinding> {
    Ok(ReadyFactorBinding {
        verified: read_program(tx, environment, factor_id, revision, parameters).await?,
    })
}
async fn read_program(
    tx: &Transaction<'_>,
    environment: &ReadEnvironment,
    factor_id: &str,
    revision: &str,
    parameters: &Value,
) -> Result<VerifiedFactorProgram> {
    let rows=tx.query("SELECT DISTINCT p.program_fingerprint,p.payload,r.source_sha256 FROM public.factor_parameter_certificate c JOIN public.factor_built_program p ON p.program_fingerprint=c.program_fingerprint JOIN public.private_factor_revision r ON r.revision_fingerprint=c.revision_fingerprint WHERE c.revision_fingerprint=$1 AND r.factor_id=$2 AND p.payload::jsonb->>'builder_artifact'=$3 AND p.payload::jsonb->>'primitive_artifact'=$4 AND c.payload::jsonb->>'certifier_artifact'=$4 AND c.payload::jsonb->>'case_suite_fingerprint'=$5 LIMIT 2",&[&revision,&factor_id,&environment.builder,&environment.native,&environment.suite]).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    let row = rows.first().ok_or(BuildError::NotReady)?;
    let pf: String = row.get(0);
    let source_sha: String = row.get(2);
    let stored = FactorBuildRepository::verify_program(row.get(1), pf.clone(), source_sha.clone())?;
    let p: Value = serde_json::from_str(stored.payload()).map_err(calc)?;
    if p["program_format"] != "TYPED_FACTOR_PROGRAM_V1" || p["numeric_policy"] != NUMERIC_POLICY {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    let program = Program::decode(encode(&p["body"], 1024 * 1024)?.as_bytes()).map_err(calc)?;
    let resolved = program.resolve_parameters(parameters).map_err(calc)?;
    let params = encode(resolved.record(), 262144)?;
    let params_fp = digest(params.as_bytes());
    let rows=tx.query("SELECT certificate_fingerprint,payload,parameters_payload FROM public.factor_parameter_certificate WHERE revision_fingerprint=$1 AND program_fingerprint=$2 AND parameters_fingerprint=$3 AND payload::jsonb->>'certifier_artifact'=$4 AND payload::jsonb->>'case_suite_fingerprint'=$5 LIMIT 2",&[&revision,&pf,&params_fp,&environment.native,&environment.suite]).await.map_err(db)?;
    if rows.len() > 1 {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    let row = rows.first().ok_or(BuildError::NotReady)?;
    let cf: String = row.get(0);
    let stored = FactorBuildRepository::verify_certificate(row.get(1), cf.clone(), row.get(2))?;
    let c: Value = serde_json::from_str(stored.payload()).map_err(calc)?;
    if stored.parameters() != params
        || c["revision_fingerprint"] != revision
        || c["program_fingerprint"] != pf
        || !certification::valid_evidence(&c["evidence"], &environment.context)
    {
        return Err(BuildError::Storage(PublicationError::Integrity));
    }
    let mut ready = VerifiedFactorProgram {
        program: program.bind(&resolved).map_err(calc)?,
        program_fingerprint: pf,
        certificate_fingerprint: cf,
        revision: revision.into(),
        metadata: Value::Null,
        interface: p["interface_fingerprint"]
            .as_str()
            .filter(|v| crate::is_sha256_hex(v))
            .ok_or(BuildError::Invalid)?
            .into(),
        source_sha,
        factor_id: factor_id.into(),
    };

    // READY owns the immutable asset declarations as well as the certified IR.
    // The exact certificate carries builder-authenticated declarations. Readers
    // need no access to authoring tables and never parse source AST. Its bytes
    // are already included in the certificate memory preflight.
    ready.bind_execution_metadata(&c["execution_metadata"])?;
    Ok(ready)
}

/// Reconstruct original mathematical observations under the immutable PG graph
/// proof. No current image selection and no execution READY token is returned.
pub(crate) async fn verify_retained_resolution(
    tx: &Transaction<'_>,
    prepared: &Value,
    revision: &Value,
    factors: &std::collections::BTreeMap<String, Value>,
) -> Result<()> {
    let proof = &prepared["build_certification"];
    crate::application::calculation_build::verify_fact(tx, proof)
        .await
        .map_err(|e| {
            BuildError::Storage(if e.ends_with("UNAVAILABLE") {
                PublicationError::Unavailable
            } else if e.ends_with("MISSING") {
                PublicationError::MissingEvidence
            } else {
                PublicationError::Integrity
            })
        })?;
    let signal =
        crate::application::calculation_build::signal_preparation(prepared).map_err(calc)?;
    let context = &proof["context"];
    if context["execution_binding"] != prepared["execution_binding"]
        || context["algorithm_resolution_request_fingerprint"]
            != fp(&signal["algorithm_resolution_request"])?
        || context["algorithm_resolution_fingerprint"] != fp(&signal["algorithm_resolution"])?
    {
        return Err(BuildError::Storage(PublicationError::Mismatch));
    }
    let observed = &prepared["algorithm_resolution"];
    let request = &prepared["algorithm_resolution_request"];
    crate::application::private_strategy::exact(
        observed,
        &[
            "schema_version",
            "contract",
            "nodes",
            "native_execution",
            "target_resolution",
            "algorithm_artifact",
        ],
    )
    .map_err(calc)?;
    crate::application::private_strategy::exact(
        request,
        &[
            "schema_version",
            "contract",
            "instances",
            "program_bindings",
            "target_resolution_request",
        ],
    )
    .map_err(calc)?;
    crate::application::private_strategy::exact(
        &observed["native_execution"],
        &["artifact", "program_bindings"],
    )
    .map_err(calc)?;
    if observed["schema_version"] != 1
        || request["schema_version"] != 1
        || observed["contract"] != "ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1"
        || request["contract"] != observed["contract"]
        || request["program_bindings"] != observed["native_execution"]["program_bindings"]
    {
        return Err(BuildError::Storage(PublicationError::Mismatch));
    }
    let image = prepared["execution_binding"]["executor_artifact_sha256"]
        .as_str()
        .ok_or(BuildError::Invalid)?;
    let builder = observed["algorithm_artifact"]
        .as_str()
        .ok_or(BuildError::Invalid)?;
    if observed["native_execution"]["artifact"] != image
        || !crate::is_sha256_hex(image)
        || !crate::is_sha256_hex(builder)
    {
        return Err(BuildError::Storage(PublicationError::Mismatch));
    }
    let definition =
        crate::application::private_strategy::Definition::from_record(&revision["definition"])
            .map_err(calc)?
            .to_record();
    let instances = definition["calculations"]
        .as_array()
        .ok_or(BuildError::Invalid)?;
    let pins = request["program_bindings"]
        .as_array()
        .ok_or(BuildError::Invalid)?;
    let mut verified = std::collections::BTreeMap::new();
    for instance in instances
        .iter()
        .filter(|i| i["type_reference"]["kind"] == "FACTOR")
    {
        let key = instance["instance_key"]
            .as_str()
            .ok_or(BuildError::Invalid)?;
        let found = pins
            .iter()
            .filter(|p| p["instance_key"] == key)
            .collect::<Vec<_>>();
        if found.len() != 1 {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        let pin = found[0];
        crate::application::private_strategy::exact(
            pin,
            &[
                "instance_key",
                "revision",
                "program",
                "parameters",
                "certificate",
            ],
        )
        .map_err(calc)?;
        let id = instance["type_reference"]["type_id"]
            .as_str()
            .ok_or(BuildError::Invalid)?;
        let factor = factors.get(id).ok_or(BuildError::Invalid)?;
        if pin["revision"] != factor["revision_fingerprint"] {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        let certificate = pin["certificate"].as_str().ok_or(BuildError::Invalid)?;
        let program = pin["program"].as_str().ok_or(BuildError::Invalid)?;
        let row = tx
            .query_opt(
                "SELECT payload, parameters_payload, EXISTS (
                    SELECT 1 FROM public.factor_built_program WHERE program_fingerprint = $2
                 ) FROM public.factor_parameter_certificate WHERE certificate_fingerprint = $1",
                &[&certificate, &program],
            )
            .await
            .map_err(db)?
            .ok_or(PublicationError::MissingEvidence)?;
        let original =
            FactorBuildRepository::verify_certificate(row.get(0), certificate.into(), row.get(1))?;
        let c: Value = serde_json::from_str(original.payload()).map_err(calc)?;
        if c["revision_fingerprint"] != pin["revision"]
            || c["program_fingerprint"] != program
            || c["parameters_fingerprint"] != pin["parameters"]
            || c["certifier_artifact"] != image
        {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        if !row.get::<_, bool>(2) {
            return Err(BuildError::Storage(PublicationError::MissingEvidence));
        }
        let suite = c["case_suite_fingerprint"]
            .as_str()
            .filter(|s| crate::is_sha256_hex(s))
            .ok_or(BuildError::Invalid)?;
        let environment = ReadEnvironment {
            builder: builder.into(),
            native: image.into(),
            suite: suite.into(),
            context: fp(
                &json!({"builder":builder,"native":image,"api":factor["factor_api_contract_fingerprint"],"suite":suite}),
            )?,
        };
        let params = instance["parameters"]
            .as_object()
            .ok_or(BuildError::Invalid)?
            .iter()
            .map(|(k, v)| (k.clone(), v["value"]["value"].clone()))
            .collect::<serde_json::Map<_, _>>();
        let mut p = read_program(
            tx,
            &environment,
            id,
            pin["revision"].as_str().ok_or(BuildError::Invalid)?,
            &Value::Object(params),
        )
        .await?;
        p.bind_metadata(factor)?;
        if p.metadata != execution_metadata(factor)
            || p.program_fingerprint != pin["program"]
            || p.certificate_fingerprint != certificate
            || p.program.parameters().fingerprint() != pin["parameters"]
        {
            return Err(BuildError::Storage(PublicationError::Mismatch));
        }
        if verified.insert(key.to_owned(), p).is_some() {
            return Err(BuildError::Invalid);
        }
    }
    if verified.len() != pins.len() {
        return Err(BuildError::Storage(PublicationError::Mismatch));
    }
    let (nodes,actual_pins)=crate::application::strategy_research::native_program_instances(instances,image,|key,bindings|{
        let p=verified.get(key).ok_or("PRIVATE_STRATEGY_RETAINED_PROGRAM_MISMATCH")?;
        let c=p.calculation(image,bindings).map_err(preparation_error)?;
        Ok((c,json!({"instance_key":key,"revision":p.revision,"program":p.program_fingerprint,"parameters":p.program.parameters().fingerprint(),"certificate":p.certificate_fingerprint})))
    }).map_err(|_|BuildError::Storage(PublicationError::Mismatch))?;
    let actual = observed["nodes"]
        .as_array()
        .ok_or(BuildError::Invalid)?
        .iter()
        .filter(|n| n["definition"]["kind"] != "TARGET")
        .cloned()
        .collect::<Vec<_>>();
    if actual != nodes || json!(actual_pins) != request["program_bindings"] {
        return Err(BuildError::Storage(PublicationError::Mismatch));
    }
    Ok(())
}

/// Index original mathematical manifest values only. Callers must already own
/// the verified original Run/history and its PG proof; this returns no READY,
/// execution permission or portable certification.
pub(crate) fn retained_factor_manifest_values(
    original: &Value,
    image: &str,
    algorithm: &str,
) -> std::result::Result<std::collections::BTreeMap<String, Value>, &'static str> {
    const INVALID: &str = "PRIVATE_STRATEGY_RETAINED_IMPLEMENTATION_MISMATCH";
    let resolution = &original["algorithm_resolution"];
    let mut values = std::collections::BTreeMap::new();
    if resolution["contract"] != "ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1" {
        if resolution.get("native_execution").is_some()
            || resolution
                .get("contract")
                .is_some_and(|v| v != "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1")
        {
            return Err(INVALID);
        }
        return Ok(values);
    }
    if resolution["native_execution"]["artifact"] != image
        || resolution["algorithm_artifact"] != algorithm
    {
        return Err(INVALID);
    }
    for node in resolution["nodes"]
        .as_array()
        .ok_or(INVALID)?
        .iter()
        .filter(|n| n["definition"]["kind"] == "FACTOR")
    {
        let definition = onlyalpha_calculation::product::Definition::from_record(
            &node["definition"],
            8 * 1024 * 1024,
        )
        .map_err(|_| INVALID)?;
        if node["definition_fingerprint"] != definition.fingerprint() {
            return Err(INVALID);
        }
        let mut roles = std::collections::BTreeSet::new();
        for body in node["implementations"].as_array().ok_or(INVALID)? {
            crate::application::research_admission::implementation_projection(body)?;
            let role = body["backend_kind"].as_str().ok_or(INVALID)?;
            if !roles.insert(role)
                || body["resources"]
                    != json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":image}])
                || ["kind", "type_id", "semantic_version"]
                    .iter()
                    .any(|k| body["calculation_type_reference"][*k] != node["definition"][*k])
            {
                return Err(INVALID);
            }
            let key = body["implementation_fingerprint"]
                .as_str()
                .ok_or(INVALID)?
                .to_owned();
            if let Some(previous) = values.insert(key, body.clone())
                && previous != *body
            {
                return Err(INVALID);
            }
        }
        if roles != std::collections::BTreeSet::from(["RESEARCH", "TRADING"]) {
            return Err(INVALID);
        }
    }
    Ok(values)
}
