//! Existing deployment namespace compatibility, never Research semantic identity.
use crate::protected_files::{FilePolicy, ReadError, read_file, read_file_at};
use std::{ffi::OsStr, fmt, os::fd::AsFd, path::Path};
use zeroize::Zeroizing;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Missing,
    Corrupt,
    Unsupported,
    Mismatch,
    BindingMissing,
    Unavailable,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "SEMANTIC_STORE_IDENTITY_MISSING",
            Self::Corrupt => "SEMANTIC_STORE_IDENTITY_CORRUPT",
            Self::Unsupported => "SEMANTIC_STORE_IDENTITY_UNSUPPORTED",
            Self::Mismatch => "SEMANTIC_STORE_IDENTITY_MISMATCH",
            Self::BindingMissing => "DEPLOYMENT_BINDING_MISSING",
            Self::Unavailable => "RESEARCH_RUN_STORE_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(self.code())
    }
}
impl std::error::Error for Error {}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SemanticStoreId(String);
impl SemanticStoreId {
    pub fn new(value: &str) -> Result<Self, Error> {
        if !crate::command::uuid4(value) {
            return Err(Error::Corrupt);
        }
        Ok(Self(value.into()))
    }
    pub fn value(&self) -> &str {
        &self.0
    }
    /// Read existing canonical metadata; never initialize, repair or fingerprint contents.
    pub fn from_document(document: &str) -> Result<Self, Error> {
        if document.len() > 32768 {
            return Err(Error::Unavailable);
        }
        let fields =
            onlyalpha_metadata_json::object_fields(document).map_err(|_| Error::Corrupt)?;
        if fields.len() != 2 {
            return Err(Error::Corrupt);
        }
        let store_id = fields.get("store_id").ok_or(Error::Corrupt)?;
        let schema = fields.get("schema_version").ok_or(Error::Corrupt)?.get();
        // JSON parsing already proves grammar. Only integer spellings are schema versions;
        // an unknown arbitrarily large integer is unsupported, never a cast overflow.
        let digits = schema.strip_prefix('-').unwrap_or(schema);
        if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(Error::Corrupt);
        }
        if schema != "1" {
            return Err(Error::Unsupported);
        }
        let id: String = serde_json::from_str(store_id.get()).map_err(|_| Error::Corrupt)?;
        Self::new(&id)
    }
}

/// Compare the existing binding on the caller-owned connection. This read-only
/// transaction never initializes/adopts a namespace or supplies a READY capability.
pub async fn verify_binding(
    client: &mut tokio_postgres::Client,
    local: &SemanticStoreId,
) -> Result<(), Error> {
    let tx = client
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .map_err(|_| Error::Unavailable)?;
    verify_binding_in_transaction(&tx, local).await?;
    tx.commit().await.map_err(|_| Error::Unavailable)?;
    Ok(())
}

pub(crate) async fn verify_binding_in_transaction(
    tx: &tokio_postgres::Transaction<'_>,
    local: &SemanticStoreId,
) -> Result<(), Error> {
    crate::postgres::bounds(tx)
        .await
        .map_err(|_| Error::Unavailable)?;
    // Read the complete singleton proof, not only rows already claiming TRUE.
    // Two rows suffice to prove corruption; malformed oversized text is bounded
    // before transfer even if a damaged physical column no longer has UUID type.
    let rows=tx.query("SELECT singleton,CASE WHEN pg_catalog.octet_length(semantic_store_id::pg_catalog.text)=36 THEN semantic_store_id::pg_catalog.text ELSE NULL END FROM public.research_deployment_semantic_store_binding LIMIT 2",&[]).await.map_err(|_|Error::Unavailable)?;
    if rows.is_empty() {
        return Err(Error::BindingMissing);
    }
    if rows.len() != 1 || !rows[0].try_get::<_, bool>(0).map_err(|_| Error::Corrupt)? {
        return Err(Error::Corrupt);
    }
    let value = rows[0]
        .try_get::<_, String>(1)
        .map_err(|_| Error::Corrupt)?;
    let expected = SemanticStoreId::new(&value)?;
    if expected != *local {
        return Err(Error::Mismatch);
    }
    Ok(())
}

/// Snapshot existing nonsecret namespace metadata without creating deployment state.
pub fn load_semantic_store_id(path: &Path) -> Result<SemanticStoreId, Error> {
    decode_store_id(read_file(path, FilePolicy::Metadata))
}
pub fn load_semantic_store_id_at(directory: &impl AsFd) -> Result<SemanticStoreId, Error> {
    decode_store_id(read_file_at(
        directory,
        OsStr::new(".onlyalpha-semantic-store.json"),
        FilePolicy::Metadata,
        32768,
    ))
}
fn decode_store_id(data: Result<Zeroizing<Vec<u8>>, ReadError>) -> Result<SemanticStoreId, Error> {
    let data = data.map_err(|error| match error {
        ReadError::Missing => Error::Missing,
        ReadError::Invalid => Error::Corrupt,
        ReadError::Unavailable => Error::Unavailable,
    })?;
    let document = std::str::from_utf8(&data).map_err(|_| Error::Corrupt)?;
    SemanticStoreId::from_document(document)
}
