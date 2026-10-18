//! Session-anchored TIME_BAR@1 over explicit calendar facts and logical time.
use crate::{executor::*, model::*, record::*};
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    market::{OnlyBar, OnlyBarFormation, OnlyBarType},
    numeric::only_add,
    time::{OnlyTimestamp, OnlyTradingDay, OnlyUtcDateTime},
    value::{OnlyMoney, OnlyQuantity},
};
use serde_json::{Value, json};
use std::sync::Arc;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionWindow {
    start: OnlyUtcDateTime,
    end: OnlyUtcDateTime,
    partial: bool,
}
impl OnlyConstructionWindow {
    pub fn start(&self) -> OnlyUtcDateTime {
        self.start
    }
    pub fn end(&self) -> OnlyUtcDateTime {
        self.end
    }
    pub fn is_partial(&self) -> bool {
        self.partial
    }
}
#[derive(Clone)]
enum TimeState {
    Empty,
    Pending(Vec<Arc<OnlyBar>>),
    Settled {
        last: Arc<OnlyBar>,
        skipped_until: Option<OnlyTimestamp>,
    },
}
impl TimeState {
    fn latest(&self) -> Option<&OnlyBar> {
        match self {
            Self::Empty => None,
            Self::Pending(bars) => bars.last().map(AsRef::as_ref),
            Self::Settled { last, .. } => Some(last),
        }
    }
    fn to_record(&self) -> Value {
        match self {
            Self::Empty => json!({"kind":"EMPTY"}),
            Self::Pending(bars) => {
                json!({"kind":"PENDING","bars":bars.iter().map(|b|b.to_record()).collect::<Vec<_>>()})
            }
            Self::Settled {
                last,
                skipped_until,
            } => {
                json!({"kind":"SETTLED","last_bar":last.to_record(),"skipped_until_ns":skipped_until.as_ref().map(|t|number(t.unix_nanos()))})
            }
        }
    }
}
pub struct OnlyTimeBarExecutor {
    edge: OnlyConstructionEdge,
    calendar: Arc<OnlyTradingCalendar>,
    calendar_fingerprint: String,
    state: TimeState,
}
impl OnlyTimeBarExecutor {
    pub fn new(
        edge: OnlyConstructionEdge,
        calendar: Arc<OnlyTradingCalendar>,
    ) -> OnlyConstructionResult<Self> {
        let OnlyConstructionInput::Bar(source) = edge.source() else {
            return Err(err("TIME_BAR_INPUT"));
        };
        if edge.recipe().algorithm() != Some(("TIME_BAR", &1u32.into())) {
            return Err(OnlyConstructionError::Unavailable);
        }
        let (OnlyBarFormation::FixedDuration(a), OnlyBarFormation::FixedDuration(b)) = (
            source.semantic().formation(),
            edge.target().semantic().formation(),
        ) else {
            return Err(err("TIME_BAR_FIXED_DURATION"));
        };
        if !source.semantic().is_aligned()
            || !edge.target().semantic().is_aligned()
            || a.alignment() != b.alignment()
            || b.window_minutes() <= a.window_minutes()
            || b.window_minutes() % a.window_minutes() != BigInt::from(0)
        {
            return Err(err("TIME_BAR_ALIGNED_DIVISIBLE"));
        }
        let calendar_fingerprint = hash(&calendar.to_record());
        Ok(Self {
            edge,
            calendar,
            calendar_fingerprint,
            state: TimeState::Empty,
        })
    }
    fn source(&self) -> &OnlyBarType {
        let OnlyConstructionInput::Bar(source) = self.edge.source() else {
            unreachable!("validated")
        };
        source
    }
    fn validate_source(&self, bar: &OnlyBar, closed: bool) -> OnlyConstructionResult<()> {
        if bar.bar_type() != self.source()
            || *bar.is_closed() != closed
            || *bar.revision() != 0.into()
            || (closed && bar.ts_event() != bar.bar_end())
        {
            return Err(err("TIME_BAR_SOURCE_FACT"));
        }
        let duration = OnlyTimestamp::from_datetime(*bar.bar_end()).to_unix_nanos()
            - OnlyTimestamp::from_datetime(*bar.bar_start()).unix_nanos();
        if duration != self.source().semantic().window_minutes().map_err(err)? * 60_000_000_000i64 {
            return Err(err("SOURCE_DURATION"));
        }
        Ok(())
    }
    pub fn window_for(&self, bar: &OnlyBar) -> OnlyConstructionResult<OnlyConstructionWindow> {
        if bar.bar_type() != self.source() {
            return Err(OnlyConstructionError::Scope);
        }
        let day = OnlyTradingDay::new(*bar.trading_day()).map_err(err)?;
        if !self.calendar.is_effective_on(day) {
            return Err(err("CALENDAR_EFFECTIVE_RANGE"));
        }
        let intervals = self
            .calendar
            .session_intervals_for_trading_day(day)
            .map_err(err)?;
        let sessions = self.calendar.sessions_for_trading_day(day);
        let ((start, end), session) = intervals
            .into_iter()
            .zip(sessions)
            .find(|((start, end), _)| {
                *start <= *bar.bar_start()
                    && *bar.bar_start() < *end
                    && *start < *bar.bar_end()
                    && *bar.bar_end() <= *end
            })
            .ok_or_else(|| err("SOURCE_OUTSIDE_SESSION"))?;
        if !session.allows_market_data() || session.session_type() != bar.session_type() {
            return Err(err("SOURCE_SESSION_METADATA"));
        }
        let origin = OnlyTimestamp::from_datetime(start).to_unix_nanos();
        let elapsed = OnlyTimestamp::from_datetime(*bar.bar_start()).to_unix_nanos() - &origin;
        let source_duration =
            self.source().semantic().window_minutes().map_err(err)? * 60_000_000_000i64;
        if &elapsed % source_duration != BigInt::from(0) {
            return Err(err("SOURCE_SESSION_GRID"));
        }
        let duration = self
            .edge
            .target()
            .semantic()
            .window_minutes()
            .map_err(err)?
            * 60_000_000_000i64;
        let from = origin + (&elapsed / &duration) * &duration;
        let nominal = &from + duration;
        let end_ns = OnlyTimestamp::from_datetime(end).to_unix_nanos();
        let partial = nominal > end_ns;
        let to = nominal.min(end_ns);
        let window = OnlyConstructionWindow {
            start: OnlyTimestamp::from_unix_nanos(from)
                .to_datetime_exact()
                .map_err(err)?,
            end: OnlyTimestamp::from_unix_nanos(to)
                .to_datetime_exact()
                .map_err(err)?,
            partial,
        };
        if bar.bar_end() > &window.end {
            return Err(err("SOURCE_CROSSES_TARGET_BOUNDARY"));
        }
        Ok(window)
    }
    fn consistent(&self, bars: &[Arc<OnlyBar>]) -> OnlyConstructionResult<()> {
        let first = bars.first().ok_or_else(|| err("EMPTY_WINDOW"))?;
        for bar in bars {
            if bar.trading_day() != first.trading_day()
                || bar.session_type() != first.session_type()
                || bar.adjustment_type() != first.adjustment_type()
                || bar.open().precision() != first.open().precision()
                || bar.volume().precision() != first.volume().precision()
            {
                return Err(err("WINDOW_METADATA_OR_PRECISION"));
            }
        }
        for values in [
            bars.iter()
                .filter_map(|b| b.quote_volume().as_ref())
                .collect::<Vec<_>>(),
            bars.iter()
                .filter_map(|b| b.open_interest().as_ref())
                .collect::<Vec<_>>(),
        ] {
            if values
                .windows(2)
                .any(|pair| pair[0].precision() != pair[1].precision())
            {
                return Err(err("OPTIONAL_QUANTITY_PRECISION"));
            }
        }
        let monies: Vec<_> = bars.iter().filter_map(|b| b.turnover().as_ref()).collect();
        if monies
            .windows(2)
            .any(|pair| pair[0].currency() != pair[1].currency())
        {
            return Err(err("TURNOVER_CURRENCY"));
        }
        Ok(())
    }
    fn assemble(
        &self,
        bars: &[Arc<OnlyBar>],
        window: &OnlyConstructionWindow,
        event: OnlyUtcDateTime,
        init: OnlyUtcDateTime,
        closed: bool,
    ) -> OnlyConstructionResult<Arc<OnlyBar>> {
        self.consistent(bars)?;
        let first = &bars[0];
        let last = bars.last().expect("nonempty");
        let mut input = first.input();
        input.bar_type = self.edge.target().clone();
        input.high = bars
            .iter()
            .reduce(|a, b| {
                if b.high().value() > a.high().value() {
                    b
                } else {
                    a
                }
            })
            .expect("nonempty")
            .high()
            .clone();
        input.low = bars
            .iter()
            .reduce(|a, b| {
                if b.low().value() < a.low().value() {
                    b
                } else {
                    a
                }
            })
            .expect("nonempty")
            .low()
            .clone();
        input.close = last.close().clone();
        input.volume =
            sum_quantities(bars.iter().map(|b| Some(b.volume())))?.expect("nonempty volumes");
        input.quote_volume = sum_quantities(bars.iter().map(|b| b.quote_volume().as_ref()))?;
        input.turnover = sum_money(bars.iter().map(|b| b.turnover().as_ref()))?;
        input.trade_count = if bars.iter().any(|b| b.trade_count().is_none()) {
            None
        } else {
            Some(
                bars.iter()
                    .map(|b| b.trade_count().as_ref().expect("known"))
                    .sum(),
            )
        };
        input.open_interest = last.open_interest().clone();
        input.bar_start = window.start;
        input.bar_end = window.end;
        input.ts_event = event;
        input.ts_init = init;
        input.is_closed = closed;
        input.revision = 0.into();
        Ok(Arc::new(OnlyBar::new(input).map_err(err)?))
    }
    fn settle(bar: &Arc<OnlyBar>, until: Option<OnlyTimestamp>) -> TimeState {
        TimeState::Settled {
            last: bar.clone(),
            skipped_until: until,
        }
    }
    fn skip(
        &self,
        state: &mut TimeState,
        bar: &Arc<OnlyBar>,
        window: &OnlyConstructionWindow,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        if self.edge.recipe().missing() != Some(OnlyMissingPolicy::SkipWindow) {
            return Err(err("SOURCE_GAP"));
        }
        let until = if *bar.bar_end() < window.end {
            Some(OnlyTimestamp::from_datetime(window.end))
        } else {
            None
        };
        *state = Self::settle(bar, until);
        Ok(vec![])
    }
    fn advance(
        &self,
        state: &mut TimeState,
        bar: &Arc<OnlyBar>,
        init: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        self.validate_source(bar, true)?;
        if init < &OnlyTimestamp::from_datetime(*bar.bar_end()) {
            return Err(OnlyConstructionError::Time);
        }
        if state
            .latest()
            .is_some_and(|last| last.bar_end() >= bar.bar_end())
        {
            return Err(OnlyConstructionError::Sequence);
        }
        let window = self.window_for(bar)?;
        if let TimeState::Settled {
            skipped_until: Some(until),
            ..
        } = state
        {
            let end = OnlyTimestamp::from_datetime(*bar.bar_end());
            if end <= *until {
                let until = if end < *until {
                    Some(until.clone())
                } else {
                    None
                };
                *state = Self::settle(bar, until);
                return Ok(vec![]);
            }
        }
        let mut bars = match state {
            TimeState::Pending(bars) => {
                let old = self.window_for(&bars[0])?;
                if old != window {
                    if self.edge.recipe().missing() != Some(OnlyMissingPolicy::SkipWindow) {
                        return Err(err("INCOMPLETE_SOURCE_WINDOW"));
                    }
                    vec![]
                } else {
                    bars.clone()
                }
            }
            _ => vec![],
        };
        let expected = bars.last().map_or(window.start, |b| *b.bar_end());
        if *bar.bar_start() != expected {
            return self.skip(state, bar, &window);
        }
        bars.push(bar.clone());
        self.consistent(&bars)?;
        if *bar.bar_end() < window.end {
            *state = TimeState::Pending(bars);
            return Ok(vec![]);
        }
        if window.partial {
            if self.edge.recipe().incomplete() != Some(OnlyIncompletePolicy::Drop) {
                return Err(err("INCOMPLETE_SESSION_TAIL"));
            }
            *state = Self::settle(bar, None);
            return Ok(vec![]);
        }
        let output = self.assemble(
            &bars,
            &window,
            window.end,
            init.to_datetime_exact().map_err(err)?,
            true,
        )?;
        *state = Self::settle(bar, None);
        Ok(vec![output])
    }
    pub fn preview(&self, bar: &OnlyBar) -> OnlyConstructionResult<Option<Arc<OnlyBar>>> {
        self.validate_source(bar, false)?;
        let window = self.window_for(bar)?;
        if window.partial {
            return Ok(None);
        }
        let mut bars = match &self.state {
            TimeState::Pending(bars) => {
                if self.window_for(&bars[0])? != window {
                    return Ok(None);
                }
                bars.clone()
            }
            TimeState::Settled {
                last,
                skipped_until,
            } => {
                if skipped_until.is_some() || last.bar_end() > bar.bar_start() {
                    return Ok(None);
                }
                vec![]
            }
            TimeState::Empty => vec![],
        };
        let expected = bars.last().map_or(window.start, |b| *b.bar_end());
        if expected != *bar.bar_start() {
            return Ok(None);
        }
        bars.push(Arc::new(bar.clone()));
        self.assemble(&bars, &window, *bar.ts_event(), *bar.ts_init(), false)
            .map(Some)
    }
    fn validate_state(&self, state: &TimeState) -> OnlyConstructionResult<()> {
        match state {
            TimeState::Empty => Ok(()),
            TimeState::Pending(bars) => {
                if bars.is_empty() {
                    return Err(err("EMPTY_PENDING_STATE"));
                }
                let window = self.window_for(&bars[0])?;
                let mut expected = window.start;
                for bar in bars {
                    self.validate_source(bar, true)?;
                    if self.window_for(bar)? != window
                        || *bar.bar_start() != expected
                        || *bar.bar_end() >= window.end
                    {
                        return Err(err("PENDING_STATE_RELATIONS"));
                    }
                    expected = *bar.bar_end();
                }
                self.consistent(bars)
            }
            TimeState::Settled {
                last,
                skipped_until,
            } => {
                self.validate_source(last, true)?;
                let window = self.window_for(last)?;
                if let Some(until) = skipped_until {
                    if self.edge.recipe().missing() != Some(OnlyMissingPolicy::SkipWindow)
                        || *until != OnlyTimestamp::from_datetime(window.end)
                        || *last.bar_end() >= window.end
                    {
                        return Err(err("SKIPPED_STATE_RELATIONS"));
                    }
                } else if *last.bar_end() != window.end
                    || (window.partial
                        && self.edge.recipe().incomplete() != Some(OnlyIncompletePolicy::Drop))
                {
                    return Err(err("SETTLED_STATE_RELATIONS"));
                }
                Ok(())
            }
        }
    }
    fn read_state(&self, v: &Value) -> OnlyConstructionResult<TimeState> {
        let row = v.as_object().ok_or_else(|| err("STATE_OBJECT"))?;
        let kind = text(row.get("kind").ok_or_else(|| err("STATE_KIND"))?)?;
        let fields: &[&str] = match kind {
            "EMPTY" => &["kind"],
            "PENDING" => &["kind", "bars"],
            "SETTLED" => &["kind", "last_bar", "skipped_until_ns"],
            _ => return Err(err("STATE_KIND")),
        };
        if row.len() != fields.len() || fields.iter().any(|k| !row.contains_key(*k)) {
            return Err(err("STATE_FIELDS"));
        }
        let state = match kind {
            "EMPTY" => TimeState::Empty,
            "PENDING" => TimeState::Pending(
                array(&row["bars"])?
                    .iter()
                    .map(|b| domain(b).map(Arc::new))
                    .collect::<OnlyConstructionResult<_>>()?,
            ),
            _ => TimeState::Settled {
                last: Arc::new(domain(&row["last_bar"])?),
                skipped_until: if row["skipped_until_ns"].is_null() {
                    None
                } else {
                    Some(OnlyTimestamp::from_unix_nanos(integer(
                        &row["skipped_until_ns"],
                    )?))
                },
            },
        };
        self.validate_state(&state)?;
        Ok(state)
    }
}
impl OnlyConstructionExecutor for OnlyTimeBarExecutor {
    fn target(&self) -> &OnlyBarType {
        self.edge.target()
    }
    fn process(
        &mut self,
        fact: &OnlyConstructionFact,
        init: &OnlyTimestamp,
    ) -> OnlyConstructionResult<Vec<Arc<OnlyBar>>> {
        let OnlyConstructionFact::Bar(bar) = fact else {
            return Err(err("TIME_BAR_INPUT_KIND"));
        };
        let mut state = self.state.clone();
        let output = self.advance(&mut state, bar, init)?;
        self.state = state;
        Ok(output)
    }
    fn capture_checkpoint(&self) -> OnlyConstructionResult<Value> {
        Ok(
            json!({"schema_version":1,"edge":self.edge.to_record(),"calendar_fingerprint":self.calendar_fingerprint,"state":self.state.to_record()}),
        )
    }
    fn restore_checkpoint(&mut self, v: &Value) -> OnlyConstructionResult<()> {
        let row = object(v, 1, &["edge", "calendar_fingerprint", "state"])?;
        if OnlyConstructionEdge::from_record(&row["edge"])? != self.edge
            || text(&row["calendar_fingerprint"])? != self.calendar_fingerprint
        {
            return Err(OnlyConstructionError::Scope);
        }
        let state = self.read_state(&row["state"])?;
        self.state = state;
        Ok(())
    }
}
fn sum_quantities<'a>(
    values: impl Iterator<Item = Option<&'a OnlyQuantity>>,
) -> OnlyConstructionResult<Option<OnlyQuantity>> {
    let mut total: Option<OnlyQuantity> = None;
    for value in values {
        let Some(value) = value else { return Ok(None) };
        let previous = match total {
            None => OnlyQuantity::new("0".parse().map_err(err)?, value.precision()).map_err(err)?,
            Some(total) => total,
        };
        total = Some(
            OnlyQuantity::new(
                only_add(previous.value(), value.value()).map_err(err)?,
                previous.precision(),
            )
            .map_err(err)?,
        );
    }
    Ok(total)
}
fn sum_money<'a>(
    values: impl Iterator<Item = Option<&'a OnlyMoney>>,
) -> OnlyConstructionResult<Option<OnlyMoney>> {
    let mut total: Option<OnlyMoney> = None;
    for value in values {
        let Some(value) = value else { return Ok(None) };
        let previous = match total {
            None => {
                OnlyMoney::new("0".parse().map_err(err)?, value.currency().clone()).map_err(err)?
            }
            Some(total) => total,
        };
        total = Some(previous.checked_add(value).map_err(err)?);
    }
    Ok(total)
}
