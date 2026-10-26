//! Read-only retained Private Asset metadata. No authoring, registration, execution
//! or Research authority follows from a published authoring Revision.
use crate::application::source_access::Session;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use tokio_postgres::{Client, IsolationLevel, Row};
const WORK: usize = 8 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Invalid,
    Corrupt,
    Unavailable,
    NotFound,
    Mismatch,
    Forbidden,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "PRIVATE_ASSET_INVALID",
            Self::Corrupt => "PRIVATE_ASSET_CORRUPT",
            Self::Unavailable => "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE",
            Self::NotFound => "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE",
            Self::Mismatch => "PRIVATE_ASSET_EXACT_READ_MISMATCH",
            Self::Forbidden => "PRIVATE_ASSET_ACCESS_DENIED",
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
type Result<T> = std::result::Result<T, Error>;
fn hash(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
fn fp(v: &Value) -> Result<String> {
    Ok(hash(
        onlyalpha_metadata_json::canonical_json(&v.to_string(), WORK)
            .map_err(|_| Error::Corrupt)?
            .as_bytes(),
    ))
}
fn exact(v: &Value, fields: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(Error::Corrupt)?;
    if o.len() != fields.len() || fields.iter().any(|k| !o.contains_key(*k)) {
        return Err(Error::Corrupt);
    }
    Ok(())
}
fn text(v: &Value, empty: bool) -> Result<&str> {
    v.as_str()
        .filter(|s| empty || !s.is_empty())
        .ok_or(Error::Corrupt)
}
fn sha(v: &Value) -> Result<&str> {
    let s = text(v, false)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(Error::Corrupt);
    }
    Ok(s)
}
fn id(s: &str, kind: &str) -> Result<()> {
    let prefix = format!("private.{}.", kind.to_lowercase());
    let tail = s.strip_prefix(&prefix).ok_or(Error::Invalid)?;
    if !tail.as_bytes().first().is_some_and(u8::is_ascii_lowercase)
        || tail.split(['.', '_', '-']).any(|s| {
            s.is_empty()
                || !s
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
        })
    {
        return Err(Error::Invalid);
    }
    Ok(())
}
fn canonical_json_values(v: &Value, depth: usize) -> Result<()> {
    if depth > 32 {
        return Err(Error::Corrupt);
    }
    match v {
        Value::Number(n) => {
            if n.as_str().contains(['.', 'e', 'E']) {
                return Err(Error::Corrupt);
            }
        }
        Value::Object(m) => {
            for value in m.values() {
                canonical_json_values(value, depth + 1)?
            }
        }
        Value::Array(a) => {
            for value in a {
                canonical_json_values(value, depth + 1)?
            }
        }
        _ => (),
    }
    Ok(())
}
fn revision(kind: &str, value: &Value) -> Result<()> {
    let common = [
        "schema_version",
        "semantic_version",
        "revision_fingerprint",
        "parent_revision_fingerprint",
        "description",
        "tags",
    ];
    let mut fields = common.to_vec();
    fields.extend(if kind == "FACTOR" {
        vec![
            "factor_id",
            "source_text",
            "source_sha256",
            "factor_api_version",
            "factor_api_contract_fingerprint",
            "input_contract",
            "parameter_contract",
            "output_contract",
            "economic_rationale",
            "category",
        ]
    } else {
        vec!["strategy_id", "definition", "definition_fingerprint"]
    });
    exact(value, &fields)?;
    if value["schema_version"] != 1 {
        return Err(Error::Corrupt);
    }
    let owner = if kind == "FACTOR" {
        "factor_id"
    } else {
        "strategy_id"
    };
    id(text(&value[owner], false)?, kind).map_err(|_| Error::Corrupt)?;
    let version = text(&value["semantic_version"], false)?;
    if version.starts_with('0') || !version.bytes().all(|b| b.is_ascii_digit()) {
        return Err(Error::Corrupt);
    }
    text(&value["description"], true)?;
    sha(&value["revision_fingerprint"])?;
    if !value["parent_revision_fingerprint"].is_null() {
        sha(&value["parent_revision_fingerprint"])?;
    }
    let tags = value["tags"]
        .as_array()
        .ok_or(Error::Corrupt)?
        .iter()
        .map(|v| text(v, false))
        .collect::<Result<Vec<_>>>()?;
    let sorted = tags.iter().copied().collect::<BTreeSet<_>>();
    if tags.len() != sorted.len() || tags.iter().copied().ne(sorted) {
        return Err(Error::Corrupt);
    }
    if kind == "FACTOR" {
        let source = text(&value["source_text"], false)?;
        if hash(source.as_bytes()) != sha(&value["source_sha256"])?
            || value["factor_api_version"] != 1
        {
            return Err(Error::Corrupt);
        }
        sha(&value["factor_api_contract_fingerprint"])?;
        text(&value["economic_rationale"], true)?;
        text(&value["category"], false)?;
        for field in ["input_contract", "parameter_contract", "output_contract"] {
            if !value[field].is_object() {
                return Err(Error::Corrupt);
            }
            canonical_json_values(&value[field], 0)?;
        }
    } else {
        if !value["definition"].is_object() {
            return Err(Error::Corrupt);
        }
        canonical_json_values(&value["definition"], 0)?;
        let mut definition = value["definition"]
            .as_object()
            .ok_or(Error::Corrupt)?
            .clone();
        definition.insert(
            "contract".into(),
            json!("ONLYALPHA_PRIVATE_STRATEGY_DEFINITION_V1"),
        );
        if fp(&Value::Object(definition))? != sha(&value["definition_fingerprint"])? {
            return Err(Error::Corrupt);
        }
    }
    let mut identity = value.as_object().ok_or(Error::Corrupt)?.clone();
    identity.remove("revision_fingerprint");
    identity.insert(
        "contract".into(),
        json!(if kind == "FACTOR" {
            "ONLYALPHA_PRIVATE_FACTOR_REVISION_V1"
        } else {
            "ONLYALPHA_PRIVATE_STRATEGY_REVISION_V1"
        }),
    );
    if fp(&Value::Object(identity))? != sha(&value["revision_fingerprint"])? {
        return Err(Error::Corrupt);
    }
    Ok(())
}
fn row(kind: &str, row: &Row) -> Result<Value> {
    let raw: Option<String> = row.try_get("payload").map_err(|_| Error::Corrupt)?;
    let raw = raw.ok_or(Error::Corrupt)?;
    if raw.len() > WORK {
        return Err(Error::Unavailable);
    }
    let value: Value = serde_json::from_str(&raw).map_err(|_| Error::Corrupt)?;
    revision(kind, &value)?;
    let owner = if kind == "FACTOR" {
        "factor_id"
    } else {
        "strategy_id"
    };
    let stored_id: String = row.try_get("asset_id").map_err(|_| Error::Corrupt)?;
    let stored_fp: Option<String> = row
        .try_get("revision_fingerprint")
        .map_err(|_| Error::Corrupt)?;
    let stored_parent: Option<String> = row
        .try_get("parent_revision_fingerprint")
        .map_err(|_| Error::Corrupt)?;
    let schema: Option<i32> = row.try_get("schema_version").map_err(|_| Error::Corrupt)?;
    if value[owner] != stored_id
        || value["revision_fingerprint"].as_str() != stored_fp.as_deref()
        || value["parent_revision_fingerprint"].as_str() != stored_parent.as_deref()
        || schema != Some(1)
    {
        return Err(Error::Corrupt);
    }
    if kind == "FACTOR" {
        let source: Option<String> = row.try_get("source_text").map_err(|_| Error::Corrupt)?;
        let digest: Option<String> = row.try_get("source_sha256").map_err(|_| Error::Corrupt)?;
        if value["source_text"].as_str() != source.as_deref()
            || value["source_sha256"].as_str() != digest.as_deref()
        {
            return Err(Error::Corrupt);
        }
    } else {
        let digest: Option<String> = row
            .try_get("definition_fingerprint")
            .map_err(|_| Error::Corrupt)?;
        if value["definition_fingerprint"].as_str() != digest.as_deref() {
            return Err(Error::Corrupt);
        }
    }
    Ok(value)
}
pub struct AssetFence {
    session: Session,
}
impl AssetFence {
    pub fn check(&self) -> Result<()> {
        self.session.check_active().map_err(|_| Error::Forbidden)
    }
}
pub struct AuthorizedAsset {
    payload: Value,
    fence: AssetFence,
}
impl AuthorizedAsset {
    pub fn into_parts(self) -> Result<(Value, AssetFence)> {
        self.fence.check()?;
        Ok((self.payload, self.fence))
    }
}
pub struct PrivateAssets<'a> {
    client: &'a mut Client,
}
impl<'a> PrivateAssets<'a> {
    pub fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub async fn current_registry(&mut self, session: &Session) -> Result<AuthorizedAsset> {
        session.check_active().map_err(|_| Error::Forbidden)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let mut entries = vec![];
        let mut bytes = 0usize;
        for (kind, sql) in [
            (
                "FACTOR",
                "SELECT a.factor_id AS asset_id,a.current_revision_fingerprint,a.schema_version AS asset_schema,r.revision_fingerprint,r.parent_revision_fingerprint,CASE WHEN pg_catalog.octet_length(r.payload::text)<=8388608 THEN r.source_text ELSE NULL END AS source_text,r.source_sha256,CASE WHEN pg_catalog.octet_length(r.payload::text)<=8388608 THEN r.payload::text ELSE NULL END AS payload,pg_catalog.octet_length(r.payload::text) AS payload_bytes,r.schema_version FROM private_factor_asset a LEFT JOIN private_factor_revision r ON r.factor_id=a.factor_id AND r.revision_fingerprint=a.current_revision_fingerprint WHERE a.current_revision_fingerprint IS NOT NULL ORDER BY a.factor_id LIMIT 10001",
            ),
            (
                "STRATEGY",
                "SELECT a.strategy_id AS asset_id,a.current_revision_fingerprint,a.schema_version AS asset_schema,r.revision_fingerprint,r.parent_revision_fingerprint,r.definition_fingerprint,CASE WHEN pg_catalog.octet_length(r.payload::text)<=8388608 THEN r.payload::text ELSE NULL END AS payload,pg_catalog.octet_length(r.payload::text) AS payload_bytes,r.schema_version FROM private_strategy_asset a LEFT JOIN private_strategy_revision r ON r.strategy_id=a.strategy_id AND r.revision_fingerprint=a.current_revision_fingerprint WHERE a.current_revision_fingerprint IS NOT NULL ORDER BY a.strategy_id LIMIT 10001",
            ),
        ] {
            let statement = tx.prepare(sql).await.map_err(|_| Error::Unavailable)?;
            let portal = tx
                .bind(&statement, &[])
                .await
                .map_err(|_| Error::Unavailable)?;
            let mut count = 0usize;
            loop {
                let mut page = tx
                    .query_portal(&portal, 1)
                    .await
                    .map_err(|_| Error::Unavailable)?;
                let Some(r) = page.pop() else { break };
                count += 1;
                let size: Option<i32> = r.try_get("payload_bytes").map_err(|_| Error::Corrupt)?;
                bytes = bytes
                    .checked_add(
                        usize::try_from(size.ok_or(Error::Corrupt)?).map_err(|_| Error::Corrupt)?,
                    )
                    .ok_or(Error::Unavailable)?;
                if count > 10000 || bytes > WORK {
                    return Err(Error::Unavailable);
                }
                let value = row(kind, &r)?;
                let current: String = r
                    .try_get("current_revision_fingerprint")
                    .map_err(|_| Error::Corrupt)?;
                let schema: i32 = r.try_get("asset_schema").map_err(|_| Error::Corrupt)?;
                if value["revision_fingerprint"] != current || schema != 1 {
                    return Err(Error::Corrupt);
                }
                let owner = if kind == "FACTOR" {
                    "factor_id"
                } else {
                    "strategy_id"
                };
                let content = if kind == "FACTOR" {
                    "source_sha256"
                } else {
                    "definition_fingerprint"
                };
                entries.push(json!({"locator":{"private_asset_kind":kind,"private_asset_id":value[owner],"revision_fingerprint":value["revision_fingerprint"],"content_fingerprint":value[content]},"semantic_version":value["semantic_version"],"description":value["description"],"category":if kind=="FACTOR"{value["category"].clone()}else{Value::Null},"tags":value["tags"]}));
            }
        }
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        session.check_active().map_err(|_| Error::Forbidden)?;
        let registry =
            fp(&json!({"contract":"ONLYALPHA_PRODUCT_ASSET_REGISTRY_V1","entries":entries}))?;
        Ok(AuthorizedAsset {
            payload: json!({"schema_version":1,"registry_fingerprint":registry,"entries":entries}),
            fence: AssetFence {
                session: session.clone(),
            },
        })
    }
    pub async fn factor_revision(
        &mut self,
        session: &Session,
        factor_id: &str,
        revision_fingerprint: &str,
        content_fingerprint: &str,
    ) -> Result<AuthorizedAsset> {
        session.check_active().map_err(|_| Error::Forbidden)?;
        id(factor_id, "FACTOR")?;
        sha(&json!(revision_fingerprint)).map_err(|_| Error::Invalid)?;
        sha(&json!(content_fingerprint)).map_err(|_| Error::Invalid)?;
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| Error::Unavailable)?;
        crate::persistence::postgres::bounds(&tx)
            .await
            .map_err(|_| Error::Unavailable)?;
        let found=tx.query_opt("SELECT factor_id AS asset_id,revision_fingerprint,parent_revision_fingerprint,CASE WHEN pg_catalog.octet_length(payload::text)<=8388608 THEN source_text ELSE NULL END AS source_text,source_sha256,CASE WHEN pg_catalog.octet_length(payload::text)<=8388608 THEN payload::text ELSE NULL END AS payload,pg_catalog.octet_length(payload::text) AS payload_bytes,schema_version FROM private_factor_revision WHERE factor_id=$1 AND revision_fingerprint=$2",&[&factor_id,&revision_fingerprint]).await.map_err(|_|Error::Unavailable)?.ok_or(Error::NotFound)?;
        let bytes: i32 = found.try_get("payload_bytes").map_err(|_| Error::Corrupt)?;
        if usize::try_from(bytes).map_err(|_| Error::Corrupt)? > WORK {
            return Err(Error::Unavailable);
        }
        let payload = row("FACTOR", &found)?;
        if payload["factor_id"] != factor_id
            || payload["revision_fingerprint"] != revision_fingerprint
            || payload["source_sha256"] != content_fingerprint
        {
            return Err(Error::Mismatch);
        }
        tx.commit().await.map_err(|_| Error::Unavailable)?;
        session.check_active().map_err(|_| Error::Forbidden)?;
        Ok(AuthorizedAsset {
            payload,
            fence: AssetFence {
                session: session.clone(),
            },
        })
    }
}
