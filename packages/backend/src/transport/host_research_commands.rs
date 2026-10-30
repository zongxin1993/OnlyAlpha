//! Human-only Product commands around the retained preparation and Run owners.
use crate::{
    application::{command::CommandId, factor_studies::PrepareInput},
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, invalid},
        host_factor_studies::input,
        research_wire::*,
    },
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use std::{sync::Arc, time::Instant};
fn revision(input: &FactorResearchPreparationRevisionInput) -> Result<i64, Failure> {
    let n = input
        .expected_revision
        .parse::<i64>()
        .map_err(|_| invalid())?;
    if input.schema_version != 1 || n < 0 || n.to_string() != input.expected_revision {
        return Err(invalid());
    }
    Ok(n)
}
impl Host {
    pub(crate) async fn research_preparation_command(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        if method == Method::GET
            && let Some(pin) = path.strip_prefix("/api/v2/factor-study-preparation-context/")
        {
            return self.research_preparation_context(human, pin).await;
        }
        if method == Method::GET
            && let Some(id) = path.strip_prefix("/api/v2/factor-study-preparations/commands/")
        {
            let id = CommandId::new(id).map_err(|_| invalid())?;
            let value = self.research_preparation(human.clone(), &id).await?;
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
        let value = if path == "/api/v2/factor-study-preparations" {
            let body: PrepareInput = serde_json::from_value(body).map_err(|_| invalid())?;
            self.accept_research_preparation(command, human.clone(), body)
                .await?
        } else {
            let tail = path
                .strip_prefix("/api/v2/factor-study-preparations/")
                .ok_or_else(invalid)?;
            let (id, action) = tail.split_once('/').ok_or_else(invalid)?;
            let id = CommandId::new(id).map_err(|_| invalid())?;
            match action {
                "resume" | "cancellation" => {
                    let body: FactorResearchPreparationRevisionInput =
                        serde_json::from_value(body).map_err(|_| invalid())?;
                    if body.preparation_command_id != id.value() {
                        return Err(invalid());
                    }
                    let expected = revision(&body)?;
                    if action == "resume" {
                        if command != id {
                            return Err(invalid());
                        }
                        self.resume_research_preparation(human.clone(), &id, expected)
                            .await?
                    } else {
                        self.cancel_research_preparation(human.clone(), command, &id, expected)
                            .await?
                    }
                }
                "confirmation" => {
                    let body: FactorResearchConfirmationInput =
                        serde_json::from_value(body).map_err(|_| invalid())?;
                    if body.schema_version != 1
                        || body.preparation_command_id != id.value()
                        || !crate::is_sha256_hex(&body.prepared_study_fingerprint)
                    {
                        return Err(invalid());
                    }
                    let outcome = self
                        .confirm_research_preparation(
                            human.clone(),
                            &id,
                            &body.prepared_study_fingerprint,
                            &command,
                        )
                        .await?;
                    let run = outcome["run_id"].as_str().map(str::to_owned);
                    if run.is_none() && outcome["state"] != "SUBMISSION_PENDING" {
                        return Err(Failure::unavailable(
                            "RESEARCH_CONFIRMATION_OUTCOME_UNKNOWN",
                        ));
                    }
                    serde_json::to_value(FactorResearchConfirmationOutcome {
                        schema_version: 1,
                        research_command_id: command.value().into(),
                        state: if run.is_some() {
                            "ACCEPTED"
                        } else {
                            "OUTCOME_UNKNOWN"
                        }
                        .into(),
                        run_id: run,
                    })
                    .map_err(|_| Failure::unavailable("RESEARCH_CONFIRMATION_OUTCOME_UNKNOWN"))?
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
mod tests {
    use super::*;
    #[test]
    fn public_revision_counters_do_not_pass_through_javascript_numbers() {
        let mut input = FactorResearchPreparationRevisionInput {
            schema_version: 1,
            preparation_command_id: "00000000-0000-4000-8000-000000000001".into(),
            expected_revision: "9007199254740993".into(),
        };
        assert_eq!(revision(&input).unwrap(), 9_007_199_254_740_993);
        for value in ["01", "+1", "-1", " 1", "9223372036854775808"] {
            input.expected_revision = value.into();
            assert!(revision(&input).is_err());
        }
    }
}
