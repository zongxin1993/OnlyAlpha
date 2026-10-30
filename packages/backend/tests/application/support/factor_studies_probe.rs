//! Technical PostgreSQL assertions only; never a Shipping user workflow.
use onlyalpha_backend::{
    application::command::CommandId, persistence::factor_studies::Studies,
    security::proposal_access::Presented,
};
use serde_json::{Value, json};

pub async fn run(request: &Value, client: &mut tokio_postgres::Client) -> Value {
    let result = async {
        let command = CommandId::new(request["command_id"].as_str().ok_or("command")?)
            .map_err(|e| e.code())?;
        let actor = request["actor"].as_str().ok_or("actor")?;
        let at = request["at"].as_str().ok_or("at")?;
        let credential = request["token"]
            .as_str()
            .map(Presented::parse)
            .transpose()?;
        let c = credential.as_ref();
        let body = request["body"].clone();
        if request["action"] == "historical-read-only" && c.is_none() {
            client.batch_execute("SET default_transaction_read_only=on").await.map_err(|_| "readonly session")?;
            let read_only: String = client.query_one("SHOW default_transaction_read_only", &[]).await.map_err(|_| "readonly observation")?.get(0);
            if read_only != "on" { return Err("readonly session required"); }
            let factor = onlyalpha_backend::persistence::factor_proposals::Proposals::new(client)
                .read(request["factor_proposal_fingerprint"].as_str().ok_or("factor")?, actor, None, at).await?;
            let study = Studies::new(client)
                .read(request["fingerprint"].as_str().ok_or("study")?, actor, None, at).await?;
            let permission = Studies::new(client).observe(
                &CommandId::new(request["grant_command"].as_str().ok_or("grant command")?).map_err(|e| e.code())?, actor, None, at).await?;
            let stage = Studies::new(client).observe(
                &CommandId::new(request["observed_command"].as_str().ok_or("stage command")?).map_err(|e| e.code())?, actor, None, at).await?;
            return Ok(json!({"read_only":read_only,"factor":factor,"study":study,"permission":permission,"stage":stage}));
        }
        let mut studies = Studies::new(client);
        match request["action"].as_str() {
            Some("grant") if c.is_none() => {
                studies
                    .grant(
                        &command,
                        actor,
                        serde_json::from_value(body).map_err(|_| "input")?,
                        at,
                    )
                    .await
            }
            Some("stage") => {
                studies
                    .stage(
                        &command,
                        c.ok_or("credential")?,
                        serde_json::from_value(body).map_err(|_| "input")?,
                        at,
                    )
                    .await
            }
            Some("withdraw") if c.is_none() && body["schema_version"] == 1 => {
                studies
                    .withdraw(
                        &command,
                        actor,
                        body["study_proposal_fingerprint"].as_str().ok_or("input")?,
                        at,
                    )
                    .await
            }
            Some("human-context") if c.is_none() => {
                studies
                    .human_context(
                        request["factor_proposal_fingerprint"]
                            .as_str()
                            .ok_or("input")?,
                        actor,
                        at,
                    )
                    .await
            }
            Some("context") => {
                studies
                    .context(
                        c.ok_or("credential")?,
                        request["factor_proposal_fingerprint"]
                            .as_str()
                            .ok_or("input")?,
                        at,
                    )
                    .await
            }
            Some("read") => {
                studies
                    .read(
                        request["fingerprint"].as_str().ok_or("input")?,
                        actor,
                        c,
                        at,
                    )
                    .await
            }
            Some("observe") => {
                studies
                    .observe(
                        &CommandId::new(request["observed_command"].as_str().ok_or("command")?)
                            .map_err(|e| e.code())?,
                        actor,
                        c,
                        at,
                    )
                    .await
            }
            _ => Err("FACTOR_STUDY_PROPOSAL_INVALID"),
        }
    }
    .await;
    match result {
        Ok(value) => value,
        Err(code) => json!({"error":code}),
    }
}
