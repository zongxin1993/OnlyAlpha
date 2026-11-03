//! Explicit fresh Infrastructure only. No Generation, activation or work binding.
use super::{Result, deployment, open_existing};
use crate::{
    persistence::{
        authority_session::AuthoritySession,
        research_preparation,
        research_runtime::Registry,
        schema::{SchemaHistory, Verdict},
    },
    security::immutable_json::Directory,
};
use rustix::fs;
use serde_json::{Value, json};
use std::path::Path;
const UNKNOWN: &str = "RESEARCH_RUNTIME_INITIALIZATION_OUTCOME_UNKNOWN";

#[cfg(test)]
#[derive(Clone, Copy)]
pub(crate) enum InitializationFault {
    Readback,
    Guard,
}
#[cfg(test)]
std::thread_local! { static NEXT_FAULT: std::cell::Cell<Option<InitializationFault>> = const { std::cell::Cell::new(None) }; }
#[cfg(test)]
pub(crate) fn fail_initialization_for_test(fault: InitializationFault) {
    NEXT_FAULT.with(|next| next.set(Some(fault)));
}

async fn verify_empty_deployment(
    session: &mut AuthoritySession,
    schema: &SchemaHistory,
    id: &deployment::SemanticStoreId,
) -> Result<()> {
    if schema
        .inspect(
            session.client_mut().await.map_err(|error| error.code())?,
            100000,
        )
        .await
        .map_err(|error| error.code())?
        != Verdict::Compatible
    {
        return Err("POSTGRES_SCHEMA_INCOMPATIBLE");
    }
    let tx = session
        .client_mut()
        .await
        .map_err(|error| error.code())?
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?;
    crate::persistence::postgres::bounds(&tx)
        .await
        .map_err(|error| error.code())?;
    AuthoritySession::verify_transaction(&tx)
        .await
        .map_err(|error| error.code())?;
    deployment::verify_binding_in_transaction(&tx, id)
        .await
        .map_err(|error| error.code())?;
    research_preparation::guard_fresh_runtime(
        research_preparation::runtime_history_exists(&tx).await?,
    )?;
    // This constructor has a narrower scope than historical Runtime discovery:
    // only a deployment that has not accepted any business command/work. This
    // includes UNKNOWN windows before a binding's later receipt/fact exists.
    let activity: bool = tx.query_one(
        "SELECT EXISTS(SELECT 1 FROM product_command_admission) OR EXISTS(SELECT 1 FROM research_run) OR EXISTS(SELECT 1 FROM research_preparation) OR EXISTS(SELECT 1 FROM chart_calculation_operation) OR EXISTS(SELECT 1 FROM chart_calculation_preparation_fact) OR EXISTS(SELECT 1 FROM chart_calculation_compilation)",
        &[],
    ).await.map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?.try_get(0).map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")?;
    if activity {
        return Err("RUNTIME_REGISTRY_FRESH_DEPLOYMENT_REQUIRED");
    }
    tx.commit()
        .await
        .map_err(|_| "RESEARCH_RUNTIME_UNAVAILABLE")
}

/// The original physical session is owned across all filesystem publication.
/// A failed/cancelled operation revokes it; callers may never retry via a new socket.
pub async fn initialize_runtime_registry(
    user_data: &Path,
    schema: &SchemaHistory,
    session: &mut AuthoritySession,
) -> Result<Value> {
    let mut owned = session.take_ownership();
    let result = initialize_owned(user_data, schema, &mut owned).await;
    match result {
        Ok(value) => {
            session.restore_ownership(owned);
            Ok(value)
        }
        Err(code) => {
            let _ = owned.close().await;
            Err(code)
        }
    }
}
async fn initialize_owned(
    user_data: &Path,
    schema: &SchemaHistory,
    session: &mut AuthoritySession,
) -> Result<Value> {
    let id = open_existing(user_data)?;
    verify_empty_deployment(session, schema, &id).await?;
    let parent = Directory::open(user_data)?;
    match fs::statat(&parent.fd, "runtime", fs::AtFlags::SYMLINK_NOFOLLOW) {
        Err(rustix::io::Errno::NOENT) => {}
        Ok(_) => return Err("RUNTIME_GENERATION_INITIALIZATION_CONFLICT"),
        Err(_) => return Err("RESEARCH_RUNTIME_UNAVAILABLE"),
    }
    parent.verify()?;
    let runtime = user_data.join("runtime");
    // Publication may have happened even when fsync/readback or the following
    // guard check fails. Retain all original bytes and report uncertainty.
    let published = async {
        let registry = Registry::initialize_fresh(&runtime)?;
        let value = registry.snapshot();
        if value != json!({"active_for_new_work":null,"states":{}}) {
            return Err("RESEARCH_RUNTIME_PROOF_INVALID");
        }
        drop(registry);
        #[cfg(test)]
        match NEXT_FAULT.with(std::cell::Cell::take) {
            Some(InitializationFault::Readback)=>return Err("RESEARCH_RUNTIME_UNAVAILABLE"),
            Some(InitializationFault::Guard)=> {
                session.client_mut().await.map_err(|error|error.code())?
                    .query_one("SELECT pg_catalog.pg_advisory_unlock(1329199301::pg_catalog.int4,5::pg_catalog.int4)",&[]).await.map_err(|_|"RESEARCH_RUNTIME_UNAVAILABLE")?;
            },
            None=>{},
        }

        if Registry::inspect(&runtime)? != value {
            return Err("RESEARCH_RUNTIME_PROOF_INVALID");
        }
        parent.verify()?;
        if open_existing(user_data)? != id {
            return Err("RESEARCH_RUNTIME_PROOF_INVALID");
        }
        verify_empty_deployment(session, schema, &id).await?;
        Ok(value)
    }
    .await;
    published.map_err(|_: &'static str| UNKNOWN)
}
