//! Actual installed manual validation producer over canonical isolated inputs.
//! Never a Shipping endpoint, fake opaque seal or Research publication fixture.
use crate::{
    application::{
        backtest_preparation::{BacktestOrigin, BacktestPrepareInput},
        command::CommandId,
        research_dataset::NativeMaterializationPlan,
        research_factor,
        research_run_execution::Control,
        strategy_validation::ResolvedValidation,
    },
    bootstrap::{deployment, research_namespace},
    persistence::{
        authority_session::AuthoritySession,
        market_data::{Catalog, ClickHouse, ClickHouseConfig, Scope, Storage},
        research_dataset::Store as Datasets,
        research_preparation::{self, BacktestAcceptance, Preparations, State},
        research_runtime::{Registry, RuntimeInputHold},
        strategy_validation::Store as Validations,
    },
    security::human_access::{Access, Admission},
    workers::research_environment,
};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::{Value, json};
use std::{path::Path, sync::Arc, time::Duration};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .ok_or_else(|| format!("missing fixture {key}").into())
}
fn out(value: Value) {
    println!("MANUAL_PRODUCER_VALUE {value}");
    std::io::Write::flush(&mut std::io::stdout()).unwrap();
}
pub async fn run_phase(
    session: &mut AuthoritySession,
    research_root: &Path,
    phase: &str,
) -> Result<()> {
    let request: Value = serde_json::from_slice(&std::fs::read(std::env::var(
        "ONLYALPHA_MANUAL_PRODUCER_REQUEST",
    )?)?)?;
    let semantic = Path::new(text(&request, "semantic_root")?);
    let runtime_root = Path::new(text(&request, "runtime_root")?);
    let at = text(&request, "at")?.parse()?;
    if phase == "environment" {
        assert_eq!(semantic.join("research"), research_root);
        let namespace = research_namespace::initialize_fresh(semantic)?;
        // Explicit isolated Infrastructure initialization, not a business fact.
        session.client_mut().await?.execute("INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,$1::text::uuid)",&[&namespace.value()]).await?;
        deployment::verify_binding(session.client_mut().await?, &namespace).await?;
        research_namespace::extend_strategy(semantic, session).await?;
        research_namespace::extend_manual_backtest(semantic, session).await?;
        let release = Path::new(text(&request, "release_root")?);
        let installation = ChartInstallation::open(
            &release.join("algorithms"),
            text(&request, "algorithm_artifact")?,
        )?;
        let vector = &request["factor"];
        let factor =
            research_factor::compile(&vector["candidate"], &vector["draft"], &vector["revision"])?;
        // This exact currently executing ELF is sealed in release/bin. The
        // installed SDK can register Target types; no Target node is built.
        let prepared = research_environment::prepare_strategy(
            &installation,
            release,
            &factor,
            &vector["revision"],
            env!("CARGO_PKG_VERSION"),
        )?;
        let generation = text(prepared.manifest(), "runtime_generation_fingerprint")?.to_owned();
        let mut registry = Registry::initialize_fresh(runtime_root)?;
        prepared.publish(
            &mut registry,
            text(&vector["revision"], "source_text")?.as_bytes(),
            "technical-fixture",
            at,
        )?;
        registry.activate(
            &CommandId::new(text(&request, "activation_command_id")?)?,
            &generation,
            None,
            "technical-fixture",
            at,
        )?;
        out(
            json!({"namespace":namespace.value(),"runtime_generation":generation,"installed_proof":prepared.proof()["installed_proof_fingerprint"]}),
        );
        return Ok(());
    }
    assert!(matches!(phase, "produce" | "bound-without-environment"));
    let command = CommandId::new(text(&request, "preparation_command_id")?)?;
    let future = CommandId::new(text(&request, "backtest_command_id")?)?;
    let namespace =
        deployment::load_semantic_store_id(&research_root.join(".onlyalpha-semantic-store.json"))?;
    let access = Access::new(&"a".repeat(64))?;
    let message = http::Request::builder()
        .uri("/api/v2/integration-types")
        .header("host", "127.0.0.1:5173")
        .header(
            "cookie",
            format!("onlyalpha_dev_session={}", "a".repeat(64)),
        )
        .body(())?;
    let Admission::Owner(human) = access.admit(&message)? else {
        return Err("actual fixture Human owner required".into());
    };
    assert_eq!(human.subject_id()?, "local-developer");
    let input = BacktestPrepareInput {
        schema_version: 2,
        profile: "BTC_SPOT_NEXT_OPEN_BACKTEST_V1".into(),
        origin: BacktestOrigin::ManualStrategy {
            strategy_id: text(&request, "strategy_id")?.into(),
            strategy_revision_fingerprint: text(&request, "strategy_revision")?.into(),
        },
        source: serde_json::from_value(request["selected_source"].clone())?,
        release_manifest_fingerprint: text(&request, "release_manifest_fingerprint")?.into(),
        expected_active_generation: Some(text(&request, "runtime_generation")?.into()),
        initialize_fresh_runtime: false,
        backtest_command_id: future.value().into(),
    };
    check_original_pre_accept_observation(session, &namespace, &command, &input).await?;
    let authoring = research_preparation::manual_backtest_authoring(
        session.client_mut().await?,
        &namespace,
        &input,
    )
    .await?;
    let mut operation = research_preparation::accept_backtest(
        session,
        &namespace,
        (&access, &human),
        &command,
        input.clone(),
        BacktestAcceptance::Manual(&authoring),
        at,
    )
    .await?;
    let observed = Preparations::new(session.client_mut().await?)
        .existing_backtest(&command, "local-developer", &input)
        .await?
        .ok_or("accepted original missing")?;
    assert_eq!(observed.accepted, operation.accepted);
    let by_command = Preparations::new(session.client_mut().await?)
        .query_backtest_command(&namespace, &command, "local-developer")
        .await?;
    assert_eq!(by_command.accepted, operation.accepted);
    assert!(matches!(
        Preparations::new(session.client_mut().await?)
            .query_backtest_command(&namespace, &command, "a-foreign-owner")
            .await,
        Err("RESEARCH_PREPARATION_COMMAND_CONFLICT")
    ));
    let mut foreign = input.clone();
    foreign.release_manifest_fingerprint = if input.release_manifest_fingerprint == "a".repeat(64) {
        "b".repeat(64)
    } else {
        "a".repeat(64)
    };
    assert!(matches!(
        Preparations::new(session.client_mut().await?)
            .existing_backtest(&command, "local-developer", &foreign)
            .await,
        Err("RESEARCH_PREPARATION_COMMAND_CONFLICT")
    ));
    operation = Preparations::new(session.client_mut().await?)
        .progress(
            &operation,
            State::Running,
            "VALIDATING",
            &operation.outputs,
            &Value::Null,
        )
        .await?;
    let binding = {
        let mut registry = Registry::open_existing(runtime_root)?;
        registry.bind_new_work_exact(
            &operation.request.reserved_run_id(),
            text(&request, "runtime_generation")?,
            future.value(),
            "local-developer",
            at,
        )?
    };
    if phase == "bound-without-environment" {
        assert_eq!(operation.state, State::Running);
        assert!(operation.outputs.get("environment").is_none());
        out(
            json!({"preparation_command_id":command.value(),"backtest_command_id":future.value(),"work_id":operation.request.reserved_run_id(),
            "owner":"local-developer","runtime_root":runtime_root,"at":request["at"],"state":"RUNNING","bound_without_environment":true,"pre_accept_observation_checks":true}),
        );
        return Ok(());
    }
    let mut outputs = operation.outputs.clone();
    outputs["environment"] =
        json!({"runtime_generation_fingerprint":request["runtime_generation"],"binding":binding});
    operation = Preparations::new(session.client_mut().await?)
        .progress(&operation, State::Running, "INPUTS", &outputs, &Value::Null)
        .await?;
    let datasets = Datasets::open(&research_root.join("datasets"), 8192, 8 * 1024 * 1024)?;
    let ch = ClickHouse::new(ClickHouseConfig {
        url: text(&request, "url")?.into(),
        database: text(&request, "database")?.into(),
        user: std::env::var("ONLYALPHA_CLICKHOUSE_USER").unwrap_or("default".into()),
        password: std::env::var("ONLYALPHA_CLICKHOUSE_PASSWORD").unwrap_or_default(),
        timeout: Duration::from_secs(5),
        tls_roots_pem: vec![],
        max_bytes: 32 * 1024 * 1024,
        max_rows: 10000,
    })?;
    ch.assert_server().await?;
    let materialized = {
        let catalog = Catalog::new(session.client_mut().await?, 10000, 32 * 1024 * 1024)?;
        let mut market = Storage::new(catalog, &ch, 10000)?;
        NativeMaterializationPlan::new(
            &request["definition"],
            text(&request, "id")?,
            Scope::from_record(&request["scope"])?,
            8192,
        )?
        .materialize(&mut market, &datasets, text(&request, "at")?)
        .await?
    };
    let materialization = materialized.lineage()["materialization_id"].clone();
    let installation = Arc::new(ChartInstallation::open(
        Path::new(text(&request, "algorithm_root")?),
        text(&request, "algorithm_artifact")?,
    )?);
    let control = Control::default();
    let runtime = RuntimeInputHold::open(
        runtime_root,
        &operation.request.reserved_run_id(),
        future.value(),
        text(&request, "runtime_generation")?,
    )?;
    let resolved = ResolvedValidation::resolve(
        session.client_mut().await?,
        &operation,
        runtime,
        installation.clone(),
        &datasets,
        &control,
    )
    .await?;
    assert_eq!(resolved.input_window()["dataset_observation_capacity"], 740);
    assert_eq!(resolved.input_window()["observation_capacity"], 720);
    assert!(
        resolved.record()["algorithm_resolution_request"]["instances"]
            .as_array()
            .unwrap()
            .iter()
            .all(|c| c["type_reference"]["kind"] != "TARGET")
    );
    let joined = tokio::task::spawn_blocking(move || {
        resolved.observe(
            installation,
            env!("CARGO_PKG_VERSION"),
            &control,
            &datasets,
            &materialized,
        )
    })
    .await??;
    let store = Validations::open(research_root)?.with_runtime_root(runtime_root)?;
    let verified = store.publish(session, joined).await?;
    verified.verify_cut()?;
    let reopened = store
        .read_verified(session.client_mut().await?, command.value())
        .await?;
    assert_eq!(reopened.record(), verified.record());
    assert_eq!(reopened.preparation_command_id(), command.value());
    let observed = Preparations::new(session.client_mut().await?)
        .query(&command, "local-developer")
        .await?;
    assert_eq!(observed.state, State::Running);
    assert!(observed.outputs.get("ready").is_none());
    let row=session.client_mut().await?.query_one("SELECT (SELECT count(*) FROM research_run),(SELECT count(*) FROM research_strategy_study_authorization),(SELECT count(*) FROM private_strategy_research_composition),(SELECT count(*) FROM product_command_admission WHERE command_kind='CREATE_RESEARCH_RUN')",&[]).await?;
    for index in 0..4 {
        assert_eq!(
            row.try_get::<_, i64>(index)?,
            0,
            "manual mathematical validation must not create Research authority"
        );
    }
    out(
        json!({"preparation_command_id":command.value(),"owner":"local-developer","runtime_root":runtime_root,"at":request["at"],
        "state":"RUNNING","pre_accept_observation_checks":true,"validation_fingerprint":verified.fingerprint(),"strategy_fingerprint":verified.source_revision().fingerprint(),
        "dataset_materialization_id":materialization,"runtime_generation":verified.runtime_generation_fingerprint()}),
    );
    Ok(())
}

/// Actual PG Command state, not a DTO grant. Admitted uncertainty is injected
/// only inside a rollback-only transaction; the real preparation then follows.
async fn check_original_pre_accept_observation(
    session: &mut AuthoritySession,
    namespace: &deployment::SemanticStoreId,
    command: &CommandId,
    input: &BacktestPrepareInput,
) -> Result<()> {
    use crate::{
        application::{
            command::{Admission as CommandAdmission, CommandKind},
            factor_content::hash,
        },
        persistence::postgres::Commands,
    };
    let owner = "local-developer";
    assert!(
        Preparations::new(session.client_mut().await?)
            .existing_backtest(command, owner, input)
            .await?
            .is_none()
    );
    assert!(matches!(
        Preparations::new(session.client_mut().await?)
            .query_backtest_command(namespace, command, owner)
            .await,
        Err(research_preparation::BACKTEST_NOT_ACCEPTED)
    ));
    let foreign_namespace = deployment::SemanticStoreId::new(
        if namespace.value() == "00000000-0000-4000-8000-000000009940" {
            "00000000-0000-4000-8000-000000009941"
        } else {
            "00000000-0000-4000-8000-000000009940"
        },
    )?;
    let wrong = Preparations::new(session.client_mut().await?)
        .query_backtest_command(&foreign_namespace, command, owner)
        .await;
    assert!(
        wrong.is_err() && !matches!(wrong, Err(research_preparation::BACKTEST_NOT_ACCEPTED)),
        "an empty wrong namespace is not original-Command absence"
    );
    let prior_snapshot = session
        .client_mut()
        .await?
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await?;
    assert!(
        matches!(
            research_preparation::backtest_command_in_transaction(
                &prior_snapshot,
                namespace,
                command,
                owner
            )
            .await,
            Err("RESEARCH_PREPARATION_UNAVAILABLE")
        ),
        "a snapshot selected before an original Command barrier cannot prove new absence"
    );
    prior_snapshot.commit().await?;
    let request = research_preparation::PreparationRequest::Backtest(input.clone());
    let tx = session.client_mut().await?.transaction().await?;
    let intent =
        hash(&json!({"contract":"ONLYALPHA_BACKTEST_PREPARATION_V2","owner":owner,"input":input}))?;
    let admission = CommandAdmission::new(command.clone(), CommandKind::PrepareBacktest, &intent)?;
    Commands::admit_exact_in_transaction(&tx, &admission).await?;
    assert!(matches!(
        research_preparation::existing_request_in_transaction(&tx, command, owner, &request).await,
        Err("RESEARCH_PREPARATION_OUTCOME_UNKNOWN")
    ));
    assert!(matches!(
        research_preparation::backtest_command_in_transaction(&tx, namespace, command, owner).await,
        Err("RESEARCH_PREPARATION_OUTCOME_UNKNOWN")
    ));
    tx.rollback().await?;
    assert!(
        Preparations::new(session.client_mut().await?)
            .existing_backtest(command, owner, input)
            .await?
            .is_none()
    );
    let (mut reader, connection) = tokio_postgres::connect(
        &std::env::var("ONLYALPHA_POSTGRES_DSN")?,
        tokio_postgres::NoTls,
    )
    .await?;
    let driver = tokio::spawn(connection);
    driver.abort();
    assert!(driver.await.is_err());
    assert!(
        matches!(
            Preparations::new(&mut reader)
                .existing_backtest(command, owner, input)
                .await,
            Err("RESEARCH_PREPARATION_UNAVAILABLE")
        ),
        "a lost original read driver is uncertainty, never observed absence"
    );
    assert!(matches!(
        Preparations::new(&mut reader)
            .query_backtest_command(namespace, command, owner)
            .await,
        Err("RESEARCH_PREPARATION_UNAVAILABLE")
    ));
    Ok(())
}
