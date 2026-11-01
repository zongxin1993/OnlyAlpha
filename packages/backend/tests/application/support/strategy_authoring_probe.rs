//! Technical DB probe, never a business acceptance or alternate Product entry point.
use onlyalpha_backend::{
    application::command::CommandId, persistence::private_strategy_postgres::Strategies,
};
use serde_json::{Value, json};
pub async fn run(request: &Value, client: &mut tokio_postgres::Client) -> Value {
    if matches!(
        request["action"].as_str(),
        Some("composition" | "resolution")
    ) {
        use onlyalpha_backend::{
            application::strategy_research::Context,
            persistence::{research_runtime::RuntimeInputHold, strategy_research::Composer},
        };
        let context = Context::new(request["context"].clone()).expect("controlled context");
        let mut runtime = RuntimeInputHold::open(
            std::path::Path::new(request["runtime_root"].as_str().unwrap()),
            "work",
            "research",
            request["runtime_generation"].as_str().unwrap(),
        )
        .expect("controlled storage fixture, not executable certification");
        if request["action"] == "resolution" {
            let installation = onlyalpha_calculation_bridge::ChartInstallation::open(
                std::path::Path::new(request["algorithm_root"].as_str().unwrap()),
                request["algorithm_artifact"].as_str().unwrap(),
            )
            .unwrap();
            return match Composer::new(client)
                .resolve(
                    request["strategy_id"].as_str().unwrap(),
                    request["revision_fingerprint"].as_str().unwrap(),
                    &context,
                    runtime,
                    &installation,
                )
                .await
            {
                Ok(value) => value.record().clone(),
                Err(error) => json!({"error":error.code()}),
            };
        }
        return match Composer::new(client)
            .compose(
                request["strategy_id"].as_str().unwrap(),
                request["revision_fingerprint"].as_str().unwrap(),
                &context,
                &mut runtime,
            )
            .await
        {
            Ok(value) => value.record().clone(),
            Err(code) => json!({"error":code}),
        };
    }
    let mut store = Strategies::new(client);
    let id = request["strategy_id"].as_str().unwrap();
    let owner = request["owner"].as_str().unwrap();
    let command = CommandId::new(request["command_id"].as_str().unwrap()).unwrap();
    let value = match request["action"].as_str().unwrap() {
        "context" => {
            use onlyalpha_backend::application::{
                private_strategy::Definition, strategy_research::Context,
            };
            (|| {
                let strategy = Definition::from_record(&request["definition"])?;
                let context = Context::new(request["context"].clone())?;
                let definition = context.definition(&strategy)?;
                Ok(
                    json!({"context":context.record(),"context_fingerprint":context.fingerprint()?,"definition":definition.record(),"definition_fingerprint":definition.fingerprint()?}),
                )
            })()
        }
        "read" => store.read(id).await,
        "list" => store.list().await,
        "exact" => {
            store
                .exact(
                    id,
                    request["revision_fingerprint"].as_str().unwrap(),
                    request["content_fingerprint"].as_str().unwrap(),
                )
                .await
        }
        "command" => store.command(id, owner, &command).await,
        "save" => {
            store
                .save(
                    &command,
                    owner,
                    id,
                    request["draft"].clone(),
                    request["expected"].as_str(),
                    request["accepted_at"].as_str().unwrap(),
                )
                .await
        }
        "publish" => {
            store
                .publish(
                    &command,
                    owner,
                    id,
                    request["expected"].as_str().unwrap(),
                    request["accepted_at"].as_str().unwrap(),
                )
                .await
        }
        _ => Err("PRIVATE_STRATEGY_INVALID"),
    };
    match value {
        Ok(value) => value,
        Err(code) => json!({"error":code}),
    }
}
