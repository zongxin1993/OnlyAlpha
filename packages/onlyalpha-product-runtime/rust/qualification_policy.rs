//! Immutable Policy1 history and explicit operator startup admission (ADR 0118).
//! Reading a policy grants no evaluation support, Promotion, Runtime or LIVE right.
use crate::{
    authority_session::AuthoritySession,
    deployment::{self, SemanticStoreId},
    protected_files::{self, FilePolicy, ReadError},
};
use onlyalpha_domain::numeric::OnlyDecimal;
use onlyalpha_strategy::record_fingerprint;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    ffi::OsStr,
    fmt,
    io::Write,
    os::fd::{BorrowedFd, OwnedFd},
};
const DOCUMENT_WORK: usize = 8 * 1024 * 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    Missing,
    Conflict,
    Unavailable,
    Authority,
    Namespace(deployment::Error),
    PublicationUnknown,
}
impl Error {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "QUALIFICATION_POLICY_NOT_FOUND",
            Self::Conflict => "QUALIFICATION_POLICY_IDENTITY_CONFLICT",
            Self::Unavailable => "QUALIFICATION_POLICY_STORE_UNAVAILABLE",
            Self::Authority => "PRODUCT_KERNEL_AUTHORITY_LOST",
            Self::Namespace(e) => e.code(),
            Self::PublicationUnknown => "QUALIFICATION_POLICY_PUBLICATION_UNKNOWN",
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
            ReadError::Invalid => Self::Conflict,
            ReadError::Unavailable => Self::Unavailable,
        }
    }
}
type Result<T> = std::result::Result<T, Error>;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Policy {
    record: Value,
}
impl Policy {
    pub fn from_json(raw: &str, max_work: usize) -> Result<Self> {
        if raw.len() > max_work.min(DOCUMENT_WORK) {
            return Err(Error::Unavailable);
        }
        let v: Value = serde_json::from_str(raw).map_err(|_| Error::Conflict)?;
        // Private record construction guarantees that every Policy is readable
        // by this store before any put-once filesystem side effect.
        if serde_json::to_vec(&v).map_err(|_| Error::Conflict)?.len() > DOCUMENT_WORK {
            return Err(Error::Unavailable);
        }
        exact(
            &v,
            &[
                "schema_version",
                "policy_id",
                "policy_version",
                "gate",
                "criteria",
                "missing_evidence_behavior",
                "aggregation",
                "policy_fingerprint",
            ],
        )?;
        // Resource bound matching the current pinned parser, never an identity rewrite.
        if text(&v["policy_version"])?.chars().count() > 4300 {
            return Err(Error::Unavailable);
        }
        if v["schema_version"].as_u64() != Some(1)
            || !identifier(text(&v["policy_id"])?)
            || !version(text(&v["policy_version"])?)
            || !matches!(
                text(&v["gate"])?,
                "RESEARCH_TO_BACKTEST" | "BACKTEST_TO_SIM"
            )
        {
            return Err(Error::Conflict);
        }
        for k in ["aggregation", "missing_evidence_behavior"] {
            nonblank(&v[k])?;
        }
        let criteria = v["criteria"]
            .as_array()
            .filter(|a| !a.is_empty())
            .ok_or(Error::Conflict)?;
        let mut previous: Option<&str> = None;
        for row in criteria {
            exact(
                row,
                &[
                    "criterion_id",
                    "evidence_kind",
                    "metric",
                    "comparison",
                    "threshold",
                ],
            )?;
            let id = nonblank(&row["criterion_id"])?;
            if previous.is_some_and(|p| p >= id)
                || !matches!(
                    text(&row["evidence_kind"])?,
                    "RESEARCH_RESULT" | "BACKTEST_EVIDENCE"
                )
                || !decimal(text(&row["threshold"])?)
            {
                return Err(Error::Conflict);
            }
            nonblank(&row["metric"])?;
            nonblank(&row["comparison"])?;
            previous = Some(id);
        }
        let mut semantic = v.clone();
        let map = semantic.as_object_mut().ok_or(Error::Conflict)?;
        map.remove("policy_fingerprint");
        map.insert(
            "domain".into(),
            json!("onlyalpha.strategy.qualification-policy"),
        );
        if v["policy_fingerprint"] != record_fingerprint(&semantic) {
            return Err(Error::Conflict);
        }
        Ok(Self { record: v })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    fn id(&self) -> &str {
        self.record["policy_id"]
            .as_str()
            .expect("validated Policy id")
    }
    fn version(&self) -> &str {
        self.record["policy_version"]
            .as_str()
            .expect("validated Policy version")
    }
    fn key(&self) -> (String, String) {
        (self.id().into(), self.version().into())
    }
}
fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let m = v.as_object().ok_or(Error::Conflict)?;
    if m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(Error::Conflict);
    }
    Ok(())
}
fn text(v: &Value) -> Result<&str> {
    v.as_str().ok_or(Error::Conflict)
}
fn nonblank(v: &Value) -> Result<&str> {
    let s = text(v)?;
    if !s
        .chars()
        .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
    {
        return Err(Error::Conflict);
    }
    Ok(s)
}
fn identifier(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && (s.as_bytes()[0].is_ascii_lowercase() || s.as_bytes()[0].is_ascii_digit())
        && s.bytes().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'_' | b'-')
        })
}
fn version(s: &str) -> bool {
    // Preserve the original Nd spelling/path, including non-ASCII leading zero.
    // OnlyDecimal reuses the canonical pinned Unicode decimal-digit table.
    !s.is_empty()
        && !s.starts_with('0')
        && s.chars().all(char::is_numeric)
        && s.parse::<OnlyDecimal>()
            .is_ok_and(|n| !n.is_zero() && !n.is_negative())
}
fn decimal(s: &str) -> bool {
    let (negative, unsigned) = s.strip_prefix('-').map_or((false, s), |v| (true, v));
    let (integer, fraction) = unsigned
        .split_once('.')
        .map_or((unsigned, None), |(i, f)| (i, Some(f)));
    if integer.is_empty()
        || !integer.bytes().all(|b| b.is_ascii_digit())
        || (integer.len() > 1 && integer.starts_with('0'))
    {
        return false;
    }
    match fraction {
        Some(f) => !f.is_empty() && f.bytes().all(|b| b.is_ascii_digit()) && !f.ends_with('0'),
        None => !(negative && integer == "0"),
    }
}
pub struct Store {
    research: OwnedFd,
}
impl Store {
    pub fn open(research: BorrowedFd<'_>) -> Result<Self> {
        Ok(Self {
            research: protected_files::duplicate_directory(research)?,
        })
    }
    /// Host closes mutation admission throughout boot. Each put is immutable; the
    /// batch is deliberately not an atomic filesystem transaction. Any later error
    /// preserves earlier published policies and revokes the original session.
    pub async fn admit(
        &self,
        session: &mut AuthoritySession,
        namespace: &SemanticStoreId,
        policies: &[Policy],
        max_work: usize,
    ) -> Result<Vec<Policy>> {
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            self.admit_owned(&mut owned, namespace, policies, max_work),
        )
        .await
        .map_err(|_| Error::Unavailable)
        .and_then(|v| v);
        if result.is_ok() {
            session.restore_ownership(owned);
        }
        result
    }
    async fn admit_owned(
        &self,
        owned: &mut AuthoritySession,
        namespace: &SemanticStoreId,
        policies: &[Policy],
        max_work: usize,
    ) -> Result<Vec<Policy>> {
        owned.verify().await.map_err(|_| Error::Authority)?;
        let selected =
            deployment::load_semantic_store_id_at(&self.research).map_err(Error::Namespace)?;
        if &selected != namespace {
            return Err(Error::Namespace(deployment::Error::Mismatch));
        }
        deployment::verify_binding(
            owned.client_mut().await.map_err(|_| Error::Authority)?,
            namespace,
        )
        .await
        .map_err(Error::Namespace)?;
        let mut work = Work(max_work);
        let mut expected = self.read_all(&mut work)?;
        let mut pending = BTreeMap::new();
        for policy in policies {
            // Charge even duplicate inputs; callers cannot create an unbounded loop of
            // free repeated records. Reserve their whole parse/retained-record allowance.
            work.take(DOCUMENT_WORK)?;
            let key = policy.key();
            if expected.get(&key).is_some_and(|old| old != policy)
                || pending.get(&key).is_some_and(|old| *old != policy)
            {
                return Err(Error::Conflict);
            }
            if !expected.contains_key(&key) {
                pending.insert(key, policy);
            }
        }
        for (key, policy) in &pending {
            work.take(
                DOCUMENT_WORK
                    .checked_add(key.0.len() + key.1.len() + 16)
                    .ok_or(Error::Unavailable)?,
            )?;
            expected.insert(key.clone(), (*policy).clone());
        }
        // The same fixed per-directory cap also holds after publication, before any
        // side effect. Sorted (id,version) keys make these counts deterministic.
        let mut counts: BTreeMap<&str, usize> = BTreeMap::new();
        for (id, _) in expected.keys() {
            let count = counts.entry(id).or_default();
            *count += 1;
            if *count > 4096 {
                return Err(Error::Unavailable);
            }
        }
        if counts.len() > 4096 {
            return Err(Error::Unavailable);
        }
        for policy in pending.values() {
            self.publish(policy)?;
        }
        let actual = self.read_all(&mut Work(max_work))?;
        if actual != expected {
            return Err(Error::Conflict);
        }
        owned.verify().await.map_err(|_| Error::Authority)?;
        Ok(actual.into_values().collect())
    }
    fn root(&self) -> Result<Option<OwnedFd>> {
        let mut fd = self.research.try_clone().map_err(|_| Error::Unavailable)?;
        for part in ["strategy", "qualification-policies"] {
            fd = match protected_files::open_directory_at(&fd, OsStr::new(part)) {
                Ok(fd) => fd,
                Err(ReadError::Missing) => return Ok(None),
                Err(e) => return Err(e.into()),
            };
        }
        Ok(Some(fd))
    }
    fn read_all(&self, work: &mut Work) -> Result<BTreeMap<(String, String), Policy>> {
        let mut result = BTreeMap::new();
        let Some(root) = self.root()? else {
            return Ok(result);
        };
        for id in protected_files::directory_entries(&root, &mut work.0)? {
            let name = id
                .to_str()
                .filter(|s| identifier(s))
                .ok_or(Error::Conflict)?;
            let identity =
                protected_files::open_directory_at(&root, &id).map_err(published_error)?;
            for v in protected_files::directory_entries(&identity, &mut work.0)? {
                let name_version = v.to_str().filter(|s| version(s)).ok_or(Error::Conflict)?;
                let target =
                    protected_files::open_directory_at(&identity, &v).map_err(published_error)?;
                if protected_files::directory_entries(&target, &mut work.0)?
                    != [OsStr::new("manifest.json")]
                {
                    return Err(Error::Conflict);
                }
                work.take(DOCUMENT_WORK)?;
                let data = protected_files::read_file_at(
                    &target,
                    OsStr::new("manifest.json"),
                    FilePolicy::HistoryDocument,
                    DOCUMENT_WORK,
                )
                .map_err(published_error)?;
                let raw = std::str::from_utf8(&data).map_err(|_| Error::Conflict)?;
                let policy = Policy::from_json(raw, DOCUMENT_WORK)?;
                if policy.id() != name
                    || policy.version() != name_version
                    || serde_json::to_vec(&policy.record)
                        .map_err(|_| Error::Conflict)?
                        .as_slice()
                        != data.as_slice()
                {
                    return Err(Error::Conflict);
                }
                result.insert(policy.key(), policy);
            }
        }
        Ok(result)
    }
    fn publish(&self, policy: &Policy) -> Result<()> {
        // Sync every new directory itself and its parent's entry before proceeding.
        let strategy = directory(&self.research, "strategy")?;
        let root = directory(&strategy, "qualification-policies")?;
        let identity = directory(&root, policy.id())?;
        let mut random = [0u8; 16];
        getrandom::fill(&mut random).map_err(|_| Error::Unavailable)?;
        let mut name = String::from(".stage-");
        for b in random {
            use std::fmt::Write;
            write!(name, "{b:02x}").map_err(|_| Error::Unavailable)?;
        }
        rustix::fs::mkdirat(
            &identity,
            name.as_str(),
            rustix::fs::Mode::from_raw_mode(0o700),
        )
        .map_err(|_| Error::Unavailable)?;
        let stage = protected_files::open_directory_at(&identity, OsStr::new(&name))?;
        let fd = rustix::fs::openat(
            &stage,
            "manifest.json",
            rustix::fs::OFlags::WRONLY
                | rustix::fs::OFlags::CREATE
                | rustix::fs::OFlags::EXCL
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::CLOEXEC
                | rustix::fs::OFlags::NONBLOCK,
            rustix::fs::Mode::from_raw_mode(0o600),
        )
        .map_err(|_| Error::Unavailable)?;
        let mut file = std::fs::File::from(fd);
        let bytes = serde_json::to_vec(&policy.record).map_err(|_| Error::Conflict)?;
        file.write_all(&bytes).map_err(|_| Error::Unavailable)?;
        file.sync_all().map_err(|_| Error::Unavailable)?;
        rustix::fs::fsync(&stage).map_err(|_| Error::Unavailable)?;
        rustix::fs::renameat_with(
            &identity,
            name.as_str(),
            &identity,
            policy.version(),
            rustix::fs::RenameFlags::NOREPLACE,
        )
        .map_err(|e| {
            if e == rustix::io::Errno::EXIST {
                Error::Conflict
            } else {
                Error::Unavailable
            }
        })?;
        // Publication may already be durable. Failure must never claim rollback or
        // delete/overwrite the published target; next process observes exact facts.
        rustix::fs::fsync(&identity).map_err(|_| Error::PublicationUnknown)?;
        Ok(())
    }
}
fn directory(parent: &OwnedFd, name: &str) -> Result<OwnedFd> {
    let created = match rustix::fs::mkdirat(parent, name, rustix::fs::Mode::from_raw_mode(0o700)) {
        Ok(()) => true,
        Err(e) if e == rustix::io::Errno::EXIST => false,
        Err(_) => return Err(Error::Unavailable),
    };
    let fd = protected_files::open_directory_at(parent, OsStr::new(name))?;
    if created {
        rustix::fs::fsync(&fd).map_err(|_| Error::Unavailable)?;
        rustix::fs::fsync(parent).map_err(|_| Error::Unavailable)?;
    }
    Ok(fd)
}
struct Work(usize);
impl Work {
    fn take(&mut self, n: usize) -> Result<()> {
        self.0 = self.0.checked_sub(n).ok_or(Error::Unavailable)?;
        Ok(())
    }
}
fn published_error(e: ReadError) -> Error {
    if e == ReadError::Missing {
        Error::Conflict
    } else {
        e.into()
    }
}
