//! 线性永续资金费只由原边界持仓、配对来源事实和冻结合约推导。
use crate::{Manager, model::*};
use bigdecimal::{RoundingMode, Zero};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyFundingRateFact, OnlyReferencePriceFact},
    market_source::OnlyMarketSourceCut,
    time::OnlyTimestamp,
};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// 不能从现金金额构造。两个经济投影以同一组紧凑索引重新取得原事实。
pub struct FundingEffect {
    record: Value,
    reference: Value,
    position_configuration: String,
    account_lineage: String,
    ledger_lineage: String,
}
impl FundingEffect {
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn reference(&self) -> &Value {
        &self.reference
    }
    pub fn position_configuration(&self) -> &str {
        &self.position_configuration
    }
    pub fn account_lineage(&self) -> &str {
        &self.account_lineage
    }
    pub fn ledger_lineage(&self) -> &str {
        &self.ledger_lineage
    }
}
impl Manager {
    // 来自原 Position 指令及真实执行结果；不是传入的汇总或未验证 checkpoint 字段。
    pub(crate) fn trade_lineage(&self) -> Result<(Value, Value), Error> {
        let mut replay = Self::new(self.config.clone())?;
        let mut account = serde_json::Map::new();
        let mut ledger = serde_json::Map::new();
        for command in &self.state.journal {
            let outcome = replay.apply(command)?;
            if command["op"] == "TRADE" && outcome.status == crate::Status::Applied {
                let p = &command["payload"];
                let fact = outcome
                    .fact
                    .ok_or_else(|| err("POSITION_FUNDING_TRADE_FACT"))?;
                let trade = id(&p["trade"])?;
                account.insert(trade.clone(),json!({"position_evidence":hash(&fact["details"]["account"]),"cause":command["cause"],"time":command["time"],"order":p["order"],"execution":p["execution"],"venue_trade":p["venue_trade"],"sequence":p["sequence"]}));
                if let Some(evidence) = p.get("trade_evidence") {
                    account.get_mut(&trade).expect("inserted trade")["trade_evidence"] =
                        evidence.clone();
                }
                if let Some(cluster) = p["cluster"].as_str() {
                    let allocation = replay.cluster(cluster, text(&p["instrument"])?)?;
                    ledger.insert(trade.clone(),json!({"cluster":p["cluster"],"order":p["order"],"execution":p["execution"],"venue_trade":p["venue_trade"],"sequence":p["sequence"],"cause":command["cause"],"time":command["time"],"allocation_evidence":hash(&allocation)}));
                    if let Some(evidence) = p.get("trade_evidence") {
                        ledger.get_mut(&trade).expect("inserted trade")["trade_evidence"] =
                            evidence.clone();
                    }
                }
            }
        }
        Ok((Value::Object(account), Value::Object(ledger)))
    }
    /// 恢复调用方已经重放的成交前缀；只能选择本 Position 原 Journal 中的连续前缀。
    /// 这不是经济边界的持仓筛选，也不接收金额或调用方摘要。
    pub fn funding_at_trade_prefix(
        &self,
        cut: &OnlyMarketSourceCut,
        reference: &Value,
        trades: &[String],
    ) -> Result<FundingEffect, Error> {
        let target: BTreeSet<_> = trades.iter().map(String::as_str).collect();
        if target.len() != trades.len() {
            return Err(err("POSITION_FUNDING_TRADE_PREFIX"));
        }
        let mut replay = Self::new(self.config.clone())?;
        if target.is_empty() {
            return replay.funding(cut, reference);
        }
        let mut seen = BTreeSet::new();
        for command in &self.state.journal {
            let outcome = replay.apply(command)?;
            if command["op"] == "TRADE" && outcome.status == crate::Status::Applied {
                let trade = text(&command["payload"]["trade"])?;
                if !target.contains(trade) {
                    return Err(err("POSITION_FUNDING_TRADE_PREFIX"));
                }
                seen.insert(trade);
                if seen == target {
                    return replay.funding(cut, reference);
                }
            }
        }
        Err(err("POSITION_FUNDING_TRADE_PREFIX"))
    }
    pub fn funding(
        &self,
        cut: &OnlyMarketSourceCut,
        reference: &Value,
    ) -> Result<FundingEffect, Error> {
        let t = &self.config["funding_rules"];
        let r = row(reference, &["mark", "funding"])?;
        if self.config["schema_version"] != 2 || t["source_cut_sha256"] != cut.fingerprint() {
            return Err(err("POSITION_FUNDING_SOURCE"));
        }
        let mark = cut
            .fact(text(&r["mark"])?)
            .ok_or_else(|| err("POSITION_FUNDING_MARK"))?;
        let rate = cut
            .fact(text(&r["funding"])?)
            .ok_or_else(|| err("POSITION_FUNDING_RATE"))?;
        let m = OnlyReferencePriceFact::from_record(mark)?;
        let f = OnlyFundingRateFact::from_record(rate)?;
        let at = OnlyTimestamp::from_datetime(*f.funding_time());
        let at_ns = at.unix_nanos();
        let seconds = at_ns
            .to_string()
            .parse::<u64>()
            .map_err(|_| err("POSITION_FUNDING_TIME"))?;
        let schedule = &t["schedule"];
        let interval = uint(&schedule["interval_seconds"])?;
        if interval == 0
            || seconds % 1_000_000_000 != 0
            || (seconds / 1_000_000_000) % interval != uint(&schedule["boundary_offset_seconds"])?
            || rate["source"] != t["source"]
            || rate["data_version"] != t["data_version"]
            || m.instrument_id().to_string() != text(&t["instrument"])?
            || mark["kind"] != "MARK"
            || f.funding_time() != m.ts_event()
            || rate["source_record_hash"].is_null()
            || rate["provider_evidence_id"].is_null()
            || [
                "instrument_id",
                "source",
                "source_sequence",
                "data_version",
                "provider_evidence_id",
                "source_record_hash",
            ]
            .iter()
            .any(|k| mark[*k] != rate[*k])
        {
            return Err(err("POSITION_FUNDING_RELATION"));
        }
        let i = text(&t["instrument"])?;
        if self.state.stale.contains_key(i) {
            return Err(err("POSITION_FUNDING_TRADE_HISTORY"));
        }
        let mut quantity = Decimal::zero();
        let mut seen = BTreeSet::new();
        for c in &self.state.journal {
            let p = &c["payload"];
            if c["op"] != "TRADE" || p["instrument"] != i || p["cluster"] != t["cluster"] {
                continue;
            }
            if p["schema_version"] != 3 || p["side"] != "BUY" {
                return Err(err("POSITION_FUNDING_TRADE_HISTORY"));
            }
            if &time(&p["economic_time"])? <= at_ns && seen.insert(text(&p["trade"])?) {
                quantity += positive(&p["quantity"])?;
            }
        }
        let amount = (-quantity
            * &self.spec(i)?.multiplier
            * positive(&mark["value"]["value"])?
            * decimal(&rate["rate"])?)
        .with_scale_round(i64::from(self.currency.precision()), RoundingMode::HalfEven);
        let cashflow = format!(
            "PFLOW-{}",
            hash(&json!([
                self.config["engine"],
                self.config["runtime"],
                self.config["account"],
                self.config["generation"],
                t["cluster"],
                t["revision"],
                t["instrument"],
                t["market_binding"],
                rate,
                mark
            ]))
        );
        let record = json!({"schema_version":1,"cashflow":cashflow,"amount":amount.to_plain_string(),"source_fact":rate["fact_id"],"instrument":t["instrument"],"cluster":t["cluster"],"account":self.config["account"]});
        let (account, ledger) = self.trade_lineage()?;
        Ok(FundingEffect {
            account_lineage: hash(&account),
            ledger_lineage: hash(&ledger),
            record,
            reference: reference.clone(),
            position_configuration: hash(&self.config),
        })
    }
}
