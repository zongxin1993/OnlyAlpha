//! 被动行的经济重算。这里的游标仅在内存内前进，不能向调用方的 Store 写入或确认 Ready。
use crate::{
    CommitIntent, Components, Error, MarketSourceCut, Prepared, Record, Store, TranscriptDraft,
    model::err,
};
use onlyalpha_broker::{Broker, source::SourceHistory};
use serde_json::Value;

#[derive(Debug, PartialEq, Eq)]
pub struct FundingDraft(Prepared);
impl FundingDraft {
    pub fn value(&self) -> &Value {
        self.0.value()
    }
}

struct Rows(Vec<Record>);
impl Store for Rows {
    fn head(&self) -> Result<u64, Error> {
        u64::try_from(self.0.len()).map_err(|_| err("EXECUTION_SEQUENCE_OVERFLOW"))
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        let index = usize::try_from(
            n.checked_sub(1)
                .ok_or_else(|| err("EXECUTION_STORE_SEQUENCE"))?,
        )
        .map_err(|_| err("EXECUTION_STORE_SEQUENCE"))?;
        Ok(self.0.get(index).cloned())
    }
    fn commit(&mut self, _: &CommitIntent) -> Result<Record, Error> {
        Err(err("EXECUTION_PROJECTION_DATA_ONLY"))
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(err("EXECUTION_PROJECTION_DATA_ONLY"))
    }
    fn mark_ready(&mut self, n: u64) -> Result<(), Error> {
        let index = usize::try_from(
            n.checked_sub(1)
                .ok_or_else(|| err("EXECUTION_STORE_SEQUENCE"))?,
        )
        .map_err(|_| err("EXECUTION_STORE_SEQUENCE"))?;
        let row = self
            .0
            .get_mut(index)
            .ok_or_else(|| err("EXECUTION_STORE_SEQUENCE"))?;
        *row = row.with_observed_flags(true, row.delivered())?;
        Ok(())
    }
}

/// 六个 owner 的计算副本。所有输出都是候选或观察数据，正式提交及回执由 Runtime 确认。
pub struct ProjectionData {
    owners: Components,
    rows: Rows,
}
impl ProjectionData {
    pub fn new(owners: &Components, rows: &[Record]) -> Self {
        let mut owners = owners.clone_data();
        owners.projection_data = true;
        Self {
            owners,
            rows: Rows(rows.to_vec()),
        }
    }
    /// 重演同一协调器的逐 owner 安装、前驱、结果摘要及读回检查，只改变本对象。
    pub fn replay(&mut self) -> Result<(), Error> {
        crate::recover(&mut self.rows, &mut self.owners)
    }
    pub fn compare(&self) -> Result<(), Error> {
        self.owners.reconcile(&self.rows).map(|_| ())
    }
    pub fn components(&self) -> Components {
        let mut copy = self.owners.clone_data();
        copy.projection_data = false;
        copy
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.owners.state(&self.rows)
    }
    pub fn transcript(&self, manifest: &Value, outcome: &Value) -> Result<TranscriptDraft, Error> {
        self.owners.transcript_draft(&self.rows, manifest, outcome)
    }
    pub fn pending_event_data(&self) -> Result<Vec<Value>, Error> {
        self.compare()?;
        crate::pending_events(&self.rows, &self.owners)
    }
    pub fn evaluate_funding(
        &self,
        input: &Value,
        cut: &MarketSourceCut,
        broker: &Broker,
        source: &SourceHistory,
    ) -> Result<FundingDraft, Error> {
        if input["op"] != "FUNDING" {
            return Err(err("EXECUTION_FUNDING_INPUT"));
        }
        self.owners
            .compute_perpetual(&self.rows, input, cut, broker, Some(source))
            .map(FundingDraft)
    }
    pub fn evaluate_perpetual(
        &self,
        input: &Value,
        cut: &MarketSourceCut,
        broker: &Broker,
    ) -> Result<Prepared, Error> {
        self.owners
            .prepare_perpetual(&self.rows, input, cut, broker)
    }
}
