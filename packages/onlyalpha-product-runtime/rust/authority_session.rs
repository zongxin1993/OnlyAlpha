//! One owned physical Product mutation session. No readiness or reconnection.
use std::fmt;
/// Failures deliberately contain no driver, SQL, configuration or credential text.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthorityError {
    AlreadyHeld,
    Reentrant,
    Lost,
    Unavailable,
    ReleaseFailed,
}
impl AuthorityError {
    pub fn code(self) -> &'static str {
        match self {
            Self::AlreadyHeld => "PRODUCT_KERNEL_AUTHORITY_ALREADY_HELD",
            Self::Reentrant => "PRODUCT_KERNEL_AUTHORITY_REENTRANT",
            Self::Lost => "PRODUCT_KERNEL_AUTHORITY_LOST",
            Self::Unavailable => "PRODUCT_KERNEL_AUTHORITY_UNAVAILABLE",
            Self::ReleaseFailed => "PRODUCT_KERNEL_AUTHORITY_RELEASE_FAILED",
        }
    }
}
impl fmt::Display for AuthorityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for AuthorityError {}

const GUARD_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(5);
// Qualify operators as well as relations/functions: a caller's search_path must
// never select a lookalike system object or alter the exact lock proof.
const GUARD_PROOF: &str = "SELECT EXISTS (
    SELECT 1 FROM pg_catalog.pg_locks
    WHERE locktype OPERATOR(pg_catalog.=) 'advisory'::pg_catalog.text
      AND database OPERATOR(pg_catalog.=) (
          SELECT oid FROM pg_catalog.pg_database
          WHERE datname OPERATOR(pg_catalog.=) pg_catalog.current_database())
      AND pid OPERATOR(pg_catalog.=) pg_catalog.pg_backend_pid()
      AND classid OPERATOR(pg_catalog.=) 1329199301::pg_catalog.int4::pg_catalog.oid
      AND objid OPERATOR(pg_catalog.=) 5::pg_catalog.int4::pg_catalog.oid
      AND objsubid OPERATOR(pg_catalog.=) 2::pg_catalog.int4
      AND granted
      AND ($1::pg_catalog.bool OR mode OPERATOR(pg_catalog.=) 'ExclusiveLock'::pg_catalog.text))";

/// Owns one physical mutation session and its connection driver. This is only
/// the Infrastructure singleton guard, NOT proof of Node READY or permission to
/// invoke Product Commands. The owning Host must also prove startup/recovery,
/// close mutation admission and drain retained work before calling `close`.
/// No reconnection, credential ownership, separate business socket or HA epoch.
pub struct AuthoritySession {
    client: Option<tokio_postgres::Client>,
    driver: Option<tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>>,
}
impl AuthoritySession {
    pub async fn acquire(
        client: tokio_postgres::Client,
        driver: tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>,
    ) -> Result<Self, AuthorityError> {
        // Construct before the first await: cancellation also drops ownership
        // and aborts the driver, rather than leaking an ambiguous acquisition.
        let mut session = Self {
            client: Some(client),
            driver: Some(driver),
        };
        let result = async {
            if session.proof(true).await? { return Err(AuthorityError::Reentrant); }
            if !session.boolean("SELECT pg_catalog.pg_try_advisory_lock(1329199301::pg_catalog.int4,5::pg_catalog.int4)", &[]).await? {
                return Err(AuthorityError::AlreadyHeld);
            }
            session.verify().await
        }.await;
        match result {
            Ok(()) => Ok(session),
            Err(error) => {
                session.invalidate().await;
                Err(error)
            }
        }
    }
    async fn boolean(
        &self,
        sql: &str,
        params: &[&(dyn tokio_postgres::types::ToSql + Sync)],
    ) -> Result<bool, AuthorityError> {
        let client = self.client.as_ref().ok_or(AuthorityError::Lost)?;
        if self
            .driver
            .as_ref()
            .is_none_or(|driver| driver.is_finished())
        {
            return Err(AuthorityError::Unavailable);
        }
        let row = tokio::time::timeout(GUARD_TIMEOUT, client.query_one(sql, params))
            .await
            .map_err(|_| AuthorityError::Unavailable)?
            .map_err(|_| AuthorityError::Unavailable)?;
        row.try_get(0).map_err(|_| AuthorityError::Unavailable)
    }
    async fn proof(&self, any_mode: bool) -> Result<bool, AuthorityError> {
        self.boolean(GUARD_PROOF, &[&any_mode]).await
    }
    pub(crate) fn take_ownership(&mut self) -> Self {
        Self {
            client: self.client.take(),
            driver: self.driver.take(),
        }
    }
    pub(crate) fn restore_ownership(&mut self, mut owned: Self) {
        debug_assert!(self.client.is_none() && self.driver.is_none());
        self.client = owned.client.take();
        self.driver = owned.driver.take();
    }
    pub async fn verify(&mut self) -> Result<(), AuthorityError> {
        // Temporarily move ownership into the future. If the query is cancelled
        // while Pending, its Drop aborts the driver and the original stays lost.
        let mut pending = self.take_ownership();
        let result = match pending.proof(false).await {
            Ok(true) => Ok(()),
            Ok(false) => Err(AuthorityError::Lost),
            Err(error) => Err(error),
        };
        if result.is_ok() {
            self.restore_ownership(pending);
        } else {
            pending.invalidate().await;
        }
        result
    }
    /// Lend the very same physical session after re-proving the lock. The Host
    /// must retain this borrow's work and its own READY admission boundary.
    pub async fn client_mut(&mut self) -> Result<&mut tokio_postgres::Client, AuthorityError> {
        self.verify().await?;
        self.client.as_mut().ok_or(AuthorityError::Lost)
    }
    async fn invalidate(&mut self) {
        self.client.take();
        if let Some(driver) = self.driver.take() {
            driver.abort();
            let _ = driver.await;
        }
    }
    /// Release exactly once and prove absence before physically closing. A
    /// remaining reentrant/shared lock is an error, never a successful drain.
    pub async fn close(mut self) -> Result<(), AuthorityError> {
        self.verify().await?;
        let result = async {
            if !self.boolean("SELECT pg_catalog.pg_advisory_unlock(1329199301::pg_catalog.int4,5::pg_catalog.int4)", &[]).await?
                || self.proof(true).await? {
                return Err(AuthorityError::ReleaseFailed);
            }
            Ok(())
        }.await;
        if result.is_err() {
            self.invalidate().await;
            return Err(AuthorityError::ReleaseFailed);
        }
        self.client.take();
        let result = tokio::time::timeout(
            GUARD_TIMEOUT,
            self.driver.as_mut().ok_or(AuthorityError::ReleaseFailed)?,
        )
        .await;
        match result {
            Ok(result) => {
                // This handle was consumed by awaiting; never poll it twice.
                self.driver.take();
                if matches!(result, Ok(Ok(()))) {
                    Ok(())
                } else {
                    Err(AuthorityError::ReleaseFailed)
                }
            }
            Err(_) => {
                // Keep the handle in self across the await: cancellation must
                // still abort the owned driver rather than detach it.
                self.invalidate().await;
                Err(AuthorityError::ReleaseFailed)
            }
        }
    }
}
impl Drop for AuthoritySession {
    fn drop(&mut self) {
        // Cancellation/drop is unconfirmed cleanup, not graceful Node STOPPED.
        self.client.take();
        if let Some(driver) = self.driver.take() {
            driver.abort();
        }
    }
}
