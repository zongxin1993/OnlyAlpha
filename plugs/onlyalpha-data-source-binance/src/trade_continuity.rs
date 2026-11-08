//! 单一原始成交序列的进程内恢复协调器。可变访问串行化全部状态；不拥有持久化。
use crate::spot_rest::{Error, Result};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, market::OnlyTradeTick};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Disconnected,
    Connected,
    Recovering,
    Ready,
    Failed,
}
/// 每个实例绑定一个 Source 原始成交 scope。不同 Source/版本应建立不同实例。
/// 不可把此易失检查点当作 WAL、持久游标或跨进程恢复证据。
pub struct TradeContinuity {
    instrument: OnlyInstrumentId,
    maximum: usize,
    state: State,
    subscribed: bool,
    baseline: bool,
    last: Option<i64>,
    recent: BTreeMap<i64, OnlyTradeTick>,
    buffer: BTreeMap<i64, OnlyTradeTick>,
}
fn sequence(t: &OnlyTradeTick) -> Result<i64> {
    t.sequence().to_string().parse().map_err(|_| Error::Range)
}
impl TradeContinuity {
    pub fn new(instrument: OnlyInstrumentId, maximum: usize) -> Result<Self> {
        if maximum == 0 || maximum > 100_000 {
            return Err(Error::Range);
        }
        Ok(Self {
            instrument,
            maximum,
            state: State::Disconnected,
            subscribed: false,
            baseline: false,
            last: None,
            recent: BTreeMap::new(),
            buffer: BTreeMap::new(),
        })
    }
    pub fn state(&self) -> State {
        self.state
    }
    pub fn checkpoint(&self) -> Option<i64> {
        self.last
    }
    pub fn buffered_count(&self) -> usize {
        self.buffer.len()
    }
    pub fn connected(&mut self) -> Result<()> {
        if self.state == State::Failed {
            return Err(Error::Order);
        }
        self.state = State::Connected;
        self.subscribed = false;
        self.baseline = false;
        Ok(())
    }
    pub fn subscription_established(&mut self) -> Result<()> {
        if self.state != State::Connected {
            return Err(Error::Order);
        }
        self.subscribed = true;
        Ok(())
    }
    pub fn begin_recovery(&mut self) -> Result<()> {
        if self.state != State::Connected || !self.subscribed {
            return Err(Error::Order);
        }
        self.state = State::Recovering;
        Ok(())
    }
    pub fn disconnected(&mut self) {
        if self.state != State::Failed {
            self.state = State::Disconnected;
        }
        self.subscribed = false;
        self.baseline = false;
    }
    fn validate(&self, tick: &OnlyTradeTick) -> Result<i64> {
        if tick.instrument_id() != &self.instrument
            || tick.source() != "BINANCE_SPOT"
            || tick.trade_id().value() != tick.sequence().to_string()
        {
            return Err(Error::Shape);
        }
        sequence(tick)
    }
    fn known(&mut self, n: i64, tick: &OnlyTradeTick) -> Result<bool> {
        if let Some(old) = self.recent.get(&n).or_else(|| self.buffer.get(&n)) {
            if old != tick {
                self.state = State::Failed;
                return Err(Error::Order);
            }
            return Ok(true);
        }
        Ok(false)
    }
    fn commit<F>(&mut self, tick: OnlyTradeTick, persist: &mut F) -> Result<()>
    where
        F: FnMut(&OnlyTradeTick) -> Result<()>,
    {
        let n = self.validate(&tick)?;
        if persist(&tick).is_err() {
            self.state = State::Failed;
            return Err(Error::Evidence);
        }
        self.last = Some(n);
        self.recent.insert(n, tick);
        while self.recent.len() > self.maximum {
            self.recent.pop_first();
        }
        Ok(())
    }
    /// 首次 baseline 必须是调用者已获取的真实成交；重连不能越过旧 checkpoint。
    pub fn accept_baseline<F>(&mut self, tick: OnlyTradeTick, persist: &mut F) -> Result<()>
    where
        F: FnMut(&OnlyTradeTick) -> Result<()>,
    {
        if self.state != State::Recovering {
            return Err(Error::Order);
        }
        let n = self.validate(&tick)?;
        if self.last.is_none() {
            self.commit(tick, persist)?;
        } else if self.last.is_some_and(|p| n > p) {
            self.buffer(tick)?;
        } else {
            self.known(n, &tick)?;
        }
        self.baseline = true;
        Ok(())
    }
    /// 调用者已记录真实空 baseline 的证据后使用；不表示插件推断历史不存在。
    pub fn establish_empty_baseline(&mut self) -> Result<()> {
        if self.state != State::Recovering || self.last.is_some() {
            return Err(Error::Order);
        }
        self.baseline = true;
        Ok(())
    }
    pub fn buffer(&mut self, tick: OnlyTradeTick) -> Result<()> {
        if self.state != State::Recovering {
            return Err(Error::Order);
        }
        let n = self.validate(&tick)?;
        if self.known(n, &tick)? || self.last.is_some_and(|p| n <= p) {
            return Ok(());
        }
        if self.buffer.len() >= self.maximum {
            self.state = State::Failed;
            return Err(Error::TooLarge);
        }
        self.buffer.insert(n, tick);
        Ok(())
    }
    /// READY 时仅接收精确下一条；缺口原事件进入有界 buffer，等待显式恢复。
    pub fn accept<F>(&mut self, tick: OnlyTradeTick, persist: &mut F) -> Result<Vec<OnlyTradeTick>>
    where
        F: FnMut(&OnlyTradeTick) -> Result<()>,
    {
        if self.state == State::Recovering {
            self.buffer(tick)?;
            return Ok(Vec::new());
        }
        if self.state != State::Ready {
            return Err(Error::Order);
        }
        let n = self.validate(&tick)?;
        if self.known(n, &tick)? || self.last.is_some_and(|p| n <= p) {
            return Ok(Vec::new());
        }
        if self.last.is_some() && self.last.and_then(|p| p.checked_add(1)) != Some(n) {
            self.state = State::Recovering;
            self.buffer(tick)?;
            return Ok(Vec::new());
        }
        self.commit(tick.clone(), persist)?;
        Ok(vec![tick])
    }
    /// 恢复输入必须完整填平至缓冲后缀；先证明全部身份/序列，再逐条持久化和提交。
    /// 缺证保持 RECOVERING，写入失败进入 FAILED，永不提前宣布 READY。
    pub fn complete_recovery<F>(
        &mut self,
        recovered: Vec<OnlyTradeTick>,
        persist: &mut F,
    ) -> Result<Vec<OnlyTradeTick>>
    where
        F: FnMut(&OnlyTradeTick) -> Result<()>,
    {
        if self.state != State::Recovering || !self.subscribed || !self.baseline {
            return Err(Error::Order);
        }
        let mut ordered = self.buffer.clone();
        if recovered.len() > self.maximum {
            return Err(Error::TooLarge);
        }
        for tick in recovered {
            let n = self.validate(&tick)?;
            self.known(n, &tick)?;
            if self.last.is_some_and(|p| n <= p) {
                continue;
            }
            if let Some(old) = ordered.get(&n)
                && old != &tick
            {
                self.state = State::Failed;
                return Err(Error::Order);
            }
            ordered.insert(n, tick);
        }
        if ordered.len() > self.maximum {
            return Err(Error::TooLarge);
        }
        let mut previous = self.last;
        for n in ordered.keys() {
            if let Some(p) = previous
                && p.checked_add(1) != Some(*n)
            {
                return Err(Error::Order);
            }
            previous = Some(*n);
        }
        let accepted: Vec<_> = ordered.into_values().collect();
        for tick in &accepted {
            self.commit(tick.clone(), persist)?;
        }
        self.buffer.clear();
        self.state = State::Ready;
        Ok(accepted)
    }
}
