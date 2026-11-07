//! Compare the native algorithm with the original Ready source. The cursor only
//! reads original projections; it never applies a projection or commits a fact.
use crate::next_open::{NativeExecution, NativeReplay, context};
use crate::{Error, MarketInput, NextOpenPolicy, boundary, err, fields};
use onlyalpha_domain::{base::OnlyDomainModel, execution::OnlyOrderSnapshot};
use onlyalpha_execution::{Components, Record};
use onlyalpha_runtime::VerifiedReplaySnapshot;
use serde_json::{Value, json};

struct OriginalExecution<'a> {
    configuration: &'a Value,
    records: &'a [Record],
    genesis: Vec<Value>,
    cursor: usize,
    end: usize,
}
impl OriginalExecution<'_> {
    fn body_components(&self) -> Result<Vec<Value>, Error> {
        if self.cursor == 0 {
            return (0..6)
                .map(|index| {
                    self.genesis
                        .get(index)
                        .cloned()
                        .ok_or_else(|| err("TERMINAL_GENESIS"))
                })
                .collect();
        }
        #[cfg(test)]
        ORIGINAL_BODY_READS.with(|count| count.set(count.get() + 1));
        let mut body = self
            .records
            .get(self.cursor - 1)
            .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?
            .prepared()
            .record();
        let rows = body["projections"]
            .as_array_mut()
            .filter(|rows| rows.len() == 6)
            .ok_or_else(|| err("TERMINAL_EXECUTION_PROJECTIONS"))?;
        rows.iter_mut()
            .map(|row| {
                row.get_mut("result")
                    .map(Value::take)
                    .ok_or_else(|| err("TERMINAL_EXECUTION_PROJECTIONS"))
            })
            .collect()
    }
    fn component(&self, index: usize) -> Result<Value, Error> {
        if index >= 6 {
            return Err(err("TERMINAL_EXECUTION_PROJECTIONS"));
        }
        if self.cursor == 0 {
            return self
                .genesis
                .get(index)
                .cloned()
                .ok_or_else(|| err("TERMINAL_GENESIS"));
        }
        self.body_components()?
            .into_iter()
            .nth(index)
            .ok_or_else(|| err("TERMINAL_EXECUTION_PROJECTIONS"))
    }
    fn components(&self) -> Result<Vec<Value>, Error> {
        self.body_components()
    }
    fn order_rows(&self) -> Result<&[Value], Error> {
        let rows = if self.cursor == 0 {
            &self
                .genesis
                .first()
                .ok_or_else(|| err("TERMINAL_GENESIS"))?["state"]["orders"]
        } else {
            self.records
                .get(self.cursor - 1)
                .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?
                .prepared()
                .order_snapshot_data()
        };
        rows.as_array()
            .map(Vec::as_slice)
            .ok_or_else(|| err("TERMINAL_ORDER_SOURCE"))
    }
    fn typed_snapshot(&self, snapshot: &Value) -> Result<OnlyOrderSnapshot, Error> {
        let original = boundary(OnlyOrderSnapshot::from_record(snapshot))?;
        if original.to_record() != *snapshot
            || Some(original.runtime_id().value()) != self.configuration["runtime"].as_str()
            || Some(original.account_id().value()) != self.configuration["account"].as_str()
            || self.configuration["profiles"]
                .get(original.cluster_id().value())
                .is_none()
        {
            return Err(err("TERMINAL_ORDER_SOURCE"));
        }
        Ok(original)
    }
    fn typed_order(&self, cluster: &str, order: &str) -> Result<OnlyOrderSnapshot, Error> {
        let mut rows = self
            .order_rows()?
            .iter()
            .map(|row| &row["snapshot"])
            .filter(|snapshot| {
                snapshot["order_id"]["value"] == order && snapshot["cluster_id"]["value"] == cluster
            });
        let snapshot = rows.next().ok_or_else(|| err("TERMINAL_ORDER_SOURCE"))?;
        if rows.next().is_some() {
            return Err(err("TERMINAL_ORDER_SOURCE"));
        }
        self.typed_snapshot(snapshot)
    }
}
impl NativeExecution for OriginalExecution<'_> {
    fn configuration(&self) -> &Value {
        self.configuration
    }
    fn sequence(&self) -> usize {
        self.cursor
    }
    fn state(&self) -> Result<Value, Error> {
        #[cfg(test)]
        FULL_ORIGINAL_STATE_CONSTRUCTIONS.with(|count| count.set(count.get() + 1));
        let p = self.components()?;
        Ok(
            json!({"schema_version":1,"execution_sequence":self.cursor,"account":p[2]["state"],"position":p[1]["state"],"ledger":p[3]["state"],"risk":p[4]["state"],"execution":p[5]}),
        )
    }
    fn position_order_view(&self) -> Result<Value, Error> {
        let mut view = if self.cursor > 0 {
            self.records
                .get(self.cursor - 1)
                .map(|record| record.prepared().position_order_data().clone())
                .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?
        } else {
            let position = self.component(1)?;
            let account = self.component(2)?;
            let metadata = self.component(5)?;
            json!({"schema_version":1,"orders":metadata["orders"],"position_accounts":position["state"]["accounts"],"position_allocations":position["state"]["allocations"],"economic_version":account["state"]["snapshot"]["economic_version"],"position_checkpoint_fingerprint":crate::hash(&position)})
        };
        let relations = view["orders"]
            .as_object()
            .ok_or_else(|| err("TERMINAL_ORDER_SOURCE"))?;
        let mut active = Vec::new();
        let mut seen = std::collections::BTreeSet::new();
        for row in self.order_rows()? {
            let snapshot = self.typed_snapshot(&row["snapshot"])?;
            let id = snapshot.order_id().value();
            let cluster = snapshot.cluster_id().value();
            if !seen.insert(id.to_owned())
                || relations
                    .get(id)
                    .is_none_or(|relation| relation["cluster"] != cluster)
            {
                return Err(err("TERMINAL_ORDER_SOURCE"));
            }
            if Components::order_snapshot_is_active(&snapshot) {
                active.push(id.to_owned());
            }
        }
        if seen.len() != relations.len() {
            return Err(err("TERMINAL_ORDER_SOURCE"));
        }
        active.sort();
        view["schema_version"] = json!(2);
        view["active_order_ids"] = json!(active);
        Ok(view)
    }
    fn checkpoint(&self) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"config":self.configuration,"sequence":self.cursor,"pending":null,"components":self.components()?}),
        )
    }
    fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        Ok(self.typed_order(cluster, order)?.to_record())
    }
    fn fee_order_preview(&self, cluster: &str, request: &Value, at: u64) -> Result<Value, Error> {
        let p = self.component(0)?;
        Ok(
            Components::fee_order_preview_checkpoint(self.configuration, &p, cluster, request, at)?
                .to_record(),
        )
    }
    fn apply(&mut self, input: &Value) -> Result<(), Error> {
        if self.cursor < self.end {
            let original = self
                .records
                .get(self.cursor)
                .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?;
            if original.prepared().input() != input {
                return Err(err("TERMINAL_NATIVE_INPUT"));
            }
            self.cursor += 1;
            return Ok(());
        }
        if input["op"] == "ADMIT"
            && let Some(rejection) =
                Components::admission_rejection(self.configuration, &self.checkpoint()?, input)?
        {
            return Err(rejection);
        }
        Err(err("TERMINAL_NATIVE_INPUT_MISSING"))
    }
}
fn accepted(preparation: &Value) -> Result<Option<&Value>, Error> {
    let rows = preparation["strategy"]["accepted"]
        .as_array()
        .filter(|rows| rows.len() <= 1)
        .ok_or_else(|| err("TERMINAL_STRATEGY_SOURCE"))?;
    Ok(rows.first().map(|row| &row["outcome"]))
}
fn closed_preparation(
    previous: &Value,
    next: &Value,
    input: &MarketInput,
    processing: &Value,
) -> Result<(), Error> {
    fields(processing, &["schema_version", "preparation", "decisions"])?;
    fields(
        &processing["preparation"],
        &[
            "schema_version",
            "input_identity",
            "snapshot",
            "receipts",
            "plans",
        ],
    )?;
    let rows = next["strategy"]["accepted"]
        .as_array()
        .filter(|rows| rows.len() == 1)
        .ok_or_else(|| err("TERMINAL_STRATEGY_SOURCE"))?;
    let row = &rows[0];
    let outcome = &row["outcome"];
    let previous_count = previous["strategy"]["processed"]
        .as_u64()
        .ok_or_else(|| err("TERMINAL_STRATEGY_SOURCE"))?;
    let receipts = next["pipeline"]["delivery_receipts"]
        .as_array()
        .filter(|rows| rows.len() == 1)
        .ok_or_else(|| err("TERMINAL_PIPELINE_SOURCE"))?;
    if processing["schema_version"] != 1
        || processing["preparation"]["schema_version"] != 2
        || processing["decisions"] != json!([outcome])
        || row["bar"] != input.bar().to_record()
        || row["instrument"] != input.bar().instrument_id().to_string()
        || row["init_ns"] != input.event_ns().to_string()
        || next["strategy"]["processed"].as_u64() != previous_count.checked_add(1)
        || outcome["event_ns"] != input.event_ns().to_string()
        || outcome["parent_identity"] != processing["preparation"]["input_identity"]
        || row["parent"] != outcome["parent_identity"]
        || processing["preparation"]["receipts"] != json!(receipts)
        || receipts[0]["input_identity"] != outcome["parent_identity"]
        || receipts[0]["event_ns"] != outcome["event_ns"]
        || receipts[0]["outcome"] != "ACCEPTED"
    {
        return Err(err("TERMINAL_PREPARATION_SOURCE"));
    }
    Ok(())
}
/// The adapter is the original immutable pure rules/Fee implementation, supplied
/// by the owning application. The complete capture must match the original pin.
pub(crate) fn verify(
    source: &VerifiedReplaySnapshot,
    inputs: &crate::Inputs,
    resolver: Box<dyn NextOpenPolicy>,
) -> Result<(), Error> {
    let binding = source.binding();
    let p = &binding["participants"];
    let cluster = p["program"]["scope"]["cluster"]
        .as_str()
        .ok_or_else(|| err("TERMINAL_CLUSTER"))?;
    let initial = binding["initial_state"]["clock_ns"]
        .as_str()
        .ok_or_else(|| err("TERMINAL_TIME"))?
        .parse()
        .map_err(|_| err("TERMINAL_TIME"))?;
    if binding["initial_state"]["participants"]["preparation"]["strategy"]["processed"] != 0
        || accepted(&binding["initial_state"]["participants"]["preparation"])?.is_some()
        || binding["initial_state"]["participants"]["preparation"]["pipeline"]["processed"] != 0
    {
        return Err(err("TERMINAL_PREPARATION_GENESIS"));
    }
    let mut native = NativeReplay::new(&p["policy"], resolver, initial, cluster)?;
    if native.binding() != p["native_policy"]
        || native.capture() != binding["initial_state"]["participants"]["native"]
    {
        return Err(err("TERMINAL_NATIVE_BINDING"));
    }
    let genesis = Components::new(p["policy"]["execution"].clone())?.checkpoint()?["components"]
        .as_array()
        .ok_or_else(|| err("TERMINAL_GENESIS"))?
        .clone();
    let mut execution = OriginalExecution {
        configuration: &p["policy"]["execution"],
        records: source.records(),
        genesis,
        cursor: 0,
        end: 0,
    };
    let mut previous = binding["initial_state"].clone();
    for reference in source.refs() {
        let step = source.read_step(reference)?;
        let next = &step["state"];
        let cause = &step["cause"];
        let kind = cause["kind"]
            .as_str()
            .ok_or_else(|| err("TERMINAL_CAUSE"))?;
        let before = &previous["participants"];
        let after = &next["participants"];
        if native.capture() != before["native"] {
            return Err(err("TERMINAL_NATIVE_CUT"));
        }
        native.validate_cut(
            p["program"]["source"]
                .as_str()
                .ok_or_else(|| err("TERMINAL_SOURCE"))?,
            accepted(&before["preparation"])?,
        )?;
        native.validate_execution(&execution)?;
        let start = step["execution_start"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?;
        execution.end = start
            .checked_add(
                step["inputs"]
                    .as_array()
                    .ok_or_else(|| err("TERMINAL_INPUTS"))?
                    .len(),
            )
            .ok_or_else(|| err("TERMINAL_EXECUTION_PREFIX"))?;
        if execution.cursor != start || execution.end > source.records().len() {
            return Err(err("TERMINAL_EXECUTION_PREFIX"));
        }
        let cursor = previous["cursor"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .ok_or_else(|| err("TERMINAL_INPUT_PREFIX"))?;
        let expected = match kind {
            "OPEN" => {
                fields(&cause["processing"], &["input", "processing"])?;
                let input = inputs
                    .records()
                    .get(cursor)
                    .ok_or_else(|| err("TERMINAL_INPUT_PREFIX"))?
                    .opening();
                native.opening(&input, &mut execution)?
            }
            "BAR" => {
                fields(&cause["processing"], &["input", "processing"])?;
                let input = inputs
                    .records()
                    .get(cursor)
                    .ok_or_else(|| err("TERMINAL_INPUT_PREFIX"))?;
                let output = &cause["processing"]["processing"];
                fields(output, &["schema_version", "preparation", "policy"])?;
                closed_preparation(
                    &before["preparation"],
                    &after["preparation"],
                    input,
                    &output["preparation"],
                )?;
                let ctx = context(
                    &input.identity(),
                    input.event_ns(),
                    &input.bar().to_record()["trading_day"],
                )?;
                let now = ctx["time"].as_u64().ok_or_else(|| err("TERMINAL_TIME"))?;
                if let Some(command) = crate::trading::valuation_input(
                    p,
                    input,
                    now,
                    &execution,
                    ctx["day_index"].clone(),
                )? {
                    execution.apply(&command)?;
                }
                let policy = native.closed(input, &output["preparation"], &execution)?;
                json!({"schema_version":2,"preparation":output["preparation"],"policy":policy})
            }
            "INPUT_END" => native.end_input(&mut execution)?,
            "CANCEL_INPUT" => native.cancel_input(&mut execution)?,
            "PAUSE" | "RESUME" | "TERMINATE" => Value::Null,
            _ => return Err(err("TERMINAL_PROFILE")),
        };
        let actual = if matches!(kind, "OPEN" | "BAR") {
            &cause["processing"]["processing"]
        } else {
            &cause["processing"]
        };
        if actual != &expected
            || execution.cursor != execution.end
            || native.capture() != after["native"]
            || (kind != "BAR" && before["preparation"] != after["preparation"])
        {
            return Err(err("TERMINAL_NATIVE_PROCESSING"));
        }
        native.validate_cut(
            p["program"]["source"]
                .as_str()
                .ok_or_else(|| err("TERMINAL_SOURCE"))?,
            accepted(&after["preparation"])?,
        )?;
        native.validate_execution(&execution)?;
        previous = next.clone();
    }
    if execution.cursor != source.records().len() {
        return Err(err("TERMINAL_EXECUTION_TAIL"));
    }
    Ok(())
}

#[cfg(test)]
std::thread_local! {
 static FULL_ORIGINAL_STATE_CONSTRUCTIONS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 static ORIGINAL_BODY_READS:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
}
#[cfg(test)]
#[path = "tests/position_order_view_tests.rs"]
mod position_order_view_tests;
