//! Durable Execution storage and bounded recovery orchestration, outside Trading Kernel.
mod replay;
mod codec;
mod dictionary_codec;
mod references;
pub use references::ReplayEntryRef;
mod readonly;
pub use readonly::VerifiedReplaySnapshot;
mod store;
use onlyalpha_execution::{
    BacktestResult, Components, Error, Record, Store, coordinate, pending_events,
};
use serde_json::Value;
use std::path::Path;
pub use store::SqliteStore;

/// Exclusive native Execution session. This is not Product Runtime admission or LIVE authority.
pub struct Runtime {
    store: SqliteStore,
    components: Components,
    healthy: bool,
}
impl Runtime {
    pub fn create(root: &Path, configuration: Value, artifact: &str) -> Result<Self, Error> {
        let store = SqliteStore::create(root, configuration.clone(), artifact)?;
        Ok(Self {
            store,
            components: Components::new(configuration)?,
            healthy: true,
        })
    }
    pub fn open(root: &Path, configuration: Value, artifact: &str) -> Result<Self, Error> {
        let store = SqliteStore::open(root, configuration.clone(), artifact)?;
        let mut runtime = Self {
            store,
            components: Components::new(configuration)?,
            healthy: false,
        };
        runtime.recover()?;
        Ok(runtime)
    }
    fn require_healthy(&self)->Result<(),Error>{
        if self.healthy {Ok(())}else{Err(Error("RUNTIME_RECOVERY_REQUIRED".into()))}
    }
    fn ready(&self) -> Result<(), Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components,|_|Ok(()))
    }
    /// Errors retain the original identity and block outward reads until explicit recovery.
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        self.require_healthy()?;
        let prepared=self.store.with_ready_source(&self.components,|source|{
            if let Some(existing)=self.components.ready_records(source)?.iter()
                .find(|record|record.prepared().input()["input_id"]==input["input_id"]) {
                if existing.prepared().input()!=input{return Err(Error("RUNTIME_STORE_IDENTITY_CONFLICT".into()));}
                return Ok(None);
            }
            self.components.prepare(source,input).map(Some)
        });
        self.healthy=false;
        if let Some(prepared)=prepared? {
            // The original coordinator reopens the actual writer source and
            // proves commit/projection/Ready readback; the view is gone.
            coordinate(&mut self.store,&mut self.components,&prepared)?;
        }
        self.healthy = true;
        Ok(())
    }
    /// Rebuild from the sole durable source, never from possibly partially installed memory.
    pub fn recover(&mut self) -> Result<(), Error> {
        self.healthy = false;
        let components = self.store.recover_components()?;
        self.components = components;
        self.healthy = true;
        Ok(())
    }
    /// Independent preflight owners at the actual healthy Ready head, never a Store or dispatch capability.
    pub fn fork_ready(&self) -> Result<(Components, Vec<Record>), Error> {
        self.require_healthy()?;
        self.store.fork_ready(&self.components)
    }
    pub fn save_checkpoint(&mut self) -> Result<Value, Error> {
        self.ready()?;
        self.healthy = false;
        let value = self.store.save_checkpoint(&self.components)?;
        self.healthy = true;
        Ok(value)
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components,|source|self.components.state(source))
    }
    pub fn records(&self) -> Result<Vec<Record>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components,|source|self.components.ready_records(source))
    }
    pub fn pending_events(&self) -> Result<Vec<Value>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components,|source|pending_events(source,&self.components))
    }
    pub fn acknowledge(&mut self, sequence: u64) -> Result<(), Error> {
        self.ready()?;
        self.healthy = false;
        self.store.acknowledge(sequence)?;
        self.healthy = true;
        Ok(())
    }
    /// Trusted Application port; does not grant Product admission or authenticate callers.
    pub fn bind_replay(&mut self, binding: &Value) -> Result<(), Error> {
        self.ready()?;
        self.store.bind_replay(binding)
    }
    pub fn replay_steps(&self) -> Result<Vec<Value>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components,|source|self.store.replay_steps_from_source(source.records()))
    }
    pub fn prepare_replay(&mut self, step: &Value) -> Result<(), Error> {
        self.ready()?;
        self.healthy = false;
        self.store.prepare_replay(step)?;
        self.healthy = true;
        Ok(())
    }
    pub fn complete_replay(&mut self, index: u64) -> Result<(), Error> {
        // Existing technical callers complete the actual owning proposal. No
        // external callback runs between observing it and the strict operation.
        let rows = self.replay_steps()?;
        let expected = rows.last().ok_or_else(|| Error("RUNTIME_REPLAY_MISSING_STEP".into()))?["step"].clone();
        self.complete_replay_rows(index, &expected).map(|_| ())
    }
    /// Complete only this original proposal and return its real post-write SQL
    /// rows after canonical reconciliation. Values are observations, not grants;
    /// the next public call always proves its own fresh source again.
    pub fn complete_replay_rows(&mut self, index: u64, expected_step: &Value) -> Result<Vec<Value>, Error> {
        self.ready()?;
        self.healthy = false;
        let rows = self.store.complete_replay(index, expected_step)?;
        self.store.with_ready_source(&self.components,|_|Ok(()))?;
        self.healthy = true;
        Ok(rows)
    }
    pub fn backtest_result(
        &self,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<BacktestResult, Error> {
        self.require_healthy()?;
        if manifest["kernel_artifact"] != self.store.identity()["kernel_artifact"] {
            return Err(Error("RUNTIME_RESULT_ARTIFACT_CONFLICT".into()));
        }
        self.store.with_ready_source(&self.components,|source|self.components.backtest_result(source,manifest,outcome))
    }
}
