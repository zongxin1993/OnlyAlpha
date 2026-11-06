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
                ("research.calculation_result_count",evidence.calculation_result_count()),
                ("research.statistics_result_count",evidence.statistics_result_count()),
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
            &BTreeMap::from([("strategy.execution_validation_passed",1)]),
        )
    }
    // Both real typed owners use one exact scalar evaluator. This private value
    // helper cannot publish a Decision or manufacture an owning evidence handle.
    fn evaluate_scalars(
        &self,
        gate: &str,
        subject: &str,
        reference: Value,
        metrics: &BTreeMap<&str, u64>,
    ) -> std::result::Result<EvaluatedDecision, &'static str> {
        const UNSUPPORTED: &str = "QUALIFICATION_POLICY_UNSUPPORTED";
        const GATE: &str = "QUALIFICATION_EVIDENCE_GATE_MISMATCH";
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
            let observed = metrics
                .get(criterion["metric"].as_str().ok_or(UNSUPPORTED)?)
                .ok_or(UNSUPPORTED)?
                .to_string();
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
