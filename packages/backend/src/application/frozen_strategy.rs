//! Read-only immutable Strategy history. No publication or READY authority.
use crate::is_sha256_hex;
use crate::persistence::authority_session::AuthoritySession;
use crate::security::protected_files::{self, FilePolicy, ReadError};
use onlyalpha_strategy::{SourceError, SourceRevision, record_fingerprint};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    ffi::OsStr,
    fmt,
    os::fd::{BorrowedFd, OwnedFd},
};
const DOCUMENT_WORK: usize = 8 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Missing,
    Corrupt,
    Unavailable,
    Authority,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "STRATEGY_NOT_FOUND",
            Self::Corrupt => "STRATEGY_CORRUPT",
            Self::Unavailable => "STRATEGY_STORE_UNAVAILABLE",
            Self::Authority => "STRATEGY_AUTHORITY_UNAVAILABLE",
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<ReadError> for Error {
    fn from(e: ReadError) -> Self {
        match e {
            ReadError::Missing => Self::Missing,
            ReadError::Invalid => Self::Corrupt,
            ReadError::Unavailable => Self::Unavailable,
        }
    }
}
fn exact<'a>(v: &'a Value, keys: &[&str]) -> Result<&'a serde_json::Map<String, Value>, Error> {
    let m = v.as_object().ok_or(Error::Corrupt)?;
    if m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(Error::Corrupt);
    }
    Ok(m)
}
fn sha(v: &Value) -> Result<&str, Error> {
    v.as_str()
        .filter(|v| is_sha256_hex(v))
        .ok_or(Error::Corrupt)
}
/// Existing FreezeRelation1 identity; audit metadata is not semantic identity.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FreezeRelation {
    record: Value,
    fingerprint: String,
    strategy: String,
}
impl FreezeRelation {
    pub fn from_json(raw: &str, max_work: usize) -> Result<Self, Error> {
        if raw.len() > max_work {
            return Err(Error::Unavailable);
        }
        let v: Value = serde_json::from_str(raw).map_err(|_| Error::Corrupt)?;
        exact(
            &v,
            &[
                "schema_version",
                "strategy_fingerprint",
                "candidate_fingerprint",
                "research_result_fingerprint",
                "research_execution_evidence_fingerprints",
                "admission_evidence_fingerprint",
                "equivalence_evidence_fingerprints",
                "relation_fingerprint",
            ],
        )?;
        if v["schema_version"].as_u64() != Some(1) {
            return Err(Error::Corrupt);
        }
        for key in [
            "strategy_fingerprint",
            "candidate_fingerprint",
            "research_result_fingerprint",
            "admission_evidence_fingerprint",
            "relation_fingerprint",
        ] {
            sha(&v[key])?;
        }
        for key in [
            "research_execution_evidence_fingerprints",
            "equivalence_evidence_fingerprints",
        ] {
            let rows = v[key]
                .as_array()
                .filter(|a| !a.is_empty())
                .ok_or(Error::Corrupt)?;
            let mut previous = None;
            for row in rows {
                let s = sha(row)?;
                if previous.is_some_and(|p| p >= s) {
                    return Err(Error::Corrupt);
                }
                previous = Some(s);
            }
        }
        let mut semantic = v.clone();
        let m = semantic.as_object_mut().ok_or(Error::Corrupt)?;
        m.remove("relation_fingerprint");
        m.insert("domain".into(), json!("onlyalpha.strategy.freeze-relation"));
        let fingerprint = record_fingerprint(&semantic);
        if v["relation_fingerprint"] != fingerprint {
            return Err(Error::Corrupt);
        }
        Ok(Self {
            strategy: sha(&v["strategy_fingerprint"])?.to_owned(),
            record: v,
            fingerprint,
        })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn strategy_fingerprint(&self) -> &str {
        &self.strategy
    }
}
/// Complete observations of the two formal trees, never proof of Node READY.
/// Missing roots remain explicit so reconciliation can reject dangling projections.
pub struct Inventory {
    revisions: BTreeMap<String, SourceRevision>,
    relations: BTreeMap<String, FreezeRelation>,
    revision_tree_present: bool,
    relation_tree_present: bool,
}
impl Inventory {
    pub fn revisions(&self) -> &BTreeMap<String, SourceRevision> {
        &self.revisions
    }
    pub fn relations(&self) -> &BTreeMap<String, FreezeRelation> {
        &self.relations
    }
    pub fn revision_tree_present(&self) -> bool {
        self.revision_tree_present
    }
    pub fn relation_tree_present(&self) -> bool {
        self.relation_tree_present
    }
}
pub struct FrozenStore {
    research: OwnedFd,
}
impl FrozenStore {
    /// Duplicate the selected capability, never reopen the original absolute path.
    pub fn open(research: BorrowedFd<'_>) -> Result<Self, Error> {
        Ok(Self {
            research: protected_files::duplicate_directory(research)?,
        })
    }
    /// Host must close mutation admission and retain this exclusive same-session
    /// borrow throughout startup/upgrade. No concurrent publisher can be admitted.
    pub async fn inventory(
        &self,
        session: &mut AuthoritySession,
        max_work: usize,
    ) -> Result<Inventory, Error> {
        session.verify().await.map_err(|_| Error::Authority)?;
        let result = self.read_all(max_work);
        session.verify().await.map_err(|_| Error::Authority)?;
        result
    }
    /// Exact read only, not a complete/quiescent inventory or execution admission.
    pub fn load_verified(
        &self,
        fingerprint: &str,
        max_work: usize,
    ) -> Result<SourceRevision, Error> {
        if !is_sha256_hex(fingerprint) {
            return Err(Error::Corrupt);
        }
        self.read_all(max_work)?
            .revisions
            .remove(fingerprint)
            .ok_or(Error::Missing)
    }
    pub(crate) fn namespace(
        &self,
    ) -> Result<crate::bootstrap::deployment::SemanticStoreId, crate::bootstrap::deployment::Error>
    {
        crate::bootstrap::deployment::load_semantic_store_id_at(&self.research)
    }
    fn tree(&self, name: &str) -> Result<Option<OwnedFd>, Error> {
        let mut fd = self.research.try_clone().map_err(ReadError::from)?;
        for part in ["strategy", name, "sha256"] {
            fd = match protected_files::open_directory_at(&fd, OsStr::new(part)) {
                Ok(fd) => fd,
                Err(ReadError::Missing) => return Ok(None),
                Err(e) => return Err(e.into()),
            };
        }
        Ok(Some(fd))
    }
    fn read_all(&self, max_work: usize) -> Result<Inventory, Error> {
        let mut work = Work(max_work);
        let revision_root = self.tree("frozen-revisions")?;
        let relation_root = self.tree("freeze-relations")?;
        let mut result = Inventory {
            revisions: BTreeMap::new(),
            relations: BTreeMap::new(),
            revision_tree_present: revision_root.is_some(),
            relation_tree_present: relation_root.is_some(),
        };
        if let Some(root) = relation_root {
            for (id, raw) in documents(&root, &mut work)? {
                let relation = FreezeRelation::from_json(&raw, DOCUMENT_WORK)?;
                if relation.fingerprint() != id {
                    return Err(Error::Corrupt);
                }
                result.relations.insert(id, relation);
            }
        }
        if let Some(root) = revision_root {
            for (id, raw) in documents(&root, &mut work)? {
                let v: Value = serde_json::from_str(&raw).map_err(|_| Error::Corrupt)?;
                exact(&v, &["schema_version", "strategy_fingerprint", "revision"])?;
                if v["schema_version"].as_u64() != Some(1) || v["strategy_fingerprint"] != id {
                    return Err(Error::Corrupt);
                }
                let source = SourceRevision::from_json(&v["revision"].to_string(), DOCUMENT_WORK)
                    .map_err(|e| match e {
                    SourceError::Invalid => Error::Corrupt,
                    SourceError::Unavailable => Error::Unavailable,
                })?;
                if source.fingerprint() != id {
                    return Err(Error::Corrupt);
                }
                result.revisions.insert(id, source);
            }
        }
        let mut matched = std::collections::BTreeSet::new();
        for relation in result.relations.values() {
            matched.insert(relation.strategy_fingerprint());
        }
        if result
            .revisions
            .keys()
            .any(|id| !matched.contains(id.as_str()))
        {
            return Err(Error::Corrupt);
        }
        Ok(result)
    }
}
struct Work(usize);
impl Work {
    fn take(&mut self, n: usize) -> Result<(), Error> {
        self.0 = self.0.checked_sub(n).ok_or(Error::Unavailable)?;
        Ok(())
    }
}
fn documents(root: &OwnedFd, work: &mut Work) -> Result<Vec<(String, String)>, Error> {
    let mut docs = Vec::new();
    for prefix in protected_files::directory_entries(root, &mut work.0)? {
        let p = prefix
            .to_str()
            .filter(|s| {
                s.len() == 2
                    && s.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
            .ok_or(Error::Corrupt)?;
        let dir = protected_files::open_directory_at(root, &prefix).map_err(published_error)?;
        for leaf in protected_files::directory_entries(&dir, &mut work.0)? {
            let id = leaf
                .to_str()
                .filter(|s| is_sha256_hex(s) && s.starts_with(p))
                .ok_or(Error::Corrupt)?;
            let target =
                protected_files::open_directory_at(&dir, &leaf).map_err(published_error)?;
            if protected_files::directory_entries(&target, &mut work.0)?
                != [OsStr::new("manifest.json")]
            {
                return Err(Error::Corrupt);
            }
            // Charge the entire per-document parse/expansion allowance, not only bytes.
            // This bounds cumulative work even for small decimal exponent spellings.
            work.take(DOCUMENT_WORK)?;
            let data = protected_files::read_file_at(
                &target,
                OsStr::new("manifest.json"),
                FilePolicy::HistoryDocument,
                DOCUMENT_WORK,
            )
            .map_err(published_error)?;
            let raw = std::str::from_utf8(&data).map_err(|_| Error::Corrupt)?;
            let v: Value = serde_json::from_str(raw).map_err(|_| Error::Corrupt)?;
            let canonical = serde_json::to_vec(&v).map_err(|_| Error::Corrupt)?;
            if canonical.as_slice() != raw.as_bytes() {
                return Err(Error::Corrupt);
            }
            docs.push((id.to_owned(), raw.to_owned()));
        }
    }
    Ok(docs)
}

fn published_error(e: ReadError) -> Error {
    if e == ReadError::Missing {
        Error::Corrupt
    } else {
        e.into()
    }
}
