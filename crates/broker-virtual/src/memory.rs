//! Finite exclusive venue/source/protocol owners. No file, external dispatch
//! permission, or caller-provided completeness token enters this boundary.
use crate::{VirtualBroker, plan::err};
use onlyalpha_broker::source::{
    SourceHistory, SourceStep, SourceTimeline, source_fact_link, source_step_digest,
};
use onlyalpha_broker::*;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::OnlyInstrumentId,
    market::OnlyBar,
    value::{OnlyMoney, OnlyPrice},
};
use serde_json::{Value, json};
struct Source {
    venue: VirtualBroker,
    timeline: SourceTimeline,
    healthy: bool,
    bytes: usize,
    opens: std::collections::BTreeMap<u64, String>,
    bars: std::collections::BTreeMap<u64, String>,
    trace: Vec<SourceTrace>,
}
/// Causal source inputs retain original commands and born facts. Bars refer to
/// the frozen market input by sequence and canonical content, without a second
/// copy of the complete market dataset or per-step component checkpoints.
#[derive(Debug)]
pub enum SourceAction {
    Clock(Value),
    Open {
        sequence: u64,
        at: i64,
        instrument: OnlyInstrumentId,
        price: OnlyPrice,
    },
    Bar {
        sequence: u64,
        fingerprint: String,
    },
    Dispatch {
        ready: bool,
        command: Value,
    },
    Published {
        identity: String,
        fingerprint: String,
    },
}
pub struct SourceTrace {
    sequence: u64,
    previous: String,
    fingerprint: String,
    action: SourceAction,
    facts: Vec<(Fact, Value)>,
    protocol: Option<String>,
    dispatch: Option<Value>,
}
impl SourceTrace {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn bar_reference(&self) -> Option<(u64, &str)> {
        match &self.action {
            SourceAction::Bar {
                sequence,
                fingerprint,
            } => Some((*sequence, fingerprint)),
            _ => None,
        }
    }
    pub fn record(&self) -> Value {
        let action = match &self.action {
            SourceAction::Clock(at) => json!({"kind":"CLOCK","at":at}),
            SourceAction::Open {
                sequence,
                at,
                instrument,
                price,
            } => {
                json!({"kind":"OPEN", "sequence":sequence, "bar_start":at, "instrument":instrument.to_record(), "open":price.to_record()})
            }
            SourceAction::Bar {
                sequence,
                fingerprint,
            } => json!({"kind":"BAR_REFERENCE","sequence":sequence,"content":fingerprint}),
            SourceAction::Dispatch { ready, command } => {
                json!({"kind":"COMMAND","ready":ready,"command":command})
            }
            SourceAction::Published {
                identity,
                fingerprint,
            } => json!({"kind":"PUBLISHED","identity":identity,"content":fingerprint}),
        };
        json!({"schema_version":1,"sequence":self.sequence,"previous":self.previous,"hash":self.fingerprint,"action":action,"born":self.facts.iter().map(|(f,at)|json!({"fact":f.record(),"stream_at":at})).collect::<Vec<_>>(),"protocol":self.protocol,"dispatch":self.dispatch})
    }
}
impl Source {
    fn step(&mut self, input: Value, witness: Option<String>) -> Result<(), Error> {
        self.apply(input, None, |_| witness)
    }
    fn apply(
        &mut self,
        input: Value,
        dispatch: Option<Value>,
        witness: impl FnOnce(&VirtualBroker) -> Option<String>,
    ) -> Result<(), Error> {
        if !self.healthy {
            return Err(err("VIRTUAL_MEMORY_FAILED"));
        }
        self.healthy = false;
        let bytes = self
            .bytes
            .checked_add(input.to_string().len())
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or_else(|| err("VIRTUAL_MEMORY_BUDGET"))?;
        let previous = self.timeline.head().to_owned();
        let sequence = self
            .timeline
            .sequence()
            .checked_add(1)
            .ok_or_else(|| err("VIRTUAL_SOURCE_SEQUENCE"))?;
        let start = self.venue.state.facts.len();
        self.venue.apply_bound_input(&input)?;
        let witness = witness(&self.venue);
        let born = self.venue.state.facts[start..]
            .iter()
            .cloned()
            .zip(self.venue.state.stream_at[start..].iter().map(|n| json!(n)))
            .collect::<Vec<_>>();
        let mut outputs = String::new();
        for (fact, at) in &born {
            outputs = source_fact_link(&outputs, fact, at);
        }
        let hash = source_step_digest(
            &previous,
            sequence,
            &input,
            born.len() as u64,
            &outputs,
            witness.as_deref(),
        );
        let action = match input[0].as_str() {
            Some("CLOCK") => SourceAction::Clock(input[1].clone()),
            Some("OPEN") => {
                let (sequence, at, instrument, price) = crate::decode_open(&input)?;
                SourceAction::Open {
                    sequence,
                    at,
                    instrument,
                    price,
                }
            }
            Some("BAR") => SourceAction::Bar {
                sequence: input[1]
                    .as_u64()
                    .ok_or_else(|| err("VIRTUAL_SOURCE_SEQUENCE"))?,
                fingerprint: digest(&input[2]),
            },
            Some("COMMAND" | "NOT_READY") => SourceAction::Dispatch {
                ready: input[0] == "COMMAND",
                command: input[1].clone(),
            },
            Some("PUBLISHED") => SourceAction::Published {
                identity: input[1]
                    .as_str()
                    .ok_or_else(|| err("VIRTUAL_SOURCE_INPUT"))?
                    .into(),
                fingerprint: input[2]
                    .as_str()
                    .ok_or_else(|| err("VIRTUAL_SOURCE_INPUT"))?
                    .into(),
            },
            _ => return Err(err("VIRTUAL_SOURCE_INPUT")),
        };
        let trace = SourceTrace {
            sequence,
            previous: previous.clone(),
            fingerprint: hash.clone(),
            action,
            facts: born.clone(),
            protocol: witness.clone(),
            dispatch: dispatch.map(|mut original| {
                original["outcome"] = json!(if self.venue.state.rejected.contains(
                    input[1]["command_id"]
                        .as_str()
                        .expect("validated source command")
                ) {
                    "REJECTED"
                } else {
                    "RECEIVED"
                });
                original
            }),
        };
        let bytes = bytes
            .checked_add(trace.record().to_string().len())
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or_else(|| err("VIRTUAL_MEMORY_BUDGET"))?;
        self.timeline.accept_step(
            SourceStep {
                sequence,
                previous: &previous,
                input: &input,
                fact_count: born.len() as u64,
                hash: &hash,
                protocol_hash: witness.as_deref(),
            },
            &born,
        )?;
        self.trace.push(trace);
        self.bytes = bytes;
        self.healthy = true;
        Ok(())
    }
}
impl TradingPort for Source {
    fn capabilities(&self) -> Capabilities {
        self.venue.capabilities()
    }
    fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult, Error> {
        Err(err("VIRTUAL_SOURCE_ORIGINAL_DISPATCH_REQUIRED"))
    }
    fn check_dispatch(&self, intent: &ReadyIntent) -> Result<(), Error> {
        if !self.healthy {
            return Err(err("VIRTUAL_MEMORY_FAILED"));
        }
        let command = BrokerCommand::decode(&intent.record()["command"])?;
        source::check_admission_clock(
            command.scope(),
            &json!(["CLOCK", self.venue.now()]),
            intent
                .admitted_at()
                .ok_or_else(|| err("VIRTUAL_SOURCE_ADMISSION_REQUIRED"))?,
        )
    }
    fn dispatch_observed(
        &mut self,
        command: &BrokerCommand,
        original: &DispatchObservation,
    ) -> Result<DispatchResult, Error> {
        let record = original.record();
        if original.command() != command
            || record["scope"] != command.scope().record()
            || record["event"]["kind"] != "DISPATCHED"
            || record["event"]["command_id"] != command.id()
        {
            return Err(err("VIRTUAL_SOURCE_ORIGINAL_DISPATCH_REQUIRED"));
        }
        let admission = original
            .admitted_at()
            .ok_or_else(|| err("VIRTUAL_SOURCE_ADMISSION_REQUIRED"))?;
        source::check_admission_clock(
            command.scope(),
            &json!(["CLOCK", self.venue.now()]),
            admission,
        )?;
        let ready = self.venue.connection == Connection::Ready;
        let kind = if ready { "COMMAND" } else { "NOT_READY" };
        let witness = digest(&json!([record["hash"], admission]));
        let input = json!([kind, command.record()]);
        self.apply(
            input,
            Some(json!({"record":record,"admitted_at":admission})),
            |venue| {
                let outcome = if venue.state.rejected.contains(command.id()) {
                    "REJECTED"
                } else {
                    "RECEIVED"
                };
                Some(digest(&json!([witness, outcome])))
            },
        )?;
        let outcome = if self.venue.state.rejected.contains(command.id()) {
            "REJECTED"
        } else {
            "RECEIVED"
        };
        Ok(if outcome == "REJECTED" {
            DispatchResult::Rejected
        } else {
            DispatchResult::Received
        })
    }
}
pub struct MemoryVirtualActor {
    source: Source,
    broker: MemoryBroker,
    scope: Scope,
}
pub struct CompletedMemoryVenue {
    protocol: CompletedMemoryBroker,
    source: String,
    trace: Vec<SourceTrace>,
}
impl CompletedMemoryVenue {
    pub fn protocol(&self) -> &Value {
        self.protocol.summary()
    }
    pub fn source_fingerprint(&self) -> &str {
        &self.source
    }
    pub fn protocol_records(&self) -> &[Record] {
        self.protocol.records()
    }
    pub fn source_trace(&self) -> &[SourceTrace] {
        &self.trace
    }
}
impl MemoryVirtualActor {
    pub fn new(
        scope: Scope,
        artifact: &str,
        cash: OnlyMoney,
        config: &Value,
        expected: &str,
    ) -> Result<Self, Error> {
        let venue = VirtualBroker::new(scope.clone(), artifact, cash, config)?;
        let broker = MemoryBroker::new(scope.clone(), venue.source_binding(), expected, 65536)?;
        let timeline = SourceTimeline::new(scope.clone(), venue.source_binding(), expected)?;
        Ok(Self {
            source: Source {
                venue,
                timeline,
                healthy: true,
                bytes: 0,
                opens: std::collections::BTreeMap::new(),
                bars: std::collections::BTreeMap::new(),
                trace: Vec::new(),
            },
            broker,
            scope,
        })
    }
    pub fn connect(&mut self) -> Result<Connection, Error> {
        let c = self.source.venue.connect()?;
        self.broker.set_connection(c);
        Ok(c)
    }
    pub fn authenticate(&mut self) -> Result<Connection, Error> {
        let c = self.source.venue.authenticate()?;
        self.source.venue.account(&self.scope)?;
        self.broker.set_connection(c);
        self.broker.set_health(true, true, true);
        Ok(c)
    }
    pub fn now(&self) -> i64 {
        self.source.venue.now()
    }
    pub fn advance(&mut self, at: i64) -> Result<(), Error> {
        self.source.step(json!(["CLOCK", at]), None)
    }
    pub fn on_open(
        &mut self,
        sequence: u64,
        bar_start: i64,
        instrument: &OnlyInstrumentId,
        open: &OnlyPrice,
    ) -> Result<(), Error> {
        if !self.source.healthy {
            return Err(err("VIRTUAL_MEMORY_FAILED"));
        }
        let input = json!([
            "OPEN",
            sequence,
            bar_start,
            instrument.to_record(),
            open.to_record()
        ]);
        let fingerprint = digest(&input);
        if let Some(original) = self.source.opens.get(&sequence) {
            if original == &fingerprint {
                return Ok(());
            }
            self.source.healthy = false;
            return Err(err("VIRTUAL_OPEN_CONFLICT"));
        }
        self.source.step(input, None)?;
        self.source.opens.insert(sequence, fingerprint);
        Ok(())
    }
    pub fn on_bar(&mut self, sequence: u64, bar: &OnlyBar) -> Result<(), Error> {
        if !self.source.healthy {
            return Err(err("VIRTUAL_MEMORY_FAILED"));
        }
        let fingerprint = digest(&bar.to_record());
        if let Some(original) = self.source.bars.get(&sequence) {
            if original == &fingerprint {
                return Ok(());
            }
            self.source.healthy = false;
            return Err(err("VIRTUAL_BAR_CONFLICT"));
        }
        self.source
            .step(json!(["BAR", sequence, bar.to_record()]), None)?;
        self.source.bars.insert(sequence, fingerprint);
        Ok(())
    }
    pub fn dispatch(
        &mut self,
        runtime: &impl FiniteRuntimeReader,
        command: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        self.broker.dispatch(runtime, &mut self.source, command)
    }
    pub fn publish(&mut self) -> Result<usize, Error> {
        let mut count = 0;
        while let Some((_, index)) = self.source.venue.next_publication() {
            let fact = self.source.venue.state.facts[index].clone();
            self.broker.ingest(std::slice::from_ref(&fact))?;
            let original = self.broker.original().observed(fact.identity())?;
            let witness = digest(&json!([original.source()["hash"], Value::Null]));
            self.source.step(
                json!(["PUBLISHED", fact.identity(), fact.fingerprint()]),
                Some(witness),
            )?;
            self.source.timeline.observe(&fact)?;
            count += 1;
        }
        Ok(count)
    }
    pub fn pending(&self) -> &[Fact] {
        self.broker.pending()
    }
    pub fn broker(&self) -> &MemoryBroker {
        &self.broker
    }
    pub fn acknowledge(
        &mut self,
        runtime: &impl FiniteRuntimeReader,
        id: &str,
    ) -> Result<(), Error> {
        self.broker.acknowledge(runtime, id)
    }
    pub fn funding_history(&self, boundary: u64, visible: u64) -> Result<SourceHistory, Error> {
        if !self.source.healthy {
            return Err(err("VIRTUAL_MEMORY_FAILED"));
        }
        self.source.timeline.funding_history(boundary, visible)
    }
    pub fn finish(self) -> Result<CompletedMemoryVenue, Error> {
        if !self.source.healthy || !self.source.venue.state.finite_quiescent() {
            return Err(err("VIRTUAL_MEMORY_NOT_DRAINED"));
        }
        Ok(CompletedMemoryVenue {
            source: self.source.timeline.head().into(),
            protocol: self.broker.finish()?,
            trace: self.source.trace,
        })
    }
}
