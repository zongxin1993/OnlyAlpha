//! Read-only admission against the existing ordered SQL-byte migration authority.
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fmt};
use tokio_postgres::{Client, IsolationLevel};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Integrity,
    Unavailable,
    ServerMajorUnsupported,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Integrity => "POSTGRES_MIGRATION_INTEGRITY_ERROR",
            Self::Unavailable => "RESEARCH_RUN_STORE_UNAVAILABLE",
            Self::ServerMajorUnsupported => "POSTGRES_SERVER_MAJOR_UNSUPPORTED",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(self.code())
    }
}
impl std::error::Error for Error {}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Verdict {
    Compatible,
    Behind,
    Ahead,
    ChecksumMismatch,
    HistoryDiverged,
    LedgerMissing,
}
impl Verdict {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Compatible => "COMPATIBLE",
            Self::Behind => "BEHIND",
            Self::Ahead => "AHEAD",
            Self::ChecksumMismatch => "CHECKSUM_MISMATCH",
            Self::HistoryDiverged => "HISTORY_DIVERGED",
            Self::LedgerMissing => "LEDGER_MISSING",
        }
    }
}
/// Immutable expected history derived from exact canonical SQL bytes, not a second manifest.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SchemaHistory {
    expected: BTreeMap<String, String>,
}
impl SchemaHistory {
    pub fn from_sql(sources: Vec<(String, Vec<u8>)>, max_work: usize) -> Result<Self, Error> {
        if sources.is_empty() {
            return Err(Error::Integrity);
        }
        let mut work = max_work;
        let mut expected = BTreeMap::new();
        for (id, sql) in sources {
            let cost = id
                .len()
                .checked_add(sql.len())
                .and_then(|size| size.checked_add(64))
                .ok_or(Error::Unavailable)?;
            work = work.checked_sub(cost).ok_or(Error::Unavailable)?;
            if id.len() > 512 || sql.len() > 32768 {
                return Err(Error::Unavailable);
            }
            if !migration_id(&id) || std::str::from_utf8(&sql).is_err() {
                return Err(Error::Integrity);
            }
            let hash = Sha256::digest(&sql)
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            if expected.insert(id, hash).is_some() {
                return Err(Error::Integrity);
            }
        }
        Ok(Self { expected })
    }
    /// The node owns its connection and finite row budget. Neither this reader nor
    /// its status initializes, migrates, repairs or selects a deployment.
    pub async fn inspect(&self, client: &mut Client, max_rows: usize) -> Result<Verdict, Error> {
        if max_rows == 0 {
            return Err(Error::Unavailable);
        }
        let limit = i64::try_from(max_rows.checked_add(1).ok_or(Error::Unavailable)?)
            .map_err(|_| Error::Unavailable)?;
        let tx = client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        crate::postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let version: String = tx
            .query_one(
                "SELECT pg_catalog.current_setting('server_version_num')",
                &[],
            )
            .await
            .map_err(|_| Error::Unavailable)?
            .try_get(0)
            .map_err(|_| Error::Unavailable)?;
        supported_server(version.parse().map_err(|_| Error::Unavailable)?)?;
        let exists: bool = tx
            .query_one(
                "SELECT pg_catalog.to_regclass('public.onlyalpha_schema_migration') IS NOT NULL",
                &[],
            )
            .await
            .map_err(|_| Error::Unavailable)?
            .try_get(0)
            .map_err(|_| Error::Unavailable)?;
        if !exists {
            tx.commit().await.map_err(|_| Error::Unavailable)?;
            return Ok(Verdict::LedgerMissing);
        }
        // Presence and data name the same canonical relation irrespective of search_path.
        // Original field lengths distinguish corrupt proof from an operational byte limit.
        let rows=tx.query("SELECT pg_catalog.octet_length(migration_id::pg_catalog.text), CASE WHEN pg_catalog.octet_length(migration_id::pg_catalog.text)<=512 THEN migration_id::pg_catalog.text END, pg_catalog.octet_length(checksum_sha256::pg_catalog.text), CASE WHEN pg_catalog.octet_length(checksum_sha256::pg_catalog.text)=64 THEN checksum_sha256::pg_catalog.text END FROM public.onlyalpha_schema_migration ORDER BY migration_id::pg_catalog.text COLLATE pg_catalog.\"C\" LIMIT $1",&[&limit]).await.map_err(|_|Error::Unavailable)?;
        if rows.len() > max_rows {
            return Err(Error::Unavailable);
        }
        let mut applied = BTreeMap::new();
        for row in rows {
            let id_len: i32 = row.try_get(0).map_err(|_| Error::Integrity)?;
            if id_len > 512 {
                return Err(Error::Unavailable);
            }
            let id: String = row.try_get(1).map_err(|_| Error::Integrity)?;
            let hash_len: i32 = row.try_get(2).map_err(|_| Error::Integrity)?;
            let hash: String = row.try_get(3).map_err(|_| Error::Integrity)?;
            if !migration_id(&id)
                || id_len <= 0
                || hash_len != 64
                || !crate::is_sha256_hex(&hash)
                || applied.insert(id, hash).is_some()
            {
                return Err(Error::Integrity);
            }
        }
        let verdict = if applied.keys().any(|id| !self.expected.contains_key(id)) {
            Verdict::Ahead
        } else if applied
            .iter()
            .any(|(id, hash)| self.expected.get(id) != Some(hash))
        {
            Verdict::ChecksumMismatch
        } else if !applied.keys().eq(self.expected.keys().take(applied.len())) {
            Verdict::HistoryDiverged
        } else if applied.len() < self.expected.len() {
            Verdict::Behind
        } else {
            Verdict::Compatible
        };
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        Ok(verdict)
    }
}
fn migration_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() >= 5
        && bytes[..4].iter().all(u8::is_ascii_digit)
        && bytes[4] == b'_'
        && !bytes.iter().any(|byte| matches!(byte, 0 | b'/'))
}
fn supported_server(version: u32) -> Result<(), Error> {
    if version / 10000 == 18 {
        Ok(())
    } else {
        Err(Error::ServerMajorUnsupported)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn source_bytes_and_work_limits_do_not_change_identity_or_certify_corruption() {
        let source = || vec![("0001_first".to_owned(), b"SELECT 1;".to_vec())];
        // Ten ID bytes, nine original SQL bytes and 64 SHA hex output bytes.
        assert!(SchemaHistory::from_sql(source(), 83).is_ok());
        assert_eq!(
            SchemaHistory::from_sql(source(), 82),
            Err(Error::Unavailable)
        );
        assert_eq!(
            SchemaHistory::from_sql(vec![("0001_first".into(), vec![0xff])], 4096),
            Err(Error::Integrity)
        );
        assert!(
            SchemaHistory::from_sql(vec![("0001_first".into(), vec![b' '; 32768])], 65536).is_ok()
        );
        assert_eq!(
            SchemaHistory::from_sql(vec![("0001_first".into(), vec![b' '; 32769])], 65536),
            Err(Error::Unavailable)
        );
    }
    #[test]
    fn supported_database_family_is_not_inferred_from_connectivity() {
        for version in [180000, 180006, 189999] {
            assert_eq!(supported_server(version), Ok(()));
        }
        for version in [0, 1, 170019, 190000, u32::MAX] {
            assert_eq!(
                supported_server(version),
                Err(Error::ServerMajorUnsupported)
            );
        }
    }
}
