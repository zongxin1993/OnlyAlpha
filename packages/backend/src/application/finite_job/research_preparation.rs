//! Read-only preparation owns its readers until it joins and returns control to the scheduler.
use super::{
    owners::{FiniteTask, prepare_backtest, start_research_claimed},
    *,
};
use crate::{
    application::{
        backtest_run,
        factor_build::FactorBuildService,
        job_input::{InputError, JobInputLoader, MemoryBudget},
        research_admission::{self, PreparationError},
        research_run::VerifiedRun,
        source_access::Selection,
    },
    bootstrap::workstation_startup::JobReadConnections,
    persistence::{
        job_publication::{AttemptClaim, AttemptExecutionBinding},
        market_data::{Catalog, Storage},
        research_runtime::RuntimeInputHold,
        strategy_research::Composer,
    },
    workers::{backtest_service, source_sessions::SourceSessions},
};
use onlyalpha_calculation_bridge::ChartInstallation;
use std::{path::PathBuf, sync::Arc};
use tracing::{Instrument, instrument::WithSubscriber};

type PreparedResult<T> = std::result::Result<T, PreparationError>;

pub(crate) struct PreparationTask<T = FiniteTask> {
    task: tokio::task::JoinHandle<(JobReadConnections, PreparedResult<T>)>,
    cancel: tokio::sync::watch::Sender<bool>,
    binding: FrozenJobBinding,
    execution: AttemptExecutionBinding,
}
/// The joined preparation returned without starting an execution task.
pub(crate) struct AbortedPreparation {
    binding: FrozenJobBinding,
    execution: AttemptExecutionBinding,
}
impl AbortedPreparation {
    pub(crate) fn binding(&self) -> &FrozenJobBinding {
        &self.binding
    }
    pub(crate) fn verify_attempt(
        &self,
        claim: &AttemptClaim<'_>,
    ) -> std::result::Result<(), PreparationError> {
        if !self.execution.matches(claim) {
            return Err("FINITE_JOB_BINDING_MISMATCH".into());
        }
        Ok(())
    }
}
pub(crate) enum PreparedExecution<T = FiniteTask> {
    Ready {
        readers: JobReadConnections,
        value: T,
    },
    Aborted {
        readers: JobReadConnections,
        proof: AbortedPreparation,
        error: PreparationError,
    },
}

pub(crate) struct LoadedBacktest {
    prepared: super::PreparedBacktestJob,
    input: crate::application::job_input::PreparedJobInput,
    proof: AbortedPreparation,
}
impl LoadedBacktest {
    pub(crate) fn discard(self) -> AbortedPreparation {
        self.proof
    }

    pub(crate) fn start(self, claim: &AttemptClaim<'_>) -> std::result::Result<FiniteTask, (AbortedPreparation, PreparationError)> {
        let Self { prepared, input, proof } = self;
        proof.verify_attempt(claim)
            .and_then(|()| prepared.start_claimed(input, proof.binding.clone(), claim))
            .map_err(|error| (proof, error))
    }
}
impl PreparationTask<FiniteTask> {
    pub(crate) fn start(
        readers: JobReadConnections,
        sources: SourceSessions,
        run: VerifiedRun,
        binding: FrozenJobBinding,
        execution: AttemptExecutionBinding,
        runtime_root: PathBuf,
        algorithms: PathBuf,
        budget: MemoryBudget,
    ) -> Self {
        Self::spawn(
            readers,
            binding,
            execution,
            "RESEARCH_EXECUTION_CANCELLED",
            "RESEARCH_PREPARATION_READ_DRAIN_UNKNOWN",
            async move |readers, pins, association| {
                #[cfg(test)]
                crate::workers::research_service::owner_tests::preparation_gate(run.run_id()).await;
                let source = sources.current(run.owner(), None).await.map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
                let installation = Arc::new(
                    ChartInstallation::open(&algorithms, run.specification().algorithm_artifact_fingerprint()?)
                        .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?,
                );
                let namespace = readers.namespace().clone();
                let physical = readers.physical();
                let (metadata, facts) = readers.clients_mut().await.map_err(|_| "RESEARCH_INPUT_READER_UNAVAILABLE")?;
                let input = {
                    let mut storage = Storage::new(Catalog::new(metadata, budget.rows(), budget.bytes()).map_err(|_| "RESEARCH_INPUT_CATALOG_UNAVAILABLE")?, physical.as_ref(), budget.rows())
                        .map_err(|_| "RESEARCH_INPUT_STORAGE_UNAVAILABLE")?;
                    let mut factors = FactorBuildService::new(facts, &namespace, installation.clone()).await
                        .map_err(|_| "RESEARCH_INPUT_FACT_READER_UNAVAILABLE")?;
                    JobInputLoader::new(&mut storage, &mut factors, &source, run.source_selection())
                        .load(&pins, &budget).await.map_err(|error| input_error(error, "RESEARCH_SOURCE_ACCESS_DENIED"))?
                };
                let held = RuntimeInputHold::open(&runtime_root, run.run_id(), "research", run.runtime_generation_fingerprint()?)?;
                let prepared = research_admission::restore_finite(&run, held, &installation, &pins, &input)?;
                start_research_claimed(run, prepared, input, pins, &mut Composer::new(metadata).with_fact_reader(facts), installation, association).await
            },
        )
    }
}
impl PreparationTask<LoadedBacktest> {
    pub(crate) fn start_backtest(
        readers: JobReadConnections,
        sources: SourceSessions,
        run: backtest_run::VerifiedRun,
        binding: FrozenJobBinding,
        execution: AttemptExecutionBinding,
        config: backtest_service::Configuration,
        budget: MemoryBudget,
    ) -> Self {
        Self::spawn(
            readers,
            binding,
            execution,
            "BACKTEST_EXECUTION_CANCELLED",
            "BACKTEST_PREPARATION_READ_DRAIN_UNKNOWN",
            async move |readers, pins, association| {
                const DENIED: &str = "BACKTEST_SOURCE_ACCESS_DENIED";
                let strategy = run.specification().record()["strategy_fingerprint"].as_str().ok_or(DENIED)?;
                let source = sources.current(run.owner(), Some(strategy)).await.map_err(|_| DENIED)?;
                let selection = Selection::from_record(&run.resolution()["source_selection"]).map_err(|_| DENIED)?;
                source.require_selection(&selection, crate::application::source_access::Permission::ClosedHistory).map_err(|_| DENIED)?;
                let physical = readers.physical();
                let (metadata, facts) = readers.clients_mut().await.map_err(|_| "BACKTEST_INPUT_READER_UNAVAILABLE")?;
                let prepared = prepare_backtest(metadata, facts, &run, &config.research_root, &config.runtime_root, &config.algorithms_root).await?;
                let mut storage = Storage::new(Catalog::new(metadata, budget.rows(), budget.bytes()).map_err(|_| "BACKTEST_INPUT_CATALOG_UNAVAILABLE")?, physical.as_ref(), budget.rows())
                    .map_err(|_| "BACKTEST_INPUT_STORAGE_UNAVAILABLE")?;
                let mut factors = FactorBuildService::new(facts, run.namespace(), prepared.installation()).await
                    .map_err(|_| "BACKTEST_INPUT_FACT_READER_UNAVAILABLE")?;
                let input = JobInputLoader::new(&mut storage, &mut factors, &source, &selection)
                    .load(&pins, &budget).await.map_err(|error| input_error(error, DENIED))?;
                #[cfg(test)]
                crate::workers::backtest_worker::tests::blocking_phase(run.run_id(), "before_produce");
                Ok(LoadedBacktest {
                    prepared,
                    input,
                    proof: AbortedPreparation { binding: pins, execution: association },
                })
            },
        )
    }
}
impl<T: Send + 'static> PreparationTask<T> {
    fn spawn(
        mut readers: JobReadConnections,
        binding: FrozenJobBinding,
        execution: AttemptExecutionBinding,
        cancelled: &'static str,
        drain_unknown: &'static str,
        prepare: impl for<'a> AsyncFnOnce(&'a mut JobReadConnections, FrozenJobBinding, AttemptExecutionBinding) -> PreparedResult<T> + Send + 'static,
    ) -> Self {
        let (cancel, mut stopped) = tokio::sync::watch::channel(false);
        let pins = binding.clone();
        let association = execution.clone();
        let runtime = tokio::runtime::Handle::current();
        let dispatch = tracing::dispatcher::get_default(Clone::clone);
        let parent = tracing::Span::current();
        let task = tokio::task::spawn_blocking(move || {
            runtime.block_on(async move {
                let result = tokio::select! {
                    biased;
                    _ = stopped.changed() => Err(PreparationError::from(cancelled)),
                    result = prepare(&mut readers, pins, association) => result,
                };
                // Acknowledged reads settle queued rollbacks before reusing these drivers.
                let result = if result.is_err() && readers.clients_mut().await.is_err() {
                    let _ = readers.close().await;
                    Err(PreparationError::unknown(drain_unknown, None))
                } else {
                    result
                };
                (readers, result)
            }.instrument(parent).with_subscriber(dispatch))
        });
        Self { task, cancel, binding, execution }
    }
    pub(crate) fn cancellation(&self) -> tokio::sync::watch::Sender<bool> {
        self.cancel.clone()
    }
    pub(crate) async fn join(self) -> PreparedResult<PreparedExecution<T>> {
        let code = match self.binding.kind() {
            JobKind::Backtest => "BACKTEST_PREPARATION_JOIN_UNKNOWN",
            JobKind::Research => "RESEARCH_PREPARATION_JOIN_UNKNOWN",
        };
        let joined = self.task.await
            .map_err(|_| PreparationError::unknown(code, None));
        drop(self.cancel);
        let (readers, result) = joined?;
        Ok(match result {
            Ok(value) => PreparedExecution::Ready { readers, value },
            Err(error) => PreparedExecution::Aborted {
                readers,
                proof: AbortedPreparation { binding: self.binding, execution: self.execution },
                error,
            },
        })
    }
}
fn input_error(error: InputError, denied: &'static str) -> PreparationError {
    match error {
        InputError::Invalid => "JOB_INPUT_INVALID".into(),
        InputError::BudgetExceeded => "JOB_INPUT_BUDGET_EXCEEDED".into(),
        InputError::MissingEvidence => "JOB_INPUT_MISSING_EVIDENCE".into(),
        InputError::Unavailable => "JOB_INPUT_UNAVAILABLE".into(),
        InputError::Mismatch => "JOB_INPUT_MISMATCH".into(),
        InputError::Forbidden => denied.into(),
        InputError::NotReady => "JOB_INPUT_NOT_READY".into(),
        InputError::Unknown => PreparationError::unknown("JOB_INPUT_OUTCOME_UNKNOWN", None),
    }
}
