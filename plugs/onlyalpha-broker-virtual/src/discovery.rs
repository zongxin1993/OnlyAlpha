//! 用 Broker 已持久化的本次原命令发现记录确定仍缺少哪些场所事实。
use super::{VirtualBroker, plan::err};
use onlyalpha_broker::*;
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// 对账期间使用同一个串行拥有的 Broker Journal；每次查询重新取得当前前缀。
struct VenueDiscovery<'a> {
    venue: &'a VirtualBroker,
    history: Vec<Record>,
    economic_watermark: bool,
    source_sequence: Option<u64>,
}
impl VirtualBroker {
    /// 通过同一串行 Journal 的已提交前缀与场所原操作进行对账。
    pub fn reconcile(
        &self,
        broker: &mut Broker,
        journal: &mut impl Journal,
        id: &str,
    ) -> Result<(), Error> {
        let mut discovery = self.discovery(journal)?;
        broker.reconcile(journal, &mut discovery, id)
    }
    /// 当前纳秒仍可产生事实；只证明严格早于 now 的完整前缀，不改变旧时钟或检查点。
    pub fn reconcile_economic_prefix(
        &self,
        broker: &mut Broker,
        journal: &mut impl Journal,
        id: &str,
    ) -> Result<(), Error> {
        let mut discovery = self.discovery(journal)?;
        discovery.economic_watermark = true;
        broker.reconcile(journal, &mut discovery, id)
    }
    /// Broker 验证 Runtime 的应用回执和新的场所查询后决定能否关闭 UNKNOWN。
    pub fn resolve(
        &self,
        broker: &mut Broker,
        journal: &mut impl Journal,
        runtime: &impl RuntimeReader,
        id: &str,
    ) -> Result<(), Error> {
        let mut discovery = self.discovery(journal)?;
        broker.resolve(journal, runtime, &mut discovery, id)
    }
    pub(super) fn bound_query(
        &self,
        history: Vec<Record>,
        sequence: u64,
        id: &str,
    ) -> Result<Discovery, Error> {
        let command = history
            .iter()
            .find_map(|row| {
                let r = row.record();
                let value = &r["event"]["intent"]["command"];
                (r["event"]["kind"] == "INTENT" && value["command_id"] == id)
                    .then(|| BrokerCommand::decode(value))
            })
            .ok_or_else(|| err("VIRTUAL_SOURCE_QUERY_COMMAND"))??;
        VenueDiscovery {
            venue: self,
            history,
            economic_watermark: true,
            source_sequence: Some(sequence),
        }
        .discover(&command)
    }
    fn discovery(&self, journal: &impl Journal) -> Result<VenueDiscovery<'_>, Error> {
        let history = journal.records()?;
        Ok(VenueDiscovery {
            venue: self,
            history,
            economic_watermark: false,
            source_sequence: None,
        })
    }
}
impl DiscoveryPort for VenueDiscovery<'_> {
    fn discover(&mut self, c: &BrokerCommand) -> Result<Discovery, Error> {
        self.venue.owner(c.scope())?;
        let mut previous = BTreeMap::new();
        let mut head = Value::Null;
        for row in &self.history {
            let r = row.record();
            if r["scope"] != c.scope().record() {
                return Err(err("VIRTUAL_JOURNAL_SCOPE"));
            }
            head = r["hash"].clone();
            let e = &r["event"];
            if e["kind"] == "DISCOVERY" && e["command_id"] == c.id() {
                if e["discovery"]["command"] != c.record() {
                    return Err(err("VIRTUAL_DISCOVERY_COMMAND"));
                }
                for raw in e["discovery"]["facts"]
                    .as_array()
                    .ok_or_else(|| err("VIRTUAL_DISCOVERY_FACTS"))?
                {
                    let fact = Fact::decode(raw)?;
                    previous.insert(fact.identity().to_owned(), fact.fingerprint().to_owned());
                }
            }
        }
        let s = &self.venue.state;
        let old = s.commands.get(c.id());
        if old.is_some_and(|o| o != c) {
            return Err(err("VIRTUAL_DISCOVERY_COMMAND"));
        }
        let o = s.order(c.order()).map(|i| &s.orders[i]);
        if o.is_some_and(|o| {
            o.submit.client() != c.client()
                || (c.operation() == Operation::Submit && o.submit != *c)
        }) || s
            .orders
            .iter()
            .any(|o| o.submit.client() == c.client() && o.submit.order() != c.order())
        {
            return Err(err("VIRTUAL_DISCOVERY_ORDER_CONFLICT"));
        }
        // 拒绝原撤单只说明未执行这次撤单，已有场所订单仍是对账依据。
        let view = if old.is_some()
            && (c.operation() == Operation::Cancel || !s.rejected.contains(c.id()))
            && !s.pending_actions().iter().any(|a| a["command"] == c.id())
        {
            o.map(|o| o.view()).transpose()?.flatten()
        } else {
            None
        };
        let presence = if view.is_some() {
            Presence::Present
        } else if c.operation() == Operation::Submit && s.rejected.contains(c.id()) && o.is_none() {
            Presence::AbsentProven
        } else {
            Presence::Inconclusive
        };
        let mut missing = Vec::new();
        if view.is_some() {
            for f in s.facts.iter().filter(|f| f.order() == Some(c.order())) {
                if let Some(old) = previous.remove(f.identity()) {
                    if old != f.fingerprint() {
                        return Err(err("VIRTUAL_FACT_CONFLICT"));
                    }
                } else {
                    missing.push(f.clone());
                }
            }
        }
        if !previous.is_empty() {
            return Err(err("VIRTUAL_DISCOVERY_HISTORY_AHEAD"));
        }
        let watermark = match self.source_sequence {
            Some(actual) => actual,
            None => u64::try_from(self.venue.inputs.len())
                .ok()
                .and_then(|n| n.checked_add(1))
                .ok_or_else(|| err("VIRTUAL_SOURCE_SEQUENCE"))?,
        };
        let proof = digest(&json!([
            self.venue.binding,
            c.record(),
            head,
            watermark,
            view.as_ref().map(OrderView::record)
        ]));
        let discovery = Discovery::new(c.clone(), proof, watermark, presence, view, missing)?;
        if self.economic_watermark {
            // fact/fill 总用 State.now，advance 禁止倒退；restore 重放同一 CLOCK/Bar 规则。
            // 因而只能封闭严格早于 now 的前缀，同一纳秒仍可有后续 Bar 成交。
            discovery.with_economic_through(
                self.venue
                    .now()
                    .checked_sub(1)
                    .ok_or_else(|| err("VIRTUAL_TIME"))?,
            )
        } else {
            Ok(discovery)
        }
    }
}
