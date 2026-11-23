use crate::{
    application::backtest_run::VerifiedRun,
    persistence::{
        backtest_evidence::{BacktestReadContext, read_context},
        research_runtime::RuntimeInputHold,
    },
};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::Value;
use std::{path::{Path, PathBuf}, sync::Arc};

const INVALID: &str = "BACKTEST_PRODUCER_INPUT_MISMATCH";
const UNAVAILABLE: &str = "BACKTEST_PRODUCER_UNAVAILABLE";
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Clone)]
pub(crate) struct Configuration {
    pub research_root: PathBuf,
    pub runtime_root: PathBuf,
    pub algorithms_root: PathBuf,
    pub native_version: String,
}

pub(crate) struct FiniteBacktestCut {
    context: Arc<BacktestReadContext>,
    runtime: RuntimeInputHold,
    installation: Arc<ChartInstallation>,
}

impl FiniteBacktestCut {
    pub(crate) async fn load(
        client: &mut tokio_postgres::Client,
        facts: &mut tokio_postgres::Client,
        run: &VerifiedRun,
        research: &Path,
        runtime: &Path,
        algorithms: &Path,
    ) -> Result<Self> {
        let context = read_context(client, facts, run.namespace(), research, runtime, run.run_id(), run.owner()).await?;
        if context.run().specification_fingerprint() != run.specification_fingerprint()
            || context.run().admission_resolution_fingerprint() != run.admission_resolution_fingerprint()
        {
            return Err(INVALID);
        }
        let operation = context.original_operation();
        let input = operation.request.backtest()?;
        let ready = &operation.outputs["ready"];
        let resolution = run.resolution();
        if input.backtest_command_id != resolution["runtime_work_binding"]["reason"]
            || operation.request.reserved_run_id() != run.run_id()
            || ready["backtest_binding"] != resolution["backtest_binding"]
        {
            return Err(INVALID);
        }
        let mut runtime = RuntimeInputHold::open(
            runtime, run.run_id(), &input.backtest_command_id, run.runtime_generation_fingerprint(),
        )?;
        if runtime.binding() != &resolution["runtime_work_binding"]
            || runtime.binding() != &operation.outputs["environment"]["binding"]
            || runtime.backtest_execution_binding()? != resolution["backtest_binding"]
        {
            return Err(INVALID);
        }
        runtime.verify_artifacts()?;
        let artifact = ready["algorithm_resolution"]["algorithm_artifact"].as_str()
            .filter(|artifact| !artifact.is_empty()).ok_or(INVALID)?;
        let installation = Arc::new(ChartInstallation::open(algorithms, artifact).map_err(|_| UNAVAILABLE)?);
        let calculations = context.validated_calculations()?;
        let decision = context.validated_decision()?;
        let source = context.source_revision().to_record();
        if calculations["algorithm_resolution"]["algorithm_artifact"] != installation.artifact_fingerprint()
            || calculations["algorithm_resolution"] != ready["algorithm_resolution"]
            || calculations["algorithm_resolution_request"] != ready["algorithm_resolution_request"]
            || decision["decision_graph"] != source["decision_graph"]
            || decision["signal_semantics"] != source["signal_semantics"]
            || context.prepared().record() != ready["preparation"]
        {
            return Err(INVALID);
        }
        let cut = Self { context, runtime, installation };
        cut.verify()?;
        Ok(cut)
    }

    pub(crate) fn verify(&self) -> Result<()> {
        self.context.verify_cut()?;
        self.runtime.verify()?;
        self.installation.verify().map_err(|_| UNAVAILABLE)
    }

    pub(crate) fn run(&self) -> &VerifiedRun {
        self.context.run()
    }

    pub(crate) fn source(&self) -> &onlyalpha_strategy::SourceRevision {
        self.context.source_revision()
    }

    pub(crate) fn prepared(&self) -> &crate::workers::backtest::PreparedNextOpen {
        self.context.prepared()
    }

    pub(crate) fn materialization(&self) -> &Value {
        self.context.materialization()
    }

    pub(crate) fn calculations(&self) -> Result<&Value> {
        self.context.validated_calculations()
    }

    pub(crate) fn installation(&self) -> &ChartInstallation {
        &self.installation
    }

    pub(crate) fn installation_owner(&self) -> Arc<ChartInstallation> {
        Arc::clone(&self.installation)
    }
}
