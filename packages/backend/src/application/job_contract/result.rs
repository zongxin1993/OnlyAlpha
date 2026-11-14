use super::*;
use crate::persistence::backtest_run::RunState;
use std::collections::BTreeSet;

/// Logical member roles, not storage filenames. EconomicResult includes the
/// complete owning Account/Ledger/order/trade/position views, not just PnL.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MemberKind {
    ExecutionFacts,
    EconomicResult,
    CloseCurve,
    CausalEvidence,
    CalculationValues,
    SignalValues,
    Statistics,
    ResearchReport,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResultMember {
    key: String,
    kind: MemberKind,
    schema: String,
    axis: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    axis_rule: Option<String>,
    rows: Option<u64>,
}
impl ResultMember {
    pub fn key(&self) -> &str {
        &self.key
    }
    pub fn kind(&self) -> MemberKind {
        self.kind
    }
    pub fn rows(&self) -> Option<u64> {
        self.rows
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PlanRecord {
    pub(super) kind: JobKind,
    members: Vec<ResultMember>,
}
impl PlanRecord {
    pub(super) fn validate(&mut self) -> Result<()> {
        if self.members.is_empty() || self.members.len() > MAX_MEMBERS {
            return Err(ContractError::Invalid);
        }
        let mut keys = BTreeSet::new();
        let mut kinds = BTreeSet::new();
        for member in &self.members {
            text(&member.key)?;
            pin(&member.schema)?;
            if !keys.insert(&member.key) {
                return Err(ContractError::Invalid);
            }
            if let Some(axis) = &member.axis {
                pin(axis)?;
            }
            if let Some(rule) = &member.axis_rule {
                pin(rule)?;
                if member.kind != MemberKind::ExecutionFacts {
                    return Err(ContractError::Invalid);
                }
            }
            if matches!(
                member.kind,
                MemberKind::ExecutionFacts
                    | MemberKind::CloseCurve
                    | MemberKind::CalculationValues
                    | MemberKind::SignalValues
            ) && member.axis.is_none()
                && !(member.kind == MemberKind::ExecutionFacts && member.axis_rule.is_some())
            {
                return Err(ContractError::Invalid);
            }
            if matches!(
                member.kind,
                MemberKind::EconomicResult
                    | MemberKind::ResearchReport
                    | MemberKind::CausalEvidence
            ) && (member.rows != Some(1) || member.axis.is_some())
            {
                return Err(ContractError::Invalid);
            }
            if member.rows.is_none() && member.kind != MemberKind::ExecutionFacts {
                return Err(ContractError::Invalid);
            }
            let valid = match self.kind {
                JobKind::Backtest => matches!(
                    member.kind,
                    MemberKind::ExecutionFacts
                        | MemberKind::EconomicResult
                        | MemberKind::CloseCurve
                        | MemberKind::CausalEvidence
                ),
                JobKind::Research => matches!(
                    member.kind,
                    MemberKind::CalculationValues
                        | MemberKind::SignalValues
                        | MemberKind::Statistics
                        | MemberKind::ResearchReport
                        | MemberKind::CausalEvidence
                ),
            };
            if !valid {
                return Err(ContractError::Mismatch);
            }
            kinds.insert(member.kind);
        }
        let required: &[MemberKind] = match self.kind {
            JobKind::Backtest => &[
                MemberKind::ExecutionFacts,
                MemberKind::EconomicResult,
                MemberKind::CloseCurve,
                MemberKind::CausalEvidence,
            ],
            JobKind::Research => &[
                MemberKind::CalculationValues,
                MemberKind::SignalValues,
                MemberKind::Statistics,
                MemberKind::ResearchReport,
                MemberKind::CausalEvidence,
            ],
        };
        if required.iter().any(|k| !kinds.contains(k)) {
            return Err(ContractError::MissingEvidence);
        }
        self.members.sort_by(|a, b| a.key.cmp(&b.key));
        Ok(())
    }
}
/// Declares complete retained output, never an observation that it was produced.
#[derive(Clone, Debug)]
pub struct ResultPlan(pub(super) PlanRecord);
impl ResultPlan {
    pub fn from_record(value: &Value) -> Result<Self> {
        let mut record: PlanRecord = decode(value)?;
        record.validate()?;
        Ok(Self(record))
    }
    pub fn record(&self) -> Value {
        serde_json::to_value(&self.0).expect("serializable plan")
    }
    pub fn fingerprint(&self) -> Result<String> {
        fingerprint(&self.0)
    }
    pub fn members(&self) -> &[ResultMember] {
        &self.0.members
    }
    /// Checks a claimed manifest only. Actual payload, axes, provenance, owner
    /// completion, joins and transaction association must also be proven later.
    pub fn check_inventory(&self, observed: &[ResultMember]) -> Result<()> {
        if observed.len() != self.0.members.len() {
            return Err(ContractError::MissingEvidence);
        }
        let mut sorted = observed.to_vec();
        sorted.sort_by(|a, b| a.key.cmp(&b.key));
        for (expected, actual) in self.0.members.iter().zip(&sorted) {
            if actual.rows.is_none() {
                return Err(ContractError::MissingEvidence);
            }
            match (&expected.axis, &expected.axis_rule, &actual.axis) {
                (None, Some(_), Some(axis)) => pin(axis)?,
                (None, Some(_), None) => return Err(ContractError::MissingEvidence),
                _ if expected.axis != actual.axis => return Err(ContractError::Mismatch),
                _ => {}
            }
            if expected.key != actual.key
                || expected.kind != actual.kind
                || expected.schema != actual.schema
                || expected.axis_rule != actual.axis_rule
                || expected.rows.is_some_and(|rows| Some(rows) != actual.rows)
            {
                return Err(ContractError::Mismatch);
            }
        }
        Ok(())
    }
}
pub fn result_publication_required(state: RunState) -> bool {
    state == RunState::Completed
}
/// A consistency predicate over existing lifecycle states, NOT permission to
/// complete, cancel, publish or promote a Run. Existing owners retain those powers.
pub fn validate_terminal_result(state: RunState, has_published_result: bool) -> Result<()> {
    match (result_publication_required(state), has_published_result) {
        (true, false) => Err(ContractError::MissingEvidence),
        (false, true) => Err(ContractError::UnexpectedResult),
        _ => Ok(()),
    }
}
