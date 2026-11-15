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
pub struct ReadyFactorBinding {
    program: BoundProgram,
    program_fingerprint: String,
    certificate_fingerprint: String,
    revision: String,
}
impl ReadyFactorBinding {
    pub fn program(&self) -> &BoundProgram {
        &self.program
    }
    pub fn program_fingerprint(&self) -> &str {
        &self.program_fingerprint
    }
    pub fn certificate_fingerprint(&self) -> &str {
        &self.certificate_fingerprint
    }
    pub fn revision_fingerprint(&self) -> &str {
        &self.revision
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
        let rows=tx.query("SELECT DISTINCT p.program_fingerprint,p.payload,r.source_sha256 FROM public.factor_parameter_certificate c JOIN public.factor_built_program p ON p.program_fingerprint=c.program_fingerprint JOIN public.private_factor_revision r ON r.revision_fingerprint=c.revision_fingerprint WHERE c.revision_fingerprint=$1 AND r.factor_id=$2 AND p.payload::jsonb->>'builder_artifact'=$3 AND p.payload::jsonb->>'primitive_artifact'=$4 AND c.payload::jsonb->>'certifier_artifact'=$4 AND c.payload::jsonb->>'case_suite_fingerprint'=$5 LIMIT 2",&[&revision,&factor_id,&self.installation.artifact_fingerprint(),&self.native,&self.suite]).await.map_err(db)?;
        if rows.len() > 1 {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        let row = rows.first().ok_or(BuildError::NotReady)?;
        let pf: String = row.get(0);
        let stored = FactorBuildRepository::verify_program(row.get(1), pf.clone(), row.get(2))?;
        let p: Value = serde_json::from_str(stored.payload()).map_err(calc)?;
        if p["program_format"] != "TYPED_FACTOR_PROGRAM_V1" {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        let program = Program::decode(encode(&p["body"], 1024 * 1024)?.as_bytes()).map_err(calc)?;
        let resolved = program.resolve_parameters(parameters).map_err(calc)?;
        let params = encode(resolved.record(), 262144)?;
        let params_fp = digest(params.as_bytes());
        let rows=tx.query("SELECT certificate_fingerprint,payload,parameters_payload FROM public.factor_parameter_certificate WHERE revision_fingerprint=$1 AND program_fingerprint=$2 AND parameters_fingerprint=$3 AND payload::jsonb->>'certifier_artifact'=$4 AND payload::jsonb->>'case_suite_fingerprint'=$5 LIMIT 2",&[&revision,&pf,&params_fp,&self.native,&self.suite]).await.map_err(db)?;
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
            || !certification::valid_evidence(&c["evidence"], &self.context)
        {
            return Err(BuildError::Storage(PublicationError::Integrity));
        }
        let ready = ReadyFactorBinding {
            program: program.bind(&resolved).map_err(calc)?,
            program_fingerprint: pf,
            certificate_fingerprint: cf,
            revision: revision.into(),
        };
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
    let cert = json!({"contract":"FACTOR_PARAMETER_CERTIFICATE_V1","revision_fingerprint":source.revision,"program_fingerprint":program_fp,"parameters_fingerprint":resolved.fingerprint(),"numeric_policy":NUMERIC_POLICY,"certifier_artifact":native,"case_suite_fingerprint":suite,"evidence":evidence});
    Ok(CertifiedBuild {
        program: container,
        certificate: cert,
        parameters: resolved.record().clone(),
    })
}
