use super::reader::{frozen, load, locked, manifest};
use super::*;
use std::time::Instant;

fn scope(b: &FrozenJobBinding, namespace: &SemanticStoreId, owner: &str) -> Result<()> {
    let record = b.record();
    if record["scope"]["namespace"] != namespace.value() || record["scope"]["owner"] != owner {
        return Err(PublicationError::Mismatch);
    }
    Ok(())
}
fn candidate(c: &CompletedJobCandidate) -> Result<()> {
    let mut bytes = 0usize;
    if c.members
        .windows(2)
        .any(|v| v[0].descriptor.key() >= v[1].descriptor.key())
    {
        return Err(PublicationError::Integrity);
    }
    c.binding
        .result_plan()
        .check_inventory(
            &c.members
                .iter()
                .map(|m| m.descriptor.clone())
                .collect::<Vec<_>>(),
        )
        .map_err(|_| PublicationError::Integrity)?;
    for m in &c.members {
        if encode(
            &serde_json::to_value(&m.descriptor).map_err(|_| PublicationError::Integrity)?,
            8192,
        )? != m.descriptor_raw
        {
            return Err(PublicationError::Integrity);
        }
        document(&m.content, CONTENT_LIMIT)?;
        if digest(m.content.as_bytes()) != m.content_fingerprint {
            return Err(PublicationError::Integrity);
        }
        bytes = bytes
            .checked_add(m.content.len())
            .filter(|n| *n <= CONTENT_LIMIT)
            .ok_or(PublicationError::BudgetExceeded)?;
    }
    if manifest(&c.binding, &c.members)? != c.manifest
        || digest(c.manifest.as_bytes()) != c.fingerprint
    {
        return Err(PublicationError::Integrity);
    }
    Ok(())
}
impl PublicationRepository<'_> {
    /// The admitted input owner supplies a private registration, never caller JSON.
    pub async fn register(&mut self, registration: &FrozenBindingRegistration) -> Result<()> {
        if !self.writable {
            return Err(PublicationError::Denied);
        }
        let b = &registration.binding;
        scope(b, &self.namespace, &self.owner)?;
        let key = RunLocator::new(b.kind(), b.run_id())?;
        let tx = self.client.transaction().await.map_err(db)?;
        durable(&tx).await?;
        let (state, _, spec, admission) = locked(&tx, &key, false).await?;
        if spec != registration.specification || admission != registration.admission {
            return Err(PublicationError::Mismatch);
        }
        if !matches!(state.as_str(), "QUEUED" | "RUNNING") {
            return Err(PublicationError::OwnershipLost);
        }
        let exists=tx.query_opt("SELECT 1 FROM public.job_frozen_binding WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?.is_some();
        if exists {
            let (old, s, a) = frozen(&tx, &self.namespace, &self.owner, &key).await?;
            if old.record() != b.record() || s != spec || a != admission {
                return Err(PublicationError::Conflict);
            }
        } else {
            let raw = encode(&b.record(), 262144)?;
            tx.execute("INSERT INTO public.job_frozen_binding(job_kind,run_id,namespace_id,owner_id,specification_fingerprint,admission_fingerprint,binding_fingerprint,payload) VALUES($1,$2::text::uuid,$3::text::uuid,$4,$5,$6,$7,$8)",&[&kind(key.kind),&key.run,&self.namespace.value(),&self.owner,&spec,&admission,&b.fingerprint(),&raw]).await.map_err(db)?;
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(db)?;
        commit(tx).await
    }
    pub async fn publish(
        &mut self,
        claim: &AttemptClaim<'_>,
        completed: &CompletedJobCandidate,
    ) -> Result<PublishOutcome> {
        let start = Instant::now();
        if !self.writable {
            return Err(PublicationError::Denied);
        }
        if !claim.certain() {
            return Err(PublicationError::OutcomeUnknown);
        }
        candidate(completed)?;
        scope(&completed.binding, &self.namespace, &self.owner)?;
        let key = &claim.locator;
        if completed.binding.kind() != key.kind
            || completed.binding.run_id() != key.run
            || completed.binding.record()["runtime_generation"] != claim.generation
        {
            return Err(PublicationError::Mismatch);
        }
        let tx = self.client.transaction().await.map_err(db)?;
        durable(&tx).await?;
        let clock = Instant::now();
        let (state, revision, spec, admission) = locked(&tx, key, false).await?;
        let mut timings = PublishTimings {
            lock_wait_ns: clock.elapsed().as_nanos(),
            ..Default::default()
        };
        let (binding, s, a) = frozen(&tx, &self.namespace, &self.owner, key).await?;
        if spec != s || admission != a || binding.record() != completed.binding.record() {
            return Err(PublicationError::Mismatch);
        }
        if let Some(original) = load(&tx, binding, key).await? {
            if !original.same(completed) {
                return Err(PublicationError::Conflict);
            }
            commit(tx).await?;
            return Ok(PublishOutcome::AlreadyPublished(original));
        }
        if !matches!(state.as_str(), "RUNNING" | "CANCEL_REQUESTED") {
            return Err(PublicationError::OwnershipLost);
        }
        revision.checked_add(1).ok_or(PublicationError::Integrity)?;
        let claim_fence = if key.kind == JobKind::Backtest {
            "fencing_token"
        } else {
            "attempt_number::bigint"
        };
        let owner=tx.query_opt(&format!("SELECT 1 FROM public.{} WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND {claim_fence}=$5 AND state='ACTIVE' AND lease_expires_at>clock_timestamp() FOR UPDATE",attempt_table(key.kind)),&[&key.run,&claim.attempt,&claim.worker,&claim.number,&claim.fence]).await.map_err(db)?;
        if owner.is_none() {
            return Err(PublicationError::OwnershipLost);
        }
        let clock = Instant::now();
        for m in &completed.members {
            tx.execute("INSERT INTO public.job_result_member(job_kind,run_id,member_key,descriptor,content,content_fingerprint) VALUES($1,$2::text::uuid,$3,$4,$5,$6)",&[&kind(key.kind),&key.run,&m.descriptor.key(),&m.descriptor_raw,&m.content,&m.content_fingerprint]).await.map_err(db)?;
        }
        tx.execute("INSERT INTO public.job_publication(job_kind,run_id,attempt_id,worker_id,attempt_number,fence,binding_fingerprint,publication_fingerprint,manifest_payload) VALUES($1,$2::text::uuid,$3::text::uuid,$4::text::uuid,$5,$6,$7,$8,$9)",&[&kind(key.kind),&key.run,&claim.attempt,&claim.worker,&claim.number,&claim.fence,&completed.binding.fingerprint(),&completed.fingerprint,&completed.manifest]).await.map_err(db)?;
        timings.members_write_ns = clock.elapsed().as_nanos();
        let clock = Instant::now();
        let fence = if key.kind == JobKind::Backtest {
            "fencing_token"
        } else {
            "attempt_number::bigint"
        };
        let query = format!(
            "UPDATE public.{} SET state='SUCCEEDED',finished_at=clock_timestamp() WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid AND worker_instance_id=$3::text::uuid AND attempt_number=$4 AND {fence}=$5 AND state='ACTIVE' AND lease_expires_at>clock_timestamp()",
            attempt_table(key.kind)
        );
        if tx
            .execute(
                &query,
                &[
                    &key.run,
                    &claim.attempt,
                    &claim.worker,
                    &claim.number,
                    &claim.fence,
                ],
            )
            .await
            .map_err(db)?
            != 1
        {
            return Err(PublicationError::OwnershipLost);
        }
        let columns = if key.kind == JobKind::Backtest {
            "evidence_fingerprint=$4,result_fingerprint=$4,determinism_fingerprint=$4"
        } else {
            "research_result_fingerprint=$4,artifact_content_fingerprint=$4"
        };
        let query = format!(
            "UPDATE public.{} SET state='COMPLETED',revision=revision+1,finished_at=$3,{columns} WHERE run_id=$1::text::uuid AND revision=$2 AND state IN ('RUNNING','CANCEL_REQUESTED') AND $3>=queued_at AND $3>=started_at AND (cancel_requested_at IS NULL OR $3>=cancel_requested_at)",
            table(key.kind)
        );
        if tx
            .execute(
                &query,
                &[
                    &key.run,
                    &revision,
                    &completed.ended_at,
                    &completed.fingerprint,
                ],
            )
            .await
            .map_err(db)?
            != 1
        {
            return Err(PublicationError::OwnershipLost);
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(db)?;
        let result = load(&tx, completed.binding.clone(), key)
            .await?
            .ok_or(PublicationError::Integrity)?;
        if !result.same(completed) {
            return Err(PublicationError::Integrity);
        }
        timings.finalization_ns = clock.elapsed().as_nanos();
        let clock = Instant::now();
        commit(tx).await?;
        timings.commit_ns = clock.elapsed().as_nanos();
        timings.total_ns = start.elapsed().as_nanos();
        Ok(PublishOutcome::Committed {
            publication: result,
            timings,
        })
    }
}
