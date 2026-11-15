//! Controlled real PG/CH input-loader exercise, never a Product admission endpoint.
use onlyalpha_backend::{
    application::{
        factor_build::FactorBuildService,
        job_contract::FrozenJobBinding,
        job_input::{JobInputLoader, MemoryBudget},
        source_access::{Authority, Grant, Permission, Reference, Selection},
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::market_data::Storage,
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};
use std::{path::Path, sync::Arc};

pub async fn run(
    store: &mut Storage<'_>,
    request: &Value,
) -> Result<Value, Box<dyn std::error::Error>> {
    let setup = std::time::Instant::now();
    let text = |key: &str| request[key].as_str().ok_or("job input probe field missing");
    let binding = FrozenJobBinding::from_record(&request["binding"])?;
    let namespace = SemanticStoreId::new(binding.namespace())?;
    let reference = Reference::new(
        "job-input-test-integration",
        text("integration_revision")?,
        Some("test.market.source"),
    )?;
    let selection = Selection::new(reference, text("source")?, "LIVE")?;
    let grant = Grant::new(selection.clone(), vec![Permission::ClosedHistory])?;
    let authority = Authority::new(
        "human:job-input-test",
        "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",
        if request["deny"] == true {
            vec![]
        } else {
            vec![grant]
        },
    )?;
    let session = authority.authenticate(&format!("Bearer {}", "e".repeat(64)))?;
    if request["revoke"] == true {
        authority.withdraw();
    }
    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")?.parse()?;
    if config
        .get_dbname()
        .is_none_or(|name| !name.ends_with("_test"))
    {
        return Err("test DSN required".into());
    }
    config.user("onlyalpha_job_storage_test_login");
    let (mut client, connection) = config.connect(tokio_postgres::NoTls).await?;
    let driver = tokio::spawn(connection);
    let result = async {
        client.batch_execute(if request["build"] == true {"SET ROLE onlyalpha_factor_builder"} else {"SET ROLE onlyalpha_job_reader"}).await?;
        let installation = Arc::new(ChartInstallation::open(Path::new(text("installation")?), text("algorithm_artifact")?)?);
        let mut factors = FactorBuildService::new(&mut client, &namespace, installation).await?;
        if request["build"] == true {
            let revision = text("revision")?;
            factors.request(text("factor_id")?, revision, &json!({})).await?;
            let built = factors.run_pending().await?.ok_or("no pending actual build")?;
            if built.revision != revision { return Err("wrong actual build consumed".into()); }
            let ready = factors.resolve_ready_binding(text("factor_id")?, revision, &json!({})).await?;
            return Ok(json!({"source_parse_count":built.source_parse_count,"factor_binding":{"revision":ready.revision_fingerprint(),"program":ready.program_fingerprint(),"certificate":ready.certificate_fingerprint(),"parameters":ready.program().parameters().fingerprint(),"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1"}}));
        }
        let mut loader = JobInputLoader::new(store, &mut factors, &session, &selection);
        let budget = MemoryBudget::new(request["rows_limit"].as_u64().unwrap_or(8192).try_into()?, request["bytes_limit"].as_u64().unwrap_or(128*1024*1024).try_into()?)?;
        let count = request["samples"].as_u64().unwrap_or(2);
        if !(1..=20).contains(&count) {return Err("invalid samples".into());}
        let setup_us = setup.elapsed().as_micros();
        let mut results = Vec::new();
        for _ in 0..count {
            let input = loader.load(&binding, &budget).await?;
            let time = input.timings();
            let physical = &time.physical;
            results.push(json!({"binding":input.binding_fingerprint(),"snapshot":input.dataset().snapshot_fingerprint(),"content":input.dataset().content_fingerprint(),"rows":input.dataset().rows(),"bars":input.bars().iter().map(OnlyDomainModel::to_record).collect::<Vec<_>>(),"programs":input.factors().len(),"profile":{"total_us":time.total.as_micros(),"budget_meter_us":time.budget_meter.as_micros(),"final_guard_us":time.final_guard.as_micros(),"allocation_ns":time.allocation.as_nanos(),"source_us":time.source_read.as_micros(),"headers_us":physical.headers.as_micros(),"body_us":physical.body.as_micros(),"decode_us":physical.decode.as_micros(),"server_us":physical.server.as_micros(),"server_samples":physical.server_samples,"requests":physical.requests,"bytes":physical.bytes,"dataset_prepare_us":time.dataset_prepare.as_micros(),"allocation_us":time.allocation.as_micros(),"sort_us":time.sort.as_micros(),"digest_us":time.digest.as_micros(),"normalize_us":time.normalize.as_micros(),"axis_us":time.axis.as_micros(),"identity_us":time.identity.as_micros(),"program_preflight_us":time.program_preflight.as_micros(),"programs_us":time.programs.as_micros()}}));
        }
        let peak = std::fs::read_to_string("/proc/self/status")?.lines().find(|line| line.starts_with("VmHWM:")).ok_or("VmHWM missing")?.to_owned();
        Ok::<_,Box<dyn std::error::Error>>(json!({"samples":results,"peak":peak,"setup_us":setup_us}))
    }.await;
    drop(client);
    driver.await??;
    result
}
