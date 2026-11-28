use super::backtest::{
    MarketInput, NextOpenModel, NextOpenPolicy, OpeningInput, next_open::context,
    trading::valuation_input,
};
use super::execution::{Admission, EconomicOwner, FiniteEconomicOwner};
use super::{Result, boundary, error};
use crate::{CompletedSession, RunConfiguration, Session, TradingInput};
use onlyalpha_broker::{
    ApplicationReceipt, BrokerCommand, Fact, FiniteRuntimeReader, ObservedFact, OrderView, Scope,
    SimulationIntent,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    numeric::OnlyDecimal,
    strategy::{OrderIntent, ReadonlyAccountState, ReadonlyPosition},
    time::OnlyTimestamp,
    value::OnlyPrice,
};
use serde_json::{Value, json};

struct AdmittedOpening {
    opening: OpeningInput,
    price: OnlyPrice,
    context: Value,
    payload: Value,
    command: BrokerCommand,
    output: Value,
    accepted: Option<Value>,
}

pub struct FiniteSessionOwner {
    session: Session,
    scope: Scope,
    model: NextOpenModel,
    policy: Box<dyn NextOpenPolicy>,
    prepared: Option<(OpeningInput, Value)>,
    admitted: Option<AdmittedOpening>,
    result: Option<Value>,
    observation_failed: bool,
}

fn decimal(value: &Value) -> Result<OnlyDecimal> {
    value
        .as_str()
        .ok_or_else(|| error("FINITE_ACCOUNT_DECIMAL"))?
        .parse()
        .map_err(boundary)
}

impl FiniteSessionOwner {
    pub(crate) fn new(
        session: Session,
        scope: Scope,
        model: NextOpenModel,
        policy: Box<dyn NextOpenPolicy>,
    ) -> Result<Self> {
        let cfg = session.configuration().record();
        let mut binding = model.binding();
        binding
            .as_object_mut()
            .ok_or_else(|| error("NEXT_OPEN_BINDING"))?
            .remove("execution_model");
        if session.sequence() != 0
            || scope.record()["runtime_kind"] != "BACKTEST"
            || cfg["schema_version"] == 3
            || [
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
            ]
            .iter()
            .any(|k| cfg[*k] != scope.record()[*k])
            || binding != policy.binding()
            || binding["configuration"] != session.configuration().fingerprint()
        {
            return Err(error("FINITE_OWNER_BINDING"));
        }
        Ok(Self {
            session,
            scope,
            model,
            policy,
            prepared: None,
            admitted: None,
            result: None,
            observation_failed: false,
        })
    }

    pub(crate) fn session(&self) -> &Session {
        &self.session
    }
    pub(crate) fn model(&self) -> &NextOpenModel {
        &self.model
    }
    pub(crate) fn policy(&self) -> &dyn NextOpenPolicy {
        self.policy.as_ref()
    }

    fn ensure_active(&self) -> Result<()> {
        if self.observation_failed {
            return Err(error("FINITE_OBSERVATION_FAILED"));
        }
        Ok(())
    }

    pub(crate) fn prepare_open(&mut self, opening: &OpeningInput, signal: &Value) -> Result<()> {
        self.ensure_active()?;
        if self.prepared.is_some() || self.admitted.is_some() || self.result.is_some() {
            return Err(error("FINITE_OPEN_PENDING"));
        }
        self.model.opening_terms(opening, signal)?;
        if self.session.configuration().record()["instruments"][0]["id"]
            != opening.instrument_id().to_string()
        {
            return Err(error("FINITE_OPEN_INSTRUMENT"));
        }
        self.prepared = Some((opening.clone(), signal.clone()));
        Ok(())
    }

    pub(crate) fn take_open_result(&mut self) -> Result<Value> {
        self.ensure_active()?;
        self.result
            .take()
            .ok_or_else(|| error("FINITE_OPEN_INCOMPLETE"))
    }

    pub(crate) fn drain_events(&mut self) -> Result<Vec<Value>> {
        let pending = self.session.pending_events()?.to_vec();
        let mut rows = Vec::with_capacity(pending.len());
        for event in pending {
            rows.push(event.record());
            self.session.acknowledge(event.sequence())?;
        }
        Ok(rows)
    }

    pub(crate) fn valuation(&mut self, binding: &Value, input: &MarketInput) -> Result<()> {
        self.ensure_active()?;
        if self.admitted.is_some() || self.prepared.is_some() {
            return Err(error("FINITE_OPEN_INCOMPLETE"));
        }
        let raw = input.bar().to_record();
        let ctx = context(&input.identity(), input.event_ns(), &raw["trading_day"])?;
        let now = ctx["time"]
            .as_u64()
            .ok_or_else(|| error("FINITE_VALUATION_TIME"))?;
        if let Some(value) =
            valuation_input(binding, input, now, &self.session, ctx["day_index"].clone())?
        {
            self.session.apply(&TradingInput::from_record(value)?)?;
        }
        Ok(())
    }

    pub(crate) fn finish(
        self,
        start: i64,
        end: i64,
    ) -> Result<(CompletedSession, Box<dyn NextOpenPolicy>)> {
        self.ensure_active()?;
        if self.admitted.is_some() || self.prepared.is_some() || self.result.is_some() {
            return Err(error("FINITE_OPEN_INCOMPLETE"));
        }
        Ok((self.session.finish_between(start, end)?, self.policy))
    }

    pub(crate) fn apply_observed(&mut self, observed: &ObservedFact) -> Result<()> {
        self.ensure_active()?;
        self.observation_failed = true;
        self.apply_observation(observed)?;
        self.observation_failed = false;
        Ok(())
    }

    fn apply_observation(&mut self, observed: &ObservedFact) -> Result<()> {
        let fact = observed.fact();
        if self
            .session
            .simulation_receipt(fact)
            .map_err(boundary)?
            .is_some()
        {
            return Ok(());
        }
        let current = self
            .admitted
            .as_mut()
            .ok_or_else(|| error("FINITE_ORDER_MISSING"))?;
        let record = fact.record();
        if fact.scope() != self.scope
            || observed.intent().record()["command"] != current.command.record()
            || fact.order() != Some(current.command.order())
            || record["ts_event"] != current.context["time"]
            || record["ts_init"] != current.context["time"]
        {
            return Err(error("FINITE_VENUE_RELATION"));
        }
        let identity = current.opening.identity();
        let order = current.command.order();
        match record["kind"].as_str() {
            Some("ACCEPTED") if current.accepted.is_none() => {
                let submission = self.model.request(
                    self.session.sequence() + 1,
                    &identity,
                    &current.context,
                    "SUBMISSION",
                    json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),
                );
                self.session
                    .apply(&TradingInput::from_record(submission)?)?;
                let payload = json!({"schema_version":1,"order":order,"venue_order":record["payload"]["venue"]});
                let mut input = self.model.request(
                    self.session.sequence() + 1,
                    &identity,
                    &current.context,
                    "ACCEPT",
                    payload,
                );
                input["broker_record"] = record.clone();
                self.session
                    .apply_cash_venue(&TradingInput::from_record(input)?, observed)?;
                current.accepted = Some(record);
            }
            Some("TRADE") if current.accepted.is_some() => {
                let accepted = current.accepted.as_ref().expect("accepted opening");
                let fill = &record["payload"]["fill"];
                if fill["price"] != current.price.to_record()
                    || fill["reference_price"] != current.opening.price().to_record()
                    || fill["quantity"] != self.model.quantity.to_record()
                    || fill["venue_order_id"]["value"] != accepted["payload"]["venue"]
                    || fill["ts_event"]["unix_nanos"] != current.context["time"]
                    || fill["ts_init"]["unix_nanos"] != current.context["time"]
                {
                    return Err(error("FINITE_FILL_TERMS"));
                }
                let snapshot = self.session.order(&self.model.cluster, order)?;
                if snapshot["fee_policy_binding"] != current.payload["fee_contract"]["binding"] {
                    return Err(error("FILL_FEE_BINDING"));
                }
                let mut ctx = current.context.clone();
                ctx["trade"] = fill["trade_id"]["value"].clone();
                let evidence =
                    self.policy
                        .fill(&snapshot, &current.price, &self.model.quantity, &ctx)?;
                self.model
                    .verify_notional(&current.price, &evidence["gross_notional"])?;
                let n = self.session.sequence() + 1;
                let payload = self.model.fill_payload(
                    &current.opening,
                    &current.price,
                    &ctx,
                    &current.payload,
                    &evidence,
                    n,
                    fill,
                )?;
                let mut input = self
                    .model
                    .request(n, &identity, &current.context, "FILL", payload);
                input["broker_record"] = record.clone();
                self.session
                    .apply_cash_venue(&TradingInput::from_record(input)?, observed)?;
                current.output["status"] = json!("FILLED");
                current.output["order"] = json!(order);
                current.output["trade"] = ctx["trade"].clone();
                current.output["economic_evidence"] = evidence;
                current.output["venue_facts"] = json!([accepted, record]);
                self.result = self.admitted.take().map(|open| open.output);
            }
            _ => return Err(error("FINITE_VENUE_OUT_OF_ORDER")),
        }
        Ok(())
    }
}

impl EconomicOwner for FiniteSessionOwner {
    fn scope(&self) -> &Scope {
        &self.scope
    }
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState> {
        let account = self.session.account_snapshot()?;
        let book = self.session.position_order_view()?;
        let mut positions = Vec::new();
        for allocation in book["position_allocations"]
            .as_array()
            .ok_or_else(|| error("FINITE_POSITION"))?
        {
            if allocation["cluster"] != self.model.cluster {
                return Err(error("FINITE_POSITION_SCOPE"));
            }
            let snapshot = &allocation["snapshot"];
            let qty = decimal(&snapshot["quantity"])?;
            if !qty.is_zero() {
                let instrument = allocation["instrument"]
                    .as_str()
                    .ok_or_else(|| error("FINITE_POSITION"))?
                    .parse()
                    .map_err(boundary)?;
                let average = if snapshot["average"].is_null() {
                    None
                } else {
                    Some(decimal(&snapshot["average"])?)
                };
                positions.push(ReadonlyPosition::new(instrument, qty, average).map_err(boundary)?);
            }
        }
        ReadonlyAccountState::new(
            at.clone(),
            decimal(&account["trade_available"])?,
            decimal(&account["equity"])?,
            positions,
        )
        .map_err(boundary)
    }
    fn admit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Admission> {
        self.ensure_active()?;
        let (opening, signal) = self
            .prepared
            .as_ref()
            .ok_or_else(|| error("FINITE_OPEN_REQUIRED"))?;
        if at.unix_nanos() != &opening.event_ns()
            || intent.instrument() != opening.instrument_id()
            || signal["side"] != intent.side().as_str()
            || signal["decision_identity"] != intent.reason_code()
            || intent.order_type().as_str() != "MARKET"
            || intent.time_in_force().as_str() != "GTC"
            || intent.limit_price().is_some()
            || intent.quantity() != self.model.quantity.value()
        {
            return Err(error("FINITE_INTENT_MISMATCH"));
        }
        let book = self.session.position_order_view()?;
        let positions = self.account(at)?;
        let held = positions.positions();
        if book["active_order_ids"]
            .as_array()
            .is_none_or(|v| !v.is_empty())
            || !match intent.side().as_str() {
                "BUY" => held.is_empty(),
                "SELL" => {
                    held.len() == 1
                        && held[0].instrument() == intent.instrument()
                        && held[0].quantity() == intent.quantity()
                }
                _ => false,
            }
        {
            return Err(error("SIGNAL_POSITION_CONFLICT"));
        }
        let (price, ctx) = self.model.opening_terms(opening, signal)?;
        let cause = ctx["cause"].as_str().ok_or_else(|| error("FINITE_CAUSE"))?;
        let request = self.model.order_request(opening, signal, cause)?;
        let preview = self.session.fee_order_preview(
            &self.model.cluster,
            &request,
            ctx["time"]
                .as_u64()
                .ok_or_else(|| error("FINITE_OPEN_TIME"))?,
        )?;
        let admission = self.policy.admission(&preview, &price, &ctx)?;
        let proof = &admission["market_provenance"];
        if admission["schema_version"] != 1
            || proof["kind"] != "MODEL_RULE_DECISION"
            || proof["reference_policy"] != "MODEL_NEXT_OPEN"
            || proof["venue_acceptance_proven"] != false
        {
            return Err(error("MODEL_ADMISSION_PROOF"));
        }
        let mut output = json!({"schema_version":1,"signal":signal,"opening":opening.record(),"execution_price":price.to_record(),"admission":admission});
        let mut command = None;
        match (admission["accepted"].as_bool(), proof["verdict"].as_str()) {
            (Some(false), Some("MODEL_REJECT"))
                if admission["reason"].as_str().is_some_and(|s| !s.is_empty()) =>
            {
                output["status"] = json!("REJECTED");
                output["reason"] = admission["reason"].clone();
                self.result = Some(output);
            }
            (Some(true), Some("MODEL_ACCEPT")) => {
                self.model.verify_settlement_policy(&admission)?;
                self.model.verify_notional(&price, &admission["notional"])?;
                let order = preview["order_id"]["value"]
                    .as_str()
                    .ok_or_else(|| error("FINITE_ORDER_ID"))?;
                let payload = self
                    .model
                    .admit_payload(&request, order, cause, &price, &admission);
                let input = self.model.request(
                    self.session.sequence() + 1,
                    &opening.identity(),
                    &ctx,
                    "ADMIT",
                    payload.clone(),
                );
                let verdict = self
                    .session
                    .apply(&TradingInput::from_record(input)?)
                    .map(|_| ());
                if let Some(reason) =
                    self.model
                        .admission_rejection(verdict, &signal["side"], &admission, || {
                            self.session.state()
                        })?
                {
                    output["status"] = json!("REJECTED");
                    output["reason"] = json!(reason);
                    self.result = Some(output);
                } else {
                    let snapshot = self.session.order(&self.model.cluster, order)?;
                    let submit = BrokerCommand::decode(&json!({"schema_version":1,"scope":self.scope.record(),"operation":"SUBMIT","command_id":format!("SUBMIT-{cause}"),"order":order,"client":snapshot["client_order_id"]["value"],"request":request})).map_err(boundary)?;
                    self.session.simulation_intent(&submit).map_err(boundary)?;
                    command = Some(submit.clone());
                    self.admitted = Some(AdmittedOpening {
                        opening: opening.clone(),
                        price,
                        context: ctx,
                        payload,
                        command: submit,
                        output,
                        accepted: None,
                    });
                }
            }
            _ => return Err(error("MODEL_ADMISSION_PROOF")),
        }
        self.prepared = None;
        Ok(Admission {
            facts: Vec::new(),
            command,
        })
    }
    fn apply_venue(&mut self, _: &Fact) -> Result<()> {
        Err(error("MEMORY_ORIGINAL_VENUE_REQUIRED"))
    }
}

impl FiniteRuntimeReader for FiniteSessionOwner {
    fn simulation_intent(
        &self,
        command: &BrokerCommand,
    ) -> std::result::Result<SimulationIntent, onlyalpha_broker::Error> {
        self.ensure_active()
            .map_err(|e| onlyalpha_broker::Error::new(&e.0))?;
        if self
            .admitted
            .as_ref()
            .is_none_or(|pending| pending.command.record() != command.record())
        {
            return Err(onlyalpha_broker::Error::new(
                "FINITE_ORIGINAL_COMMAND_MISMATCH",
            ));
        }
        self.session.simulation_intent(command)
    }
    fn simulation_order(
        &self,
        command: &BrokerCommand,
    ) -> std::result::Result<Option<OrderView>, onlyalpha_broker::Error> {
        self.session.simulation_order(command)
    }
    fn simulation_receipt(
        &self,
        fact: &Fact,
    ) -> std::result::Result<Option<ApplicationReceipt>, onlyalpha_broker::Error> {
        self.session.simulation_receipt(fact)
    }
}
impl FiniteEconomicOwner for FiniteSessionOwner {
    fn configuration(&self) -> &RunConfiguration {
        self.session.configuration()
    }
}

#[cfg(test)]
#[path = "../tests/finite_owner.rs"]
mod tests;
