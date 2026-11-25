//! Query location for immutable build facts, never READY/Claim/admission authority.
//! Control callers own the original AS driver before entering a transaction.
//! Reader callers retain their separately owned, fixed-role connection/driver.
use super::job_publication::{PublicationError,db,deployment_error,read_control_facts,role};
use crate::bootstrap::deployment::{self,SemanticStoreId};
use serde_json::Value;
use std::collections::BTreeMap;
use tokio_postgres::Transaction;

enum Location<'a,'t> { Control {tx:&'a Transaction<'t>,owner:&'a super::authority_session::ControlRoleOwner}, Reader {metadata:&'a Transaction<'t>,facts:&'a Transaction<'t>} }
pub(crate) struct BuildFactRead<'a,'t> { location:Location<'a,'t> }
impl<'a,'t> BuildFactRead<'a,'t> {
    pub(crate) fn control(tx:&'a Transaction<'t>,owner:&'a super::authority_session::ControlRoleOwner) -> Self { Self {location:Location::Control {tx,owner}} }
    /// No role switching on the metadata socket. The actual separate reader is
    /// readonly, exact-role and bound to the same original semantic namespace.
    pub(crate) async fn reader(metadata:&'a Transaction<'t>,tx:&'a Transaction<'t>,namespace:&SemanticStoreId) -> Result<Self,PublicationError> {
        deployment::verify_binding_in_transaction(metadata,namespace).await.map_err(deployment_error)?;
        // Metadata keeps its original consistent snapshot. Immutable build
        // rows are read by exact identities under READ COMMITTED, so a reader
        // opened earlier cannot falsely miss a fact referenced by later metadata.
        let readonly:bool=tx.query_one("SELECT pg_catalog.current_setting('transaction_read_only')='on' AND pg_catalog.current_setting('transaction_isolation')='read committed'",&[]).await.map_err(db)?.get(0);
        if !readonly { return Err(PublicationError::Denied); }
        role(tx,&["onlyalpha_job_reader"]).await?;
        deployment::verify_binding_in_transaction(tx,namespace).await.map_err(deployment_error)?;
        Ok(Self {location:Location::Reader {metadata,facts:tx}})
    }
    pub(crate) async fn verify_research_registration(&self,run:&crate::application::research_run::VerifiedRun) -> Result<(),PublicationError> {
        let namespace=deployment::read_binding(self).await.map_err(deployment_error)?;
        match self.location {
            Location::Control {tx,owner}=>read_control_facts(tx,owner,|facts| async move {
                super::job_publication::verify_frozen_identity(facts,&namespace,run).await
            }).await?,
            Location::Reader {facts,..}=>super::job_publication::verify_frozen_identity(facts,&namespace,run).await,
        }
    }
    pub(crate) async fn read_research_publication(
        &self,
        namespace: &SemanticStoreId,
        run: &crate::application::research_run::VerifiedRun,
    ) -> Result<super::job_publication::PublishedJobResult, PublicationError> {
        use super::job_publication::read_registered_research;
        deployment::verify_binding_in_transaction(self, namespace).await.map_err(deployment_error)?;
        match self.location {
            Location::Control { tx, owner } => read_control_facts(tx, owner, |facts| async move {
                read_registered_research(facts, namespace, run).await
            }).await?,
            Location::Reader { facts, .. } => read_registered_research(facts, namespace, run).await,
        }
    }

    pub(crate) async fn read_backtest_publication(
        &self,
        namespace: &SemanticStoreId,
        run: &crate::application::backtest_run::VerifiedRun,
    ) -> Result<super::job_publication::BacktestStorage, PublicationError> {
        use super::job_publication::read_registered_backtest;
        deployment::verify_binding_in_transaction(self, namespace).await.map_err(deployment_error)?;
        match self.location {
            Location::Control { tx, owner } => read_control_facts(tx, owner, |facts| async move {
                read_registered_backtest(facts, namespace, run).await
            }).await?,
            Location::Reader { facts, .. } => read_registered_backtest(facts, namespace, run).await,
        }
    }

    pub(crate) async fn verify_calculation(&self,proof:&Value) -> Result<(),&'static str> {
        match self.location {
            Location::Control {tx,owner}=>read_control_facts(tx,owner,|facts| async move {
                crate::application::calculation_build::verify_fact(facts,proof).await
            }).await.map_err(|_|"CALCULATION_BUILD_PROOF_UNAVAILABLE")?,
            Location::Reader {facts:tx,..}=>crate::application::calculation_build::verify_fact(tx,proof).await,
        }
    }
    pub(crate) async fn verify_retained(&self,prepared:&Value,revision:&Value,factors:&BTreeMap<String,Value>) -> Result<(),crate::application::factor_build::BuildError> {
        match self.location {
            Location::Control {tx,owner}=>read_control_facts(tx,owner,|facts| async move {
                crate::application::factor_build::verify_retained_resolution(facts,prepared,revision,factors).await
            }).await.map_err(crate::application::factor_build::BuildError::Storage)?,
            Location::Reader {facts:tx,..}=>crate::application::factor_build::verify_retained_resolution(tx,prepared,revision,factors).await,
        }
    }
}

impl<'a,'t> std::ops::Deref for BuildFactRead<'a,'t> {
    type Target=Transaction<'t>;
    fn deref(&self) -> &Self::Target {
        match self.location { Location::Control {tx,..}=>tx, Location::Reader {metadata,..}=>metadata }
    }
}
