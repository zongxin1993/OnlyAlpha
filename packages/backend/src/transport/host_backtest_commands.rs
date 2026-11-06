//! Human commands around the original Backtest preparation owner.
//! This adapter validates syntax and projects outcomes; it never constructs a grant.
use super::*;
fn backtest_command_observation_error(
    command: &CommandId,
    code: &'static str,
) -> Result<serde_json::Value, Failure> {
    if code != crate::persistence::research_preparation::BACKTEST_NOT_ACCEPTED {
        return Err(Failure::unavailable(code));
    }
    serde_json::to_value(
        crate::transport::research_wire::BacktestCommandNotAccepted {
            schema_version: 2,
            command_id: command.value().into(),
            state: crate::transport::research_wire::BacktestCommandObservationState::NotAccepted,
        },
    )
    .map_err(|_| Failure::unavailable("BACKTEST_PREPARATION_OBSERVATION_UNAVAILABLE"))
}
impl Host {
    pub(super) async fn backtest_preparation_command(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let prefix = "/api/v2/backtest/preparations";
        if method == Method::GET {
            if Instant::now() >= deadline {
                return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
            }
            let tail = path
                .strip_prefix(prefix)
                .and_then(|v| v.strip_prefix('/'))
                .ok_or_else(invalid)?;
            let id = if let Some(id) = tail.strip_prefix("commands/") {
                id
            } else {
                tail.strip_suffix("/ready").ok_or_else(invalid)?
            };
            let id = CommandId::new(id).map_err(|_| invalid())?;
            let owner = human.subject_id()?.to_owned();
            let operation = {
                let mut reader = self.reader.lock().await;
                let client = reader
                    .as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                crate::persistence::research_preparation::Preparations::new(client)
                    .query_backtest_command(self.inputs.namespace(), &id, &owner)
                    .await
            };
            let value = match operation {
                Ok(operation) => self
                    .preparation_view(&operation, &human)
                    .await
                    .map_err(|error| Failure::unavailable(error.code()))?,
                Err(code) => backtest_command_observation_error(&id, code)?,
            };
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(
                Json(value).into_response(),
                Release::Generation(human.metadata_session()),
            ));
        }
        if method != Method::POST {
            return Err(invalid());
        }
        let (command, body) = input(request).await?;
        if Instant::now() >= deadline {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let value = if path == prefix {
            let input: crate::application::backtest_preparation::BacktestPrepareInput =
                serde_json::from_value(body).map_err(|_| invalid())?;
            self.accept_backtest_preparation(command, human.clone(), input)
                .await?
        } else {
            let tail = path
                .strip_prefix(prefix)
                .and_then(|v| v.strip_prefix('/'))
                .ok_or_else(invalid)?;
            let (id, action) = tail.split_once('/').ok_or_else(invalid)?;
            let id = CommandId::new(id).map_err(|_| invalid())?;
            self.require_backtest_preparation_kind(&human, &id).await?;
            match action {
                "resume" | "cancellation" => {
                    let input: BacktestPreparationRevisionInput =
                        serde_json::from_value(body).map_err(|_| invalid())?;
                    let revision = input.validate(&id).map_err(|_| invalid())?;
                    if action == "resume" {
                        if command != id {
                            return Err(invalid());
                        }
                        self.resume_research_preparation(human.clone(), &id, revision)
                            .await?
                    } else {
                        self.cancel_research_preparation(human.clone(), command, &id, revision)
                            .await?
                    }
                }
                "submit" => {
                    let input: BacktestConfirmationInput =
                        serde_json::from_value(body).map_err(|_| invalid())?;
                    input.validate(&id).map_err(|_| invalid())?;
                    let outcome = self
                        .confirm_backtest_preparation(
                            human.clone(),
                            &id,
                            &input.preparation_fingerprint,
                            &command,
                        )
                        .await?;
                    let run = outcome["run_id"].as_str().map(str::to_owned);
                    if run
                        .as_deref()
                        .is_some_and(|id| !crate::application::command::uuid4(id))
                        || (run.is_none() && outcome["state"] != "SUBMISSION_PENDING")
                    {
                        return Err(Failure::unavailable("BACKTEST_PREPARATION_OUTCOME_UNKNOWN"));
                    }
                    serde_json::to_value(BacktestConfirmationOutcome {
                        schema_version: 1,
                        backtest_command_id: command.value().into(),
                        state: if run.is_some() {
                            "ACCEPTED"
                        } else {
                            "OUTCOME_UNKNOWN"
                        }
                        .into(),
                        run_id: run,
                    })
                    .map_err(|_| Failure::unavailable("BACKTEST_PREPARATION_OUTCOME_UNKNOWN"))?
                }
                _ => return Err(invalid()),
            }
        };
        self.human_access.check_session(&human)?;
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}

#[cfg(test)]
#[path = "../../tests/transport/backtest_preparation_observation.rs"]
mod observation_response_tests;
