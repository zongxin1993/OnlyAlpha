//! Human Freeze commands reuse the sole durable publisher and original receipts.
use crate::{
    application::{
        command::CommandId,
        frozen_strategy::FrozenStore,
        strategy_projection::{self, FreezeRequest, Freezes},
    },
    bootstrap::startup::Directory,
    persistence::{research_evidence::Store as Evidence, research_submission},
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, ROWS, WORK, invalid, now},
        host_factor_studies::{failed, input},
        research_wire::StrategyFreezeInput,
    },
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use std::{sync::Arc, time::Instant};
impl Host {
    pub(crate) async fn strategy_freeze_command(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        let owner = human.subject_id()?.to_owned();
        if request.uri().query().is_some() {
            return Err(invalid());
        }
        let path = request.uri().path().to_owned();
        let original = path.strip_prefix("/api/v2/strategy-freezes/commands/");
        if request.method() == Method::GET {
            let id = CommandId::new(original.ok_or_else(invalid)?).map_err(|_| invalid())?;
            let result = {
                let mut reader = self.reader.lock().await;
                let client = reader
                    .as_mut()
                    .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                strategy_projection::freeze_outcome(client, self.inputs.namespace(), &owner, &id)
                    .await
                    .map_err(failed)?
            };
            self.human_access.check_session(&human)?;
            return Ok(ingress::attach(
                Json(result).into_response(),
                Release::Generation(human.metadata_session()),
            ));
        }
        if request.method() != Method::POST {
            return Err(invalid());
        }
        let (command, raw) = input(request).await?;
        let body: StrategyFreezeInput =
            serde_json::from_value(raw.clone()).map_err(|_| invalid())?;
        let intent = FreezeRequest::new(
            command.clone(),
            &body.research_run_id,
            &body.candidate_fingerprint,
            body.comment.as_deref(),
        )
        .map_err(failed)?;
        if let Some(tail) = original {
            let id = CommandId::new(tail.strip_suffix("/resume").ok_or_else(invalid)?)
                .map_err(|_| invalid())?;
            if id != command {
                return Err(invalid());
            }
            let observed = {
                let mut reader = self.reader.lock().await;
                let client = reader
                    .as_mut()
                    .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                strategy_projection::freeze_outcome(client, self.inputs.namespace(), &owner, &id)
                    .await
                    .map_err(failed)?
            };
            if observed["state"] == "NOT_SUBMITTED" || observed["request"] != raw {
                return Err(failed("STRATEGY_FREEZE_COMMAND_CONFLICT"));
            }
        } else if path != "/api/v2/strategy-freezes" {
            return Err(invalid());
        }
        let run = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            research_submission::load(client, intent.run_id().map_err(failed)?, Some(&owner))
                .await
                .map_err(failed)?
        };
        run.strategy_specification().map_err(failed)?;
        let research = self.research_preparation_config.research_root.clone();
        let runtime = self.research_preparation_config.runtime_root.clone();
        let evidence = tokio::task::spawn_blocking(move || {
            Evidence::open(&research)?
                .with_runtime_root(&runtime)?
                .read_verified_strategy(&run)
        })
        .await
        .map_err(|_| Failure::unavailable("STRATEGY_RESEARCH_EVIDENCE_UNAVAILABLE"))?
        .map_err(failed)?;
        if Instant::now() >= deadline {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        self.human_access.check_session(&human)?;
        let frozen = FrozenStore::open(self.inputs.roots().directory(Directory::Research))
            .map_err(|e| failed(e.code()))?;
        let result = {
            let mut writer = self.writer.lock().await;
            let session = writer
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            Freezes::new(session, &frozen, self.inputs.namespace(), &human)
                .execute(&intent, &evidence, &now()?.to_string(), ROWS, WORK)
                .await
                .map_err(failed)?
        };
        self.human_access.check_session(&human)?;
        Ok(ingress::attach(
            Json(result).into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}
