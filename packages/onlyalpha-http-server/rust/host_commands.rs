//! Thin admitted Human commands; every durable effect uses the retained physical
//! AuthoritySession. No provider or algorithm wait holds that business borrow.
use crate::host::{Failure, Host, ROWS, WORK, invalid, now, parameters, required};
use crate::wire::*;
use axum::{
    Json,
    body::{Body, to_bytes},
    response::{IntoResponse, Response},
};
use http::{Method, Request, StatusCode};
use onlyalpha_integration_contract::IntegrationTypeId;
use onlyalpha_product_runtime::{
    command::CommandId,
    integration_commands::{
        self as commands, ClearSecret, CreateIntegration, PublishRevision, ResetDraftContract,
        SetLifecycle, SetSecret, UpdateDraft,
    },
    integration_configuration::{IntegrationId, Lifecycle, ObjectDocument},
    integration_postgres::Integrations,
    watchlist_postgres::Watchlists,
    watchlists::{Book, List, Member},
};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::{sync::Arc, time::Instant};
impl From<commands::Error> for Failure {
    fn from(e: commands::Error) -> Self {
        use commands::Error::*;
        Self::with_status(
            match e {
                NotFound | DraftNotFound => StatusCode::NOT_FOUND,
                InvalidConfiguration | SecretField => StatusCode::BAD_REQUEST,
                DraftVersion
                | BaseRevision
                | LifecycleConflict
                | TypeChanged
                | Archived
                | Command(onlyalpha_product_runtime::command::Error::Conflict) => {
                    StatusCode::CONFLICT
                }
                Model(model) => return Self::from(model),
                _ => StatusCode::SERVICE_UNAVAILABLE,
            },
            e.code(),
        )
    }
}
// Only explicit owning command rejections may reopen Source admission after
// cutoff. Persistence conflicts/corruption and UNKNOWN are not user rejections.
fn source_reissue_rejection(error: &commands::Error) -> bool {
    matches!(
        error,
        commands::Error::InvalidConfiguration
            | commands::Error::SecretField
            | commands::Error::BaseRevision
            | commands::Error::DraftVersion
            | commands::Error::DraftNotFound
            | commands::Error::TypeChanged
            | commands::Error::Archived
            | commands::Error::LifecycleConflict
            | commands::Error::NotFound
            | commands::Error::Command(onlyalpha_product_runtime::command::Error::Conflict)
    )
}
fn decode<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, Failure> {
    serde_json::from_slice(bytes).map_err(|_| invalid())
}
fn version(n: i64) -> Result<i32, Failure> {
    i32::try_from(n).ok().filter(|n| *n > 0).ok_or_else(invalid)
}
fn command(request: &Request<Body>) -> Result<CommandId, Failure> {
    let mut values = request.headers().get_all("idempotency-key").iter();
    let value = values
        .next()
        .and_then(|v| v.to_str().ok())
        .ok_or_else(invalid)?;
    if values.next().is_some() {
        return Err(invalid());
    }
    CommandId::new(value).map_err(|_| invalid())
}
fn response(result: commands::CommandResult, integration_id: &str) -> Response {
    Json(json!({"schema_version":1,"command_id":result.receipt.admission().id().value(),"integration_id":integration_id,"replayed":result.replayed,"outcome_kind":result.receipt.outcome().kind().as_str(),"outcome_id":result.receipt.outcome().id()})).into_response()
}
impl Host {
    pub(crate) async fn integration_command(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let human = request
            .extensions()
            .get::<crate::human_access::Session>()
            .cloned()
            .ok_or(Failure::unavailable("HUMAN_SESSION_UNAVAILABLE"))?;
        let path = request.uri().path().to_owned();
        let method = request.method().clone();
        let p = parameters(request.uri())?;
        let id = command(&request)?;
        let bytes = to_bytes(request.into_body(), 65536)
            .await
            .map_err(|_| invalid())?;
        let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
        let mut writer = self.writer.lock().await;
        let authority = writer
            .as_mut()
            .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        let client = authority
            .client_mut()
            .await
            .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        // The ingress deadline is retained across both queueing and the physical
        // AuthoritySession proof. No first durable effect starts after that deadline.
        if deadline <= Instant::now() {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let accepted_at = now()?;
        let mut store = Integrations::new(client);
        let mut rejected = false;
        let outcome: Result<(commands::CommandResult, String, bool), Failure> = async {
            let result = match (parts.as_slice(), method) {
                (["api", "v2", "integrations"], Method::POST) => {
                    let dto: IntegrationCreateRequestDto = decode(&bytes)?;
                    let owner = IntegrationId::new(&dto.integration_id).map_err(|_| invalid())?;
                    let cmd = CreateIntegration::new(
                        id,
                        owner,
                        IntegrationTypeId::new(&dto.type_id).map_err(|_| invalid())?,
                        &dto.display_name,
                    )?;
                    (
                        store.create(&cmd, &self.catalog, accepted_at, WORK).await?,
                        dto.integration_id,
                        false,
                    )
                }
                (["api", "v2", "integrations", integration, "draft"], Method::PUT) => {
                    let dto: IntegrationDraftUpdateRequestDto = decode(&bytes)?;
                    // Validate the typed shape, preserve original metadata number kinds/bytes.
                    let raw: std::collections::BTreeMap<String, Box<serde_json::value::RawValue>> =
                        decode(&bytes)?;
                    let public = ObjectDocument::new(
                        raw.get("public_configuration").ok_or_else(invalid)?.get(),
                        WORK,
                    )
                    .map_err(|_| invalid())?;
                    let probe = raw
                        .get("probe_configuration")
                        .filter(|v| v.get() != "null")
                        .map(|v| ObjectDocument::new(v.get(), WORK).map_err(|_| invalid()))
                        .transpose()?;
                    let cmd = UpdateDraft::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        version(dto.expected_draft_version)?,
                        public,
                        probe,
                    )?;
                    (
                        store
                            .update_draft(&cmd, &self.catalog, accepted_at, ROWS, WORK)
                            .await?,
                        (*integration).into(),
                        false,
                    )
                }
                (
                    [
                        "api",
                        "v2",
                        "integrations",
                        integration,
                        "draft",
                        "contract-reset",
                    ],
                    Method::POST,
                ) => {
                    let dto: IntegrationDraftContractResetRequestDto = decode(&bytes)?;
                    let cmd = ResetDraftContract::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        version(dto.expected_draft_version)?,
                    )?;
                    (
                        store
                            .reset_draft_contract(&cmd, &self.catalog, accepted_at, ROWS, WORK)
                            .await?,
                        (*integration).into(),
                        false,
                    )
                }
                (
                    [
                        "api",
                        "v2",
                        "integrations",
                        integration,
                        "draft",
                        "secrets",
                        field,
                    ],
                    Method::PUT,
                ) => {
                    let dto: IntegrationSecretSetRequestDto = decode(&bytes)?;
                    let cmd = SetSecret::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        version(dto.expected_draft_version)?,
                        field,
                        &dto.secret,
                    )?;
                    (
                        store
                            .set_secret(
                                &cmd,
                                &self.catalog,
                                self.inputs.key(),
                                accepted_at,
                                ROWS,
                                WORK,
                            )
                            .await?,
                        (*integration).into(),
                        false,
                    )
                }
                (
                    [
                        "api",
                        "v2",
                        "integrations",
                        integration,
                        "draft",
                        "secrets",
                        field,
                    ],
                    Method::DELETE,
                ) => {
                    if !bytes.is_empty() {
                        return Err(invalid());
                    }
                    let expected = required(&p, "expected_draft_version")?
                        .parse()
                        .map_err(|_| invalid())?;
                    let cmd = ClearSecret::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        version(expected)?,
                        field,
                    )?;
                    (
                        store
                            .clear_secret(&cmd, &self.catalog, accepted_at, ROWS, WORK)
                            .await?,
                        (*integration).into(),
                        false,
                    )
                }
                (["api", "v2", "integrations", integration, "lifecycle"], Method::PUT) => {
                    let dto: IntegrationLifecycleUpdateRequestDto = decode(&bytes)?;
                    let parse = |v: &Value| {
                        v.as_str()
                            .ok_or_else(invalid)?
                            .parse::<Lifecycle>()
                            .map_err(|_| invalid())
                    };
                    let cmd = SetLifecycle::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        parse(
                            &serde_json::to_value(dto.expected_lifecycle_state)
                                .map_err(|_| invalid())?,
                        )?,
                        parse(&serde_json::to_value(dto.lifecycle_state).map_err(|_| invalid())?)?,
                    );
                    self.withdraw_sources().await?;
                    if deadline <= Instant::now() {
                        return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
                    }
                    let result = store.set_lifecycle(&cmd, accepted_at, WORK).await;
                    rejected = result.as_ref().err().is_some_and(source_reissue_rejection);
                    (result?, (*integration).into(), true)
                }
                (["api", "v2", "integrations", integration, "revisions"], Method::POST) => {
                    let dto: IntegrationPublishRequestDto = decode(&bytes)?;
                    let cmd = PublishRevision::new(
                        id,
                        IntegrationId::new(integration).map_err(|_| invalid())?,
                        version(dto.expected_draft_version)?,
                    )?;
                    self.withdraw_sources().await?;
                    if deadline <= Instant::now() {
                        return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
                    }
                    let result = store
                        .publish_revision(&cmd, &self.catalog, accepted_at, ROWS, WORK)
                        .await;
                    rejected = result.as_ref().err().is_some_and(source_reissue_rejection);
                    (result?, (*integration).into(), true)
                }
                _ => return Err(invalid()),
            };
            Ok(result)
        }
        .await;
        // Rejected management commands do not leave the whole workstation's
        // Sources withdrawn. Reconstruct a fresh issuer only from an actual
        // authoritative read on the still-owned physical writer. UNKNOWN and
        // unavailable/corrupt outcomes keep the cutoff closed.
        let refresh = match &outcome {
            Ok((_, _, rotation)) => *rotation,
            Err(_) => rejected,
        };
        if refresh {
            let snapshots = store.list_snapshots(None, None, ROWS, WORK).await?;
            authority
                .verify()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            if !self.admitted() {
                return Err(Failure::unavailable("PRODUCT_NODE_NOT_READY"));
            }
            if human.subject_id()? != "local-developer" {
                return Err(Failure::with_status(
                    StatusCode::FORBIDDEN,
                    "OWNER_OPERATION_DENIED",
                ));
            }
            self.replace_sources(&snapshots).await?;
        }
        let (result, integration_id, _) = outcome?;
        Ok(response(result, &integration_id))
    }
    pub(crate) async fn watchlists(
        self: &Arc<Self>,
        request: Request<Body>,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let method = request.method().clone();
        let path = request.uri().path().to_owned();
        if method == Method::GET {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let mut store = Watchlists::new(client, self.inputs.namespace().value())?;
            let value = if path == "/api/v2/watchlists" {
                store.read().await?
            } else {
                let id = CommandId::new(path.rsplit('/').next().ok_or_else(invalid)?)
                    .map_err(|_| invalid())?;
                store.command(&id).await?.ok_or_else(|| {
                    Failure::with_status(StatusCode::NOT_FOUND, "WATCHLIST_COMMAND_NOT_FOUND")
                })?
            };
            return Ok(Json(watchlist_wire(value)).into_response());
        }
        let dto: SaveWatchlistsDto = decode(
            &to_bytes(request.into_body(), 65536)
                .await
                .map_err(|_| invalid())?,
        )?;
        let id = CommandId::new(&dto.command_id).map_err(|_| invalid())?;
        let mut lists = vec![];
        for list in dto.lists {
            let mut members = vec![];
            for member in list.members {
                members.push(Member::new(
                    onlyalpha_product_runtime::source_access::Reference::new(
                        &member.source.integration_id,
                        &member.source.integration_revision_fingerprint,
                        Some(&member.source.expected_type_id),
                    )?,
                    &member.instrument_id,
                )?);
            }
            lists.push(List::new(&list.list_id, &list.name, members)?);
        }
        let proposed = Book::new(
            u64::try_from(dto.expected_version).map_err(|_| invalid())?,
            lists,
        )?;
        let prior = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let mut store = Watchlists::new(client, self.inputs.namespace().value())?;
            // Accepted immutable receipts do not re-admit provider work. save() below
            // remains the sole exact intent/replay/conflict Authority, including UNKNOWN.
            if store.command(&id).await?.is_some() {
                None
            } else {
                Some(store.read().await?)
            }
        };
        // Retained unavailable members may be renamed/reordered/removed. Only actual
        // newly added exact Source+instrument identities require current provider work.
        if let Some(prior) = prior {
            for list in proposed.lists() {
                for member in list.members() {
                    if prior
                        .lists()
                        .iter()
                        .flat_map(|l| l.members())
                        .any(|old| old == member)
                    {
                        continue;
                    }
                    let (resolved, session) = self.resolve(member.source()).await?;
                    self.app
                        .reference(&resolved, &session, member.instrument_id(), deadline)
                        .await?
                        .into_parts()?;
                }
            }
        }
        let mut writer = self.writer.lock().await;
        let client = writer
            .as_mut()
            .ok_or_else(|| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
            .client_mut()
            .await
            .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
        if deadline <= Instant::now() {
            return Err(Failure::unavailable("REQUEST_DEADLINE_EXPIRED"));
        }
        let value = Watchlists::new(client, self.inputs.namespace().value())?
            .save(&id, &proposed, &now()?.to_string())
            .await?;
        Ok(Json(watchlist_wire(value)).into_response())
    }
}
fn watchlist_wire(book: Book) -> Value {
    let mut value = book.to_record();
    value["schema_version"] = json!(2);
    value
}

#[cfg(test)]
mod source_reissue_tests {
    use super::*;
    #[test]
    fn command_rejections_do_not_classify_unknown_or_corruption_as_recoverable() {
        for error in [
            commands::Error::LifecycleConflict,
            commands::Error::DraftVersion,
            commands::Error::InvalidConfiguration,
            commands::Error::NotFound,
        ] {
            assert!(source_reissue_rejection(&error));
        }
        for error in [
            commands::Error::Unknown,
            commands::Error::Model(
                onlyalpha_product_runtime::integration_configuration::Error::Unavailable,
            ),
            commands::Error::Model(
                onlyalpha_product_runtime::integration_configuration::Error::PersistenceConflict,
            ),
        ] {
            assert!(!source_reissue_rejection(&error));
        }
    }
}
