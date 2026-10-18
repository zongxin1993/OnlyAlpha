use crate::{model::*, pipeline::*};
use onlyalpha_calculation::{InputPosition, StateOutcome};
use onlyalpha_domain::{
    base::OnlyDomainModel, identifiers::OnlyClusterId, market::OnlyBar, time::OnlyTimestamp,
};
use onlyalpha_market_data_construction::*;
use onlyalpha_market_data_state::*;
use serde_json::{Map, Value, json};
use std::{
    collections::BTreeMap,
    panic::{AssertUnwindSafe, catch_unwind},
    sync::Arc,
};
struct Restored<C> {
    chain: String,
    managers: BTreeMap<String, OnlyConstructionManager>,
    state: OnlyMarketDataState,
    delivery: onlyalpha_market_data_delivery::OnlyMarketDataDelivery,
    calculations: C,
    processed: u64,
    frontiers: BTreeMap<String, Frontier>,
    last_init: Option<OnlyTimestamp>,
    expectations: BTreeMap<String, InputPosition>,
    last_inputs: BTreeMap<String, Arc<OnlyBar>>,
    quarantined: BTreeMap<OnlyClusterId, Value>,
}
const MAX_CHECKPOINT: usize = 64 * 1024 * 1024;
fn bad() -> PipelineError {
    PipelineError::Record("CHECKPOINT_RELATION")
}
fn object<'a>(v: &'a Value, keys: &[&str]) -> PipelineResult<&'a Map<String, Value>> {
    let m = v.as_object().ok_or_else(bad)?;
    if m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)) {
        return Err(bad());
    }
    Ok(m)
}
fn text(v: &Value) -> PipelineResult<&str> {
    v.as_str().ok_or_else(bad)
}
fn array(v: &Value) -> PipelineResult<&Vec<Value>> {
    v.as_array().ok_or_else(bad)
}
fn integer(v: &Value) -> PipelineResult<u64> {
    v.as_u64().ok_or_else(bad)
}
fn stamp(v: &Value) -> PipelineResult<OnlyTimestamp> {
    let raw = text(v)?;
    if raw.len() > 128 {
        return Err(bad());
    }
    let n: num_bigint::BigInt = raw.parse().map_err(|_| bad())?;
    if n.to_string() != raw {
        return Err(bad());
    }
    Ok(OnlyTimestamp::from_unix_nanos(n))
}
// A derived composition manifest, not an independent input or execution authority.
// Its caller-expected outer digest remains the checkpoint trust root.
fn component_bindings(value: &Value) -> PipelineResult<Value> {
    let frontiers = array(&value["frontiers"])?;
    let mut bindings = Vec::new();
    for row in array(&value["managers"])? {
        let pair = array(row)?;
        if pair.len() != 2 {
            return Err(bad());
        }
        let source = text(&pair[0])?;
        let inputs: Vec<_> = frontiers
            .iter()
            .filter(|f| f["source"] == source)
            .cloned()
            .collect();
        bindings.push(json!([source, {
            "prefix": value["chain"], "frontiers": inputs,
            "checkpoint_sha256": digest(&pair[1])
        }]));
    }
    let components: Map<String, Value> = value
        .as_object()
        .ok_or_else(bad)?
        .iter()
        .filter(|(k, _)| k.as_str() != "component_bindings" && k.as_str() != "managers")
        .map(|(k, v)| (k.clone(), json!(digest(v))))
        .collect();
    Ok(json!({"sources": bindings, "components": components}))
}
fn positions<C: CalculationPort>(
    program: &PipelineProgram,
    port: &mut C,
    state: &OnlyMarketDataState,
    expected: &BTreeMap<String, InputPosition>,
    inputs: &BTreeMap<String, Arc<OnlyBar>>,
    quarantined: &BTreeMap<OnlyClusterId, Value>,
) -> PipelineResult<()> {
    program.validate_registrations(port)?;
    if expected.keys().ne(program.slots.keys())
        || inputs.keys().any(|k| !program.slots.contains_key(k))
    {
        return Err(bad());
    }
    for (id, slot) in &program.slots {
        let snapshot = port.snapshot(id).map_err(|_| bad())?;
        if snapshot.binding() != &slot.binding || snapshot.outcome() == StateOutcome::Unknown {
            return Err(bad());
        }
        let record = snapshot.to_record();
        let cursor = &record["cursor"];
        let samples = integer(&cursor["samples"])?;
        let revision = integer(&cursor["revision"])?;
        if revision != samples {
            return Err(bad());
        }
        if let Some(bar) = inputs.get(id) {
            if bar.bar_type() != &slot.bar_type {
                return Err(bad());
            }
            let failed = matches!(
                snapshot.outcome(),
                StateOutcome::Failed | StateOutcome::Unavailable
            );
            let (r, s) = if failed {
                (
                    revision.checked_add(1).ok_or_else(bad)?,
                    samples.checked_add(1).ok_or_else(bad)?,
                )
            } else {
                (revision, samples)
            };
            let position = InputPosition::new(
                r,
                s,
                &OnlyTimestamp::from_datetime(*bar.bar_end())
                    .unix_nanos()
                    .to_string(),
                &digest(&bar.to_record()),
            )
            .map_err(|_| bad())?;
            if expected[id] != position
                || (!failed && snapshot.position().as_ref() != Some(&position))
            {
                return Err(bad());
            }
            let latest = state.latest_closed(&slot.bar_type).ok_or_else(bad)?;
            let version: u64 = state
                .version(&slot.bar_type)
                .to_string()
                .parse()
                .map_err(|_| bad())?;
            if latest.bar_end() < bar.bar_end()
                || s > version
                || (!failed
                    && !quarantined.contains_key(&slot.cluster)
                    && (latest != bar.as_ref() || s != version))
            {
                return Err(bad());
            }
            let history = state
                .history(&slot.bar_type, state.history_limit())
                .map_err(|_| bad())?;
            if history
                .first()
                .is_some_and(|oldest| oldest.bar_end() <= bar.bar_end())
                && !history.iter().any(|b| b.as_ref() == bar.as_ref())
            {
                return Err(bad());
            }
        } else if snapshot.outcome() != StateOutcome::Uninitialized
            || samples != 0
            || expected[id] != InputPosition::unobserved()
            || (!quarantined.contains_key(&slot.cluster)
                && state.latest_closed(&slot.bar_type).is_some())
        {
            return Err(bad());
        }
    }
    Ok(())
}
impl<C: CalculationPort, D: PreparationConsumer> MarketDataPipeline<C, D> {
    pub fn capture_checkpoint(&mut self) -> PipelineResult<Value> {
        if self.failed {
            return Err(PipelineError::RecoveryRequired);
        }
        self.failed = true;
        let result = catch_unwind(AssertUnwindSafe(|| self.capture_inner()))
            .unwrap_or(Err(PipelineError::Shared("CHECKPOINT_PANIC")));
        if result.is_ok() {
            self.failed = false;
        }
        result
    }
    fn capture_inner(&mut self) -> PipelineResult<Value> {
        positions(
            &self.program,
            &mut self.calculations,
            &self.state,
            &self.expected,
            &self.last_inputs,
            &self.quarantined,
        )?;
        let port = self
            .calculations
            .capture()
            .map_err(|_| PipelineError::Shared("CHECKPOINT_CALCULATION"))?;
        positions(
            &self.program,
            &mut self.calculations,
            &self.state,
            &self.expected,
            &self.last_inputs,
            &self.quarantined,
        )?;
        let managers = self
            .managers
            .iter()
            .map(|(k, m)| Ok(json!([k, m.capture_checkpoint().map_err(|_| bad())?])))
            .collect::<PipelineResult<Vec<_>>>()?;
        let frontiers = self
            .frontiers
            .values()
            .map(|f| {
                json!({
                    "source": f.source, "input": f.input.to_record(), "sequence": f.sequence,
                    "count": f.count, "event_ns": f.event.unix_nanos().to_string()
                })
            })
            .collect::<Vec<_>>();
        let mut value = json!({
            "schema_version": 1, "program": self.program.to_record(), "processed": self.processed,
            "chain": self.chain, "last_init_ns": self.last_init.as_ref().map(|t| t.unix_nanos().to_string()),
            "frontiers": frontiers, "managers": managers, "state": self.state.capture_checkpoint(),
            "delivery": self.delivery.capture_checkpoint(),
            "expected": self.expected.iter().map(|(k, v)| json!([k, v.to_record()])).collect::<Vec<_>>(),
            "last_inputs": self.last_inputs.iter().map(|(k, b)| json!([k, b.to_record()])).collect::<Vec<_>>(),
            "calculations": port, "quarantined": self.quarantined.values().collect::<Vec<_>>()
        });
        value["component_bindings"] = component_bindings(&value)?;
        if value.to_string().len() > MAX_CHECKPOINT {
            return Err(bad());
        }
        Ok(value)
    }
    pub fn restore_checkpoint(
        &mut self,
        bytes: &[u8],
        expected_digest: &str,
    ) -> PipelineResult<()> {
        validate_digest(expected_digest)?;
        if bytes.len() > MAX_CHECKPOINT {
            return Err(bad());
        }
        let value: Value = serde_json::from_slice(bytes).map_err(|_| bad())?;
        if value.to_string().as_bytes() != bytes || digest(&value) != expected_digest {
            return Err(bad());
        }
        // All mutation is confined to candidates, including process creation/restoration.
        let result = catch_unwind(AssertUnwindSafe(|| self.restore_candidate(&value)))
            .unwrap_or(Err(PipelineError::Shared("RESTORE_PANIC")))?;
        self.chain = result.chain;
        self.managers = result.managers;
        self.state = result.state;
        self.delivery = result.delivery;
        self.calculations = result.calculations;
        self.processed = result.processed;
        self.frontiers = result.frontiers;
        self.last_init = result.last_init;
        self.expected = result.expectations;
        self.last_inputs = result.last_inputs;
        self.quarantined = result.quarantined;
        self.failed = false;
        Ok(())
    }
    fn restore_candidate(&self, value: &Value) -> PipelineResult<Restored<C>> {
        object(
            value,
            &[
                "schema_version",
                "program",
                "processed",
                "chain",
                "last_init_ns",
                "frontiers",
                "managers",
                "component_bindings",
                "state",
                "delivery",
                "expected",
                "last_inputs",
                "calculations",
                "quarantined",
            ],
        )?;
        if value["schema_version"].as_u64() != Some(1)
            || value["program"] != self.program.to_record()
        {
            return Err(bad());
        }
        if value["component_bindings"] != component_bindings(value)? {
            return Err(bad());
        }
        let processed = integer(&value["processed"])?;
        validate_digest(text(&value["chain"])?)?;
        let last_init = if value["last_init_ns"].is_null() {
            None
        } else {
            Some(stamp(&value["last_init_ns"])?)
        };
        if (processed == 0) != last_init.is_none() {
            return Err(bad());
        }
        let mut managers = self.program.managers()?;
        let mut seen = std::collections::BTreeSet::new();
        for pair in array(&value["managers"])? {
            let pair = array(pair)?;
            if pair.len() != 2 {
                return Err(bad());
            }
            let id = text(&pair[0])?;
            if !seen.insert(id) {
                return Err(bad());
            }
            managers
                .get_mut(id)
                .ok_or_else(bad)?
                .restore_checkpoint(&pair[1])
                .map_err(|_| bad())?;
        }
        if seen.len() != managers.len() {
            return Err(bad());
        }
        let mut state = OnlyMarketDataState::new(
            self.program.scope.clone(),
            OnlyMarketDataStateConfig {
                history_limit: self.program.history_limit,
            },
        )
        .map_err(|_| bad())?;
        state
            .restore_checkpoint(&value["state"])
            .map_err(|_| bad())?;
        if processed == 0
            && value["chain"]
                != digest(
                    &json!({"schema_version":1,"program":self.program.fingerprint(),"initial_state":state.capture_checkpoint()}),
                )
        {
            return Err(bad());
        }
        let mut frontiers = BTreeMap::new();
        let mut count = 0u64;
        for row in array(&value["frontiers"])? {
            object(row, &["source", "input", "sequence", "count", "event_ns"])?;
            let source = text(&row["source"])?.to_owned();
            let input = OnlyConstructionInput::from_record(&row["input"]).map_err(|_| bad())?;
            let graph = &self.program.sources.get(&source).ok_or_else(bad)?.graph;
            if !graph.providers().contains(&input) {
                return Err(bad());
            }
            let sequence = integer(&row["sequence"])?;
            let local_count = integer(&row["count"])?;
            let event = stamp(&row["event_ns"])?;
            if local_count == 0
                || sequence < local_count
                || last_init.as_ref().is_none_or(|t| t < &event)
            {
                return Err(bad());
            }
            count = count.checked_add(local_count).ok_or_else(bad)?;
            if let OnlyConstructionInput::Bar(kind) = &input
                && (state
                    .latest_closed(kind)
                    .is_none_or(|b| OnlyTimestamp::from_datetime(*b.bar_end()) != event)
                    || state.version(kind).to_string() != local_count.to_string())
            {
                return Err(bad());
            }
            let key = json!([source, input.to_record()]).to_string();
            if frontiers
                .insert(
                    key,
                    Frontier {
                        source,
                        input,
                        sequence,
                        count: local_count,
                        event,
                    },
                )
                .is_some()
            {
                return Err(bad());
            }
        }
        if count != processed {
            return Err(bad());
        }
        for kind in state.bar_types() {
            let source = self.program.owners.get(&bar_key(&kind)).ok_or_else(bad)?;
            let frontier = frontiers
                .values()
                .filter(|f| &f.source == source)
                .map(|f| &f.event)
                .max()
                .ok_or_else(bad)?;
            let bar = state.latest_closed(&kind).ok_or_else(bad)?;
            let version: u64 = state
                .version(&kind)
                .to_string()
                .parse()
                .map_err(|_| bad())?;
            if &OnlyTimestamp::from_datetime(*bar.bar_end()) > frontier || version > processed {
                return Err(bad());
            }
        }
        let mut delivery = self.program.delivery()?;
        delivery
            .restore_checkpoint(&value["delivery"])
            .map_err(|_| bad())?;
        for registration in array(&value["delivery"]["registrations"])? {
            let id = text(&registration["cluster_id"])?;
            let cluster: OnlyClusterId = id.parse().map_err(|_| bad())?;
            if cluster.value() != id {
                return Err(bad());
            }
            if !registration["last_planned_event_ns"].is_null() {
                let event = registration["last_planned_event_ns"]
                    .as_number()
                    .ok_or_else(bad)?
                    .to_string();
                let event = stamp(&json!(event))?;
                let primary = self
                    .program
                    .clusters
                    .get(&cluster)
                    .ok_or_else(bad)?
                    .primary();
                if state
                    .latest_closed(primary)
                    .is_none_or(|b| OnlyTimestamp::from_datetime(*b.bar_end()) != event)
                {
                    return Err(bad());
                }
            } else if state
                .latest_closed(
                    self.program
                        .clusters
                        .get(&cluster)
                        .ok_or_else(bad)?
                        .primary(),
                )
                .is_some()
            {
                return Err(bad());
            }
        }
        let mut expectations = BTreeMap::new();
        for pair in array(&value["expected"])? {
            let p = array(pair)?;
            if p.len() != 2
                || expectations
                    .insert(
                        text(&p[0])?.to_owned(),
                        InputPosition::from_record(&p[1]).map_err(|_| bad())?,
                    )
                    .is_some()
            {
                return Err(bad());
            }
        }
        let mut last_inputs = BTreeMap::new();
        for pair in array(&value["last_inputs"])? {
            let p = array(pair)?;
            if p.len() != 2
                || last_inputs
                    .insert(
                        text(&p[0])?.to_owned(),
                        Arc::new(OnlyBar::from_record(&p[1]).map_err(|_| bad())?),
                    )
                    .is_some()
            {
                return Err(bad());
            }
        }
        let mut calculations = self
            .calculations
            .restore_candidate(&value["calculations"])
            .map_err(|_| bad())?;
        let mut quarantined = BTreeMap::new();
        for row in array(&value["quarantined"])? {
            object(
                row,
                &[
                    "cluster",
                    "event_ns",
                    "delivery_id",
                    "input_identity",
                    "called",
                    "outcome",
                    "degraded",
                ],
            )?;
            let raw = text(&row["cluster"])?;
            let cluster: OnlyClusterId = raw.parse().map_err(|_| bad())?;
            if cluster.value() != raw
                || !self.program.clusters.contains_key(&cluster)
                || row["called"] != true
                || !matches!(text(&row["outcome"])?, "FAILED" | "UNKNOWN")
                || !row["degraded"].is_boolean()
            {
                return Err(bad());
            }
            validate_digest(text(&row["delivery_id"])?)?;
            validate_digest(text(&row["input_identity"])?)?;
            let event = stamp(&row["event_ns"])?;
            let planned = array(&value["delivery"]["registrations"])?
                .iter()
                .find(|r| r["cluster_id"] == raw)
                .ok_or_else(bad)?;
            let last = planned["last_planned_event_ns"]
                .as_number()
                .ok_or_else(bad)?
                .to_string();
            if event > stamp(&json!(last))? || quarantined.insert(cluster, row.clone()).is_some() {
                return Err(bad());
            }
        }
        positions(
            &self.program,
            &mut calculations,
            &state,
            &expectations,
            &last_inputs,
            &quarantined,
        )?;
        Ok(Restored {
            chain: text(&value["chain"])?.to_owned(),
            managers,
            state,
            delivery,
            calculations,
            processed,
            frontiers,
            last_init,
            expectations,
            last_inputs,
            quarantined,
        })
    }
}
