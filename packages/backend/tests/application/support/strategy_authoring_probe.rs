//! Technical DB probe, never a business acceptance or alternate Product entry point.
use onlyalpha_backend::{
    application::command::CommandId, persistence::private_strategy_postgres::Strategies,
};
use serde_json::{Value, json};
pub async fn run(request: &Value, client: &mut tokio_postgres::Client) -> Value {
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
