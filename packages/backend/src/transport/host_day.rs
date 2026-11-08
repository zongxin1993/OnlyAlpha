//! 日线显式命令与原操作查询。下载期间释放 PG 业务连接，单独的 lease 保持原操作所有权。
use super::host::{Failure, Host, ROWS, WORK, invalid, now, uuid};
use super::host_acquisition::{Operation, OwnerAdmission};
use crate::{
    application::{
        integration_configuration::RuntimeBinding,
        market_product::{self as product, Authorized, day},
        source_access::{Permission, Reference, Selection, Session},
    },
    persistence::{
        authority_session::AuthoritySession,
        integration_postgres::Snapshot,
        market_data::{
            AcquisitionAttempt, AcquisitionIntent, Catalog, ExecutionLease, RevisionPublication,
            Storage,
        },
    },
    security::{
        human_access,
        ingress::{self, Release},
    },
};
use axum::{
    Json,
    response::{IntoResponse, Response},
};
use http::StatusCode;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_integration_contract::{
    Category,
    source::{HistoricalDayRequest, HistoryInputPolicy, MarketIdentity},
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Instant};

fn response(value: Authorized<Value>) -> Result<Response, Failure> {
    let (value, fence) = value.into_parts()?;
    Ok(ingress::attach(
        Json(value).into_response(),
        Release::Source(fence),
    ))
}
fn binding(snapshot: &Snapshot, reference: &Reference) -> Result<RuntimeBinding, Failure> {
    let (revision, _) = snapshot
        .history()
        .iter()
        .find(|(r, _)| r.record().revision_fingerprint == reference.revision())
        .ok_or_else(invalid)?;
    Ok(RuntimeBinding::from_revision(
        revision,
        Category::DataSource,
        None,
    )?)
}
impl Host {
    async fn day_store<'a>(
        &'a self,
        writer: &'a mut Option<AuthoritySession>,
    ) -> Result<Storage<'a>, Failure> {
        let unavailable = || Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE");
        let client = writer
            .as_mut()
            .ok_or_else(unavailable)?
            .client_mut()
            .await
            .map_err(|_| unavailable())?;
        Ok(Storage::new(
            Catalog::new(client, ROWS, WORK)?,
            &self.clickhouse,
            100000,
        )?)
    }
    pub(crate) async fn original_day_status(
        &self,
        snapshot: &Snapshot,
        reference: &Reference,
        session: &Session,
        id: &str,
    ) -> Result<Option<Response>, Failure> {
        // 先验证精确 Source grant，再在只读连接查询；当前可执行物/凭据状态不进入原结果路径。
        session.require_reference(reference, Permission::ClosedHistory)?;
        let identity = Self::identity(snapshot, reference)?;
        let selected = product::original_selection(snapshot, reference, session, &identity)?;
        let mut reader = self.reader.lock().await;
        let mut store = Storage::new(
            Catalog::new(
                reader
                    .as_mut()
                    .ok_or_else(|| Failure::unavailable("PRODUCT_READ_DRIVER_UNAVAILABLE"))?,
                ROWS,
                WORK,
            )?,
            &self.clickhouse,
            100000,
        )?;
        let Some(intent) = store.catalog().intent(id).await? else {
            if crate::application::command::uuid4(id) {
                return Err(Failure::with_status(
                    StatusCode::NOT_FOUND,
                    "MARKET_DATA_ACQUISITION_NOT_FOUND",
                ));
            }
            return Ok(None);
        };
        if intent.to_record()["identity_version"] != 3 {
            return Ok(None);
        }
        day::matches_original(
            &intent,
            &selected,
            &identity,
            binding(snapshot, reference)?.fingerprint(),
        )?;
        response(day::status(session, &selected, &mut store, &intent).await?).map(Some)
    }
    pub(crate) async fn day_acquisition(
        self: &Arc<Self>,
        reference: &Reference,
        body: &Value,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        let original = body["original_request_id"]
            .as_str()
            .filter(|s| crate::application::command::uuid4(s))
            .ok_or_else(invalid)?;
        let request = day::request(body)?;
        let session = self.source_session().await;
        let snapshots = self.snapshots().await?;
        let snapshot = snapshots
            .iter()
            .find(|s| s.integration().record().integration_id.value() == reference.integration_id())
            .ok_or_else(invalid)?;
        let (identity, declared) =
            Self::declared_source(snapshot, reference)?.ok_or_else(invalid)?;
        if declared.as_ref() != Some(&request.semantic) {
            return Err(invalid());
        }
        let selection = product::original_selection(snapshot, reference, &session, &identity)?;
        let admission = OwnerAdmission {
            human,
            operation: Operation::Acquisition(selection.clone()),
        };
        admission.day(&selection)?;
        let original_binding = binding(snapshot, reference)?;
        let at = now()?.to_string();
        let intent = {
            let mut writer = self.writer.lock().await;
            let mut store = self.day_store(&mut writer).await?;
            let existing = store.catalog().intent(original).await?;
            if let Some(intent) = existing {
                day::matches_original(
                    &intent,
                    &selection,
                    &identity,
                    original_binding.fingerprint(),
                )?;
                day::matches_body(&intent, &request)?;
                intent
            } else {
                if snapshot
                    .integration()
                    .record()
                    .current_revision_fingerprint
                    .as_deref()
                    != Some(reference.revision())
                {
                    return Err(product::Error::Selection.into());
                }
                let installed = self.resolver.installation(snapshot, reference, None)?;
                if installed.binding.fingerprint() != original_binding.fingerprint() {
                    return Err(product::Error::Conflict.into());
                }
                let requested = json!({"original_request_id":original,"source_id":identity.source_id,"provider":identity.provider,"venue":identity.venue,
                    "market":identity.market,"environment":identity.environment,"integration_id":reference.integration_id(),"integration_revision_fingerprint":reference.revision(),
                    "artifact_fingerprint":installed.artifact(),"implementation_fingerprint":installed.implementation,"instrument_id":request.instrument.to_string(),
                    "bar_semantic":request.semantic.to_record(),"start_ns":product::ns(request.start)?,"end_ns":product::ns(request.end)?,
                    "adjustment_anchor":request.anchor.map(|v|v.to_record())});
                let candidate = AcquisitionIntent::build_history(
                    &requested,
                    original_binding.fingerprint(),
                    &at,
                )?;
                admission.day(&selection)?;
                session.require_selection(&selection, Permission::ClosedHistory)?;
                let intent = store.catalog().admit_intent(&candidate).await?;
                if intent.id() != candidate.id() {
                    day::matches_original(
                        &intent,
                        &selection,
                        &identity,
                        original_binding.fingerprint(),
                    )?;
                    return response(day::status(&session, &selection, &mut store, &intent).await?);
                }
                intent
            }
        };
        let lease = self
            .database
            .lease(intent.id(), self.inputs.namespace())
            .await?;
        let execution = DayExecution {
            host: self,
            snapshot,
            reference,
            session: &session,
            selection: &selection,
            identity: &identity,
            admission: &admission,
            intent: &intent,
            lease: &lease,
            deadline,
        };
        let result = execution.run(&request, &at).await;
        let closed = lease.close().await;
        let result = result?;
        closed?;
        response(result)
    }
}
struct DayExecution<'a> {
    host: &'a Host,
    snapshot: &'a Snapshot,
    reference: &'a Reference,
    session: &'a Session,
    selection: &'a Selection,
    identity: &'a MarketIdentity,
    admission: &'a OwnerAdmission,
    intent: &'a AcquisitionIntent,
    lease: &'a ExecutionLease,
    deadline: Instant,
}
impl DayExecution<'_> {
    fn grants_active(&self) -> bool {
        self.admission.day(self.selection).is_ok()
            && self
                .session
                .require_selection(self.selection, Permission::ClosedHistory)
                .is_ok()
    }
    async fn check(&self) -> Result<(), Failure> {
        self.admission.day(self.selection)?;
        self.session
            .require_selection(self.selection, Permission::ClosedHistory)?;
        self.lease.verify().await?;
        product::budget(self.deadline)?;
        Ok(())
    }
    async fn run(
        &self,
        request: &HistoricalDayRequest,
        at: &str,
    ) -> Result<Authorized<Value>, Failure> {
        self.check().await?;
        let attempt = {
            let mut writer = self.host.writer.lock().await;
            let mut store = self.host.day_store(&mut writer).await?;
            if let Some(attempt) = store.catalog().latest_attempt(self.intent.id()).await? {
                if attempt.is_unknown()
                    && store
                        .catalog()
                        .history_preparation(&attempt)
                        .await?
                        .is_some()
                {
                    let wal = self.host.capture_wal(&self.identity.source_id, None)?;
                    let mut sealed = wal
                        .sealed_handle()
                        .map_err(|_| Failure::unavailable("MARKET_DATA_WAL_UNAVAILABLE"))?;
                    store
                        .publish_prepared_day(&mut sealed, self.intent, &attempt, at, |_| {
                            self.grants_active()
                        })
                        .await?;
                }
                return Ok(
                    day::status(self.session, self.selection, &mut store, self.intent).await?,
                );
            }
            store.catalog().start_attempt(self.lease, at).await?
        };
        finish_sampling(
            self.sample(request, &attempt).await,
            |(wal, prepared)| self.publish(&attempt, wal, prepared),
            |code| self.fail_sample(&attempt, code),
        )
        .await?;
        let mut writer = self.host.writer.lock().await;
        let mut store = self.host.day_store(&mut writer).await?;
        Ok(day::status(self.session, self.selection, &mut store, self.intent).await?)
    }

    async fn fail_sample(
        &self,
        attempt: &AcquisitionAttempt,
        code: &'static str,
    ) -> Result<(), Failure> {
        self.admission.day(self.selection)?;
        self.session
            .require_selection(self.selection, Permission::ClosedHistory)?;
        self.lease.verify().await?;
        let mut writer = self.host.writer.lock().await;
        let mut store = self.host.day_store(&mut writer).await?;
        store
            .catalog()
            .record_failure(attempt, code, &now()?.to_string())
            .await?;
        Ok(())
    }

    async fn sample(
        &self,
        request: &HistoricalDayRequest,
        attempt: &AcquisitionAttempt,
    ) -> Result<(crate::persistence::market_data_wal::Wal, day::PreparedDay), Failure> {
        self.check().await?;
        let resolved = self
            .host
            .current_source(self.snapshot, self.reference, self.session)
            .await?;
        let intent = self.intent.to_record();
        if resolved.implementation_fingerprint()
            != intent["requested_scope"]["implementation_fingerprint"]
                .as_str()
                .ok_or_else(invalid)?
            || resolved.artifact_fingerprint()
                != intent["requested_scope"]["artifact_fingerprint"]
                    .as_str()
                    .ok_or_else(invalid)?
        {
            return Err(product::Error::Conflict.into());
        }
        let days = resolved.resource().historical_days().ok_or_else(invalid)?;
        let queries = days.inputs(request).map_err(product::Error::from)?;
        if queries.is_empty() || queries.len() > 32 {
            return Err(invalid());
        }
        let mut cached = BTreeMap::new();
        if days.input_policy() != HistoryInputPolicy::ForceRefresh {
            let mut writer = self.host.writer.lock().await;
            let mut store = self.host.day_store(&mut writer).await?;
            if let Some(id) = store.catalog().previous_history_inputs(self.intent).await? {
                let (owner, original) = store.catalog().original_attempt(&id).await?;
                let old = owner.to_record();
                let prior = Reference::new(
                    self.reference.integration_id(),
                    old["requested_scope"]["integration_revision_fingerprint"]
                        .as_str()
                        .ok_or_else(invalid)?,
                    self.reference.expected_type_id(),
                )?;
                let selected = product::original_selection(
                    self.snapshot,
                    &prior,
                    self.session,
                    self.identity,
                )?;
                day::matches_original(
                    &owner,
                    &selected,
                    self.identity,
                    binding(self.snapshot, &prior)?.fingerprint(),
                )?;
                let p = store
                    .catalog()
                    .history_preparation(&original)
                    .await?
                    .ok_or(product::Error::Unknown)?;
                let refs = &p["input_manifest"]["candidate_refs"];
                let scope =
                    crate::persistence::market_data::Scope::from_record(&p["requested_scope"])?;
                store
                    .original_day_revision(
                        &scope,
                        refs,
                        original.to_record()["revision_id"].as_str(),
                    )
                    .await?
                    .ok_or(product::Error::Corrupt)?;
                for input in p["input_manifest"]["inputs"]
                    .as_array()
                    .ok_or(product::Error::Corrupt)?
                {
                    let mut link = input.clone();
                    link["producer_attempt_id"] = input
                        .get("producer_attempt_id")
                        .unwrap_or(&input["attempt_id"])
                        .clone();
                    link["attempt_id"] = attempt.id().into();
                    cached.insert(input["query_document"].to_string(), link);
                }
                if cached.len() != queries.len()
                    || queries.iter().any(|q| !cached.contains_key(&q.to_string()))
                {
                    return Err(product::Error::Corrupt.into());
                }
            } else if days.input_policy() == HistoryInputPolicy::CacheOnly {
                return Err(Failure::unavailable("MARKET_DATA_HISTORY_CACHE_MISS"));
            }
        }
        let mut wal = self.host.capture_wal(&self.identity.source_id, None)?;
        let mut inputs = vec![];
        for query in queries {
            self.check().await?;
            if let Some(link) = cached.remove(&query.to_string()) {
                let mut writer = self.host.writer.lock().await;
                let mut store = self.host.day_store(&mut writer).await?;
                self.check().await?;
                let original = store
                    .link_history_input(self.intent, attempt, self.lease, &link)
                    .await?;
                inputs.push(original);
                continue;
            }
            let bytes = tokio::time::timeout_at(
                self.deadline.into(),
                days.fetch(&query, product::budget(self.deadline)?),
            )
            .await
            .map_err(|_| {
                product::Error::Source(onlyalpha_integration_contract::source::SourceError::Timeout)
            })?
            .map_err(product::Error::from)?;
            self.check().await?;
            let observed = now()?;
            let at = observed.to_string();
            let segment = uuid()?;
            let input = day::capture_input(
                &mut wal,
                &resolved,
                attempt,
                &query,
                &bytes,
                &segment,
                &at,
                product::ns(observed)?,
            )?;
            let mut writer = self.host.writer.lock().await;
            let mut store = self.host.day_store(&mut writer).await?;
            let mut sealed = wal.sealed_handle().map_err(|_| product::Error::Unknown)?;
            self.check().await?;
            store
                .drain(
                    &mut sealed,
                    &[segment],
                    None,
                    RevisionPublication {
                        parent: None,
                        reason: "REST_BACKFILL",
                        at: &at,
                    },
                    |_| self.grants_active(),
                )
                .await?;
            let original = store
                .link_history_input(self.intent, attempt, self.lease, &input)
                .await?;
            inputs.push(original);
        }
        self.check().await?;
        let prepared = day::DayProducer {
            resolved: &resolved,
            session: self.session,
            intent: self.intent,
            attempt,
        }
        .prepare(request, inputs, &mut wal, &uuid()?, now()?, self.deadline)
        .await?;
        Ok((wal, prepared))
    }

    async fn publish(
        &self,
        attempt: &AcquisitionAttempt,
        wal: crate::persistence::market_data_wal::Wal,
        prepared: day::PreparedDay,
    ) -> Result<(), Failure> {
        let at = now()?.to_string();
        let mut writer = self.host.writer.lock().await;
        let mut store = self.host.day_store(&mut writer).await?;
        let mut sealed = wal.sealed_handle().map_err(|_| product::Error::Unknown)?;
        self.check().await?;
        store
            .bind_history_scope(self.intent, attempt, self.lease, prepared, &mut sealed)
            .await?;
        self.check().await?;
        store
            .publish_prepared_day(&mut sealed, self.intent, attempt, &at, |_| {
                self.grants_active()
            })
            .await?;
        Ok(())
    }
}

/// 已知错误只可终结准备前的采样。开始提交准备后所有错误均保留原操作待观察。
async fn finish_sampling<T, Publish, Fail>(
    sampled: Result<T, Failure>,
    publish: impl FnOnce(T) -> Publish,
    fail_sample: impl FnOnce(&'static str) -> Fail,
) -> Result<(), Failure>
where
    Publish: Future<Output = Result<(), Failure>> + Send,
    Fail: Future<Output = Result<(), Failure>> + Send,
{
    match sampled {
        Ok(candidate) => publish(candidate).await,
        Err(error)
            if matches!(
                error.code(),
                "MARKET_DATA_REQUEST_INVALID"
                    | "MARKET_DATA_SOURCE_UNAVAILABLE"
                    | "MARKET_DATA_CAPABILITY_UNSUPPORTED"
                    | "MARKET_DATA_CONTINUITY_UNPROVEN"
                    | "MARKET_DATA_SOURCE_TIMEOUT"
                    | "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE"
                    | "MARKET_DATA_HISTORICAL_INPUT_REJECTED"
                    | "MARKET_DATA_HISTORY_CACHE_MISS"
            ) =>
        {
            fail_sample(error.code()).await
        }
        Err(error) => Err(error),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, Ordering};

    #[tokio::test]
    async fn committed_preparation_timeout_and_unknown_ack_never_record_failed() {
        for code in [
            "MARKET_DATA_SOURCE_TIMEOUT",
            "MARKET_DATA_SUBMISSION_UNKNOWN",
        ] {
            let committed = &AtomicBool::new(false);
            let failed = &AtomicBool::new(false);
            let result = finish_sampling(
                Ok(()),
                |()| async move {
                    committed.store(true, Ordering::Relaxed);
                    if code == "MARKET_DATA_SOURCE_TIMEOUT" {
                        product::budget(Instant::now() - std::time::Duration::from_secs(1))?;
                    }
                    Err(Failure::unavailable("MARKET_DATA_SUBMISSION_UNKNOWN"))
                },
                |_| async move {
                    failed.store(true, Ordering::Relaxed);
                    Ok(())
                },
            )
            .await;
            assert!(committed.load(Ordering::Relaxed));
            assert_eq!(result.unwrap_err().code(), code);
            assert!(!failed.load(Ordering::Relaxed));
        }
        let failed = &AtomicBool::new(false);
        finish_sampling(
            Err(Failure::unavailable("MARKET_DATA_SOURCE_TIMEOUT")),
            |(): ()| async { panic!("准备前失败不能发布") },
            |code| async move {
                assert_eq!(code, "MARKET_DATA_SOURCE_TIMEOUT");
                failed.store(true, Ordering::Relaxed);
                Ok(())
            },
        )
        .await
        .unwrap();
        assert!(failed.load(Ordering::Relaxed));
    }
}
