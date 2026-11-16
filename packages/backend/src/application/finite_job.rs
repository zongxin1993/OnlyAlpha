//! 有限作业的真实执行、回收和未发布结果；不连接正式 worker 或终态事务。
use super::{
    factor_content::hash,
    job_contract::{FrozenJobBinding, JobKind, MemberKind, ResultMember, ResultPlan},
};
use crate::persistence::job_publication::{PublicationError, content_fingerprint};
use serde_json::{Value, json};
use std::collections::BTreeMap;
type Result<T> = std::result::Result<T, PublicationError>;
fn invalid<T>(_: T) -> PublicationError {
    PublicationError::Mismatch
}
/// Versioned content format, not evidence that any member has been produced.
pub fn member_schema(kind: MemberKind) -> Result<String> {
    hash(&json!({"contract":"FINITE_JOB_MEMBER","schema_version":1,"role":kind,"sequence_fields":["axis","rows"],"root_fields":["body"],"numeric":"OWNING_TYPED_VALUES"})).map_err(invalid)
}
/// All execution facts retain actual sequence/family and complete owning body.
/// Partitions are contiguous balanced slices in sorted logical-key order.
pub fn fact_axis_rule() -> Result<String> {
    hash(&json!({"contract":"FINITE_EXECUTION_AXIS","schema_version":1,"axis":["sequence","family","body_fingerprint"],"partition":"CONTIGUOUS_BALANCED_SORTED_KEYS"})).map_err(invalid)
}
/// Pure planning over already selected axes. It creates no Run or permission.
pub fn plan_members(
    kind: JobKind,
    full_axis: &Value,
    sample_axis: &Value,
    statistics: usize,
) -> Result<ResultPlan> {
    let roles: &[MemberKind] = match kind {
        JobKind::Research => &[
            MemberKind::CalculationValues,
            MemberKind::SignalValues,
            MemberKind::Statistics,
            MemberKind::ResearchReport,
            MemberKind::CausalEvidence,
        ],
        JobKind::Backtest => &[
            MemberKind::ExecutionFacts,
            MemberKind::EconomicResult,
            MemberKind::CloseCurve,
            MemberKind::CausalEvidence,
        ],
    };
    let mut members = Vec::new();
    for role in roles {
        let (axis, rows) = match role {
            MemberKind::CalculationValues | MemberKind::SignalValues => (
                Some(hash(full_axis).map_err(invalid)?),
                Some(
                    full_axis
                        .as_array()
                        .ok_or(PublicationError::Integrity)?
                        .len(),
                ),
            ),
            MemberKind::CloseCurve => (
                Some(hash(sample_axis).map_err(invalid)?),
                Some(
                    sample_axis
                        .as_array()
                        .ok_or(PublicationError::Integrity)?
                        .len(),
                ),
            ),
            MemberKind::Statistics => (None, Some(statistics)),
            MemberKind::ExecutionFacts => (None, None),
            _ => (None, Some(1)),
        };
        let mut member = json!({"key":serde_json::to_value(role).map_err(invalid)?.as_str().ok_or(PublicationError::Integrity)?.to_lowercase(),"kind":role,"schema":member_schema(*role)?,"axis":axis,"rows":rows});
        if *role == MemberKind::ExecutionFacts {
            member["axis_rule"] = json!(fact_axis_rule()?);
        }
        members.push(member);
    }
    ResultPlan::from_record(&json!({"kind":kind,"members":members})).map_err(invalid)
}
struct Products {
    sequences: BTreeMap<MemberKind, Vec<(Value, Value)>>,
    roots: BTreeMap<MemberKind, Value>,
    causal: Value,
}
fn contents(binding: &FrozenJobBinding, products: Products) -> Result<Vec<(ResultMember, Value)>> {
    let plan = binding.result_plan();
    let mut output = Vec::new();
    for (kind, values) in products.sequences {
        if kind == MemberKind::ExecutionFacts {
            for (index, (axis, body)) in values.iter().enumerate() {
                if body["sequence"].as_u64() != Some(index as u64 + 1)
                    || !matches!(
                        body["family"].as_str(),
                        Some("OPEN" | "BAR" | "EXECUTION" | "END")
                    )
                    || *axis
                        != json!([
                            body["sequence"],
                            body["family"],
                            hash(&body["body"]).map_err(invalid)?
                        ])
                {
                    return Err(PublicationError::Mismatch);
                }
            }
        }
        let members = plan
            .members()
            .iter()
            .filter(|m| m.kind() == kind)
            .collect::<Vec<_>>();
        if members.is_empty() {
            return Err(PublicationError::MissingEvidence);
        }
        let mut offset: usize = 0;
        for (index, member) in members.iter().enumerate() {
            let mut actual = serde_json::to_value(member).map_err(invalid)?;
            if actual["schema"] != member_schema(kind)? {
                return Err(PublicationError::Mismatch);
            }
            let size = if kind == MemberKind::ExecutionFacts {
                if actual["axis_rule"] != fact_axis_rule()? {
                    return Err(PublicationError::Mismatch);
                }
                values.len() / members.len() + usize::from(index < values.len() % members.len())
            } else {
                usize::try_from(member.rows().ok_or(PublicationError::MissingEvidence)?)
                    .map_err(invalid)?
            };
            let end = offset
                .checked_add(size)
                .ok_or(PublicationError::BudgetExceeded)?;
            let slice = values.get(offset..end).ok_or(PublicationError::Mismatch)?;
            let axis = slice
                .iter()
                .map(|(axis, _)| axis.clone())
                .collect::<Vec<_>>();
            let rows = slice.iter().map(|(_, row)| row.clone()).collect::<Vec<_>>();
            let fingerprint = hash(&json!(axis)).map_err(invalid)?;
            if kind == MemberKind::ExecutionFacts {
                actual["axis"] = json!(fingerprint);
                actual["rows"] = json!(size);
            } else if !actual["axis"].is_null() && actual["axis"] != fingerprint {
                return Err(PublicationError::Mismatch);
            }
            let descriptor: ResultMember = serde_json::from_value(actual).map_err(invalid)?;
            output.push((
                descriptor,
                json!({"schema_version":1,"kind":kind,"axis":axis,"rows":rows}),
            ));
            offset = end;
        }
        if offset != values.len() {
            return Err(PublicationError::Mismatch);
        }
    }
    for (kind, mut body) in products.roots {
        if kind == MemberKind::ResearchReport {
            body["members"] = json!(
                output
                    .iter()
                    .map(|(m, value)| Ok(
                        json!({"key":m.key(),"content":content_fingerprint(value)?})
                    ))
                    .collect::<Result<Vec<_>>>()?
            );
        }
        for member in plan.members().iter().filter(|m| m.kind() == kind) {
            if serde_json::to_value(member).map_err(invalid)?["schema"] != member_schema(kind)? {
                return Err(PublicationError::Mismatch);
            }
            output.push((
                member.clone(),
                json!({"schema_version":1,"kind":kind,"body":body}),
            ));
        }
    }
    output.sort_by(|a, b| a.0.key().cmp(b.0.key()));
    let references = output
        .iter()
        .map(|(m, body)| Ok(json!({"key":m.key(),"content":content_fingerprint(body)?})))
        .collect::<Result<Vec<_>>>()?;
    for member in plan
        .members()
        .iter()
        .filter(|m| m.kind() == MemberKind::CausalEvidence)
    {
        if serde_json::to_value(member).map_err(invalid)?["schema"]
            != member_schema(MemberKind::CausalEvidence)?
        {
            return Err(PublicationError::Mismatch);
        }
        output.push((member.clone(),json!({"schema_version":1,"kind":MemberKind::CausalEvidence,"body":{"binding":binding.record(),"execution":products.causal,"members":references}})));
    }
    output.sort_by(|a, b| a.0.key().cmp(b.0.key()));
    plan.check_inventory(&output.iter().map(|(m, _)| m.clone()).collect::<Vec<_>>())
        .map_err(invalid)?;
    let bytes = output.iter().try_fold(0usize, |n, (_, b)| {
        n.checked_add(b.to_string().len())
            .ok_or(PublicationError::BudgetExceeded)
    })?;
    if bytes > 128 * 1024 * 1024 {
        return Err(PublicationError::BudgetExceeded);
    }
    Ok(output)
}
mod owners;
#[cfg(test)]
#[path = "../tests/finite_job_tests.rs"]
mod tests;
pub use owners::{
    FiniteTask, PreparedBacktestJob, backtest_execution_values, prepare_backtest,
    research_execution_values, start_research,
};
pub use owners::{JoinedCut, JoinedFiniteJob};
