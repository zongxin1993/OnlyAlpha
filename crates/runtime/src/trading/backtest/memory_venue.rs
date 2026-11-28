//! 冻结行情与内存虚拟券商的有限回测装配。
use super::{Error, Inputs, MarketInput, boundary, err, hash};
use crate::{
    MarketBar, ResearchPanel, RunConfiguration,
    trading::execution::{
        BacktestVenue, FiniteEconomicOwner, ObservationState, VenueFacts, VirtualVenue,
    },
};
use onlyalpha_broker::{BrokerCommand, CommandState, Fact, Scope};
use onlyalpha_broker_virtual::{CompletedMemoryVenue, MemoryVirtualActor};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    numeric::OnlyDecimal,
    value::{OnlyCurrency, OnlyMoney},
};
use serde_json::{Value, json};

pub struct MemoryBacktestVenue<'a> {
    scope: Scope,
    actor: MemoryVirtualActor,
    records: &'a [MarketInput],
    cursor: usize,
    configuration: String,
    snapshot: String,
    panel_content: String,
    terminal_at: i64,
    closed: bool,
}

impl<'a> MemoryBacktestVenue<'a> {
    pub fn input_fingerprint(panel: &ResearchPanel, inputs: &Inputs, terminal_at: i64) -> String {
        hash(&json!([
            "BACKTEST_VIRTUAL_MARKET_V1",
            panel.snapshot(),
            panel.content_digest(),
            inputs.fingerprint(),
            terminal_at
        ]))
    }

    pub fn new(
        configuration: &RunConfiguration,
        panel: &ResearchPanel,
        artifact: &str,
        venue_config: &Value,
        expected_source: &str,
        inputs: &'a Inputs,
        terminal_at: i64,
        expected_inputs: &str,
    ) -> Result<Self, Error> {
        let config = configuration.record();
        if config["runtime_kind"] != "BACKTEST" {
            return Err(err("VENUE_SCOPE"));
        }
        if !inputs.matches_snapshot(panel.snapshot())
            || Self::input_fingerprint(panel, inputs, terminal_at) != expected_inputs
        {
            return Err(err("VENUE_INPUT_BINDING"));
        }
        let records = inputs.records();
        if records.len() != panel.periods() * panel.instrument_count() {
            return Err(err("VENUE_BAR_COUNT"));
        }
        for (row, slice) in records.chunks_exact(panel.instrument_count()).enumerate() {
            for (leg, input) in slice.iter().enumerate() {
                let bar = input.bar();
                if bar.instrument_id() != &panel.instrument_ids()[leg]
                    || &input.event_ns() != panel.timestamps()[row].unix_nanos()
                {
                    return Err(err("VENUE_BAR_RELATION"));
                }
                let fields = &panel.instruments()[leg];
                for (field, raw) in [
                    ("open", bar.open().value()),
                    ("high", bar.high().value()),
                    ("low", bar.low().value()),
                    ("close", bar.close().value()),
                    ("volume", bar.volume().value()),
                ] {
                    if let Some(value) = fields.get(field).and_then(|column| column[row].as_ref()) {
                        if &boundary(value.to_string().parse::<OnlyDecimal>())? != raw {
                            return Err(err("VENUE_BAR_VALUE"));
                        }
                    }
                }
            }
        }
        if records
            .last()
            .is_some_and(|last| last.event_ns() > terminal_at.into())
        {
            return Err(err("VENUE_TERMINAL_TIME"));
        }
        let scope = boundary(Scope::decode(&json!({
            "engine":config["engine"], "runtime":config["runtime"], "gateway":config["gateway"],
            "account":config["account"], "generation":config["generation"], "runtime_kind":config["runtime_kind"],
        })))?;
        let currency = boundary(OnlyCurrency::from_record(&config["currency"]))?;
        let amount = config["initial_cash"]
            .as_str()
            .ok_or_else(|| err("VENUE_INITIAL_CASH"))?;
        let cash = boundary(OnlyMoney::new(boundary(amount.parse())?, currency))?;
        let mut actor = boundary(MemoryVirtualActor::new(
            scope.clone(),
            artifact,
            cash,
            venue_config,
            expected_source,
        ))?;
        boundary(actor.connect())?;
        boundary(actor.authenticate())?;
        Ok(Self {
            scope,
            actor,
            records,
            cursor: 0,
            configuration: configuration.fingerprint().into(),
            snapshot: panel.snapshot().into(),
            panel_content: panel.content_digest().into(),
            terminal_at,
            closed: false,
        })
    }

    pub(super) fn scope(&self) -> &Scope {
        &self.scope
    }

    pub(super) fn open(&mut self, opening: &super::OpeningInput) -> Result<(), Error> {
        if self.closed
            || self
                .records
                .get(self.cursor)
                .map(|row| row.opening().identity())
                != Some(opening.identity())
        {
            return Err(err("VENUE_OPEN_RELATION"));
        }
        let at = i64::try_from(opening.event_ns()).map_err(|_| err("VENUE_OPEN_TIME"))?;
        boundary(self.actor.on_open(
            opening.sequence(),
            at,
            opening.instrument_id(),
            opening.price(),
        ))
    }

    pub(super) fn observed(&self, fact: &Fact) -> Result<onlyalpha_broker::ObservedFact, Error> {
        let original = boundary(self.actor.broker().original().observed(fact.identity()))?;
        if original.fact() != fact {
            return Err(err("VENUE_ORIGINAL_MISMATCH"));
        }
        Ok(original)
    }

    pub fn finish(self) -> Result<CompletedMemoryVenue, Error> {
        if !self.closed {
            return Err(err("VENUE_INPUT_OPEN"));
        }
        boundary(self.actor.finish())
    }
}

impl<O: FiniteEconomicOwner> BacktestVenue<O> for MemoryBacktestVenue<'_> {
    fn verify_inputs(
        &self,
        configuration: &RunConfiguration,
        panel: &ResearchPanel,
    ) -> Result<(), Error> {
        if self.cursor != 0
            || self.closed
            || self.configuration != configuration.fingerprint()
            || self.snapshot != panel.snapshot()
            || self.panel_content != panel.content_digest()
        {
            return Err(err("VENUE_INPUT_BINDING"));
        }
        Ok(())
    }
}

impl<O: FiniteEconomicOwner> VenueFacts<O> for MemoryBacktestVenue<'_> {
    fn scope(&self) -> &Scope {
        &self.scope
    }

    fn stage(&mut self, fact: &Fact) -> Result<ObservationState, Error> {
        ObservationState::from_broker(self.actor.broker().original(), fact)?
            .ok_or_else(|| err("VENUE_FACT_UNOBSERVED"))
    }

    fn acknowledge(&mut self, owner: &O, fact: &Fact) -> Result<(), Error> {
        boundary(self.actor.acknowledge(owner, fact.identity()))
    }
}

impl<O: FiniteEconomicOwner> VirtualVenue<O> for MemoryBacktestVenue<'_> {
    fn prepare_market(&mut self, market: &MarketBar) -> Result<(), Error> {
        let (row, _) = self.records[self.cursor..]
            .split_at_checked(market.instruments().len())
            .ok_or_else(|| err("VENUE_BAR_MISSING"))?;
        for (input, id) in row.iter().zip(market.instruments()) {
            if input.bar().instrument_id() != id
                || &input.event_ns() != market.timestamp().unix_nanos()
            {
                return Err(err("VENUE_BAR_RELATION"));
            }
        }
        for (sequence, input) in ((self.cursor as u64 + 1)..).zip(row) {
            boundary(self.actor.on_bar(sequence, input.bar()))?;
        }
        self.cursor += row.len();
        Ok(())
    }

    fn finish_market_input(&mut self) -> Result<(), Error> {
        if self.cursor != self.records.len() {
            return Err(err("VENUE_UNCONSUMED_BARS"));
        }
        if !self.closed {
            boundary(self.actor.advance(self.terminal_at))?;
            self.closed = true;
        }
        Ok(())
    }

    fn pending_venue(&mut self) -> Result<Option<Fact>, Error> {
        if self.actor.pending().is_empty() {
            boundary(self.actor.publish())?;
        }
        Ok(self.actor.pending().first().cloned())
    }

    fn dispatch_simulated(
        &mut self,
        owner: &O,
        command: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        if self.closed {
            return Err(err("VENUE_INPUT_CLOSED"));
        }
        boundary(self.actor.dispatch(owner, command))
    }
}
