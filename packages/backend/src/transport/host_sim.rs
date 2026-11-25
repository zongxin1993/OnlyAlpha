use super::{
    host::{Failure, Host, invalid, now},
    host_factor_studies::{failed, input},
};
use crate::{
    application::{
        command::CommandId,
        sim_account::{self, AccountError, SimAccountRevisionPublishInput},
        sim_run::{self, StartContext, StartError},
    },
    persistence::{sim_account::Error as SimAccountError, sim_run::Error},
    security::{human_access::Session, ingress::{self, Release}},
};
use axum::{Json, body::{Body, to_bytes}, response::{IntoResponse, Response}};
use http::{Method, Request, StatusCode};
use std::time::Instant;

fn account_failure(error: AccountError) -> Failure {
    match error {
        AccountError::Access(error) => match error {
            crate::application::source_access::Error::Unauthorized => {
                Failure::with_status(StatusCode::UNAUTHORIZED, error.code())
            }
            crate::application::source_access::Error::Forbidden => {
                Failure::with_status(StatusCode::FORBIDDEN, error.code())
            }
            _ => failed(error.code()),
        },
        AccountError::OperatorRequired => {
            Failure::with_status(StatusCode::FORBIDDEN, "OWNER_OPERATION_DENIED")
        }
        AccountError::Storage(error) => match error {
            SimAccountError::Invalid => {
                Failure::with_status(StatusCode::BAD_REQUEST, "SIM_ACCOUNT_REVISION_INVALID")
            }
            SimAccountError::Missing => {
                Failure::with_status(StatusCode::NOT_FOUND, "SIM_ACCOUNT_REVISION_NOT_FOUND")
            }
            SimAccountError::Mismatch => {
                Failure::with_status(StatusCode::CONFLICT, "SIM_ACCOUNT_REVISION_MISMATCH")
            }
            SimAccountError::Unavailable => Failure::unavailable("SIM_ACCOUNT_REVISION_UNAVAILABLE"),
        },
        AccountError::UnknownCommit => Failure::unavailable("SIM_ACCOUNT_REVISION_OUTCOME_UNKNOWN"),
    }
}

fn failure(error: StartError) -> Failure {
    match error {
        StartError::Access(error) => match error {
            crate::application::source_access::Error::Unauthorized => Failure::with_status(StatusCode::UNAUTHORIZED, error.code()),
            crate::application::source_access::Error::Forbidden => Failure::with_status(StatusCode::FORBIDDEN, error.code()),
            _ => failed(error.code()),
        },
        StartError::Proof(code) => failed(code),
        StartError::Storage(error) => match error {
            Error::Invalid => Failure::with_status(StatusCode::BAD_REQUEST, "SIM_START_INTENT_INVALID"),
            Error::Missing => Failure::with_status(StatusCode::NOT_FOUND, "SIM_START_REFERENCE_NOT_FOUND"),
            Error::Mismatch => Failure::with_status(StatusCode::CONFLICT, "SIM_START_BINDING_MISMATCH"),
            Error::Conflict => Failure::with_status(StatusCode::CONFLICT, "SIM_START_CONFLICT"),
            Error::Integrity => Failure::unavailable("SIM_START_STORED_FACT_INVALID"),
            Error::Unavailable => Failure::unavailable("SIM_START_STORAGE_UNAVAILABLE"),
            Error::UnknownCommit => Failure::unavailable("SIM_START_OUTCOME_UNKNOWN"),
        },
    }
}

impl Host {
    pub(super) async fn sim_start_command(&self, request: Request<Body>, human: Session, deadline: Instant)
        -> Result<Response, Failure>
    {
        self.human_access.check_session(&human)?;
        if request.uri().query().is_some() { return Err(invalid()); }
        let (id, selection) = if request.method() == Method::POST {
            let (id, body) = input(request).await?;
            (id, Some(serde_json::from_value(body).map_err(|_| invalid())?))
        } else {
            let value = request.uri().path().strip_prefix("/api/v2/sim/commands/").ok_or_else(invalid)?;
            (CommandId::new(value).map_err(|_| invalid())?, None)
        };
        let mut writer = tokio::time::timeout_at(deadline.into(), self.writer.lock()).await
            .map_err(|_| Failure::unavailable("REQUEST_DEADLINE_EXPIRED"))?;
        let authority = writer.as_mut().ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        if !self.admitted() { return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY")); }
        let namespace = self.inputs.namespace();
        let view = if let Some(selection) = selection {
            let (frozen, _, decisions) = self.qualification_stores()?;
            let context = StartContext { deployment: namespace,
                runtime_root: &self.research_preparation_config.runtime_root,
                research_root: &self.research_preparation_config.research_root,
                frozen, decisions };
            sim_run::start_human_run(authority, &self.human_access, &human, &context, &id, selection, now()?).await
        } else {
            sim_run::observe_human_start(authority, &self.human_access, &human, namespace, &id).await
        }.map_err(failure)?;
        self.human_access.check_session(&human)?;
        Ok(ingress::attach(Json(view).into_response(), Release::Generation(human.metadata_session())))
    }

    pub(super) async fn sim_account_revision(
        &self,
        request: Request<Body>,
        human: Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        if !self.human_access.local_operator(human.subject_id()?) {
            return Err(Failure::with_status(StatusCode::FORBIDDEN, "OWNER_OPERATION_DENIED"));
        }
        if request.uri().query().is_some() {
            return Err(invalid());
        }
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let parts: Vec<_> = path.split('/').collect();
        let namespace = self.inputs.namespace();
        let view = match (method, parts.as_slice()) {
            (Method::POST, ["", "api", "v2", "sim", "accounts", account_id, "revisions"]) => {
                let bytes = to_bytes(request.into_body(), 65_536)
                    .await
                    .map_err(|_| invalid())?;
                ingress::validate_json(&bytes).map_err(|_| invalid())?;
                let payload: SimAccountRevisionPublishInput =
                    serde_json::from_slice(&bytes).map_err(|_| invalid())?;
                let mut writer = tokio::time::timeout_at(deadline.into(), self.writer.lock())
                    .await
                    .map_err(|_| Failure::unavailable("REQUEST_DEADLINE_EXPIRED"))?;
                let authority = writer
                    .as_mut()
                    .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
                if !self.admitted() {
                    return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
                }
                sim_account::publish_operator_revision(
                    authority,
                    &self.human_access,
                    &human,
                    namespace,
                    account_id,
                    payload,
                )
                .await
                .map_err(account_failure)?
            }
            (
                Method::GET,
                ["", "api", "v2", "sim", "accounts", account_id, "revisions", revision_fingerprint],
            ) => {
                let mut reader = tokio::time::timeout_at(deadline.into(), self.reader.lock())
                    .await
                    .map_err(|_| Failure::unavailable("REQUEST_DEADLINE_EXPIRED"))?;
                let client = reader
                    .as_mut()
                    .ok_or(Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
                if !self.admitted() {
                    return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
                }
                sim_account::read_operator_revision(
                    client,
                    &self.human_access,
                    &human,
                    namespace,
                    account_id,
                    revision_fingerprint,
                )
                .await
                .map_err(account_failure)?
            }
            _ => return Err(invalid()),
        };
        self.human_access.check_session(&human)?;
        Ok(ingress::attach(
            Json(view).into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}
