//! Exclusive, unpublished economic work. It has no Store or dispatch receipt.
use crate::{Components, Error, backtest_result::TranscriptParts, model::*};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};

/// Actual in-process advancement; a passive observation grants no durable authority.
#[derive(Clone, Debug)]
pub struct WorkingStep {
    sequence: u64,
    input: Arc<Value>,
    payload_fingerprint: String,
}
impl WorkingStep {
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    pub fn input(&self) -> &Value {
        &self.input
    }
    pub fn payload_fingerprint(&self) -> &str {
        &self.payload_fingerprint
    }
}
/// Current typed owners only. Unexpected errors poison this unpublished work;
/// rebuilding a new finite job is distinct from durable recovery.
pub struct WorkingState {
    configuration_fingerprint: String,
    seal: Arc<()>,
    evidence_binding: Option<String>,
    admissions: BTreeMap<String, Arc<MemoryAdmission>>,
    admission_orders: BTreeMap<String, String>,
    owners: Components,
    healthy: bool,
}
/// Produced only by the final economic barrier, never by deserializing a result.
/// ```compile_fail
/// let forged = onlyalpha_execution::CompletedWorkingState { state: serde_json::json!({}) };
/// ```
pub struct CompletedWorkingState {
    state: Value,
    result: Value,
    account_checkpoint: Arc<Value>,
    equity_points: Vec<Value>,
}
impl CompletedWorkingState {
    pub fn state(&self) -> &Value {
        &self.state
    }
    pub fn result(&self) -> &Value {
        &self.result
    }
    pub fn account_checkpoint(&self) -> &Value {
        &self.account_checkpoint
    }
    pub fn equity_points(&self) -> &[Value] {
        &self.equity_points
    }
}
/// Actual accepted finite admission data, never a durable Ready token.
pub struct MemoryAdmission {
    input: Arc<Value>,
    transaction: String,
    payload: String,
}
impl MemoryAdmission {
    pub fn input(&self) -> &Value {
        &self.input
    }
    pub fn transaction(&self) -> &str {
        &self.transaction
    }
    pub fn payload_fingerprint(&self) -> &str {
        &self.payload
    }
}
/// Local, current-owner evidence only; not caller constructible or serializable.
pub struct OriginalEvidence {
    seal: Arc<()>,
    sequence: u64,
    input: String,
    origin: Value,
}
impl WorkingState {
    pub fn new(configuration: Value) -> Result<Self, Error> {
        let owners = Components::new(configuration)?;
        let configuration_fingerprint = hash(owners.configuration());
        Ok(Self {
            configuration_fingerprint,
            seal: Arc::new(()),
            evidence_binding: None,
            admissions: BTreeMap::new(),
            admission_orders: BTreeMap::new(),
            owners,
            healthy: true,
        })
    }
    pub fn for_run(configuration: Value, binding: &str) -> Result<Self, Error> {
        fp(&json!(binding))?;
        let mut owner = Self::new(configuration)?;
        owner.evidence_binding = Some(binding.into());
        Ok(owner)
    }
    pub fn admission(&self, order: &str) -> Result<Arc<MemoryAdmission>, Error> {
        self.ready()?;
        self.admission_orders
            .get(order)
            .and_then(|id| self.admissions.get(id))
            .cloned()
            .ok_or_else(|| err("EXECUTION_MEMORY_ADMISSION_MISSING"))
    }
    pub fn order_submission(&self, cluster: &str, order: &str) -> Result<String, Error> {
        self.ready()?;
        Ok(boundary(self.owners.order.submission(cluster, order))?.into())
    }
    pub fn check_plain_input(&self, input: &Value) -> Result<(), Error> {
        self.ready()?;
        self.owners.require_original_evidence(input)
    }
    pub fn check_cash_observation(
        &self,
        input: &Value,
        observed: &onlyalpha_broker::ObservedFact,
    ) -> Result<OriginalEvidence, Error> {
        self.ready()?;
        let fact = observed.fact();
        let order = id(&input["payload"]["order"])?;
        let admission = self.admission(order)?;
        let intent = observed.intent().record();
        if input.get("broker_record") != Some(&fact.record())
            || fact.order() != Some(order)
            || intent["command"]["scope"] != fact.scope().record()
            || intent["command"]["order"] != order
            || intent["command"]["request"] != admission.input()["payload"]["request"]
            || intent["transaction"] != admission.transaction()
            || intent["payload_hash"] != admission.payload_fingerprint()
            || input["cluster"] != admission.input()["cluster"]
            || input["revision"] != admission.input()["revision"]
        {
            return Err(err("EXECUTION_CASH_OBSERVATION_MISMATCH"));
        }
        Ok(OriginalEvidence {
            seal: Arc::clone(&self.seal),
            sequence: self.sequence(),
            input: hash(input),
            origin: Value::Null,
        })
    }
    pub fn check_original_input(
        &self,
        input: &Value,
        cut: &crate::MarketSourceCut,
        broker: &onlyalpha_broker::MemoryBroker,
        source: Option<&onlyalpha_broker::source::SourceHistory>,
    ) -> Result<OriginalEvidence, Error> {
        self.ready()?;
        if self.evidence_binding.is_none() || self.owners.config["runtime_kind"] != "BACKTEST" {
            return Err(err("EXECUTION_MEMORY_ORIGINAL_BINDING"));
        }
        if self.owners.config["perpetual"]["execution_source_binding"] != broker.source_binding() {
            return Err(err("EXECUTION_MEMORY_SOURCE_BINDING"));
        }
        let origin =
            self.owners
                .original_origin(input, cut, broker.original(), source, |intent| {
                    let Some(admission) = intent["transaction"]
                        .as_str()
                        .and_then(|key| self.admissions.get(key))
                    else {
                        return Ok(false);
                    };
                    Ok(admission.input()["op"] == "ADMIT"
                        && admission.input()["payload"]["request"] == intent["command"]["request"]
                        && admission.input()["payload"]["order"] == input["payload"]["order"]
                        && intent["payload_hash"] == admission.payload_fingerprint())
                })?;
        Ok(OriginalEvidence {
            seal: Arc::clone(&self.seal),
            sequence: self.owners.sequence,
            input: hash(input),
            origin,
        })
    }
    pub fn apply_verified(
        &mut self,
        input: &Value,
        evidence: OriginalEvidence,
    ) -> Result<WorkingStep, Error> {
        self.ready()?;
        if !Arc::ptr_eq(&self.seal, &evidence.seal)
            || self.owners.sequence != evidence.sequence
            || hash(input) != evidence.input
        {
            self.healthy = false;
            return Err(err("EXECUTION_MEMORY_ORIGINAL_OWNER"));
        }
        self.apply_inner(input, evidence.origin)
    }
    fn ready(&self) -> Result<(), Error> {
        if self.healthy {
            Ok(())
        } else {
            Err(err("MEMORY_SESSION_FAILED"))
        }
    }
    pub fn sequence(&self) -> u64 {
        self.owners.sequence
    }
    pub fn apply(&mut self, input: &Value) -> Result<WorkingStep, Error> {
        self.ready()?;
        if let Err(error) = self.check_plain_input(input) {
            self.healthy = false;
            return Err(error);
        }
        self.apply_inner(input, Value::Null)
    }
    fn apply_inner(&mut self, input: &Value, origin: Value) -> Result<WorkingStep, Error> {
        self.ready()?;
        self.healthy = false;
        let n = self.owners.validate_planning_input(input)?;
        self.owners.invalidate_payloads();
        match self.owners.apply_operation(input) {
            Ok(()) => (),
            Err(error)
                if input["op"] == "ADMIT"
                    && matches!(
                        error.0.as_str(),
                        "EXECUTION_RISK_DENIED" | "EXECUTION_ACCOUNT_CAPACITY_DENIED"
                    ) =>
            {
                self.healthy = true;
                return Err(error);
            }
            Err(error) => return Err(error),
        }
        if !origin.is_null() {
            let p = &input["payload"];
            let economic = &mut Arc::make_mut(&mut self.owners.meta)["perpetual"];
            let row = if input["op"] == "FUNDING" {
                &mut economic["funding"][text(&p["fact"]["fact_id"])?]
            } else {
                &mut economic["broker_facts"][text(&p["broker"]["id"])?]
            };
            if row.get("origin").is_none() {
                row["origin"] = origin;
            }
        }
        self.owners.sequence = self
            .owners
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("EXECUTION_SEQUENCE_OVERFLOW"))?;
        let sequence = self.owners.sequence;
        let fingerprint = hash(input);
        let meta = Arc::make_mut(&mut self.owners.meta);
        meta["inputs"][text(&input["input_id"])?] = json!(fingerprint);
        meta["sources"][text(&input["source_ref"])?] = json!(fingerprint);
        meta["last_runtime_sequence"] = json!(n);
        meta["transactions"][sequence.to_string()] = json!(format!("ETX-{fingerprint}"));
        self.owners.invalidate_payloads();
        self.healthy = true;
        let input = Arc::new(input.clone());
        let payload_fingerprint = hash(
            &json!({"schema_version":1,"kind":"FINITE_MEMORY_INPUT","binding":self.evidence_binding,"configuration":self.configuration_fingerprint,"sequence":sequence,"input":fingerprint}),
        );
        if input["op"] == "ADMIT" && self.evidence_binding.is_some() {
            let transaction = format!("ETX-{fingerprint}");
            self.admission_orders.insert(
                text(&input["payload"]["order"])?.into(),
                transaction.clone(),
            );
            self.admissions.insert(
                transaction.clone(),
                Arc::new(MemoryAdmission {
                    input: Arc::clone(&input),
                    transaction,
                    payload: payload_fingerprint.clone(),
                }),
            );
        }
        Ok(WorkingStep {
            sequence,
            input,
            payload_fingerprint,
        })
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.ready()?;
        Ok(self.owners.state_data())
    }
    pub fn account_snapshot(&self) -> Result<Value, Error> {
        self.ready()?;
        Ok(self.owners.account.snapshot())
    }
    pub fn position_order_view(&self) -> Result<Value, Error> {
        self.ready()?;
        self.owners.position_order_data()
    }
    pub fn order(&self, cluster: &str, order: &str) -> Result<Value, Error> {
        self.ready()?;
        Ok(boundary(self.owners.order.get(cluster, order))?.to_record())
    }
    pub fn fee_order_preview(
        &self,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<Value, Error> {
        self.ready()?;
        if request.to_string().len() > 65536
            || self.owners.config["profiles"].get(cluster).is_none()
        {
            return Err(err("EXECUTION_PREVIEW_SCOPE"));
        }
        bound_decimal_leaves(request)?;
        let mut order = self.owners.order.as_ref().clone();
        let outcome = boundary(order.apply(&json!({"schema_version":1,"op":"CREATE","cluster_id":cluster,"account_id":self.owners.config["account"],"request":request,"cause":hash(request),"at":at})))?;
        if outcome.result != onlyalpha_order::ApplyResult::Applied {
            return Err(err("EXECUTION_PREVIEW_REQUEST_CONFLICT"));
        }
        Ok(outcome
            .snapshot
            .ok_or_else(|| err("EXECUTION_PREVIEW_MISSING"))?
            .to_record())
    }
    /// Reconcile all retained inputs against these actual owners once at finish.
    /// The shared result assembler preserves Account/Ledger numerical authority,
    /// full orders/trades, timelines, reservations and risk diagnostics.
    pub fn finish(
        self,
        inputs: &[Value],
        binding: &Value,
        initial_ns: i64,
        final_ns: i64,
    ) -> Result<CompletedWorkingState, Error> {
        self.ready()?;
        fp(&binding["kernel_artifact"])?;
        fp(&binding["input_pin"])?;
        if binding["configuration"] != hash(&self.owners.config) {
            return Err(err("MEMORY_BINDING_MISMATCH"));
        }
        if initial_ns > final_ns
            || inputs.len() as u64 != self.owners.sequence
            || self.owners.meta["inputs"].as_object().map(|m| m.len()) != Some(inputs.len())
        {
            return Err(err("MEMORY_COMPLETION_PREFIX"));
        }
        let mut fee = boundary(onlyalpha_fee::Manager::new(
            self.owners.meta["fee_authority"]["config"].clone(),
            usize::try_from(uint(&self.owners.meta["fee_authority"]["capacity"])?)
                .map_err(|_| err("RECONCILIATION_FEE_CAPACITY"))?,
        ))?;
        let mut expected = BTreeMap::new();
        let mut facts = Vec::with_capacity(inputs.len());
        let mut trades = Vec::new();
        let mut seen_native_fills = std::collections::BTreeSet::new();
        for (i, input) in inputs.iter().enumerate() {
            let sequence = i as u64 + 1;
            let transaction = format!("ETX-{}", hash(input));
            let time = input["time"]
                .as_i64()
                .ok_or_else(|| err("RESULT_INPUT_TIME"))?;
            if time < initial_ns
                || time > final_ns
                || self.owners.meta["transactions"][sequence.to_string()] != transaction
                || self.owners.meta["inputs"][text(&input["input_id"])?] != hash(input)
            {
                return Err(err("MEMORY_COMPLETION_PREFIX"));
            }
            let native = input["op"] == "FILL"
                && input["payload"]["schema_version"] == 2
                && input["payload"]["broker"].is_object();
            let row = if native {
                &self.owners.meta["perpetual"]["broker_facts"]
                    [text(&input["payload"]["broker"]["id"])?]
            } else {
                &Value::Null
            };
            let duplicate = native
                && !seen_native_fills.insert(text(&input["payload"]["broker"]["id"])?.to_owned());
            let normalized = crate::reconciliation::canonical_fee_input(input, row, duplicate)?;
            if let Some(value) = &normalized {
                crate::reconciliation::record_fee_input(value.as_ref(), &mut fee, &mut expected)?;
            }
            let fact = json!({"sequence":sequence,"transaction":transaction,"input":input});
            if input["op"] == "FILL" && !duplicate {
                trades.push(fact.clone());
            }
            facts.push(fact);
        }
        if fee.checkpoint() != self.owners.meta["fee_authority"] {
            return Err(err("RECONCILIATION_FEE_HISTORY_UNAVAILABLE"));
        }
        let owners = self.owners.payloads()?;
        let (totals, differences) = crate::reconciliation::compare(
            &self.owners.config,
            &owners[2],
            &owners[3],
            &expected,
            self.owners.precision,
        )?;
        let source = json!({"schema_version":1,"kind":"UNPUBLISHED_MEMORY_EXECUTION","configuration":hash(&self.owners.config),"inputs":hash(&json!(inputs)),"rows":inputs.len()});
        let reconciliation = json!({"schema_version":1,"source":source,"status":if differences.is_empty(){"MATCHED"}else{"MISMATCHED"},"totals":totals,"differences":differences});
        let initial = OnlyTimestamp::from_unix_nanos(initial_ns.into());
        let final_time = OnlyTimestamp::from_unix_nanos(final_ns.into());
        let manifest = json!({"schema_version":1,"configuration":hash(&self.owners.config),"kernel_artifact":binding["kernel_artifact"],"input_pin":binding["input_pin"],"initial_time":initial.to_record(),"final_time":final_time.to_record(),"inputs":inputs.iter().map(hash).collect::<Vec<_>>()});
        let performance = boundary(self.owners.account.performance(&initial))?.record();
        let equity_points = equity_points(inputs, &performance)?;
        let result = self
            .owners
            .assemble_transcript(
                &manifest,
                &json!({"schema_version":1,"status":"COMPLETED","reason":null}),
                TranscriptParts {
                    source,
                    reconciliation,
                    runtime_performance: performance,
                    facts,
                    trades,
                },
            )?
            .into_record();
        if result["run"]["status"] != "COMPLETED" {
            return Err(err("MEMORY_ECONOMIC_COMPLETION_REFUSED"));
        }
        Ok(CompletedWorkingState {
            state: self.owners.state_data(),
            result,
            account_checkpoint: boundary(self.owners.account.checkpoint_record())?.0,
            equity_points,
        })
    }
}
// Project the Account owner's actual complete timeline once. This is the same
// prefix/high-water/drawdown relation used by the existing result reader, with
// Account's own drawdown reducer and final summary as the numerical authority.
pub(crate) fn equity_points<'a>(
    inputs: impl IntoIterator<Item = &'a Value>,
    performance: &Value,
) -> Result<Vec<Value>, Error> {
    use onlyalpha_domain::numeric::OnlyDecimal;
    let number = |v: &Value| -> Result<OnlyDecimal, Error> {
        boundary(
            v.as_str()
                .ok_or_else(|| err("RESULT_ACCOUNT_DECIMAL"))?
                .parse(),
        )
    };
    let causes = inputs
        .into_iter()
        .enumerate()
        .map(|(i, v)| (hash(v), i as u64 + 1))
        .collect::<BTreeMap<_, _>>();
    let mut peak = number(&performance["summary"]["initial_equity"])?;
    let mut maximum: Option<OnlyDecimal> = None;
    let mut previous = 0;
    let mut points = Vec::new();
    for (index, point) in performance["timeline"]
        .as_array()
        .filter(|v| !v.is_empty())
        .ok_or_else(|| err("RESULT_ACCOUNT_TIMELINE"))?
        .iter()
        .enumerate()
    {
        let prefix = if index == 0 {
            if point["source"] != "ACCOUNT_CREATED" {
                return Err(err("RESULT_ACCOUNT_GENESIS"));
            }
            0
        } else {
            *causes
                .get(
                    point["provenance"]["upstream_cause"]
                        .as_str()
                        .ok_or_else(|| err("RESULT_ACCOUNT_CAUSE"))?,
                )
                .ok_or_else(|| err("RESULT_ACCOUNT_CAUSE"))?
        };
        if prefix < previous {
            return Err(err("RESULT_ACCOUNT_PREFIX"));
        }
        previous = prefix;
        let nav = number(&point["snapshot"]["equity"])?;
        if nav > peak {
            peak = nav.clone();
        }
        let drawdown = boundary(onlyalpha_account::equity_drawdown(&nav, &peak))?;
        if let Some(d) = &drawdown
            && maximum.as_ref().is_none_or(|m| d < m)
        {
            maximum = Some(d.clone());
        }
        points.push(json!({"execution_prefix":prefix,"account_sequence":point["account_sequence"],"nav":nav.to_string(),"high_water_mark":peak.to_string(),"drawdown":drawdown.map(|d|d.to_string())}));
    }
    let expected = if performance["summary"]["maximum_drawdown"].is_null() {
        None
    } else {
        Some(number(&performance["summary"]["maximum_drawdown"])?)
    };
    if maximum != expected
        || number(
            &points
                .last()
                .ok_or_else(|| err("RESULT_ACCOUNT_TIMELINE"))?["nav"],
        )? != number(&performance["summary"]["final_equity"])?
    {
        return Err(err("RESULT_ACCOUNT_SUMMARY"));
    }
    Ok(points)
}

#[cfg(test)]
#[path = "tests/working_state_tests.rs"]
mod tests;
