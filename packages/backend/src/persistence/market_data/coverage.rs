//! Coverage is derived from exact canonical occurrences, never inferred from ACKs.
use super::*;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyAdjustmentType,
    market::{OnlyBar, OnlyBarSemantic},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::{
    OnlyConstructionIdentity, only_construction_expected_ends,
};
use std::collections::{BTreeMap, BTreeSet};
pub fn deduplicate_facts(facts: &[Value]) -> Result<Vec<Value>> {
    let mut selected: BTreeMap<String, (String, Value)> = BTreeMap::new();
    for fact in facts {
        let id = text(&fact["canonical_fact_id"])?;
        let p = &fact["canonical_payload"];
        if !p.is_object() || fingerprint(p)? != text(&fact["canonical_payload_hash"])? {
            return Err(Error::Unprovable);
        }
        let mut market = p.clone();
        let o = market.as_object_mut().ok_or(Error::Unprovable)?;
        o.remove("runtime_id");
        o.remove("ts_init");
        let fp = fingerprint(&market)?;
        if let Some((old, chosen)) = selected.get_mut(id) {
            if old != &fp {
                return Err(Error::Conflict);
            }
            if text(&fact["raw_event_id"])? < text(&chosen["raw_event_id"])? {
                *chosen = fact.clone();
            }
        } else {
            selected.insert(id.into(), (fp, fact.clone()));
        }
    }
    let mut result: Vec<_> = selected.into_values().map(|(_, f)| f).collect();
    result.sort_by_key(|v| {
        (
            v["ts_event_ns"].as_i64(),
            v["canonical_fact_id"]
                .as_str()
                .unwrap_or_default()
                .to_owned(),
        )
    });
    Ok(result)
}
pub fn coverage(
    scope: &Scope,
    segments: &[Segment],
    facts: &[Value],
    limit: usize,
) -> Result<Manifest> {
    if limit == 0 || facts.len() > limit || segments.len() > limit {
        return Err(Error::Unavailable);
    }
    let mut ids = BTreeSet::new();
    let mut references = vec![];
    for segment in segments {
        if !ids.insert(segment.id()) || !scope.family_matches(&segment.recovery_scope()?) {
            return Err(Error::Unprovable);
        }
        references.push(json!([segment.id(), segment.content_hash()]));
    }
    references.sort_by_key(|v| v[0].as_str().unwrap_or_default().to_owned());
    if facts
        .iter()
        .any(|f| !ids.contains(f["segment_id"].as_str().unwrap_or_default()))
    {
        return Err(Error::Unprovable);
    }
    let facts = deduplicate_facts(facts)?
        .into_iter()
        .filter_map(|f| match scope.contains(&f) {
            Ok(true) => Some(Ok(f)),
            Ok(false) => None,
            Err(e) => Some(Err(e)),
        })
        .collect::<Result<Vec<_>>>()?;
    let mut proof = vec![format!("canonical_fact_count={}", facts.len())];
    let mut issues: Vec<String> = vec![];
    let mut gaps = vec![];
    let status = if scope.kind() == "BAR" {
        if scope.record["bar_construction"].is_null() {
            return Manifest::build(
                scope.clone(),
                references.into(),
                CoverageStatus::Unprovable,
                json!(proof),
                json!(["BAR_CONSTRUCTION_UNPROVABLE"]),
                json!([]),
            );
        }
        let construction = OnlyConstructionIdentity::from_record(&scope.record["bar_construction"])
            .map_err(|_| Error::Unprovable)?;
        if !construction.plan().recipe().is_native() {
            return Err(Error::Unprovable);
        }
        let semantic = construction.plan().target();
        let stride: i64 = semantic
            .stride_minutes()
            .map_err(|_| Error::Unprovable)?
            .to_string()
            .parse()
            .map_err(|_| Error::Unavailable)?;
        let stride = stride
            .checked_mul(60_000_000_000)
            .ok_or(Error::Unavailable)?;
        let window: i64 = semantic
            .window_minutes()
            .map_err(|_| Error::Unprovable)?
            .to_string()
            .parse()
            .map_err(|_| Error::Unavailable)?;
        let window = window
            .checked_mul(60_000_000_000)
            .ok_or(Error::Unavailable)?;
        let origin: i64 = construction
            .plan()
            .grid_origin()
            .to_string()
            .parse()
            .map_err(|_| Error::Unavailable)?;
        let aligned =
            (i128::from(scope.start_ns()) - i128::from(origin)).rem_euclid(i128::from(stride)) == 0
                && (i128::from(scope.end_ns()) - i128::from(origin)).rem_euclid(i128::from(stride))
                    == 0;
        let expected = only_construction_expected_ends(
            semantic,
            scope.start_ns().into(),
            scope.end_ns().into(),
            construction.plan().grid_origin().clone(),
            limit,
        )
        .map_err(|_| Error::Unavailable)?
        .iter()
        .map(|v| v.to_string().parse::<i64>().map_err(|_| Error::Unavailable))
        .collect::<Result<Vec<_>>>()?;
        let actual = facts
            .iter()
            .map(|f| integer(&f["ts_event_ns"]))
            .collect::<Result<Vec<_>>>()?;
        let mut valid = true;
        for fact in &facts {
            let bar = OnlyBar::from_record(&fact["canonical_payload"]["payload"]["value"])
                .map_err(|_| Error::Unprovable)?;
            let end = OnlyTimestamp::from_datetime(*bar.bar_end())
                .unix_nanos()
                .to_string()
                .parse::<i64>()
                .map_err(|_| Error::Unavailable)?;
            let start = OnlyTimestamp::from_datetime(*bar.bar_start())
                .unix_nanos()
                .to_string()
                .parse::<i64>()
                .map_err(|_| Error::Unavailable)?;
            valid &= *bar.is_closed()
                && bar.ts_event() == bar.bar_end()
                && end.checked_sub(start) == Some(window)
                && bar.bar_type().semantic() == semantic
                && bar.adjustment_type() == &OnlyAdjustmentType::Raw
                && bar.instrument_id().to_string() == text(&scope.record["instrument_id"])?
                && end == integer(&fact["ts_event_ns"])?
                && (i128::from(end) - i128::from(origin)).rem_euclid(i128::from(stride)) == 0
                && fact["canonical_payload"]["data_version"] == scope.record["data_version"]
                && fingerprint(&bar.bar_type().to_record())? == text(&scope.record["bar_type"])?
                && fact["quality_state"] == "VALID";
        }
        proof = vec![
            format!("canonical_fact_count={}", facts.len()),
            format!("bar_grid_count={}", expected.len()),
            format!("closed_external_bar={valid}"),
        ];
        if !aligned || actual != expected {
            issues.push("BAR_GRID_INCOMPLETE".into());
        }
        if !valid {
            issues.push("BAR_SEMANTICS_INVALID".into());
        }
        let actual: BTreeSet<_> = actual.into_iter().collect();
        for end in expected {
            if !actual.contains(&end) {
                gaps.push(json!({"start_ns":end-stride,"end_ns":end}));
            }
        }
        if issues.is_empty() {
            CoverageStatus::Complete
        } else {
            CoverageStatus::Incomplete
        }
    } else if scope.kind() == "TRADE" {
        let proven = !facts.is_empty()
            && facts.iter().all(|f| {
                f["canonical_payload"]["sequence_semantics"] == "CONTIGUOUS"
                    && f["canonical_payload"]["source_sequence"].is_i64()
            });
        let mut seq = facts
            .iter()
            .filter_map(|f| f["canonical_payload"]["source_sequence"].as_i64())
            .collect::<Vec<_>>();
        seq.sort();
        let expected = match (
            scope.record["first_sequence"].as_i64(),
            scope.record["last_sequence"].as_i64(),
        ) {
            (Some(first), Some(last)) => {
                if i128::from(last) - i128::from(first) + 1 > limit as i128 {
                    return Err(Error::Unavailable);
                }
                (first..=last).collect::<Vec<_>>()
            }
            _ => vec![],
        };
        proof.push(format!("provider_sequence_contiguous={proven}"));
        proof.push(format!(
            "provider_identity_range={}:{}",
            seq.first().map_or("none".into(), ToString::to_string),
            seq.last().map_or("none".into(), ToString::to_string)
        ));
        let status = if proven && !expected.is_empty() && seq == expected {
            CoverageStatus::Complete
        } else {
            issues.push("TRADE_PROVIDER_HISTORY_INCOMPLETE".into());
            CoverageStatus::Incomplete
        };
        for n in expected {
            if !seq.contains(&n) {
                if let Some(last) = gaps.last_mut()
                    && last["last_sequence"].as_i64() == n.checked_sub(1)
                {
                    last["last_sequence"] = n.into();
                } else {
                    gaps.push(json!({"first_sequence":n,"last_sequence":n}));
                }
            }
        }
        status
    } else {
        proof.push("coverage_capability=unsupported".into());
        issues.push(format!("COVERAGE_UNPROVABLE:{}", scope.kind()));
        CoverageStatus::Unprovable
    };
    Manifest::build(
        scope.clone(),
        references.into(),
        status,
        json!(proof),
        json!(issues),
        json!(gaps),
    )
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WindowPlan {
    pub intervals: Vec<(i64, i64)>,
    pub provider_intervals: Vec<(i64, i64)>,
}
/// Provider supplies this explicit 24x7 calendar identity; no provider selection occurs here.
pub fn plan_bar_window(
    semantic: &OnlyBarSemantic,
    before: Option<i64>,
    latest_closed: i64,
    count: usize,
    limit: usize,
) -> Result<WindowPlan> {
    if latest_closed <= 0
        || count == 0
        || count > limit
        || !semantic.is_aligned()
        || !semantic.is_fixed_duration()
        || before.is_some_and(|n| n <= 0 || n > latest_closed)
    {
        return Err(Error::Invalid);
    }
    const DAY: i128 = 86_400_000_000_000;
    let step: i64 = semantic
        .stride_minutes()
        .map_err(|_| Error::Invalid)?
        .to_string()
        .parse()
        .map_err(|_| Error::Unavailable)?;
    let step = step.checked_mul(60_000_000_000).ok_or(Error::Unavailable)?;
    let step = i128::from(step);
    if step > DAY {
        return Err(Error::Invalid);
    }
    let anchor = i128::from(before.unwrap_or(latest_closed));
    let full = DAY - DAY % step;
    let mut day = anchor.div_euclid(DAY) * DAY;
    let mut end = (day + full).min(day + (anchor - day) / step * step);
    if end == day {
        day -= DAY;
        end = day + full;
    }
    let mut intervals = vec![];
    while intervals.len() < count {
        let start = end.checked_sub(step).ok_or(Error::Invalid)?;
        if start < day {
            day -= DAY;
            end = day + full;
            continue;
        }
        if start < 0 {
            return Err(Error::Invalid);
        }
        intervals.push((
            i64::try_from(start).map_err(|_| Error::Invalid)?,
            i64::try_from(end).map_err(|_| Error::Invalid)?,
        ));
        end = start;
    }
    intervals.reverse();
    let mut merged: Vec<(i64, i64)> = vec![];
    for &(s, e) in &intervals {
        if let Some(last) = merged.last_mut()
            && last.1 == s
        {
            last.1 = e;
        } else {
            merged.push((s, e));
        }
    }
    Ok(WindowPlan {
        intervals,
        provider_intervals: merged,
    })
}
