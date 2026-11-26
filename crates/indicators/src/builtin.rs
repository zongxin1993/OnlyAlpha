//! Built-in financial indicators composed strictly from certified operators.

use crate::compose::{Builder, ComposedIndicator, ComposedStream, IndicatorState, Result};
use onlyalpha_operators::algebra::{Decimal, Error, Operator, Parameters};
use std::num::NonZeroUsize;

fn period_params(period: NonZeroUsize) -> Parameters {
    Parameters {
        period: Some(period),
        ..Default::default()
    }
}

fn scale_params(factor: Decimal) -> Parameters {
    Parameters {
        factor: Some(factor),
        ..Default::default()
    }
}

pub fn sma(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let out = b.op(Operator::RollingMean, period_params(period), &[x])?;
    Ok(b.finish(vec![out], period.get()))
}

pub fn wma(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let out = b.op(Operator::DecayLinear, period_params(period), &[x])?;
    Ok(b.finish(vec![out], period.get()))
}

pub fn roc(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let diff = b.op(Operator::Delta, period_params(period), &[x])?;
    let lagged = b.op(Operator::Delay, period_params(period), &[x])?;
    let out = b.op(Operator::Divide, Parameters::default(), &[diff, lagged])?;
    Ok(b.finish(vec![out], period.get().saturating_add(1)))
}

pub fn ema(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let out = b.op(Operator::EMA, period_params(period), &[x])?;
    Ok(b.finish(vec![out], 1))
}

pub fn rolling_volatility(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let out = b.op(Operator::RollingStd, period_params(period), &[x])?;
    Ok(b.finish(vec![out], period.get()))
}

pub fn zscore(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let zero = b.constant(Decimal::from(0));
    let mean = b.op(Operator::RollingMean, period_params(period), &[x])?;
    let std = b.op(Operator::RollingStd, period_params(period), &[x])?;
    let diff = b.op(Operator::Subtract, Parameters::default(), &[x, mean])?;
    let ratio = b.op(Operator::Divide, Parameters::default(), &[diff, std])?;
    let out = b.op(Operator::Where, Parameters::default(), &[std, ratio, zero])?;
    Ok(b.finish(vec![out], period.get()))
}

pub fn bollinger(period: NonZeroUsize, multiplier: Decimal) -> Result<ComposedIndicator> {
    if multiplier < 0 {
        return Err(Error::InvalidParameters);
    }
    let mut b = Builder::new(1);
    let x = b.input(0);
    let mid = b.op(Operator::RollingMean, period_params(period), &[x])?;
    let std = b.op(Operator::RollingStd, period_params(period), &[x])?;
    let band = b.op(Operator::Scale, scale_params(multiplier), &[std])?;
    let upper = b.op(Operator::Add, Parameters::default(), &[mid, band])?;
    let lower = b.op(Operator::Subtract, Parameters::default(), &[mid, band])?;
    Ok(b.finish(vec![mid, upper, lower], period.get()))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MACDCross {
    None,
    Golden,
    Death,
}

impl MACDCross {
    pub fn from_histograms(previous: Option<&Decimal>, current: Option<&Decimal>) -> Self {
        let Some(curr) = current else {
            return Self::None;
        };
        let zero = Decimal::from(0);
        let prev = previous.unwrap_or(&zero);
        if curr > &zero && prev <= &zero {
            Self::Golden
        } else if curr < &zero && prev >= &zero {
            Self::Death
        } else {
            Self::None
        }
    }
}

pub fn macd(
    fast: NonZeroUsize,
    slow: NonZeroUsize,
    signal: NonZeroUsize,
) -> Result<ComposedIndicator> {
    if fast >= slow {
        return Err(Error::InvalidParameters);
    }
    let mut b = Builder::new(1);
    let x = b.input(0);
    let fast_ema = b.op(Operator::EMA, period_params(fast), &[x])?;
    let slow_ema = b.op(Operator::EMA, period_params(slow), &[x])?;
    let dif = b.op(
        Operator::Subtract,
        Parameters::default(),
        &[fast_ema, slow_ema],
    )?;
    let dea = b.op(Operator::EMA, period_params(signal), &[dif])?;
    let histogram = b.op(Operator::Subtract, Parameters::default(), &[dif, dea])?;
    Ok(b.finish(vec![dif, dea, histogram], 1))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RSIZone {
    Oversold,
    Neutral,
    Overbought,
}

impl RSIZone {
    pub fn from_value(value: Option<&Decimal>) -> Self {
        let Some(v) = value else {
            return Self::Neutral;
        };
        if *v < 30 {
            Self::Oversold
        } else if *v > 70 {
            Self::Overbought
        } else {
            Self::Neutral
        }
    }
}

pub fn rsi(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(1);
    let x = b.input(0);
    let zero = b.constant(Decimal::from(0));
    let fifty = b.constant(Decimal::from(50));
    let change = b.op(Operator::Delta, period_params(NonZeroUsize::MIN), &[x])?;
    let gain = b.op(
        Operator::Where,
        Parameters::default(),
        &[change, change, zero],
    )?;
    let abs_change = b.op(Operator::Abs, Parameters::default(), &[change])?;
    let loss = b.op(
        Operator::Where,
        Parameters::default(),
        &[change, zero, abs_change],
    )?;
    let avg_gain = b.op(Operator::RMA, period_params(period), &[gain])?;
    let avg_loss = b.op(Operator::RMA, period_params(period), &[loss])?;
    let total = b.op(Operator::Add, Parameters::default(), &[avg_gain, avg_loss])?;
    let ratio = b.op(Operator::Divide, Parameters::default(), &[avg_gain, total])?;
    let pct = b.op(Operator::Scale, scale_params(Decimal::from(100)), &[ratio])?;
    let out = b.op(Operator::Where, Parameters::default(), &[total, pct, fifty])?;
    Ok(b.finish(vec![out], period.get().saturating_add(1)))
}

/// Inputs: `[high, low, close]`. Outputs: `[atr, normalized_atr]`.
pub fn atr(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(3);
    let high = b.input(0);
    let low = b.input(1);
    let close = b.input(2);
    let hl = b.op(Operator::Subtract, Parameters::default(), &[high, low])?;
    let prev_close = b.op(Operator::Delay, period_params(NonZeroUsize::MIN), &[close])?;
    let high_prev = b.op(
        Operator::Subtract,
        Parameters::default(),
        &[high, prev_close],
    )?;
    let hc = b.op(Operator::Abs, Parameters::default(), &[high_prev])?;
    let low_prev = b.op(
        Operator::Subtract,
        Parameters::default(),
        &[low, prev_close],
    )?;
    let lc = b.op(Operator::Abs, Parameters::default(), &[low_prev])?;
    let hl_minus_hc = b.op(Operator::Subtract, Parameters::default(), &[hl, hc])?;
    let max1 = b.op(
        Operator::Where,
        Parameters::default(),
        &[hl_minus_hc, hl, hc],
    )?;
    let max1_minus_lc = b.op(Operator::Subtract, Parameters::default(), &[max1, lc])?;
    let tr = b.op(
        Operator::Where,
        Parameters::default(),
        &[max1_minus_lc, max1, lc],
    )?;
    let atr_val = b.op(Operator::RMA, period_params(period), &[tr])?;
    let norm = b.op(Operator::Divide, Parameters::default(), &[atr_val, close])?;
    Ok(b.finish(vec![atr_val, norm], period.get().saturating_add(1)))
}

/// Inputs: `[close, volume]`. Outputs: `[obv]`.
pub fn obv() -> Result<ComposedIndicator> {
    let mut b = Builder::new(2);
    let close = b.input(0);
    let volume = b.input(1);
    let change = b.op(Operator::Delta, period_params(NonZeroUsize::MIN), &[close])?;
    let dir = b.op(Operator::Sign, Parameters::default(), &[change])?;
    let signed_vol = b.op(Operator::Multiply, Parameters::default(), &[dir, volume])?;
    let out = b.op(Operator::CumSum, Parameters::default(), &[signed_vol])?;
    Ok(b.finish(vec![out], 2))
}

/// Rolling VWAP over `[price, volume]`. Outputs: `[vwap]`.
pub fn vwap(period: NonZeroUsize) -> Result<ComposedIndicator> {
    let mut b = Builder::new(2);
    let price = b.input(0);
    let volume = b.input(1);
    let pv = b.op(Operator::Multiply, Parameters::default(), &[price, volume])?;
    let sum_pv = b.op(Operator::RollingSum, period_params(period), &[pv])?;
    let sum_v = b.op(Operator::RollingSum, period_params(period), &[volume])?;
    let out = b.op(Operator::Divide, Parameters::default(), &[sum_pv, sum_v])?;
    Ok(b.finish(vec![out], period.get()))
}

/// Inputs: `[high, low, close]`. Outputs: `[k, d]`.
pub fn stochastic(
    k_period: NonZeroUsize,
    smooth_k: NonZeroUsize,
    d_period: NonZeroUsize,
) -> Result<ComposedIndicator> {
    let mut b = Builder::new(3);
    let high = b.input(0);
    let low = b.input(1);
    let close = b.input(2);
    let hh = b.op(Operator::RollingMax, period_params(k_period), &[high])?;
    let ll = b.op(Operator::RollingMin, period_params(k_period), &[low])?;
    let num = b.op(Operator::Subtract, Parameters::default(), &[close, ll])?;
    let den = b.op(Operator::Subtract, Parameters::default(), &[hh, ll])?;
    let ratio = b.op(Operator::Divide, Parameters::default(), &[num, den])?;
    let raw_k = b.op(Operator::Scale, scale_params(Decimal::from(100)), &[ratio])?;
    let k = b.op(Operator::RollingMean, period_params(smooth_k), &[raw_k])?;
    let d = b.op(Operator::RollingMean, period_params(d_period), &[k])?;
    let minimum = k_period
        .get()
        .saturating_add(smooth_k.get())
        .saturating_add(d_period.get())
        .saturating_sub(2);
    Ok(b.finish(vec![k, d], minimum))
}

const DAY_NS: u64 = 86_400_000_000_000;

fn session_vwap_dag() -> ComposedIndicator {
    let mut b = Builder::new(4);
    let high = b.input(0);
    let low = b.input(1);
    let close = b.input(2);
    let volume = b.input(3);
    let three = b.constant(Decimal::from(3));
    let hl = b
        .op(Operator::Add, Parameters::default(), &[high, low])
        .expect("valid add");
    let hlc = b
        .op(Operator::Add, Parameters::default(), &[hl, close])
        .expect("valid add");
    let weighted = b
        .op(Operator::Multiply, Parameters::default(), &[hlc, volume])
        .expect("valid multiply");
    let cum_weighted = b
        .op(Operator::CumSum, Parameters::default(), &[weighted])
        .expect("valid cumsum");
    let cum_vol = b
        .op(Operator::CumSum, Parameters::default(), &[volume])
        .expect("valid cumsum");
    let denom = b
        .op(Operator::Multiply, Parameters::default(), &[cum_vol, three])
        .expect("valid multiply");
    let out = b
        .op(
            Operator::Divide,
            Parameters::default(),
            &[cum_weighted, denom],
        )
        .expect("valid divide");
    b.finish(vec![out], 1)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UtcSessionVwapState {
    pub previous_start: Option<u64>,
    pub stream_state: IndicatorState,
}

/// Session VWAP over typical prices `(high + low + close) / 3`, reset at UTC midnight,
/// composed purely from certified `Add` / `Multiply` / `CumSum` / `Divide` operators.
#[derive(Clone, Debug)]
pub struct UtcSessionVWAP {
    dag: ComposedIndicator,
    previous_start: Option<u64>,
    stream: ComposedStream,
}

impl Default for UtcSessionVWAP {
    fn default() -> Self {
        Self::new()
    }
}

impl UtcSessionVWAP {
    pub fn new() -> Self {
        let dag = session_vwap_dag();
        let stream = dag.event_stream().expect("session vwap dag is time series");
        Self {
            dag,
            previous_start: None,
            stream,
        }
    }

    pub fn evaluate_vector(
        start_ns: &[u64],
        high: &[Option<Decimal>],
        low: &[Option<Decimal>],
        close: &[Option<Decimal>],
        volume: &[Option<Decimal>],
    ) -> Result<Vec<Option<Decimal>>> {
        let len = start_ns.len();
        if high.len() != len || low.len() != len || close.len() != len || volume.len() != len {
            return Err(Error::InvalidInputs);
        }
        let dag = session_vwap_dag();
        let mut out = Vec::with_capacity(len);
        let mut i = 0;
        let mut prev_ts: Option<u64> = None;
        while i < len {
            let day = start_ns[i] / DAY_NS;
            let start = i;
            while i < len && start_ns[i] / DAY_NS == day {
                if let Some(prev) = prev_ts
                    && start_ns[i] <= prev
                {
                    return Err(Error::InvalidInputs);
                }
                prev_ts = Some(start_ns[i]);
                i += 1;
            }
            let session_out = dag.evaluate_vector(&[
                high[start..i].to_vec(),
                low[start..i].to_vec(),
                close[start..i].to_vec(),
                volume[start..i].to_vec(),
            ])?;
            out.extend(session_out.into_iter().next().expect("single output"));
        }
        Ok(out)
    }

    pub fn step(
        &mut self,
        start_ns: u64,
        high: Option<Decimal>,
        low: Option<Decimal>,
        close: Option<Decimal>,
        volume: Option<Decimal>,
    ) -> Result<Option<Decimal>> {
        let mut candidate_stream = if let Some(prev) = self.previous_start {
            if start_ns <= prev {
                return Err(Error::InvalidInputs);
            }
            if start_ns / DAY_NS != prev / DAY_NS {
                self.dag.event_stream()?
            } else {
                self.stream.clone()
            }
        } else {
            self.stream.clone()
        };
        let result = candidate_stream.step(&[high, low, close, volume])?;
        self.stream = candidate_stream;
        self.previous_start = Some(start_ns);
        Ok(result.into_iter().next().expect("single output"))
    }

    pub fn capture_state(&self) -> UtcSessionVwapState {
        UtcSessionVwapState {
            previous_start: self.previous_start,
            stream_state: self.stream.capture_state(),
        }
    }

    pub fn restore_state(&mut self, state: UtcSessionVwapState) -> Result<()> {
        let mut candidate = self.dag.event_stream()?;
        candidate.restore_state(state.stream_state)?;
        self.stream = candidate;
        self.previous_start = state.previous_start;
        Ok(())
    }
}
