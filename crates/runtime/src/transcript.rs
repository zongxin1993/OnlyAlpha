//! 本 Run 的 Execution transcript 封存。实际 Ready 记录和当前六个 owner 共同确定结果。
use crate::SqliteStore;
use onlyalpha_execution::{Components, Error, digest};
use serde_json::{Value, json};

/// 由 Runtime 在原始 SQLite 记录上确认、封存的 BACKTEST_RESULT@1。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunBacktestResult {
    value: Value,
}
impl RunBacktestResult {
    pub fn record(&self) -> Value {
        self.value.clone()
    }

    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
}

impl SqliteStore {
    pub(crate) fn backtest_result_at_ready(
        &self,
        current: &Components,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<RunBacktestResult, Error> {
        self.with_ready_source(current, |source| {
            if source.records().iter().any(|row| !row.ready()) {
                return Err(Error("RUNTIME_RESULT_SOURCE_UNREADY".into()));
            }
            let value = if let Some(data) = source.funded_data(current) {
                // with_ready_source 已用实际 Broker、Mark 和 Funding 原件核对过这段前缀。
                let mut value = data.transcript(manifest, outcome)?.into_record();
                value["final_seal"] = json!({"kind":"READ_ONLY_OBSERVATION","time":manifest["final_time"],"source":value["source"]});
                let fingerprint = digest(value.to_string().as_bytes());
                value["determinism_fingerprint"] = json!(fingerprint);
                value["result_fingerprint"] = json!(fingerprint);
                value["id"] = json!(format!("BTR-{}", digest(value.to_string().as_bytes())));
                value
            } else {
                self.verify_perpetual_inputs(source.records())?;
                current.backtest_result(source, manifest, outcome)?.into_record()
            };
            Ok(RunBacktestResult { value })
        })
    }
}
