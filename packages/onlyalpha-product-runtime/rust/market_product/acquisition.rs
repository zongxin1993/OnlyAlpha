use super::queries::{self, Application, Authorized};
use super::*;
use crate::{
    market_data::{
        AcquisitionAttempt, AcquisitionIntent, CoverageStatus, ExecutionLease, RevisionPublication,
        Scope, Storage,
    },
    market_data_wal::Wal,
    source_access::{Permission, Selection, Session},
};
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::json;
use std::{collections::BTreeMap, sync::Arc, time::Instant};
/// Explicit, operation-specific Host human Command policy. It must retain the
/// issuing authenticated session and exact operation; a Source grant is not it.
pub trait MutationAdmission: Send + Sync {
    fn require_acquisition(&self, selection: &Selection, scope: &Scope) -> Result<()>;
}
/// Exact current acquisition inputs; clocks and admission time remain explicit.
pub struct AcquisitionRequest<'a> {
    pub instrument_id: &'a str,
    pub semantic: &'a onlyalpha_domain::market::OnlyBarSemantic,
    pub start_ns: i64,
    pub end_ns: i64,
    pub clock_ns: i64,
    pub admitted_at: &'a str,
}
pub struct CaptureRequest<'a> {
    pub segment_id: &'a str,
    pub capture_id: &'a str,
    pub created_at: &'a str,
    pub deadline: Instant,
}
pub struct AcquisitionWork {
    resolved: Arc<Resolved>,
    session: Session,
    admission: Arc<dyn MutationAdmission>,
    intent: AcquisitionIntent,
    scope: Scope,
    selected: Vec<(String, String)>,
    gaps: Vec<Value>,
    attempt: Option<AcquisitionAttempt>,
}
pub struct Captured<'a> {
    work: &'a AcquisitionWork,
    lease: &'a ExecutionLease,
    segments: Vec<(String, String)>,
    failure: Option<Error>,
}
impl Captured<'_> {
    pub fn segment_ids(&self) -> impl Iterator<Item = &str> {
        self.segments.iter().map(|(id, _)| id.as_str())
    }
    pub fn failure(&self) -> Option<Error> {
        self.failure
    }
}
impl Application {
    pub async fn prepare_acquisition(
        &self,
        r: Arc<Resolved>,
        session: Session,
        admission: Arc<dyn MutationAdmission>,
        store: &mut Storage<'_>,
        request: AcquisitionRequest<'_>,
    ) -> Result<AcquisitionWork> {
        let AcquisitionRequest {
            instrument_id: instrument,
            semantic: target,
            start_ns: start,
            end_ns: end,
            clock_ns,
            admitted_at,
        } = request;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let p = queries::plan(&r, instrument, target)?;
        let native = if p.recipe().is_native() {
            p
        } else {
            queries::plan(&r, instrument, &queries::semantic(1)?)?
        };
        let scope = queries::scope(&r, instrument, start, end, &native)?;
        let stride: i64 = native
            .target()
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<i64>()
            .map_err(|_| Error::Invalid)?
            .checked_mul(60_000_000_000)
            .ok_or(Error::Invalid)?;
        if start < 0
            || start >= end
            || end > clock_ns.div_euclid(stride) * stride
            || start % stride != 0
            || end % stride != 0
            || i128::from(end) - i128::from(start) > 7 * 86_400_000_000_000i128
        {
            return Err(Error::Invalid);
        }
        admission.require_acquisition(&r.selection, &scope)?;
        // The exact immutable Intent is durable before reference/session/WAL effects.
        let intent = store
            .catalog()
            .admit_intent(&AcquisitionIntent::build(
                scope.clone(),
                "REST_BACKFILL",
                r.binding.fingerprint(),
                admitted_at,
            )?)
            .await?;
        if intent.to_record()["integration_binding_fingerprint"] != r.binding.fingerprint() {
            return Err(Error::Conflict);
        }
        let (selected, gaps) = readiness(store, &scope).await?;
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        admission.require_acquisition(&r.selection, &scope)?;
        Ok(AcquisitionWork {
            resolved: r,
            session,
            admission,
            intent,
            scope,
            selected,
            gaps,
            attempt: None,
        })
    }
    pub async fn acquisition_status(
        &self,
        r: &Resolved,
        session: &Session,
        store: &mut Storage<'_>,
        id: &str,
        execution: Option<&ExecutionLease>,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&r.selection, Permission::ClosedHistory)?;
        let intent = store.catalog().intent(id).await?.ok_or(Error::Invalid)?;
        let record = intent.to_record();
        if record["source_id"] != r.identity().source_id
            || record["integration_binding_fingerprint"] != r.binding.fingerprint()
        {
            return Err(Error::Conflict);
        }
        let scope = Scope::from_record(&record["requested_scope"])?;
        let attempt = store.catalog().latest_attempt(id).await?;
        let verified = store
            .read_range(&scope, &queries::native_intervals(&scope)?)
            .await?;
        let mut seal = None;
        if verified.coverage_status == CoverageStatus::Complete {
            for e in &verified.evidence {
                let (revision, _) = store
                    .read_exact(e["revision_id"].as_str().ok_or(Error::Corrupt)?)
                    .await?;
                if revision.manifest().to_record()["scope"] == scope.to_record() {
                    seal = Some(revision);
                    break;
                }
            }
        }
        let active = if let Some(lease) = execution {
            if lease.intent_id() != id {
                return Err(Error::Conflict);
            }
            lease.verify().await?;
            true
        } else {
            false
        };
        let outcome = attempt.as_ref().map(AcquisitionAttempt::to_record);
        let status = if seal.is_some() {
            "COMPLETE"
        } else if active {
            "RUNNING"
        } else if outcome.as_ref().is_some_and(|a| a["outcome"] == "FAILED") {
            "FAILED"
        } else {
            "PENDING"
        };
        Authorized::new(
            json!({"schema_version":1,"acquisition_id":intent.id(),"status":status,"source_id":r.identity().source_id,"integration_binding_fingerprint":r.binding.fingerprint(),"instrument_id":scope.to_record()["instrument_id"],"bar_semantic":scope.to_record()["bar_construction"]["plan"]["target_semantic"],"start_ns":scope.start_ns().to_string(),"end_ns":scope.end_ns().to_string(),"provenance":record["provenance"],"coverage":{"status":verified.coverage_status.as_str(),"manifest_id":seal.as_ref().map(|s|s.manifest().id()),"manifest_fingerprint":seal.as_ref().map(|s|s.manifest().to_record()["fingerprint"].clone()),"expected_bar_count":verified.expected_base_fact_count,"actual_bar_count":verified.complete_interval_count,"gaps":verified.gaps.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?,"planned_acquisition_ranges":queries::coalesce_gaps(&verified.gaps,7*86_400_000_000_000)?.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?,"issues":verified.issues},"revision_id":seal.as_ref().map(|s|s.id()),"revision_fingerprint":seal.as_ref().map(|s|s.revision()["fingerprint"].clone()),"seal_id":seal.as_ref().map(|s|s.seal()["seal_id"].clone()),"failure_detail":if status=="FAILED"{outcome.map(|v|v["detail"].clone())}else{None}}),
            session,
            r,
            Permission::ClosedHistory,
        )
    }
}
impl AcquisitionWork {
    pub fn id(&self) -> &str {
        self.intent.id()
    }
    pub fn scope(&self) -> &Scope {
        &self.scope
    }
    pub fn resolved(&self) -> &Resolved {
        &self.resolved
    }
    fn check(&self) -> Result<()> {
        self.session
            .require_selection(&self.resolved.selection, Permission::ClosedHistory)?;
        self.admission
            .require_acquisition(&self.resolved.selection, &self.scope)
    }
    pub async fn start(
        &mut self,
        store: &mut Storage<'_>,
        lease: &ExecutionLease,
        at: &str,
    ) -> Result<()> {
        self.check()?;
        lease.verify().await?;
        if lease.intent_id() != self.id() || self.attempt.is_some() {
            return Err(Error::Conflict);
        }
        let (selected, gaps) = readiness(store, &self.scope).await?;
        lease.verify().await?;
        self.check()?;
        self.selected = selected;
        self.gaps = gaps;
        self.attempt = Some(store.catalog().start_attempt(lease, at).await?);
        Ok(())
    }
    /// No business Client is borrowed while provider I/O runs. Cancellation drops
    /// the future and leaves the original started occurrence explicitly UNKNOWN.
    pub async fn capture<'a>(
        &'a self,
        app: &Application,
        wal: &mut Wal,
        request: CaptureRequest<'_>,
        lease: &'a ExecutionLease,
    ) -> Result<Captured<'a>> {
        let CaptureRequest {
            segment_id: segment,
            capture_id: capture,
            created_at: at,
            deadline,
        } = request;
        self.check()?;
        lease.verify().await?;
        if lease.intent_id() != self.id() {
            return Err(Error::Conflict);
        }
        if self.attempt.is_none() {
            return Err(Error::Conflict);
        }
        if self.gaps.is_empty() {
            return Ok(Captured {
                work: self,
                lease,
                segments: vec![],
                failure: None,
            });
        }
        let instrument = self.scope.to_record()["instrument_id"]
            .as_str()
            .ok_or(Error::Corrupt)?
            .to_owned();
        let reference = app
            .reference(&self.resolved, &self.session, &instrument, deadline)
            .await?
            .for_resource(&self.resolved, Permission::ClosedHistory)?
            .0;
        self.check()?;
        lease.verify().await?;
        self.check()?;
        let mut recorder = WalRecorder::open(
            wal,
            &self.resolved,
            self.session.clone(),
            self.scope.clone(),
            segment,
            capture,
            at,
        )?;
        let mut result = Ok(());
        for gap in &self.gaps {
            self.check()?;
            let scope = self.scope.with_range(
                gap["start_ns"].as_i64().ok_or(Error::Corrupt)?,
                gap["end_ns"].as_i64().ok_or(Error::Corrupt)?,
            )?;
            let request = Application::history_request(&self.resolved, reference.clone(), &scope)?;
            if let Err(error) = self
                .resolved
                .resource
                .history(
                    &request,
                    budget(deadline)?,
                    &mut CommandRecorder {
                        work: self,
                        recorder: &mut recorder,
                    },
                )
                .await
            {
                result = Err(Error::Source(error));
                break;
            }
        }
        let seal_at = time(self.resolved.clock.now_ns()?)?.to_string();
        let sealed = recorder.seal(&seal_at)?;
        lease.verify().await?;
        self.check()?;
        let segments = sealed
            .map(|s| {
                s["content_hash"]
                    .as_str()
                    .map(|hash| vec![(segment.to_owned(), hash.to_owned())])
                    .ok_or(Error::Corrupt)
            })
            .transpose()?
            .unwrap_or_default();
        Ok(Captured {
            work: self,
            lease,
            segments,
            failure: result.err(),
        })
    }
    pub async fn publish(
        &self,
        store: &mut Storage<'_>,
        wal: &Wal,
        captured: &Captured<'_>,
        at: &str,
    ) -> Result<Authorized<Value>> {
        if !std::ptr::eq(captured.work, self) {
            return Err(Error::Conflict);
        }
        let lease = captured.lease;
        self.check()?;
        lease.verify().await?;
        if lease.intent_id() != self.id() {
            return Err(Error::Conflict);
        }
        let attempt = self.attempt.as_ref().ok_or(Error::Conflict)?;
        let mut sealed = wal.sealed_handle().map_err(|_| Error::Unavailable)?;
        let mut refs = self.selected.clone();
        for (id, hash) in &captured.segments {
            self.check()?;
            lease.verify().await?;
            let metadata = market_data::Segment::from_record(
                &sealed.load_segment(id).map_err(|_| Error::Unavailable)?,
            )?;
            if metadata.content_hash() != hash
                || metadata.to_record()["integration_binding_fingerprint"]
                    != self.resolved.binding.fingerprint()
            {
                return Err(Error::Conflict);
            }
            let mut intervals = vec![];
            for bundle in sealed.read_sealed(id).map_err(|_| Error::Unavailable)? {
                for fact in bundle["canonical_facts"].as_array().ok_or(Error::Corrupt)? {
                    let bar = onlyalpha_domain::market::OnlyBar::from_record(
                        &fact["canonical_payload"]["payload"]["value"],
                    )
                    .map_err(|_| Error::Corrupt)?;
                    intervals.push((ns(*bar.bar_start())?, ns(*bar.bar_end())?));
                }
            }
            intervals.sort_unstable();
            let mut complete: Vec<(i64, i64)> = vec![];
            for (start, end) in intervals {
                if let Some(last) = complete.last_mut()
                    && start <= last.1
                {
                    last.1 = last.1.max(end);
                } else {
                    complete.push((start, end));
                }
            }
            store
                .drain(
                    &mut sealed,
                    std::slice::from_ref(id),
                    if complete.is_empty() {
                        None
                    } else {
                        Some(&self.scope)
                    },
                    RevisionPublication {
                        parent: None,
                        reason: "EXPLICIT_ACQUISITION",
                        at,
                    },
                    |_| true,
                )
                .await?;
            lease.verify().await?;
            self.check()?;
            // A failed later page cannot erase earlier accepted facts. Each exact
            // contiguous own subrange receives the same formal physical/Seal proof.
            for (start, end) in complete {
                if start < self.scope.start_ns() || end > self.scope.end_ns() {
                    return Err(Error::Conflict);
                }
                let scope = self.scope.with_range(start, end)?;
                let (_, revision) = store
                    .commit_scope(
                        &scope,
                        &[(id.clone(), hash.clone())],
                        RevisionPublication {
                            parent: None,
                            reason: "EXPLICIT_ACQUISITION",
                            at,
                        },
                    )
                    .await?;
                if revision.is_none() {
                    return Err(Error::Unknown);
                }
                lease.verify().await?;
                self.check()?;
            }
            if metadata.to_record()["canonical_count"]
                .as_u64()
                .ok_or(Error::Corrupt)?
                > 0
                && !refs.iter().any(|(old, _)| old == id)
            {
                refs.push((id.clone(), hash.clone()));
            }
        }
        if refs.is_empty() {
            return Err(captured.failure.unwrap_or(Error::Unknown));
        }
        self.check()?;
        lease.verify().await?;
        // Reuse an exact already-sealed full scope without relabelling its owning
        // Revision reason (for example REALTIME_STREAM). No captured occurrence is
        // discarded: nonempty captures must follow their own explicit composition.
        let mut existing = None;
        if captured.segments.is_empty() {
            let verified = store
                .read_range(&self.scope, &queries::native_intervals(&self.scope)?)
                .await?;
            if verified.coverage_status == CoverageStatus::Complete {
                for evidence in verified.evidence {
                    let (revision, _) = store
                        .read_exact(evidence["revision_id"].as_str().ok_or(Error::Corrupt)?)
                        .await?;
                    if revision.manifest().to_record()["scope"] == self.scope.to_record() {
                        existing = Some(revision);
                        break;
                    }
                }
            }
        }
        let revision = if existing.is_some() {
            existing
        } else {
            let (_, revision) = store
                .commit_scope(
                    &self.scope,
                    &refs,
                    RevisionPublication {
                        parent: None,
                        reason: "EXPLICIT_ACQUISITION",
                        at,
                    },
                )
                .await?;
            revision
        };
        lease.verify().await?;
        self.check()?;
        let revision = revision.ok_or(captured.failure.unwrap_or(Error::Unknown))?;
        // The sealed success already exists if the optional attempt terminal write is
        // unavailable. It never gets relabelled FAILED or erased by that write.
        let _ = store
            .complete_acquisition(attempt, revision.id(), "EXPLICIT_ACQUISITION", at)
            .await;
        Authorized::new(
            json!({"schema_version":1,"acquisition_id":self.id(),"status":"COMPLETE","source_id":self.resolved.identity().source_id,"integration_binding_fingerprint":self.resolved.binding.fingerprint(),"instrument_id":self.scope.to_record()["instrument_id"],"bar_semantic":self.scope.to_record()["bar_construction"]["plan"]["target_semantic"],"start_ns":self.scope.start_ns().to_string(),"end_ns":self.scope.end_ns().to_string(),"provenance":"REST_BACKFILL","coverage":sealed_coverage(&revision)?,"revision_id":revision.id(),"revision_fingerprint":revision.revision()["fingerprint"],"seal_id":revision.seal()["seal_id"],"failure_detail":null}),
            &self.session,
            &self.resolved,
            Permission::ClosedHistory,
        )
    }
    pub async fn record_failure(
        &self,
        store: &mut Storage<'_>,
        lease: &ExecutionLease,
        error: Error,
        at: &str,
    ) -> Result<()> {
        self.check()?;
        lease.verify().await?;
        if lease.intent_id() != self.id()
            || matches!(
                error,
                Error::Unknown
                    | Error::Source(SourceError::Evidence)
                    | Error::Store(market_data::Error::Unknown)
            )
        {
            return Err(Error::Unknown);
        }
        let attempt = self.attempt.as_ref().ok_or(Error::Conflict)?;
        store
            .catalog()
            .record_failure(attempt, error.code(), at)
            .await?;
        Ok(())
    }
}

// The original operation-specific Human admission is rechecked at every durable
// page boundary, as well as before and after the owning I/O/commit operations.
struct CommandRecorder<'a, 'w> {
    work: &'a AcquisitionWork,
    recorder: &'a mut WalRecorder<'w>,
}
impl onlyalpha_integration_contract::source::Recorder for CommandRecorder<'_, '_> {
    fn record(
        &mut self,
        observation: onlyalpha_integration_contract::source::Observation,
    ) -> std::result::Result<(), SourceError> {
        self.work.check().map_err(|_| SourceError::Evidence)?;
        onlyalpha_integration_contract::source::Recorder::record(self.recorder, observation)
    }
    fn finish(&mut self) -> std::result::Result<(), SourceError> {
        self.work.check().map_err(|_| SourceError::Evidence)?;
        onlyalpha_integration_contract::source::Recorder::finish(self.recorder)
    }
}

async fn readiness(
    store: &mut Storage<'_>,
    scope: &Scope,
) -> Result<(Vec<(String, String)>, Vec<Value>)> {
    let verified = store
        .read_range(scope, &queries::native_intervals(scope)?)
        .await?;
    let mut selected = BTreeMap::new();
    for evidence in verified.evidence {
        let id = evidence["revision_id"].as_str().ok_or(Error::Corrupt)?;
        let (revision, _) = store.read_exact(id).await?;
        for reference in revision.revision()["segment_refs"]
            .as_array()
            .ok_or(Error::Corrupt)?
        {
            let pair = reference
                .as_array()
                .filter(|v| v.len() == 2)
                .ok_or(Error::Corrupt)?;
            let id = pair[0].as_str().ok_or(Error::Corrupt)?.to_owned();
            let hash = pair[1].as_str().ok_or(Error::Corrupt)?.to_owned();
            if selected
                .insert(id, hash.clone())
                .is_some_and(|old| old != hash)
            {
                return Err(Error::Conflict);
            }
        }
    }
    let gaps = queries::coalesce_gaps(&verified.gaps, 7 * 86_400_000_000_000)?;
    Ok((selected.into_iter().collect(), gaps))
}

fn sealed_coverage(revision: &market_data::SealedRevision) -> Result<Value> {
    let manifest = revision.manifest().to_record();
    let scope = Scope::from_record(&manifest["scope"])?;
    let count = queries::native_intervals(&scope)?.len();
    Ok(
        json!({"status":revision.manifest().status().as_str(),"manifest_id":revision.manifest().id(),"manifest_fingerprint":manifest["fingerprint"],"expected_bar_count":count,"actual_bar_count":count,"issues":manifest["issues"],"gaps":manifest["gaps"].as_array().ok_or(Error::Corrupt)?.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?,"planned_acquisition_ranges":manifest["gaps"].as_array().ok_or(Error::Corrupt)?.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?}),
    )
}
