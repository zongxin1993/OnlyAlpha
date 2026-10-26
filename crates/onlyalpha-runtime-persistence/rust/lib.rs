//! Durable Execution storage and bounded recovery orchestration, outside Trading Kernel.
mod replay;
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
    fn ready(&self) -> Result<(), Error> {
        if self.healthy {
            self.components.reconcile(&self.store).map(|_| ())
        } else {
            Err(Error("RUNTIME_RECOVERY_REQUIRED".into()))
        }
    }
    /// Errors retain the original identity and block outward reads until explicit recovery.
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        self.ready()?;
        self.healthy = false;
        if let Some(existing) = self
            .components
            .ready_records(&self.store)?
            .iter()
            .find(|r| r.prepared().input()["input_id"] == input["input_id"])
        {
            if existing.prepared().input() != input {
                return Err(Error("RUNTIME_STORE_IDENTITY_CONFLICT".into()));
            }
            self.healthy = true;
            return Ok(());
        }
        let prepared = self.components.prepare(&self.store, input)?;
        coordinate(&mut self.store, &mut self.components, &prepared)?;
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
    pub fn save_checkpoint(&mut self) -> Result<Value, Error> {
        self.ready()?;
        self.healthy = false;
        let value = self.store.save_checkpoint(&self.components)?;
        self.healthy = true;
        Ok(value)
    }
    pub fn state(&self) -> Result<Value, Error> {
        self.ready()?;
        self.components.state(&self.store)
    }
    pub fn records(&self) -> Result<Vec<Record>, Error> {
        self.ready()?;
        self.components.ready_records(&self.store)
    }
    pub fn pending_events(&self) -> Result<Vec<Value>, Error> {
        self.ready()?;
        pending_events(&self.store, &self.components)
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
        self.ready()?;
        self.store.replay_steps()
    }
    pub fn prepare_replay(&mut self, step: &Value) -> Result<(), Error> {
        self.ready()?;
        self.store.prepare_replay(step)
    }
    pub fn complete_replay(&mut self, index: u64) -> Result<(), Error> {
        self.ready()?;
        self.store.complete_replay(index)
    }
    pub fn backtest_result(
        &self,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<BacktestResult, Error> {
        self.ready()?;
        if manifest["kernel_artifact"] != self.store.identity()["kernel_artifact"] {
            return Err(Error("RUNTIME_RESULT_ARTIFACT_CONFLICT".into()));
        }
        self.components
            .backtest_result(&self.store, manifest, outcome)
    }
}
