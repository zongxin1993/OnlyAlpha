//! Immutable Policy1 history and explicit operator startup admission (ADR 0118).
//! Reading a policy grants no evaluation support, Promotion, Runtime or LIVE right.
use crate::bootstrap::deployment::{self, SemanticStoreId};
use crate::persistence::authority_session::AuthoritySession;
use crate::security::protected_files::{self, FilePolicy, ReadError};
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
                "RESEARCH_TO_BACKTEST" | "MANUAL_STRATEGY_TO_BACKTEST" | "BACKTEST_TO_SIM"
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
                    "RESEARCH_RESULT" | "STRATEGY_VALIDATION" | "BACKTEST_EVIDENCE"
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
/// 将权威纯十进制串规范化为与 Policy `threshold` 一致的无尾零、无 `-0`、无科学计数法格式。
pub(crate) fn canonical_plain_decimal(raw: &str) -> std::result::Result<String, &'static str> {
    const INVALID: &str = "QUALIFICATION_EVIDENCE_CORRUPT";
    let (negative, unsigned) = raw.strip_prefix('-').map_or((false, raw), |v| (true, v));
    let (integer, fraction) = unsigned
        .split_once('.')
        .map_or((unsigned, None), |(i, f)| (i, Some(f)));
    if integer.is_empty()
        || !integer.bytes().all(|b| b.is_ascii_digit())
        || (integer.len() > 1 && integer.starts_with('0'))
    {
        return Err(INVALID);
    }
    let trimmed = match fraction {
        Some(f) if !f.is_empty() && f.bytes().all(|b| b.is_ascii_digit()) => {
            f.trim_end_matches('0')
        }
        Some(_) => return Err(INVALID),
        None => "",
    };
    let canonical = if integer == "0" && trimmed.is_empty() {
        "0".to_string()
    } else if trimmed.is_empty() {
        if negative {
            format!("-{integer}")
        } else {
            integer.to_string()
        }
    } else if negative {
        format!("-{integer}.{trimmed}")
    } else {
        format!("{integer}.{trimmed}")
    };
    if !decimal(&canonical) || canonical.parse::<OnlyDecimal>().is_err() {
        return Err(INVALID);
    }
    Ok(canonical)
}
/// 经 PG 原子发布与经济/因果全量验签的回测权威标量；由证据所有者提取，评估器不重算指标。
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct BacktestQualificationMetrics {
    pub(crate) close_curve_point_count: u64,
    pub(crate) valuation_count: u64,
    pub(crate) order_count: u64,
    pub(crate) fill_count: u64,
    pub(crate) roundtrip_count: u64,
    pub(crate) return_since_start: Option<String>,
    pub(crate) maximum_drawdown: Option<String>,
    pub(crate) net_pnl: String,
    pub(crate) realized_pnl: String,
    pub(crate) unrealized_pnl: String,
    pub(crate) fees: String,
    pub(crate) final_equity: String,
}
enum ScalarValue {
    Present(String),
    Missing,
}
pub struct Store {
    research: OwnedFd,
}
impl Store {
    pub(crate) fn namespace(&self) -> std::result::Result<SemanticStoreId, &'static str> {
        deployment::load_semantic_store_id_at(&self.research).map_err(|e| e.code())
    }

    pub fn load_exact(&self, id: &str, revision: &str, max_work: usize) -> Result<Policy> {
        if !identifier(id) || !version(revision) {
            return Err(Error::Conflict);
        }
        self.read_all(&mut Work(max_work))?
            .remove(&(id.into(), revision.into()))
            .ok_or(Error::Missing)
    }
    pub fn policies(&self, max_work: usize) -> Result<Vec<Policy>> {
        Ok(self.read_all(&mut Work(max_work))?.into_values().collect())
    }
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

/// Pure Policy1 evaluation over an owning-read evidence handle. Producing this
/// value alone grants no durable Decision, Promotion, Runtime or LIVE authority.
#[derive(Debug)]
pub struct EvaluatedDecision {
    record: Value,
}
impl EvaluatedDecision {
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> &str {
        self.record["decision_fingerprint"]
            .as_str()
            .expect("evaluator constructed Decision fingerprint")
    }
}
impl Policy {
    /// Evaluate only manifest-owned Research counts; unsupported declarations
    /// remain readable and fail closed at this execution boundary.
    pub fn evaluate_research_counts(
        &self,
        evidence: &crate::persistence::research_evidence::VerifiedResearchCounts,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        self.evaluate_scalars(
            "RESEARCH_TO_BACKTEST",
            evidence.subject_strategy_fingerprint(),
            json!({"kind":"RESEARCH_RESULT","evidence_fingerprint":evidence.research_result_fingerprint(),
                "locator_fingerprint":evidence.research_result_plan_fingerprint(),
                "subject_binding_fingerprint":evidence.freeze_relation_fingerprint()}),
            &BTreeMap::from([
                (
                    "research.calculation_result_count",
                    ScalarValue::Present(evidence.calculation_result_count().to_string()),
                ),
                (
                    "research.statistics_result_count",
                    ScalarValue::Present(evidence.statistics_result_count().to_string()),
                ),
            ]),
        )
    }
    /// A completed owning validation plus its exact Freeze is technical evidence,
    /// not a scientific Result or a profitability claim. No DTO supplies the 1.
    pub(crate) fn evaluate_manual_validation(
        &self,
        evidence: &crate::application::frozen_strategy::VerifiedManualBacktestEvidence,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        evidence.verify_cut()?;
        self.evaluate_scalars(
            "MANUAL_STRATEGY_TO_BACKTEST",
            evidence.subject_strategy_fingerprint(),
            json!({"kind":"STRATEGY_VALIDATION","evidence_fingerprint":evidence.validation_fingerprint(),
                "preparation_command_id":evidence.preparation_command_id(),
                "subject_binding_fingerprint":evidence.freeze_relation_fingerprint()}),
            &BTreeMap::from([(
                "strategy.execution_validation_passed",
                ScalarValue::Present("1".into()),
            )]),
        )
    }
    /// 仅消费经 PG 原子发布与经济/因果全量验签后的回测权威标量；
    /// 已退役的文件式计数（artifact_count / implementation_count）与未知指标继续 fail-closed。
    pub(crate) fn evaluate_backtest_evidence(
        &self,
        evidence: &crate::persistence::qualification_decision::VerifiedBacktestEvidence,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        evidence.verify_cut()?;
        self.evaluate_backtest_scalars(
            evidence.subject_strategy_fingerprint(),
            evidence.evidence_fingerprint(),
            evidence.run_id(),
            evidence.freeze_relation_fingerprint(),
            evidence.metrics(),
        )
    }
    fn evaluate_backtest_scalars(
        &self,
        subject: &str,
        evidence_fingerprint: &str,
        run_id: &str,
        freeze_relation_fingerprint: &str,
        metrics: &BacktestQualificationMetrics,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        let optional = |value: &Option<String>| match value {
            Some(v) => ScalarValue::Present(v.clone()),
            None => ScalarValue::Missing,
        };
        let scalars = BTreeMap::from([
            ("backtest.execution_completed", ScalarValue::Present("1".into())),
            (
                "backtest.close_curve_point_count",
                ScalarValue::Present(metrics.close_curve_point_count.to_string()),
            ),
            (
                "backtest.valuation_count",
                ScalarValue::Present(metrics.valuation_count.to_string()),
            ),
            (
                "backtest.order_count",
                ScalarValue::Present(metrics.order_count.to_string()),
            ),
            (
                "backtest.fill_count",
                ScalarValue::Present(metrics.fill_count.to_string()),
            ),
            (
                "backtest.roundtrip_count",
                ScalarValue::Present(metrics.roundtrip_count.to_string()),
            ),
            (
                "backtest.return_since_start",
                optional(&metrics.return_since_start),
            ),
            (
                "backtest.maximum_drawdown",
                optional(&metrics.maximum_drawdown),
            ),
            (
                "backtest.net_pnl",
                ScalarValue::Present(metrics.net_pnl.clone()),
            ),
            (
                "backtest.realized_pnl",
                ScalarValue::Present(metrics.realized_pnl.clone()),
            ),
            (
                "backtest.unrealized_pnl",
                ScalarValue::Present(metrics.unrealized_pnl.clone()),
            ),
            ("backtest.fees", ScalarValue::Present(metrics.fees.clone())),
            (
                "backtest.final_equity",
                ScalarValue::Present(metrics.final_equity.clone()),
            ),
        ]);
        self.evaluate_scalars(
            "BACKTEST_TO_SIM",
            subject,
            json!({"kind":"BACKTEST_EVIDENCE","evidence_fingerprint":evidence_fingerprint,
                "backtest_run_id":run_id,"subject_binding_fingerprint":freeze_relation_fingerprint}),
            &scalars,
        )
    }
    // All real typed owners use one exact scalar evaluator. This private value
    // helper cannot publish a Decision or manufacture an owning evidence handle.
    fn evaluate_scalars(
        &self,
        gate: &str,
        subject: &str,
        reference: Value,
        metrics: &BTreeMap<&str, ScalarValue>,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        const UNSUPPORTED: &str = "QUALIFICATION_POLICY_UNSUPPORTED";
        const GATE: &str = "QUALIFICATION_EVIDENCE_GATE_MISMATCH";
        const MISSING: &str = "QUALIFICATION_EVIDENCE_MISSING";
        if self.record["gate"] != gate {
            return Err(GATE);
        }
        if self.record["missing_evidence_behavior"] != "FAIL" || self.record["aggregation"] != "ALL"
        {
            return Err(UNSUPPORTED);
        }
        let mut results = Vec::new();
        let mut approved = true;
        for criterion in self.record["criteria"]
            .as_array()
            .expect("validated Policy criteria")
        {
            if criterion["evidence_kind"] != reference["kind"] {
                return Err(GATE);
            }
            let raw = match metrics
                .get(criterion["metric"].as_str().ok_or(UNSUPPORTED)?)
                .ok_or(UNSUPPORTED)?
            {
                ScalarValue::Present(raw) => raw,
                ScalarValue::Missing => return Err(MISSING),
            };
            let observed = canonical_plain_decimal(raw)?;
            let value = observed.parse::<OnlyDecimal>().map_err(|_| UNSUPPORTED)?;
            let threshold = criterion["threshold"]
                .as_str()
                .expect("validated Policy threshold")
                .parse::<OnlyDecimal>()
                .map_err(|_| UNSUPPORTED)?;
            let passed = match criterion["comparison"].as_str() {
                Some("GT") => value > threshold,
                Some("GE") => value >= threshold,
                Some("EQ") => value == threshold,
                Some("LE") => value <= threshold,
                Some("LT") => value < threshold,
                _ => return Err(UNSUPPORTED),
            };
            approved &= passed;
            results.push(json!({"criterion_id":criterion["criterion_id"],"source_evidence_fingerprint":reference["evidence_fingerprint"],
                "metric":criterion["metric"],"observed_value":observed,"comparison":criterion["comparison"],"threshold":criterion["threshold"],
                "outcome":if passed{"PASS"}else{"FAIL"}}));
        }
        let mut record = json!({"schema_version":1,"subject_strategy_fingerprint":subject,"gate":self.record["gate"],
            "policy_id":self.record["policy_id"],"policy_version":self.record["policy_version"],"policy_fingerprint":self.record["policy_fingerprint"],
            "evidence":[reference],"criterion_results":results,"outcome":if approved{"APPROVED"}else{"REJECTED"}});
        let mut identity = record.clone();
        identity["domain"] = json!("onlyalpha.strategy.qualification-decision");
        record["decision_fingerprint"] = json!(record_fingerprint(&identity));
        Ok(EvaluatedDecision { record })
    }
}

#[cfg(test)]
mod research_counts_tests {
    use super::*;
    use crate::persistence::research_evidence::VerifiedResearchCounts;

    fn policy_record() -> Value {
        json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1",
        "gate":"RESEARCH_TO_BACKTEST","missing_evidence_behavior":"FAIL","aggregation":"ALL",
        "criteria":[
            {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
            {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}
        ]})
    }
    fn signed_policy(mut record: Value) -> Value {
        record.as_object_mut().unwrap().remove("policy_fingerprint");
        let mut identity = record.clone();
        identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
        record["policy_fingerprint"] = json!(record_fingerprint(&identity));
        record
    }
    fn policy(record: Value) -> Policy {
        Policy::from_json(&signed_policy(record).to_string(), DOCUMENT_WORK).unwrap()
    }
    fn counts(statistics: u64, calculations: u64) -> VerifiedResearchCounts {
        // Value-only input. This cfg(test) constructor grants no persisted Evidence,
        // evaluator publication, command receipt, Promotion or Runtime authority.
        VerifiedResearchCounts::for_value_test(
            "a".repeat(64),
            "b".repeat(64),
            "c".repeat(64),
            "d".repeat(64),
            statistics,
            calculations,
        )
    }
    fn expected_error(record: Value, code: &str) {
        match policy(record).evaluate_research_counts(&counts(7, 3)) {
            Ok(_) => panic!("unsupported policy must fail closed: {code}"),
            Err(error) => assert_eq!(error.to_string(), code),
        }
    }
    #[test]
    fn existing_decision1_wire_and_identity_bind_only_exact_scientific_inputs() {
        let p = policy(policy_record());
        let first = p.evaluate_research_counts(&counts(7, 3)).unwrap();
        let record = first.to_record();
        let expected = json!({"schema_version":1,"subject_strategy_fingerprint":"a".repeat(64),
            "gate":"RESEARCH_TO_BACKTEST","policy_id":"experimental-backtest","policy_version":"1",
            "policy_fingerprint":"847daa4ac92199b563b0aebd4f519c37570aa03489644944278918d14f611849",
            "evidence":[{"kind":"RESEARCH_RESULT","evidence_fingerprint":"b".repeat(64),"locator_fingerprint":"c".repeat(64),"subject_binding_fingerprint":"d".repeat(64)}],
            "criterion_results":[
                {"criterion_id":"calculation-count","source_evidence_fingerprint":"b".repeat(64),"metric":"research.calculation_result_count","observed_value":"3","comparison":"GE","threshold":"1","outcome":"PASS"},
                {"criterion_id":"statistics-count","source_evidence_fingerprint":"b".repeat(64),"metric":"research.statistics_result_count","observed_value":"7","comparison":"GE","threshold":"2","outcome":"PASS"}
            ],"outcome":"APPROVED","decision_fingerprint":"2e9690d17ff6336cf95ee035be5042bedd91ca742217e71604c2f3db059f2a57"});
        assert_eq!(record, expected);
        assert_eq!(
            first.fingerprint(),
            "2e9690d17ff6336cf95ee035be5042bedd91ca742217e71604c2f3db059f2a57"
        );
        assert_eq!(
            p.evaluate_research_counts(&counts(7, 3))
                .unwrap()
                .to_record(),
            record
        );
        for forbidden in ["actor", "recorded_at", "created_at", "host", "comment"] {
            assert!(record.get(forbidden).is_none());
        }
    }
    #[test]
    fn all_five_comparisons_are_exact_at_equality_and_decimal_neighbors() {
        for (comparison, equal, below, above) in [
            ("GT", false, true, false),
            ("GE", true, true, false),
            ("EQ", true, false, false),
            ("LE", true, false, true),
            ("LT", false, false, true),
        ] {
            for (threshold, approved) in [
                ("3", equal),
                ("2.9999999999999999999999999999999999999", below),
                ("3.0000000000000000000000000000000000001", above),
            ] {
                let mut p = policy_record();
                p["criteria"].as_array_mut().unwrap().truncate(1);
                p["criteria"][0]["comparison"] = json!(comparison);
                p["criteria"][0]["threshold"] = json!(threshold);
                let result = policy(p)
                    .evaluate_research_counts(&counts(7, 3))
                    .unwrap()
                    .to_record();
                assert_eq!(
                    result["outcome"],
                    if approved { "APPROVED" } else { "REJECTED" },
                    "{comparison} {threshold}"
                );
                assert_eq!(result["criterion_results"][0]["observed_value"], "3");
                assert_eq!(result["criterion_results"][0]["threshold"], threshold);
            }
        }
    }
    #[test]
    fn count_values_are_exact_above_f64_integer_precision_and_at_u64_boundary() {
        for count in [9_007_199_254_740_993_u64, u64::MAX] {
            let mut p = policy_record();
            p["criteria"].as_array_mut().unwrap().truncate(1);
            p["criteria"][0]["comparison"] = json!("EQ");
            p["criteria"][0]["threshold"] = json!(count.to_string());
            let p = policy(p);
            let result = p
                .evaluate_research_counts(&counts(0, count))
                .unwrap()
                .to_record();
            assert_eq!(result["outcome"], "APPROVED");
            assert_eq!(
                result["criterion_results"][0]["observed_value"],
                count.to_string()
            );
            assert_eq!(
                p.evaluate_research_counts(&counts(0, count - 1))
                    .unwrap()
                    .to_record()["outcome"],
                "REJECTED"
            );
        }
    }
    #[test]
    fn all_aggregation_retains_failed_results_and_exact_zero_counts() {
        let result = policy(policy_record())
            .evaluate_research_counts(&counts(0, 3))
            .unwrap()
            .to_record();
        assert_eq!(result["outcome"], "REJECTED");
        assert_eq!(result["criterion_results"].as_array().unwrap().len(), 2);
        assert_eq!(result["criterion_results"][0]["outcome"], "PASS");
        assert_eq!(result["criterion_results"][1]["outcome"], "FAIL");
        assert_eq!(result["criterion_results"][1]["observed_value"], "0");
        let original = policy(policy_record())
            .evaluate_research_counts(&counts(7, 3))
            .unwrap();
        assert_ne!(
            original.fingerprint(),
            policy(policy_record())
                .evaluate_research_counts(&counts(8, 3))
                .unwrap()
                .fingerprint()
        );
    }
    #[test]
    fn history_reader_preserves_unsupported_declarations_but_evaluation_fails_closed() {
        for (field, value, code) in [
            ("aggregation", "ANY", "QUALIFICATION_POLICY_UNSUPPORTED"),
            (
                "missing_evidence_behavior",
                "IGNORE",
                "QUALIFICATION_POLICY_UNSUPPORTED",
            ),
            (
                "gate",
                "BACKTEST_TO_SIM",
                "QUALIFICATION_EVIDENCE_GATE_MISMATCH",
            ),
        ] {
            let mut p = policy_record();
            p[field] = json!(value);
            expected_error(p, code);
        }
        for (field, value, code) in [
            (
                "metric",
                "research.unknown",
                "QUALIFICATION_POLICY_UNSUPPORTED",
            ),
            (
                "metric",
                "research.net_return",
                "QUALIFICATION_POLICY_UNSUPPORTED",
            ),
            ("comparison", "APPROX", "QUALIFICATION_POLICY_UNSUPPORTED"),
            ("comparison", "NE", "QUALIFICATION_POLICY_UNSUPPORTED"),
            (
                "evidence_kind",
                "BACKTEST_EVIDENCE",
                "QUALIFICATION_EVIDENCE_GATE_MISMATCH",
            ),
        ] {
            let mut p = policy_record();
            p["criteria"][1][field] = json!(value);
            // A failed earlier count must not hide unknown semantics later in ALL.
            p["criteria"][0]["threshold"] = json!("999");
            expected_error(p, code);
        }
    }
    #[test]
    fn strict_policy1_identity_canonical_counts_and_declared_criteria_are_preserved() {
        let original = signed_policy(policy_record());
        assert_eq!(
            Policy::from_json(&original.to_string(), DOCUMENT_WORK)
                .unwrap()
                .to_record(),
            original
        );
        for attack in 0..6 {
            let mut p = original.clone();
            match attack {
                0 => p["extra"] = json!(true),
                1 => p["criteria"].as_array_mut().unwrap().reverse(),
                2 => p["criteria"][1]["criterion_id"] = p["criteria"][0]["criterion_id"].clone(),
                3 => p["criteria"][0]["threshold"] = json!("1.0"),
                4 => p["criteria"][0]["threshold"] = json!("1e0"),
                _ => p["policy_fingerprint"] = json!("0".repeat(64)),
            }
            if attack != 5 {
                p = signed_policy(p);
            }
            assert!(
                Policy::from_json(&p.to_string(), DOCUMENT_WORK).is_err(),
                "attack {attack}"
            );
        }
    }
}

#[cfg(test)]
mod manual_policy_declaration_tests {
    use super::*;
    #[test]
    fn exact_manual_policy_declares_execution_validation_without_research_statistics() {
        let mut body = json!({"schema_version":1,"policy_id":"manual-backtest","policy_version":"1",
            "gate":"MANUAL_STRATEGY_TO_BACKTEST","missing_evidence_behavior":"FAIL","aggregation":"ALL",
            "criteria":[{"criterion_id":"execution-validation","evidence_kind":"STRATEGY_VALIDATION",
                "metric":"strategy.execution_validation_passed","comparison":"EQ","threshold":"1"}]});
        let mut identity = body.clone();
        identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
        body["policy_fingerprint"] = json!(record_fingerprint(&identity));
        assert_eq!(
            Policy::from_json(&body.to_string(), DOCUMENT_WORK)
                .unwrap()
                .to_record(),
            body
        );
        let mut wrong = body;
        wrong["gate"] = json!("MANUAL_STRATEGY_TO_LIVE");
        let mut identity = wrong.clone();
        identity
            .as_object_mut()
            .unwrap()
            .remove("policy_fingerprint");
        identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
        wrong["policy_fingerprint"] = json!(record_fingerprint(&identity));
        assert!(Policy::from_json(&wrong.to_string(), DOCUMENT_WORK).is_err());
    }
}

#[cfg(test)]
mod backtest_policy_declaration_tests {
    use super::*;

    fn signed_policy(mut body: Value) -> Policy {
        body.as_object_mut().unwrap().remove("policy_fingerprint");
        let mut identity = body.clone();
        identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
        body["policy_fingerprint"] = json!(record_fingerprint(&identity));
        Policy::from_json(&body.to_string(), DOCUMENT_WORK).unwrap()
    }

    fn backtest_policy(criteria: Value) -> Policy {
        signed_policy(json!({
            "schema_version": 1,
            "policy_id": "sim-backtest",
            "policy_version": "1",
            "gate": "BACKTEST_TO_SIM",
            "missing_evidence_behavior": "FAIL",
            "aggregation": "ALL",
            "criteria": criteria
        }))
    }

    fn sample_metrics() -> BacktestQualificationMetrics {
        BacktestQualificationMetrics {
            close_curve_point_count: 120,
            valuation_count: 124,
            order_count: 6,
            fill_count: 4,
            roundtrip_count: 2,
            return_since_start: Some("0.10000000".into()),
            maximum_drawdown: Some("-0.08333333".into()),
            net_pnl: "1000.50000000".into(),
            realized_pnl: "1000.50000000".into(),
            unrealized_pnl: "-0.00000000".into(),
            fees: "12.34000000".into(),
            final_equity: "11000.50000000".into(),
        }
    }

    #[test]
    fn canonical_plain_decimal_normalizes_zeros_trailing_zeros_and_small_values_without_exponent() {
        for (raw, expected) in [
            ("0.10000000", "0.1"),
            ("-0.08333333", "-0.08333333"),
            ("0.00000000", "0"),
            ("-0.00000000", "0"),
            ("-0", "0"),
            ("0.00000001", "0.00000001"),
            ("-0.00000001", "-0.00000001"),
            ("10000.00", "10000"),
            ("-12.3400", "-12.34"),
            ("18446744073709551615", "18446744073709551615"),
        ] {
            assert_eq!(canonical_plain_decimal(raw).unwrap(), expected, "{raw}");
        }
        for bad in ["", " 1", "1 ", "+1", "01", "-01", "1.", ".1", "1e0", "1E-8", "1_000", "NaN"] {
            assert!(canonical_plain_decimal(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn backtest_policy_rejects_counts_the_current_publication_does_not_own() {
        let metrics = sample_metrics();
        for metric in [
            "backtest.artifact_count",
            "backtest.implementation_count",
            "backtest.unknown_metric",
        ] {
            let policy = backtest_policy(json!([
                {"criterion_id":"count","evidence_kind":"BACKTEST_EVIDENCE","metric":metric,"comparison":"GE","threshold":"1"}
            ]));
            let error = policy
                .evaluate_backtest_scalars(
                    &"a".repeat(64),
                    &"b".repeat(64),
                    "11111111-1111-4111-8111-111111111111",
                    &"c".repeat(64),
                    &metrics,
                )
                .err()
                .expect("unowned backtest metric must fail closed at evaluation");
            assert_eq!(error, "QUALIFICATION_POLICY_UNSUPPORTED", "{metric}");
        }
    }

    #[test]
    fn backtest_policy_evaluates_all_thirteen_owned_metrics_with_canonical_observed_values() {
        let policy = backtest_policy(json!([
            {"criterion_id":"01-execution","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.execution_completed","comparison":"EQ","threshold":"1"},
            {"criterion_id":"02-curve","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.close_curve_point_count","comparison":"GE","threshold":"100"},
            {"criterion_id":"03-valuation","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.valuation_count","comparison":"GE","threshold":"120"},
            {"criterion_id":"04-orders","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.order_count","comparison":"GE","threshold":"1"},
            {"criterion_id":"05-fills","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.fill_count","comparison":"GE","threshold":"4"},
            {"criterion_id":"06-roundtrips","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.roundtrip_count","comparison":"GE","threshold":"2"},
            {"criterion_id":"07-return","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.return_since_start","comparison":"GE","threshold":"0.05"},
            {"criterion_id":"08-drawdown","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.maximum_drawdown","comparison":"GE","threshold":"-0.2"},
            {"criterion_id":"09-net-pnl","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.net_pnl","comparison":"GT","threshold":"1000.499999999"},
            {"criterion_id":"10-realized","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.realized_pnl","comparison":"EQ","threshold":"1000.5"},
            {"criterion_id":"11-unrealized","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.unrealized_pnl","comparison":"EQ","threshold":"0"},
            {"criterion_id":"12-fees","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.fees","comparison":"LE","threshold":"12.34"},
            {"criterion_id":"13-final-equity","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.final_equity","comparison":"GE","threshold":"11000.5"}
        ]));
        let first = policy
            .evaluate_backtest_scalars(
                &"a".repeat(64),
                &"b".repeat(64),
                "11111111-1111-4111-8111-111111111111",
                &"c".repeat(64),
                &sample_metrics(),
            )
            .unwrap();
        let record = first.to_record();
        assert_eq!(record["outcome"], "APPROVED");
        let observed: Vec<&str> = record["criterion_results"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["observed_value"].as_str().unwrap())
            .collect();
        assert_eq!(
            observed,
            vec![
                "1",
                "120",
                "124",
                "6",
                "4",
                "2",
                "0.1",
                "-0.08333333",
                "1000.5",
                "1000.5",
                "0",
                "12.34",
                "11000.5"
            ]
        );
        // 尾零不同的等价权威小数产出完全相同的 decision_fingerprint
        let mut trimmed_metrics = sample_metrics();
        trimmed_metrics.return_since_start = Some("0.1".into());
        trimmed_metrics.unrealized_pnl = "0".into();
        trimmed_metrics.net_pnl = "1000.5".into();
        let second = policy
            .evaluate_backtest_scalars(
                &"a".repeat(64),
                &"b".repeat(64),
                "11111111-1111-4111-8111-111111111111",
                &"c".repeat(64),
                &trimmed_metrics,
            )
            .unwrap();
        assert_eq!(first.fingerprint(), second.fingerprint());
    }

    #[test]
    fn backtest_policy_rejects_drawdown_breach_and_fails_closed_on_null_economic_scalars() {
        let drawdown_policy = backtest_policy(json!([
            {"criterion_id":"01-fills","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.fill_count","comparison":"GE","threshold":"999"},
            {"criterion_id":"02-drawdown","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.maximum_drawdown","comparison":"GE","threshold":"-0.05"}
        ]));
        let rejected = drawdown_policy
            .evaluate_backtest_scalars(
                &"a".repeat(64),
                &"b".repeat(64),
                "11111111-1111-4111-8111-111111111111",
                &"c".repeat(64),
                &sample_metrics(),
            )
            .unwrap()
            .to_record();
        assert_eq!(rejected["outcome"], "REJECTED");
        assert_eq!(rejected["criterion_results"][1]["outcome"], "FAIL");

        // 即使前一条规则已经 FAIL，后续引用 null 经济指标仍必须 fail-closed（绝不掩盖为 REJECTED）
        let mut missing_drawdown = sample_metrics();
        missing_drawdown.maximum_drawdown = None;
        assert_eq!(
            drawdown_policy
                .evaluate_backtest_scalars(
                    &"a".repeat(64),
                    &"b".repeat(64),
                    "11111111-1111-4111-8111-111111111111",
                    &"c".repeat(64),
                    &missing_drawdown,
                )
                .unwrap_err(),
            "QUALIFICATION_EVIDENCE_MISSING"
        );

        let return_policy = backtest_policy(json!([
            {"criterion_id":"01-return","evidence_kind":"BACKTEST_EVIDENCE","metric":"backtest.return_since_start","comparison":"GE","threshold":"0"}
        ]));
        let mut missing_return = sample_metrics();
        missing_return.return_since_start = None;
        assert_eq!(
            return_policy
                .evaluate_backtest_scalars(
                    &"a".repeat(64),
                    &"b".repeat(64),
                    "11111111-1111-4111-8111-111111111111",
                    &"c".repeat(64),
                    &missing_return,
                )
                .unwrap_err(),
            "QUALIFICATION_EVIDENCE_MISSING"
        );

        // 未引用 null 指标的完整性政策（如 experimental-sim/1）不受 null 经济指标阻塞
        let completeness_policy =
            crate::bootstrap::research_namespace::experimental_sim_policy().unwrap();
        let approved = completeness_policy
            .evaluate_backtest_scalars(
                &"a".repeat(64),
                &"b".repeat(64),
                "11111111-1111-4111-8111-111111111111",
                &"c".repeat(64),
                &missing_return,
            )
            .unwrap()
            .to_record();
        assert_eq!(approved["outcome"], "APPROVED");
        assert_eq!(approved["policy_id"], "experimental-sim");
    }
}
