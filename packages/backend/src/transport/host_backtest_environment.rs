//! Manual Backtest reuses the original installed-generation/Registry lifecycle.
//! Generation preparation is not a Study, a Research Run, Freeze or Backtest grant.
use super::*;
use crate::application::{
    backtest_preparation::BacktestOrigin, private_assets, private_strategy::Definition,
};
use std::collections::BTreeMap;
use tracing::Instrument;
const ENV_INVALID: &str = "BACKTEST_ENVIRONMENT_INPUT_MISMATCH";
/// Follow actual saved Strategy bindings. Port aliases never imply historical semantics.
fn explicit_factor_bindings(
    strategy: &Value,
    factor: &Value,
) -> std::result::Result<Value, &'static str> {
    let definition = Definition::from_record(&strategy["definition"])?;
    let value = definition.to_record();
    let dependencies = value["factor_revision_dependencies"]
        .as_array()
        .filter(|values| values.len() == 1)
        .ok_or(ENV_INVALID)?;
    if dependencies[0]["factor_id"] != factor["factor_id"]
        || dependencies[0]["revision_fingerprint"] != factor["revision_fingerprint"]
    {
        return Err(ENV_INVALID);
    }
    let calculations = value["calculations"].as_array().ok_or(ENV_INVALID)?;
    let factors = calculations
        .iter()
        .filter(|node| node["type_reference"]["kind"] == "FACTOR")
        .collect::<Vec<_>>();
    if factors.len() != 1
        || factors[0]["type_reference"]["type_id"] != factor["factor_id"]
        || factors[0]["type_reference"]["semantic_version"] != factor["semantic_version"]
    {
        return Err(ENV_INVALID);
    }
    let field = |value: &Value| -> std::result::Result<String, &'static str> {
        let source = value
            .as_str()
            .and_then(|value| value.strip_prefix("bar."))
            .filter(|value| ["open", "high", "low", "close", "volume"].contains(value))
            .ok_or(ENV_INVALID)?;
        Ok(source.into())
    };
    let mut bindings = BTreeMap::new();
    for binding in factors[0]["input_bindings"].as_array().ok_or(ENV_INVALID)? {
        let name = binding["input_name"].as_str().ok_or(ENV_INVALID)?;
        let source = &binding["source"];
        let dependency = if source.is_string() {
            json!({"input":field(source)?,"closed_only":true})
        } else {
            if source["kind"] != "VARIABLE" || source["output_name"] != "value" {
                return Err(ENV_INVALID);
            }
            let selected = calculations
                .iter()
                .filter(|node| node["instance_key"] == source["instance_key"])
                .collect::<Vec<_>>();
            if selected.len() != 1 {
                return Err(ENV_INVALID);
            }
            let node = selected[0];
            let operator = node["type_reference"]["type_id"]
                .as_str()
                .filter(|value| {
                    [
                        "onlyalpha.operator.delay",
                        "onlyalpha.operator.rolling_mean",
                    ]
                    .contains(value)
                })
                .ok_or(ENV_INVALID)?;
            let inputs = node["input_bindings"]
                .as_array()
                .filter(|values| values.len() == 1)
                .ok_or(ENV_INVALID)?;
            let parameters = node["parameters"]
                .as_object()
                .filter(|values| values.len() == 1)
                .ok_or(ENV_INVALID)?;
            let period = parameters.get("period").ok_or(ENV_INVALID)?;
            if node["type_reference"]["kind"] != "INDICATOR"
                || node["type_reference"]["semantic_version"] != "2"
                || inputs[0]["input_name"] != "value"
                || period["kind"] != "FIXED"
                || period["value"]["type"] != "INTEGER"
            {
                return Err(ENV_INVALID);
            }
            let period = period["value"]["value"]
                .as_u64()
                .filter(|value| (1..=10000).contains(value))
                .ok_or(ENV_INVALID)?;
            json!({"input":field(&inputs[0]["source"])?,"operator":operator,"semantic_version":node["type_reference"]["semantic_version"],"period":period,"closed_only":true})
        };
        if bindings.insert(name.to_owned(), dependency).is_some() {
            return Err(ENV_INVALID);
        }
    }
    Ok(json!(bindings))
}
impl Host {
    /// Original Human prepare command, existing namespace and existing Registry only.
    /// expected_active_generation is the activation CAS, not the resulting work Generation.
    pub(super) async fn prepare_manual_backtest_environment(
        self: &Arc<Self>,
        original: Operation,
        human: &human_access::Session,
        installation: Arc<ChartInstallation>,
    ) -> Result<Operation> {
        let config = self.research_preparation_config.clone();
        pinned_release(&config, &original)?;
        let mut operation = self.preparation_checkpoint(&original, human).await?;
        let input = operation.request.backtest()?.clone();
        let BacktestOrigin::ManualStrategy {
            strategy_id,
            strategy_revision_fingerprint,
        } = &input.origin
        else {
            return Err(ENV_INVALID.into());
        };
        if operation.outputs.get("environment").is_some() {
            retained_manual_backtest_environment(&config, &operation)?;
            return Ok(operation);
        }
        let (strategy, revision) = {
            let mut reader = self.reader.lock().await;
            let client = reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let tx = client
                .build_transaction()
                .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                .read_only(true)
                .start()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            crate::persistence::research_preparation::require_current(&tx, &operation).await?;
            let strategy = private_assets::strategy_revision_in_transaction(
                &tx,
                strategy_id,
                strategy_revision_fingerprint,
            )
            .await
            .map_err(|error| error.code())?;
            let dependencies = strategy["definition"]["factor_revision_dependencies"]
                .as_array()
                .filter(|rows| rows.len() == 1)
                .ok_or(ENV_INVALID)?;
            let revision = private_assets::factor_revision_in_transaction(
                &tx,
                text(&dependencies[0], "factor_id")?,
                text(&dependencies[0], "revision_fingerprint")?,
            )
            .await
            .map_err(|error| error.code())?;
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            (strategy, revision)
        };
        let bindings = explicit_factor_bindings(&strategy, &revision)?;
        let compiled = crate::application::research_factor::compile_revision(&revision, &bindings)?;
        let background = config.clone();
        let factor_revision = revision.clone();
        // Reuse the installed SDK's full Strategy library/archive contract. The
        // available Target type library creates no Manual Target node or Research work.
        let prepared = crate::workers::backtest_profile::spawn_blocking(move || {
            research_environment::prepare_strategy(
                &installation,
                &background.release_root,
                &compiled,
                &factor_revision,
                &background.native_version,
            )
        })
        .await
        .map_err(|_| "RESEARCH_PREPARATION_PROCESS_OUTCOME_UNKNOWN")??;
        let generation = text(prepared.manifest(), "runtime_generation_fingerprint")?.to_owned();
        let capabilities = prepared.proof()["native_descriptor"]["execution_capabilities"]
            .as_array()
            .ok_or(ENV_INVALID)?;
        if capabilities
            .iter()
            .filter(|row| {
                **row == json!({"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"})
            })
            .count()
            != 1
        {
            return Err("BACKTEST_EXECUTOR_UNAVAILABLE".into());
        }
        operation = self.preparation_checkpoint(&operation, human).await?;
        let (authority, source_session, selection) =
            self.preparation_sources(human, &input.source, true).await?;
        let root = config.runtime_root.clone();
        let command = operation.command.clone();
        let actor = operation.owner.clone();
        let expected = input.expected_active_generation.clone();
        let future = input.backtest_command_id.clone();
        let work = operation.request.reserved_run_id();
        let actual = generation.clone();
        let source = revision["source_text"]
            .as_str()
            .ok_or(ENV_INVALID)?
            .as_bytes()
            .to_vec();
        let at = now().map_err(|error| error.code())?;
        let binding = {
            let mut writer_hold = crate::workers::backtest_profile::HoldEnd::pending();
            let writer_wait = onlyalpha_observability::Operation::start(
                "backend",
                "writer.wait",
                onlyalpha_observability::Correlation::default(),
            );
            let mut writer = self
                .writer
                .lock()
                .instrument(writer_wait.span().clone())
                .await;
            writer_wait.finish("acquired", 1, 0);
            writer_hold.acquired("writer", "writer.hold");
            let _writer_release_begin = writer_hold.begin_release_marker();
            let session = writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            let tx = session
                .client_mut()
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?
                .transaction()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_UNAVAILABLE")?;
            crate::persistence::research_preparation::require_running_backtest_preparation(
                &tx,
                self.inputs.namespace(),
                &operation,
            )
            .await?;
            self.preparation_owner(human)?;
            authority
                .check_session(&source_session)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
            source_session
                .require_selection(&selection, Permission::ClosedHistory)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
            crate::persistence::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            let binding =
                crate::workers::backtest_profile::spawn_blocking(move || -> Result<Value> {
                    let mut registry = Registry::open_existing(&root)?;
                    let prior = original_activation(&root, &command)?;
                    if prior.is_none()
                        && registry.snapshot()["active_for_new_work"] != json!(expected)
                    {
                        return Err("GENERATION_ACTIVATION_CONFLICT".into());
                    }
                    prepared.publish(&mut registry, &source, &actor, at)?;
                    if prior.is_some()
                        || expected.as_deref() != Some(&actual)
                        || registry.snapshot()["active_for_new_work"] != actual
                    {
                        registry.activate(&command, &actual, expected.as_deref(), &actor, at)?;
                    } else {
                        let original = last_activation(&root)?
                            .ok_or("RESEARCH_ACTIVATION_PROOF_UNAVAILABLE")?;
                        if original["generation_fingerprint"] != actual {
                            return Err(ENV_INVALID.into());
                        }
                    }
                    registry
                        .bind_new_work_exact(&work, &actual, &future, &actor, at)
                        .map_err(Into::into)
                })
                .await
                .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")??;
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")?;
            crate::persistence::research_preparation::require_running_backtest_preparation(
                &tx,
                self.inputs.namespace(),
                &operation,
            )
            .await?;
            self.preparation_owner(human)?;
            authority
                .check_session(&source_session)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
            source_session
                .require_selection(&selection, Permission::ClosedHistory)
                .map_err(|_| "RESEARCH_SOURCE_ACCESS_DENIED")?;
            crate::persistence::authority_session::AuthoritySession::verify_transaction(&tx)
                .await
                .map_err(|_| "PRODUCT_AUTHORITY_UNAVAILABLE")?;
            tx.commit()
                .await
                .map_err(|_| "RESEARCH_PREPARATION_OUTCOME_UNKNOWN")?;
            binding
        };
        let mut outputs = operation.outputs.clone();
        outputs["environment"] =
            json!({"runtime_generation_fingerprint":generation,"binding":binding});
        operation = self
            .preparation_progress(&operation, State::Running, "INPUTS", &outputs, &Value::Null)
            .await?;
        retained_manual_backtest_environment(&config, &operation)?;
        Ok(operation)
    }
}
/// Original immutable Registry occurrence only, not a client cache or a current-image substitute.
pub(super) fn retained_manual_backtest_environment(
    config: &PreparationConfig,
    operation: &Operation,
) -> Result<()> {
    let input = operation.request.backtest()?;
    let environment = &operation.outputs["environment"];
    let generation = text(environment, "runtime_generation_fingerprint")?;
    let observed = Registry::inspect_work(
        &config.runtime_root,
        &operation.request.reserved_run_id(),
        generation,
        &input.backtest_command_id,
    )?;
    if observed["binding"] != environment["binding"] {
        return Err(ENV_INVALID.into());
    }
    let mut runtime = crate::persistence::research_runtime::RuntimeEvidenceHold::open(
        &config.runtime_root,
        &operation.request.reserved_run_id(),
        &input.backtest_command_id,
        generation,
    )?;
    let metadata = runtime.backtest_metadata(text(&release(config)?, "algorithm_artifact")?)?;
    if metadata.installed["release_manifest_sha256"] != input.release_manifest_fingerprint {
        return Err(ENV_INVALID.into());
    }
    if let Some(activation) = original_activation(&config.runtime_root, &operation.command)? {
        if activation["generation_fingerprint"] != generation
            || activation["actor"] != operation.owner
            || activation["expected_current"] != json!(input.expected_active_generation)
        {
            return Err(ENV_INVALID.into());
        }
    } else if input.expected_active_generation.as_deref() != Some(generation) {
        return Err("RESEARCH_ACTIVATION_PROOF_UNAVAILABLE".into());
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dependencies_follow_actual_saved_bindings_and_never_alias_period_inference() {
        let value: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_factor.json"
        ))
        .unwrap();
        let definition =
            crate::application::manual_backtest_context::btc_definition(&value["revision"])
                .unwrap()
                .to_record();
        let mut strategy = json!({"definition":definition});
        let bindings = explicit_factor_bindings(&strategy, &value["revision"]).unwrap();
        assert_eq!(bindings["close_lag_20"]["period"], 20);
        assert_eq!(bindings["close_lag_20"]["semantic_version"], "2");
        assert_eq!(bindings["volume_mean_20"]["semantic_version"], "2");
        // Saved old/unknown references remain exact input records. Current
        // native preparation rejects them instead of relabeling them as V2.
        for version in [Value::Null, json!("1"), json!("3")] {
            let mut historical = strategy.clone();
            for node in historical["definition"]["calculations"]
                .as_array_mut()
                .unwrap()
            {
                if node["type_reference"]["type_id"] == "onlyalpha.operator.delay" {
                    if version.is_null() {
                        node["type_reference"]
                            .as_object_mut()
                            .unwrap()
                            .remove("semantic_version");
                    } else {
                        node["type_reference"]["semantic_version"] = version.clone();
                    }
                }
            }
            let before = historical.clone();
            assert!(explicit_factor_bindings(&historical, &value["revision"]).is_err());
            assert_eq!(historical, before);
        }
        for node in strategy["definition"]["calculations"]
            .as_array_mut()
            .unwrap()
        {
            if node["type_reference"]["type_id"] == "onlyalpha.operator.delay" {
                node["parameters"]["period"]["value"]["value"] = json!(21);
            }
        }
        assert_eq!(
            explicit_factor_bindings(&strategy, &value["revision"]).unwrap()["close_lag_20"]["period"],
            21
        );
        let mut wrong = value["revision"].clone();
        wrong["revision_fingerprint"] = json!("f".repeat(64));
        assert!(explicit_factor_bindings(&strategy, &wrong).is_err());
    }
}
