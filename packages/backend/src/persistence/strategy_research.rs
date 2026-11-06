//! PostgreSQL owns exact Strategy/Factor revisions and immutable Composition1.
//! Runtime remains the existing held Generation; this owner grants no Run or Freeze.
use crate::{
    application::{
        private_assets,
        strategy_research::{Composition, Context, ResolvedCalculations},
    },
    persistence::{postgres::bounds, research_runtime::RuntimeInputHold},
};
use serde_json::Value;
use std::collections::BTreeMap;
use tokio_postgres::Client;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "PRIVATE_STRATEGY_COMPOSITION_INVALID";
const CORRUPT: &str = "PRIVATE_STRATEGY_COMPOSITION_CORRUPT";
const UNAVAILABLE: &str = "PRIVATE_STRATEGY_COMPOSITION_UNAVAILABLE";
fn asset_error(error: private_assets::Error) -> &'static str {
    match error {
        private_assets::Error::Unavailable => UNAVAILABLE,
        private_assets::Error::NotFound => "PRIVATE_STRATEGY_COMPOSITION_REVISION_UNAVAILABLE",
        private_assets::Error::Invalid => INVALID,
        _ => CORRUPT,
    }
}
fn decode(raw: Option<String>) -> Result<Value> {
    serde_json::from_str(&raw.ok_or(UNAVAILABLE)?).map_err(|_| CORRUPT)
}
pub struct Composer<'a> {
    client: &'a mut Client,
}
impl<'a> Composer<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    /// Mathematical resolution retains exact original work, not a new Run grant.
    pub async fn resolve(
        &mut self,
        id: &str,
        revision: &str,
        context: &Context,
        mut runtime: RuntimeInputHold,
        installation: &onlyalpha_calculation_bridge::ChartInstallation,
    ) -> std::result::Result<
        ResolvedCalculations,
        crate::application::research_admission::PreparationError,
    > {
        let (composition, strategy, factors) = self
            .compose_inputs(id, revision, context, &mut runtime)
            .await?;
        ResolvedCalculations::resolve(
            runtime,
            installation,
            &strategy,
            context,
            &factors,
            &composition,
        )
    }
    /// Re-anchor every immutable input through its owner in one consistent DB
    /// transaction, retaining the caller's actual Runtime hold across publication.
    pub async fn compose(
        &mut self,
        id: &str,
        revision: &str,
        context: &Context,
        runtime: &mut RuntimeInputHold,
    ) -> Result<Composition> {
        Ok(self.compose_inputs(id, revision, context, runtime).await?.0)
    }
    /// Read the original immutable Composition fact and its exact revisions.
    /// Missing history is corruption; this path cannot publish or repair it.
    pub(crate) async fn reanchor(
        &mut self,
        composition: &Value,
        context: &Context,
        runtime: &RuntimeInputHold,
    ) -> Result<Value> {
        let (_, strategy, _, original) = self.retained_inputs(composition, runtime).await?;
        if original.record() != context.record() {
            return Err(CORRUPT);
        }
        Ok(strategy)
    }
    /// Restoration consumes only the existing composition and original work;
    /// it must not enter compose_inputs, whose publication may create a fact.
    pub(crate) async fn resolve_retained(
        &mut self,
        composition: &Value,
        mut runtime: RuntimeInputHold,
        installation: &onlyalpha_calculation_bridge::ChartInstallation,
    ) -> std::result::Result<
        (ResolvedCalculations, Context),
        crate::application::research_admission::PreparationError,
    > {
        runtime.verify_artifacts()?;
        let (composition, strategy, factors, context) =
            self.retained_inputs(composition, &runtime).await?;
        let resolved = ResolvedCalculations::resolve(
            runtime,
            installation,
            &strategy,
            &context,
            &factors,
            &composition,
        )?;
        Ok((resolved, context))
    }
    pub(crate) async fn retained_inputs(
        &mut self,
        expected: &Value,
        runtime: &RuntimeInputHold,
    ) -> Result<(Composition, Value, BTreeMap<String, Value>, Context)> {
        let pin = expected["composition_fingerprint"]
            .as_str()
            .filter(|p| crate::is_sha256_hex(p))
            .ok_or(CORRUPT)?;
        runtime.verify().map_err(|_| UNAVAILABLE)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await.map_err(|_| UNAVAILABLE)?;
        let stored=tx.query_opt("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=8388608 THEN (to_jsonb(c)-'research_context_payload')::text ELSE NULL END AS record,CASE WHEN octet_length(research_context_payload::text)<=8388608 THEN research_context_payload::text ELSE NULL END AS context FROM private_strategy_research_composition c WHERE composition_fingerprint=$1",&[&pin]).await.map_err(|_|UNAVAILABLE)?.ok_or(CORRUPT)?;
        let record = decode(stored.try_get("record").map_err(|_| CORRUPT)?)?;
        let context = Context::new(decode(stored.try_get("context").map_err(|_| CORRUPT)?)?)?;
        if record != *expected {
            return Err(CORRUPT);
        }
        let id = record["private_strategy_id"].as_str().ok_or(CORRUPT)?;
        let revision = record["private_strategy_revision_fingerprint"]
            .as_str()
            .ok_or(CORRUPT)?;
        let (strategy, factors) = revisions(&tx, id, revision).await?;
        let composition = Composition::derive(&strategy, &context, runtime.manifest(), &factors)?;
        if composition.record() != expected {
            return Err(CORRUPT);
        }
        runtime.verify().map_err(|_| UNAVAILABLE)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok((composition, strategy, factors, context))
    }
    async fn compose_inputs(
        &mut self,
        id: &str,
        revision: &str,
        context: &Context,
        runtime: &mut RuntimeInputHold,
    ) -> Result<(Composition, Value, BTreeMap<String, Value>)> {
        runtime.verify_artifacts().map_err(|_| UNAVAILABLE)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .start()
            .await
            .map_err(|_| UNAVAILABLE)?;
        bounds(&tx).await.map_err(|_| UNAVAILABLE)?;
        let (strategy, factors) = revisions(&tx, id, revision).await?;
        let composition = Composition::derive(&strategy, context, runtime.manifest(), &factors)?;
        let record = composition.record();
        let text = |key: &str| record[key].as_str().ok_or(CORRUPT);
        let pin = text("composition_fingerprint")?;
        let definition = text("private_strategy_definition_fingerprint")?;
        let context_pin = text("research_context_fingerprint")?;
        let catalog = text("catalog_generation_fingerprint")?;
        let research = text("research_definition_fingerprint")?;
        let bindings = record["factor_revision_bindings"].to_string();
        let payload = context.record().to_string();
        tx.execute("INSERT INTO private_strategy_research_composition(composition_fingerprint,schema_version,private_strategy_id,private_strategy_revision_fingerprint,private_strategy_definition_fingerprint,research_context_fingerprint,factor_revision_bindings,catalog_generation_fingerprint,research_definition_fingerprint,research_context_payload) VALUES($1,1,$2,$3,$4,$5,$6::text::jsonb,$7,$8,$9::text::jsonb) ON CONFLICT(composition_fingerprint) DO NOTHING",&[&pin,&id,&revision,&definition,&context_pin,&bindings,&catalog,&research,&payload]).await.map_err(|_|UNAVAILABLE)?;
        let stored=tx.query_one("SELECT CASE WHEN octet_length(to_jsonb(c)::text)<=8388608 THEN (to_jsonb(c)-'research_context_payload')::text ELSE NULL END AS record,CASE WHEN octet_length(research_context_payload::text)<=8388608 THEN research_context_payload::text ELSE NULL END AS context FROM private_strategy_research_composition c WHERE composition_fingerprint=$1",&[&pin]).await.map_err(|_|UNAVAILABLE)?;
        if decode(stored.try_get("record").map_err(|_| CORRUPT)?)? != *record
            || decode(stored.try_get("context").map_err(|_| CORRUPT)?)? != *context.record()
        {
            return Err(CORRUPT);
        }
        runtime.verify().map_err(|_| UNAVAILABLE)?;
        tx.commit()
            .await
            .map_err(|_| "PRIVATE_STRATEGY_COMPOSITION_OUTCOME_UNKNOWN")?;
        Ok((composition, strategy, factors))
    }
}

async fn revisions(
    tx: &tokio_postgres::Transaction<'_>,
    id: &str,
    revision: &str,
) -> Result<(Value, BTreeMap<String, Value>)> {
    let strategy = private_assets::strategy_revision_in_transaction(tx, id, revision)
        .await
        .map_err(asset_error)?;
    let mut factors = BTreeMap::new();
    for dependency in strategy["definition"]["factor_revision_dependencies"]
        .as_array()
        .ok_or(CORRUPT)?
    {
        let id = dependency["factor_id"].as_str().ok_or(CORRUPT)?;
        let pin = dependency["revision_fingerprint"].as_str().ok_or(CORRUPT)?;
        let factor = private_assets::factor_revision_in_transaction(tx, id, pin)
            .await
            .map_err(asset_error)?;
        if factors.insert(id.to_owned(), factor).is_some() {
            return Err(CORRUPT);
        }
    }
    Ok((strategy, factors))
}
