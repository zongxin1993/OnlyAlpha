//! Immutable build-content storage, not a compiler, certifier or execution grant.
//! Production BuildPublication construction is intentionally not enabled yet.
use super::job_publication::{
    PublicationError, bounded, db, deployment_error, digest, durable, encode, role,
};
use crate::bootstrap::deployment::{self, SemanticStoreId};
use serde_json::Value;
use tokio_postgres::Client;
type Result<T> = std::result::Result<T, PublicationError>;
#[derive(Clone, Debug)]
pub struct StoredProgram {
    fingerprint: String,
    payload: String,
    source: String,
}
impl StoredProgram {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn payload(&self) -> &str {
        &self.payload
    }
}
#[derive(Clone, Debug)]
pub struct StoredCertificate {
    fingerprint: String,
    payload: String,
    parameters: String,
}
impl StoredCertificate {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn payload(&self) -> &str {
        &self.payload
    }
    pub fn parameters(&self) -> &str {
        &self.parameters
    }
}
/// Private builder-owned publication, not constructible from API JSON or from
/// StoredProgram/StoredCertificate metadata reads.
pub struct BuildPublication {
    program: StoredProgram,
    certificate: StoredCertificate,
}
pub struct FactorBuildRepository<'a> {
    client: &'a mut Client,
    writable: bool,
}
fn parsed(raw: &str, fp: &str, contract: &str, fields: &[&str]) -> Result<Value> {
    if raw.len() > 8 * 1024 * 1024 {
        return Err(PublicationError::BudgetExceeded);
    }
    let v: Value = serde_json::from_str(raw).map_err(|_| PublicationError::Integrity)?;
    if encode(&v, 8 * 1024 * 1024)? != raw
        || digest(raw.as_bytes()) != fp
        || v["contract"] != contract
        || v["numeric_policy"] != "DECIMAL28_HALF_EVEN_Q12_V1"
        || v.as_object()
            .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(PublicationError::Integrity);
    }
    for key in fields
        .iter()
        .filter(|s| s.ends_with("fingerprint") || s.ends_with("sha256") || s.ends_with("artifact"))
    {
        let p = v[*key].as_str().ok_or(PublicationError::Integrity)?;
        if p.len() != 64
            || !p
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        {
            return Err(PublicationError::Integrity);
        }
    }
    Ok(v)
}
const PROGRAM_FIELDS: &[&str] = &[
    "contract",
    "source_sha256",
    "interface_fingerprint",
    "builder_artifact",
    "numeric_policy",
    "primitive_artifact",
    "program_format",
    "body",
];
const CERTIFICATE_FIELDS: &[&str] = &[
    "contract",
    "revision_fingerprint",
    "program_fingerprint",
    "parameters_fingerprint",
    "numeric_policy",
    "certifier_artifact",
    "case_suite_fingerprint",
    "evidence",
];
fn program(raw: String, fp: String, source: String) -> Result<StoredProgram> {
    let v = parsed(&raw, &fp, "FACTOR_PROGRAM_CONTAINER_V1", PROGRAM_FIELDS)?;
    if v["source_sha256"] != source
        || v["program_format"].as_str().is_none_or(str::is_empty)
        || !v["body"].is_object()
    {
        return Err(PublicationError::Integrity);
    }
    Ok(StoredProgram {
        payload: raw,
        fingerprint: fp,
        source,
    })
}
fn certificate(raw: String, fp: String, parameters: String) -> Result<StoredCertificate> {
    let v = parsed(
        &raw,
        &fp,
        "FACTOR_PARAMETER_CERTIFICATE_V1",
        CERTIFICATE_FIELDS,
    )?;
    let params: Value =
        serde_json::from_str(&parameters).map_err(|_| PublicationError::Integrity)?;
    if !params.is_object()
        || encode(&params, 262144)? != parameters
        || v["parameters_fingerprint"] != digest(parameters.as_bytes())
        || !v["evidence"].is_object()
    {
        return Err(PublicationError::Integrity);
    }
    Ok(StoredCertificate {
        payload: raw,
        fingerprint: fp,
        parameters,
    })
}
impl<'a> FactorBuildRepository<'a> {
    pub async fn new(client: &'a mut Client, namespace: &SemanticStoreId) -> Result<Self> {
        let r = role(
            client,
            &[
                "onlyalpha_factor_builder",
                "onlyalpha_job_reader",
                "onlyalpha_job_publisher",
            ],
        )
        .await?;
        deployment::verify_binding(client, namespace)
            .await
            .map_err(deployment_error)?;
        Ok(Self {
            client,
            writable: r == "onlyalpha_factor_builder",
        })
    }
    pub async fn put(&mut self, publication: &BuildPublication) -> Result<()> {
        if !self.writable {
            return Err(PublicationError::Denied);
        }
        let p = program(
            publication.program.payload.clone(),
            publication.program.fingerprint.clone(),
            publication.program.source.clone(),
        )?;
        let c = certificate(
            publication.certificate.payload.clone(),
            publication.certificate.fingerprint.clone(),
            publication.certificate.parameters.clone(),
        )?;
        let v: Value = serde_json::from_str(&c.payload).map_err(|_| PublicationError::Integrity)?;
        if v["program_fingerprint"] != p.fingerprint {
            return Err(PublicationError::Mismatch);
        }
        let revision = v["revision_fingerprint"]
            .as_str()
            .ok_or(PublicationError::Integrity)?;
        let params = v["parameters_fingerprint"]
            .as_str()
            .ok_or(PublicationError::Integrity)?;
        let tx = self.client.transaction().await.map_err(db)?;
        durable(&tx).await?;
        tx.execute("INSERT INTO public.factor_built_program(program_fingerprint,source_sha256,payload) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",&[&p.fingerprint,&p.source,&p.payload]).await.map_err(db)?;
        let row=tx.query_one("SELECT source_sha256,payload FROM public.factor_built_program WHERE program_fingerprint=$1",&[&p.fingerprint]).await.map_err(db)?;
        if row.get::<_, String>(0) != p.source || row.get::<_, String>(1) != p.payload {
            return Err(PublicationError::Conflict);
        }
        tx.execute("INSERT INTO public.factor_parameter_certificate(certificate_fingerprint,revision_fingerprint,program_fingerprint,source_sha256,parameters_fingerprint,parameters_payload,payload) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",&[&c.fingerprint,&revision,&p.fingerprint,&p.source,&params,&c.parameters,&c.payload]).await.map_err(db)?;
        let row=tx.query_one("SELECT payload,parameters_payload FROM public.factor_parameter_certificate WHERE certificate_fingerprint=$1",&[&c.fingerprint]).await.map_err(db)?;
        if row.get::<_, String>(0) != c.payload || row.get::<_, String>(1) != c.parameters {
            return Err(PublicationError::Conflict);
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(db)?;
        tx.commit().await.map_err(|e| {
            if e.code().is_some() {
                db(e)
            } else {
                PublicationError::OutcomeUnknown
            }
        })
    }
    pub async fn read_program(&mut self, fp: &str) -> Result<StoredProgram> {
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let row=tx.query_opt("SELECT payload,source_sha256 FROM public.factor_built_program WHERE program_fingerprint=$1",&[&fp]).await.map_err(db)?.ok_or(PublicationError::MissingEvidence)?;
        let result = program(row.get(0), fp.into(), row.get(1))?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub async fn read_certificate(&mut self, fp: &str) -> Result<StoredCertificate> {
        let tx = self
            .client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let row=tx.query_opt("SELECT c.payload,c.parameters_payload,c.program_fingerprint,p.payload,p.source_sha256,c.revision_fingerprint,c.parameters_fingerprint,c.source_sha256,r.source_sha256 FROM public.factor_parameter_certificate c JOIN public.factor_built_program p ON p.program_fingerprint=c.program_fingerprint JOIN public.private_factor_revision r ON r.revision_fingerprint=c.revision_fingerprint WHERE c.certificate_fingerprint=$1",&[&fp]).await.map_err(db)?.ok_or(PublicationError::MissingEvidence)?;
        let p = program(row.get(3), row.get(2), row.get(4))?;
        let c = certificate(row.get(0), fp.into(), row.get(1))?;
        let v: Value = serde_json::from_str(&c.payload).map_err(|_| PublicationError::Integrity)?;
        if v["program_fingerprint"] != p.fingerprint
            || v["revision_fingerprint"] != row.get::<_, String>(5)
            || v["parameters_fingerprint"] != row.get::<_, String>(6)
            || p.source != row.get::<_, String>(7)
            || p.source != row.get::<_, String>(8)
        {
            return Err(PublicationError::Integrity);
        }
        tx.commit().await.map_err(db)?;
        Ok(c)
    }
}
#[cfg(test)]
#[path = "../tests/support/factor_build_fixture.rs"]
#[allow(dead_code)]
pub(crate) mod fixture;
