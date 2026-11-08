//! Durable Execution storage and bounded recovery orchestration, outside Trading Kernel.
mod broker_source_store;
mod codec;
mod perpetual_sources;
pub use broker_source_store::BoundBrokerJournal;
pub use perpetual_sources::BrokerJournal;
mod dictionary_codec;
mod references;
mod replay;
pub use references::{ReplayCompletion, ReplayEntryRef};
mod readonly;
pub use readonly::VerifiedReplaySnapshot;
mod store;
mod transcript;
use onlyalpha_execution::{Components, Error, Record, coordinate};
use serde_json::Value;
use std::path::Path;
pub use store::{RunFundingPlan, RunPlan, SqliteStore};
pub use transcript::RunBacktestResult;

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
    fn require_healthy(&self) -> Result<(), Error> {
        if self.healthy {
            Ok(())
        } else {
            Err(Error("RUNTIME_RECOVERY_REQUIRED".into()))
        }
    }
    fn ready(&self) -> Result<(), Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |_| Ok(()))
    }
    /// Errors retain the original identity and block outward reads until explicit recovery.
    pub fn apply(&mut self, input: &Value) -> Result<(), Error> {
        self.require_healthy()?;
        enum Application {
            AlreadyApplied,
            Run(RunPlan),
            Ordinary(onlyalpha_execution::Prepared),
        }
        let plan = self.store.with_ready_source(&self.components, |source| {
            if let Some(existing) = source
                .records()
                .iter()
                .find(|r| r.prepared().input()["input_id"] == input["input_id"])
            {
                if existing.prepared().input() != input {
                    return Err(Error("RUNTIME_STORE_IDENTITY_CONFLICT".into()));
                }
                self.store.verify_perpetual_inputs(source.records())?;
                return Ok(Application::AlreadyApplied);
            }
            if self.store.requires_run_plan(source, input) {
                return self
                    .store
                    .plan_from_prefix(&self.components, source, input)
                    .map(Application::Run);
            }
            self.store
                .prepare_input(&self.components, source, input)
                .map(Application::Ordinary)
        });
        self.healthy = false;
        match plan? {
            Application::AlreadyApplied => {}
            Application::Ordinary(p) => coordinate(&mut self.store, &mut self.components, &p)?,
            Application::Run(plan) => {
                self.store.commit_run_plan(&plan)?;
                self.components = self.store.recover_components()?;
            }
        }
        self.healthy = true;
        Ok(())
    }
    /// 在现金或尚无 Funding 的普通前缀上准备事务。Funding 及其后续输入使用 prepare_run_plan。
    pub fn prepare(&self, input: &Value) -> Result<onlyalpha_execution::Prepared, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |source| {
            if self.store.requires_run_plan(source, input) {
                return Err(Error("RUNTIME_RUN_PLAN_REQUIRED".into()));
            }
            self.store.prepare_input(&self.components, source, input)
        })
    }
    /// 从实际源和本 Run 的 Ready 前缀准备 Funding 或 Funding 后的普通事务。
    pub fn prepare_run_plan(&self, input: &Value) -> Result<RunPlan, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |source| {
            self.store.plan_from_prefix(&self.components, source, input)
        })
    }
    /// 用签发计划的同一个持锁 Store 提交并按原件恢复。
    pub fn apply_run_plan(&mut self, plan: &RunPlan) -> Result<(), Error> {
        self.ready()?;
        self.healthy = false;
        self.store.commit_run_plan(plan)?;
        self.recover()
    }
    pub fn prepare_original_funding(&self, input: &Value) -> Result<RunFundingPlan, Error> {
        if self.components.configuration()["schema_version"] != 3 || input["op"] != "FUNDING" {
            return Err(Error("RUNTIME_STORE_FUNDING_INPUT".into()));
        }
        self.prepare_run_plan(input)
    }
    pub fn apply_original_funding(&mut self, plan: &RunFundingPlan) -> Result<(), Error> {
        if plan.value()["input"]["op"] != "FUNDING" {
            return Err(Error("RUNTIME_STORE_FUNDING_INPUT".into()));
        }
        self.apply_run_plan(plan)
    }
    /// Commit an original canonical plan through the actual owning source.
    /// This technical port grants no Product work or planner origin to decoded data.
    pub fn apply_prepared(
        &mut self,
        prepared: &onlyalpha_execution::Prepared,
    ) -> Result<(), Error> {
        self.require_healthy()?;
        let existing = self.store.with_ready_source(&self.components, |source| {
            if self.components.configuration()["schema_version"] != 3
                || !source.has_funding()
                || prepared.input()["op"] == "FUNDING"
            {
                return Ok(false);
            }
            let row = source
                .records()
                .iter()
                .find(|row| row.prepared().sequence() == prepared.sequence())
                .ok_or_else(|| Error("RUNTIME_RUN_PLAN_REQUIRED".into()))?;
            if !row.ready() || row.prepared() != prepared {
                return Err(Error("RUNTIME_STORE_IDENTITY_CONFLICT".into()));
            }
            Ok(true)
        });
        self.healthy = false;
        if !existing? {
            coordinate(&mut self.store, &mut self.components, prepared)?;
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
        self.store.fork_ready(&self.components, |_| Ok(()))
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
        self.store
            .with_ready_source(&self.components, |source| source.state(&self.components))
    }
    pub fn records(&self) -> Result<Vec<Record>, Error> {
        self.require_healthy()?;
        self.store
            .with_ready_source(&self.components, |source| Ok(source.records().to_vec()))
    }
    pub fn pending_events(&self) -> Result<Vec<Value>, Error> {
        self.require_healthy()?;
        self.store.with_ready_source(&self.components, |source| {
            source.pending_events(&self.components)
        })
    }
    pub fn acknowledge(&mut self, sequence: u64) -> Result<(), Error> {
        self.ready()?;
        self.healthy = false;
        self.store.acknowledge_original(sequence)?;
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
        self.store.with_ready_source(&self.components, |source| {
            self.store.replay_steps_from_source(source.records())
        })
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
        let expected = rows
            .last()
            .ok_or_else(|| Error("RUNTIME_REPLAY_MISSING_STEP".into()))?["step"]
            .clone();
        self.complete_replay_rows(index, &expected).map(|_| ())
    }
    /// Complete only this original proposal and return its real post-write SQL
    /// rows after canonical reconciliation. Values are observations, not grants;
    /// the next public call always proves its own fresh source again.
    pub fn complete_replay_rows(
        &mut self,
        index: u64,
        expected_step: &Value,
    ) -> Result<Vec<Value>, Error> {
        self.ready()?;
        self.healthy = false;
        let rows = self.store.complete_replay(index, expected_step)?;
        self.store.with_ready_source(&self.components, |_| Ok(()))?;
        self.healthy = true;
        Ok(rows)
    }
    pub fn backtest_result(
        &self,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<RunBacktestResult, Error> {
        self.require_healthy()?;
        if manifest["kernel_artifact"] != self.store.identity()["kernel_artifact"] {
            return Err(Error("RUNTIME_RESULT_ARTIFACT_CONFLICT".into()));
        }
        self.store
            .backtest_result_at_ready(&self.components, manifest, outcome)
    }
}
