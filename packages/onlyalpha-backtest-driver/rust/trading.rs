//! Actual native Pipeline/Strategy with passive Python plugin world and canonical Execution.
use crate::{Candidate, Error, MarketInput, Participants, boundary, err, fields, hash};
use onlyalpha_calculation_worker::{StrategyPreparation, Worker};
use onlyalpha_clock::BigInt;
use onlyalpha_domain::{base::OnlyDomainModel, execution::OnlyOrderRequest, time::OnlyTimestamp};
use onlyalpha_market_data_pipeline::{PipelineInput, construction::OnlyConstructionFact};
use onlyalpha_strategy::NodePort;
use serde_json::{Value, json};
use std::{collections::BTreeSet, sync::Arc, time::Duration};
const DEADLINE: Duration = Duration::from_secs(10);
pub struct Trading<C: NodePort> {
    preparation: StrategyPreparation<C>,
    worker: Worker,
    settings: Value,
    binding: Value,
    world: Value,
    fees: Value,
    next: usize,
    now: u64,
    effects: Vec<Value>,
}
impl<C: NodePort> Trading<C> {
    pub fn new(
        mut preparation: StrategyPreparation<C>,
        mut worker: Worker,
        mut settings: Value,
        initial_ns: BigInt,
    ) -> Result<Self, Error> {
        fields(
            &settings,
            &[
                "schema_version",
                "execution",
                "instrument",
                "maximum_fill_quantity",
                "requests",
            ],
        )?;
        let initial = boundary(preparation.capture_checkpoint())?;
        let program = preparation.strategy().program();
        let e = settings["execution"].clone();
        let instrument = boundary(onlyalpha_domain::instrument::OnlyInstrument::from_record(
            &settings["instrument"],
        ))?
        .to_record();

        let cluster = program.scope().cluster.value();
        let revision = program.revision().fingerprint();
        let sources = &initial["pipeline"]["program"]["sources"];
        if settings["schema_version"] != 1
            || e["runtime_kind"] != "BACKTEST"
            || e["engine"] != program.scope().engine.value()
            || e["runtime"] != program.scope().runtime.value()
            || e["generation"] != program.generation()
            || e["profiles"].as_object().is_none_or(|m| m.len() != 1)
            || e["profiles"][cluster]["revision"] != revision
            || e["instruments"].as_array().is_none_or(|v| v.len() != 1)
            || program.revision().universe().len() != 1
            || e["instruments"][0]["id"] != program.revision().universe()[0].to_string()
            || worker.binding() != (program.generation(), program.artifact())
            || sources.as_array().is_none_or(|s| s.len() != 1)
        {
            return Err(err("TRADING_CONTEXT"));
        }
        if instrument != settings["instrument"]
            || instrument["instrument_id"] != program.revision().universe()[0].to_record()
            || instrument["price_precision"] != e["instruments"][0]["price_precision"]
            || instrument["quantity_precision"] != e["instruments"][0]["quantity_precision"]
            || instrument["settlement_currency"] != e["currency"]
            || instrument["contract_multiplier"]["value"] != e["instruments"][0]["multiplier"]
            || instrument["market_type"] != "CASH"
        {
            return Err(err("TRADING_INSTRUMENT_CONTEXT"));
        }
        let now = boundary(initial_ns.to_string().parse::<u64>())?;
        let candidate = Candidate::new(e.clone(), vec![])?;
        let mut request_ids = BTreeSet::new();
        for v in settings["requests"]
            .as_array()
            .filter(|v| v.len() <= 16)
            .ok_or_else(|| err("POLICY_BOUND"))?
        {
            candidate.fee_order_preview(cluster, v, now)?;
            let request = boundary(OnlyOrderRequest::from_record(v))?;
            if !request_ids.insert(request.request_id().to_string())
                || request.instrument_id() != &program.revision().universe()[0]
            {
                return Err(err("POLICY_REQUEST_IDENTITY"));
            }
        }
        settings["calendar"] = sources[0]["calendar"].clone();
        let world=boundary(worker.exchange_replay(json!({"schema_version":1,"configuration":settings,"checkpoint":null,"operation":"INIT","payload":{},"now":now}),DEADLINE))?;
        world_proof(&world)?;
        let binding = json!({"schema_version":1,"configuration":hash(&e),"generation":program.generation(),"initial_ns":initial_ns.to_string(),"strategies":{cluster:revision},"sources":[program.source()],"program":program.to_record(),"pipeline":initial["pipeline"]["program"],"policy":settings});
        Ok(Self {
            preparation,
            worker,
            settings,
            binding,
            world,
            fees: json!({}),
            next: 0,
            now,
            effects: vec![],
        })
    }
    fn exchange(&mut self, operation: &str, payload: Value) -> Result<Value, Error> {
        let value=boundary(self.worker.exchange_replay(json!({"schema_version":1,"configuration":self.settings,"checkpoint":self.world["checkpoint"],"operation":operation,"payload":payload,"now":self.now}),DEADLINE))?;
        if matches!(operation, "INIT" | "VALIDATE" | "BAR" | "SUBMIT") {
            world_proof(&value)?;
        }
        Ok(value)
    }
    fn request(
        &self,
        c: &Candidate,
        input: &MarketInput,
        op: &str,
        payload: Value,
        cause: &str,
    ) -> Result<Value, Error> {
        let config = c.configuration();
        let program = self.preparation.strategy().program();
        let n = c.records().len() as u64 + 1;
        let id = format!(
            "REPLAY-{}",
            hash(
                &json!({"market":input.identity(),"cause":cause,"sequence":n,"op":op,"payload":payload,"program":self.binding})
            )
        );
        Ok(
            json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":"BACKTEST","cluster":program.scope().cluster.value(),"revision":program.revision().fingerprint(),"input_id":id,"source_ref":format!("CAUSE-{}",hash(&json!([input.identity(),cause,n,op]))),"time":self.now,"runtime_sequence":n,"trading_day":input.bar().to_record()["trading_day"],"day_index":self.world["day_index"],"op":op,"payload":payload}),
        )
    }
    fn apply_updates(
        &mut self,
        c: &mut Candidate,
        input: &MarketInput,
        cause: &str,
    ) -> Result<(), Error> {
        let updates = self.world["updates"]
            .as_array()
            .ok_or_else(|| err("BROKER_UPDATES"))?
            .clone();
        let cluster = self
            .preparation
            .strategy()
            .program()
            .scope()
            .cluster
            .value()
            .to_owned();
        for row in updates {
            let update = &row["update"];
            let order = update["order_id"]["value"]
                .as_str()
                .ok_or_else(|| err("BROKER_ORDER"))?;
            let config = c.configuration().clone();
            if update["runtime_id"]["value"] != config["runtime"]
                || update["account_id"]["value"] != config["account"]
                || update["gateway_id"]["value"] != config["gateway"]
                || update["ts_event"]["unix_nanos"] != self.now
            {
                return Err(err("BROKER_CONTEXT"));
            }
            let (op, payload) = match row["kind"].as_str().ok_or_else(|| err("BROKER_FAMILY"))? {
                "ACCEPT" => (
                    "ACCEPT",
                    json!({"schema_version":1,"order":order,"venue_order":update["venue_order_id"]["value"]}),
                ),
                "CANCELLED" | "REJECTED" | "EXPIRED" => (
                    "TERMINAL",
                    json!({"schema_version":1,"order":order,"outcome":row["kind"],"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
                ),
                "FILL" => {
                    let snapshot = c.order(&cluster, order)?;
                    let fill = &update["fill"];
                    if fill["order_id"]["value"] != order {
                        return Err(err("FILL_RELATION"));
                    }
                    let evidence = self.exchange(
                        "FEE",
                        json!({"order":snapshot,"fill":fill,"accrual":self.fees[order]}),
                    )?;
                    let trade = fill["trade_id"]["value"]
                        .as_str()
                        .ok_or_else(|| err("TRADE"))?;
                    let n = c.records().len() as u64 + 1;
                    let scope = json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":"BACKTEST","cluster":cluster,"revision":self.preparation.strategy().program().revision().fingerprint(),"instrument":input.bar().instrument_id().to_string(),"request":snapshot["request_id"]["value"]});
                    let reference = hash(&json!([input.identity(), row, evidence]));
                    let reference = format!("PLUGIN-{reference}");
                    let mut fee = json!({"schema_version":1,"instruction":format!("FEE-{reference}"),"source_ref":format!("FEE-{reference}"),"policy":snapshot["fee_policy_binding"]["fingerprint"],"order":order,"trade":trade,"currency":config["currency"],"charge_target":evidence["charge_target"],"rebate_target":evidence["rebate_target"]});
                    let mut settlement = json!({"schema_version":1,"instruction":format!("SET-{reference}"),"source_ref":format!("SET-{reference}"),"order":order,"trade":trade,"currency":config["currency"],"model":"CASH_SETTLEMENT","calendar":self.settings["calendar"],"policy":evidence["settlement_policy"],"gross_notional":evidence["gross_notional"],"rounding":"HALF_EVEN"});
                    let mut valuation = json!({"schema_version":1,"source_ref":format!("VAL-{reference}"),"currency":config["currency"],"mark":fill["price"]["value"]});
                    for (proof, family) in [
                        (&mut fee, "ORDER_FEE_ACCRUAL"),
                        (&mut settlement, "SETTLEMENT"),
                        (&mut valuation, "VALUATION"),
                    ] {
                        proof["scope"] = scope.clone();
                        proof["family"] = json!(family);
                        proof["version"] = json!(n);
                        proof["as_of_sequence"] = json!(n);
                        proof["source_digest"] = json!(hash(proof));
                    }
                    self.effects.push(json!({"fill":fill,"fee":evidence}));
                    self.fees[order] = evidence["accrual"].clone();
                    (
                        "FILL",
                        json!({"schema_version":1,"order":order,"trade":trade,"venue_trade":fill["venue_trade_id"]["value"],"venue_order":fill["venue_order_id"]["value"],"quantity":fill["quantity"]["value"],"price":fill["price"]["value"],"fees":fee,"settlement":settlement,"valuation":valuation,"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
                    )
                }
                _ => return Err(err("BROKER_FAMILY")),
            };
            let normalized = self.request(c, input, op, payload, &hash(&json!([cause, row])))?;
            c.apply(&normalized)?;
        }
        Ok(())
    }
    fn valuation(&self, c: &mut Candidate, input: &MarketInput) -> Result<(), Error> {
        let state = c.state()?;
        let positions = state["position"]["accounts"]
            .as_array()
            .ok_or_else(|| err("POSITION"))?;
        if positions.is_empty() {
            return Ok(());
        }
        let n = c.records().len() as u64 + 1;
        let marks=positions.iter().map(|p|{if p["instrument"]!=input.bar().instrument_id().to_string(){return Err(err("MARK_SOURCE"));}Ok(json!({"schema_version":1,"instrument":p["instrument"],"mark":input.bar().to_record()["close"]["value"],"source_ref":format!("BAR-{}",input.identity()),"family":"CLOSED_BAR","version":n,"time":self.now,"as_of_sequence":n}))}).collect::<Result<Vec<_>,Error>>()?;
        let payload = json!({"schema_version":1,"valuation":format!("VALUATION-{}",input.identity()),"version":n,"position_evidence":hash(&c.checkpoint()?["components"][1]),"economic_version":state["account"]["snapshot"]["economic_version"],"marks":marks});
        c.apply(&self.request(c, input, "VALUATION", payload, &input.identity())?)
    }
}
impl<C: NodePort> Participants for Trading<C> {
    fn binding(&self) -> Value {
        self.binding.clone()
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"binding":hash(&self.binding),"preparation":boundary(self.preparation.capture_checkpoint())?,"world":self.world,"fees":self.fees,"next":self.next,"now":self.now}),
        )
    }
    fn restore(&mut self, v: &Value) -> Result<(), Error> {
        fields(
            v,
            &[
                "schema_version",
                "binding",
                "preparation",
                "world",
                "fees",
                "next",
                "now",
            ],
        )?;
        if v["schema_version"] != 1
            || v["binding"] != hash(&self.binding)
            || v["next"].as_u64().is_none_or(|n| {
                n > self.settings["requests"]
                    .as_array()
                    .expect("requests")
                    .len() as u64
            })
        {
            return Err(err("TRADING_CHECKPOINT"));
        }
        boundary(self.preparation.restore_checkpoint(
            v["preparation"].to_string().as_bytes(),
            &hash(&v["preparation"]),
        ))?;
        self.world = v["world"].clone();
        self.now = v["now"].as_u64().ok_or_else(|| err("NOW"))?;
        let checked = self.exchange("VALIDATE", json!({}))?;
        if checked["checkpoint"] != self.world["checkpoint"]
            || checked["open_orders"] != self.world["open_orders"]
            || checked["pending"] != self.world["pending"]
        {
            return Err(err("BROKER_CHECKPOINT"));
        }
        self.fees = v["fees"].clone();
        self.next = usize::try_from(v["next"].as_u64().ok_or_else(|| err("NEXT"))?)
            .map_err(|_| err("BOUND"))?;
        Ok(())
    }
    fn process(&mut self, input: &MarketInput, c: &mut Candidate) -> Result<Value, Error> {
        self.effects.clear();
        if input.source() != self.preparation.strategy().program().source() {
            return Err(err("SOURCE_BINDING"));
        }
        self.now = boundary(input.event_ns().to_string().parse())?;
        self.world = self.exchange("BAR", json!({"bar":input.bar().to_record()}))?;
        self.apply_updates(c, input, &input.identity())?;
        self.valuation(c, input)?;
        let pipeline = PipelineInput {
            source: input.source().into(),
            sequence: input.sequence(),
            fact: OnlyConstructionFact::Bar(Arc::new(input.bar().clone())),
            logical_init: OnlyTimestamp::from_datetime(*input.bar().ts_init()),
            quality: vec![],
        };
        let processing = boundary(self.preparation.process(&pipeline))?;
        let mut policy = Value::Null;
        if let Some(request) = self.settings["requests"]
            .as_array()
            .expect("requests")
            .get(self.next)
            .cloned()
        {
            let decisions = processing["decisions"]
                .as_array()
                .ok_or_else(|| err("DECISIONS"))?;
            if decisions.len() > 1 {
                return Err(err("DECISION_BOUND"));
            }
            if let Some(outcome) = decisions.first() {
                let d = &outcome["decision"];
                let signal = if request["side"] == "BUY" {
                    "entry"
                } else {
                    "exit"
                };
                if d["eligibility"] == true
                    && d[signal] == true
                    && self.world["open_orders"]
                        .as_array()
                        .is_some_and(Vec::is_empty)
                {
                    let cluster = self
                        .preparation
                        .strategy()
                        .program()
                        .scope()
                        .cluster
                        .value()
                        .to_owned();
                    let preview = c.fee_order_preview(&cluster, &request, self.now)?;
                    let admission =
                        self.exchange("ADMISSION", json!({"order":preview,"state":c.state()?}))?;
                    if admission["schema_version"] != 1 || !admission["accepted"].is_boolean() {
                        return Err(err("ADMISSION_PROOF"));
                    }
                    policy = json!({"request":request,"decision":hash(d),"admission":admission});
                    if admission["accepted"] == true {
                        let order = preview["order_id"]["value"]
                            .as_str()
                            .ok_or_else(|| err("ORDER"))?
                            .to_owned();
                        let payload = json!({"schema_version":1,"request":request,"fee_contract":admission["contract"],"fee_budget":admission["fee_budget"],"market":{"schema_version":1,"verdict":"ACCEPT","source_ref":format!("MARKET-{}",hash(&json!([input.identity(),d,admission]))),"request_digest":hash(&request),"notional":admission["notional"],"rounding":"HALF_EVEN"},"order":order,"collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}});
                        let normalized = self.request(c, input, "ADMIT", payload, &hash(d))?;
                        match c.apply(&normalized) {
                            Ok(()) => {
                                self.next += 1;
                                let snapshot = c.order(&cluster, &order)?;
                                let ready = c
                                    .records()
                                    .last()
                                    .ok_or_else(|| err("ADMIT_RECORD"))?
                                    .prepared()
                                    .record();
                                let broker = json!({"schema_version":2,"gateway_request_id":{"schema_version":1,"value":format!("SUBMIT-{}",hash(&normalized))},"order_id":snapshot["order_id"],"client_order_id":snapshot["client_order_id"],"account_id":snapshot["account_id"],"instrument_id":snapshot["instrument_id"],"side":snapshot["side"],"offset":snapshot["offset"],"order_type":snapshot["order_type"],"time_in_force":snapshot["time_in_force"],"quantity":snapshot["quantity"],"price":snapshot["price"],"submitted_at":{"schema_version":1,"unix_nanos":self.now},"runtime_intent_transaction_id":ready["transaction_id"],"runtime_intent_authority_hash":hash(&ready),"execution_intent":snapshot["execution_intent"]});
                                self.world = self.exchange("SUBMIT", json!({"request":broker}))?;
                                c.apply(&self.request(c,input,"SUBMISSION",json!({"schema_version":1,"order":order,"outcome":"DISPATCHED"}),&hash(d))?)?;
                                self.apply_updates(c, input, &hash(d))?;
                            }
                            Err(e) if e.0 == "EXECUTION_RISK_DENIED" => {
                                policy["risk_denied"] = json!(true);
                            }
                            Err(e) => return Err(e),
                        }
                    }
                }
            }
        }
        Ok(
            json!({"schema_version":1,"preparation":processing,"policy":policy,"broker":self.world,"economic_evidence":self.effects}),
        )
    }
    fn quiescent(&self) -> Result<bool, Error> {
        let pending = self.world["pending"]
            .as_u64()
            .ok_or_else(|| err("BROKER_PENDING_PROOF"))?;
        let orders = self.world["open_orders"]
            .as_array()
            .ok_or_else(|| err("BROKER_OPEN_PROOF"))?;
        Ok(pending == 0 && orders.is_empty())
    }
}

fn world_proof(value: &Value) -> Result<(), Error> {
    fields(
        value,
        &[
            "schema_version",
            "checkpoint",
            "updates",
            "open_orders",
            "pending",
            "trading_day",
            "day_index",
        ],
    )?;
    if value["schema_version"] != 1
        || !value["checkpoint"].is_object()
        || value["updates"].as_array().is_none_or(|v| v.len() > 64)
        || value["open_orders"].as_array().is_none_or(|v| v.len() > 16)
        || value["pending"].as_u64().is_none()
    {
        return Err(err("BROKER_WORLD_PROOF"));
    }
    Ok(())
}
