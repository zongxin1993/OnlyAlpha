//! Actual owning preparation over sealed Dataset and exact Composer/Runtime inputs.
//! Technical evidence only; it submits no Research or Freeze command.
#[path = "strategy_submission_probe.rs"]
pub(super) mod strategy_submission_probe;
use onlyalpha_backend::{
    application::{
        research_admission::PreparedInputs,
        research_dataset::MaterializedDataset,
        research_run_execution::Control,
        strategy_research::{Context, RunSpecification, StrategyEvaluation},
    },
    persistence::{
        research_dataset::Store, research_runtime::RuntimeInputHold, strategy_research::Composer,
    },
};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::{Value, json};
use std::path::Path;
pub async fn run(
    session: &mut onlyalpha_backend::persistence::authority_session::AuthoritySession,
    v: &Value,
    materialized: &MaterializedDataset,
    datasets: &Store,
) -> Result<Value, Box<dyn std::error::Error>> {
    let client = session.client_mut().await?;
    let work = v["research_command"]
        .as_str()
        .map(|id| {
            onlyalpha_backend::application::command::CommandId::new(id)
                .map(|id| onlyalpha_backend::persistence::research_submission::run_id(&id))
        })
        .transpose()?;
    let mut context = Context::new(v["strategy_context"].clone())?;
    let runtime = RuntimeInputHold::open(
        Path::new(v["runtime_root"].as_str().ok_or("runtime")?),
        work.as_deref().unwrap_or("use_test_strategy_prepare"),
        "research",
        v["runtime_generation"].as_str().ok_or("generation")?,
    )?;
    let installation = ChartInstallation::open(
        Path::new(v["algorithm_root"].as_str().ok_or("algorithms")?),
        v["algorithm_artifact"].as_str().ok_or("artifact")?,
    )?;
    let resolved = Composer::new(client)
        .resolve(
            v["strategy_id"].as_str().ok_or("strategy")?,
            v["strategy_revision"].as_str().ok_or("revision")?,
            &context,
            runtime,
            &installation,
        )
        .await?;
    let original = resolved.record().clone();
    if v["strategy_fault"] == "context" {
        let mut changed = context.record().clone();
        changed["display_metadata"] = json!({"changed":"after actual resolution"});
        context = Context::new(changed)?;
    }
    if v["strategy_fault"] == "missing-composition" {
        let pin = original["composition"]["composition_fingerprint"]
            .as_str()
            .ok_or("composition")?;
        // Deliberate physical corruption in the guarded disposable test DB.
        // The production reader must refuse to recreate this missing fact.
        client
            .batch_execute("ALTER TABLE private_strategy_research_composition DISABLE TRIGGER USER")
            .await?;
        let removed=client.execute("DELETE FROM private_strategy_research_composition WHERE composition_fingerprint=$1",&[&pin]).await;
        client
            .batch_execute("ALTER TABLE private_strategy_research_composition ENABLE TRIGGER USER")
            .await?;
        assert_eq!(removed?, 1);
    }
    let (prepared, spec) = PreparedInputs::prepare_strategy(
        &mut Composer::new(client),
        resolved,
        &context,
        &installation,
        datasets,
        materialized,
    )
    .await?;
    prepared.verify_runtime()?;
    if v["strategy_evidence"] == true {
        return super::strategy_evidence_probe::submit(session, v, prepared, spec, datasets).await;
    }
    if v["submission_mode"].is_string() {
        return strategy_submission_probe::submit(session, v, prepared, spec, datasets).await;
    }
    let mut result = json!({"prepared_inputs":prepared.record(),"specification":spec.record(),"specification_fingerprint":spec.fingerprint()?,
        "scientific_specification_fingerprint":spec.scientific_specification_fingerprint()?,"candidate_fingerprint":spec.candidate_fingerprint()?,
        "calculation_fingerprint":spec.calculation_fingerprint()?,"calculation_execution_fingerprint":spec.calculation_execution_fingerprint()?,
        "original_resolution":original});
    if v["strategy_evaluation"] == true {
        let control = Control::default();
        if v["strategy_fault"] == "eval-cancel" {
            control.stop()?;
        }
        let specification = if v["strategy_fault"] == "eval-spec" {
            let mut changed = spec.record().clone();
            changed["runtime_generation_fingerprint"] = json!("f".repeat(64));
            RunSpecification::from_record(&changed)?
        } else {
            spec
        };
        if v["strategy_fault"] == "eval-dataset" {
            let pin = prepared.record()["dataset_snapshot_fingerprint"]
                .as_str()
                .ok_or("dataset")?;
            let manifest = Path::new(v["dataset_root"].as_str().ok_or("dataset root")?)
                .join("sha256")
                .join(&pin[..2])
                .join(pin)
                .join("manifest.json");
            // Deliberate physical corruption after the real opaque preparation.
            std::fs::write(manifest, b"not an immutable Dataset manifest")?;
        }
        let observed = StrategyEvaluation::observe(
            prepared,
            specification,
            datasets,
            std::sync::Arc::new(installation),
            env!("CARGO_PKG_VERSION"),
            &control,
        )?;
        result["evaluation"] = observed.record().clone();
    }
    Ok(result)
}
