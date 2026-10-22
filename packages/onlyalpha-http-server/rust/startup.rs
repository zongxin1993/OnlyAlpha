//! Concrete frozen storage inputs for native Node startup, never Node READY.
//! Owning registry, durable history/reconciliation, mutation guard and work drain
//! remain separate mandatory prerequisites of the actual Host composition.
use crate::configuration::{self, MasterKeyFileError};
use onlyalpha_product_runtime::protected_files::{self, ReadError};
use onlyalpha_product_runtime::{
    credentials::Key,
    deployment::{self, SemanticStoreId},
    schema::{self, SchemaHistory},
};
use std::{
    ffi::OsStr,
    fmt,
    os::fd::{AsFd, BorrowedFd, OwnedFd},
    path::Path,
};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    RequiredRootUnusable,
    MasterKey(MasterKeyFileError),
    Namespace(deployment::Error),
    Schema(schema::Error),
    SchemaIncompatible(schema::Verdict),
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::RequiredRootUnusable => "REQUIRED_ROOT_UNUSABLE",
            Self::MasterKey(e) => e.code(),
            Self::Namespace(e) => e.code(),
            Self::Schema(e) => e.code(),
            Self::SchemaIncompatible(_) => "SCHEMA_INCOMPATIBLE",
            Self::Unavailable => "RESEARCH_RUN_STORE_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Directory {
    UserData,
    Research,
    Secrets,
    Artifacts,
    BacktestEvidence,
    Datasets,
    EconomicBindings,
}
/// Retain the actual selected directory capabilities for later owning readers;
/// no re-resolution of a replaceable original absolute path is required.
pub struct StorageRoots {
    user_data: OwnedFd,
    research: OwnedFd,
    secrets: OwnedFd,
    artifacts: OwnedFd,
    backtest_evidence: OwnedFd,
    datasets: OwnedFd,
    economic_bindings: OwnedFd,
}
impl StorageRoots {
    pub fn open(root: &Path) -> Result<Self, Error> {
        let required = |_: ReadError| Error::RequiredRootUnusable;
        let user_data = protected_files::open_directory(root).map_err(required)?;
        let research = protected_files::open_directory_at(&user_data, OsStr::new("research"))
            .map_err(required)?;
        let artifacts = protected_files::open_directory_at(&research, OsStr::new("artifacts"))
            .map_err(required)?;
        let datasets = protected_files::open_directory_at(&research, OsStr::new("datasets"))
            .map_err(required)?;
        let economic_bindings =
            protected_files::open_directory_at(&research, OsStr::new("dataset-economic-bindings"))
                .map_err(required)?;
        let backtest = protected_files::open_directory_at(&user_data, OsStr::new("backtest"))
            .map_err(required)?;
        let backtest_evidence =
            protected_files::open_directory_at(&backtest, OsStr::new("evidence"))
                .map_err(required)?;
        let secrets = protected_files::open_directory_at(&user_data, OsStr::new("secrets"))
            .map_err(|e| {
                Error::MasterKey(if e == ReadError::Missing {
                    MasterKeyFileError::Missing
                } else {
                    MasterKeyFileError::Invalid
                })
            })?;
        // Opening a directory for reading does not prove that its children can
        // be searched. Ask the OS for the effective identity, preserving ACLs.
        for directory in [
            &user_data,
            &artifacts,
            &backtest_evidence,
            &datasets,
            &economic_bindings,
        ] {
            rustix::fs::accessat(
                directory,
                ".",
                rustix::fs::Access::READ_OK | rustix::fs::Access::EXEC_OK,
                rustix::fs::AtFlags::EACCESS,
            )
            .map_err(|_| Error::RequiredRootUnusable)?;
        }
        Ok(Self {
            user_data,
            research,
            secrets,
            artifacts,
            backtest_evidence,
            datasets,
            economic_bindings,
        })
    }
    pub fn directory(&self, kind: Directory) -> BorrowedFd<'_> {
        match kind {
            Directory::UserData => &self.user_data,
            Directory::Research => &self.research,
            Directory::Secrets => &self.secrets,
            Directory::Artifacts => &self.artifacts,
            Directory::BacktestEvidence => &self.backtest_evidence,
            Directory::Datasets => &self.datasets,
            Directory::EconomicBindings => &self.economic_bindings,
        }
        .as_fd()
    }
}
/// Complete startup inputs only, with no cached compatibility/READY flag.
/// Loading does not initialize, migrate, repair or select a new semantic store.
pub struct StorageInputs {
    roots: StorageRoots,
    key: Key,
    namespace: SemanticStoreId,
    schema: SchemaHistory,
}
impl StorageInputs {
    pub fn load(
        roots: StorageRoots,
        schema_source: &Path,
        max_schema_work: usize,
    ) -> Result<Self, Error> {
        let key = configuration::load_master_key_at(&roots.secrets).map_err(Error::MasterKey)?;
        let namespace =
            deployment::load_semantic_store_id_at(&roots.research).map_err(Error::Namespace)?;
        let schema = configuration::load_schema_history(schema_source, max_schema_work)
            .map_err(Error::Schema)?;
        Ok(Self {
            roots,
            key,
            namespace,
            schema,
        })
    }
    pub fn roots(&self) -> &StorageRoots {
        &self.roots
    }
    pub fn key(&self) -> &Key {
        &self.key
    }
    pub fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
    /// Reuse the owning read-only readers on this exact caller-owned session.
    /// These are two startup observations, not one atomic DB snapshot. A changed
    /// deployment requires controlled restart/revalidation; no READY is cached.
    /// Cancellation/error returns no proof. The Host owns failed-startup cleanup.
    pub async fn verify(
        &self,
        client: &mut tokio_postgres::Client,
        max_rows: usize,
    ) -> Result<(), Error> {
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            let verdict = self
                .schema
                .inspect(client, max_rows)
                .await
                .map_err(Error::Schema)?;
            if verdict != schema::Verdict::Compatible {
                return Err(Error::SchemaIncompatible(verdict));
            }
            deployment::verify_binding(client, &self.namespace)
                .await
                .map_err(Error::Namespace)
        })
        .await
        .map_err(|_| Error::Unavailable)?
    }
}
