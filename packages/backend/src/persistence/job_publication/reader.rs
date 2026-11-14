use super::*;
use tokio_postgres::IsolationLevel;

pub(super) async fn frozen(
    tx: &Transaction<'_>,
    scope: &SemanticStoreId,
    owner: &str,
    key: &RunLocator,
) -> Result<(FrozenJobBinding, String, String)> {
    let r=tx.query_opt("SELECT namespace_id::text,owner_id,CASE WHEN octet_length(payload)<=262144 THEN payload END,binding_fingerprint,specification_fingerprint,admission_fingerprint FROM public.job_frozen_binding WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?.ok_or(PublicationError::MissingEvidence)?;
    if r.get::<_, String>(0) != scope.value() || r.get::<_, String>(1) != owner {
        return Err(PublicationError::Mismatch);
    }
    let raw: String = r
        .get::<_, Option<String>>(2)
        .ok_or(PublicationError::BudgetExceeded)?;
    let value = document(&raw, 262144)?;
    let b = FrozenJobBinding::from_record(&value).map_err(|_| PublicationError::Integrity)?;
    if b.fingerprint() != r.get::<_, String>(3) || b.run_id() != key.run || b.kind() != key.kind {
        return Err(PublicationError::Integrity);
    }
    Ok((b, r.get(4), r.get(5)))
}
pub(super) async fn locked(
    tx: &Transaction<'_>,
    key: &RunLocator,
    nowait: bool,
) -> Result<(String, i64, String, String)> {
    let query = format!(
        "SELECT state,revision,specification_fingerprint,admission_resolution_fingerprint FROM public.{} WHERE run_id=$1::text::uuid FOR UPDATE{}",
        table(key.kind),
        if nowait { " NOWAIT" } else { "" }
    );
    let row = tx
        .query_opt(&query, &[&key.run])
        .await
        .map_err(|e| {
            if e.code() == Some(&tokio_postgres::error::SqlState::LOCK_NOT_AVAILABLE) {
                PublicationError::OutcomeUnknown
            } else {
                db(e)
            }
        })?
        .ok_or(PublicationError::MissingEvidence)?;
    Ok((row.get(0), row.get(1), row.get(2), row.get(3)))
}
pub(super) async fn load(
    tx: &Transaction<'_>,
    binding: FrozenJobBinding,
    key: &RunLocator,
) -> Result<Option<PublishedJobResult>> {
    let p=tx.query_opt("SELECT publication_fingerprint,CASE WHEN octet_length(manifest_payload)<=1048576 THEN manifest_payload END,binding_fingerprint,attempt_id::text,worker_id::text,attempt_number,fence FROM public.job_publication WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    let Some(p) = p else { return Ok(None) };
    if p.get::<_, String>(2) != binding.fingerprint() {
        return Err(PublicationError::Integrity);
    }
    let raw: String = p
        .get::<_, Option<String>>(1)
        .ok_or(PublicationError::BudgetExceeded)?;
    let expected = document(&raw, 1048576)?;
    let fp: String = p.get(0);
    if digest(raw.as_bytes()) != fp {
        return Err(PublicationError::Integrity);
    }
    let size=tx.query_one("SELECT count(*)::bigint,COALESCE(sum(octet_length(content)),0)::bigint,COALESCE(max(octet_length(descriptor)),0)::bigint FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    if size.get::<_, i64>(0) > 1024
        || size.get::<_, i64>(1) > CONTENT_LIMIT as i64
        || size.get::<_, i64>(2) > 8192
    {
        return Err(PublicationError::BudgetExceeded);
    }
    let rows=tx.query("SELECT descriptor,content,content_fingerprint FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid ORDER BY member_key COLLATE \"C\"",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    if rows.len() > 1024 {
        return Err(PublicationError::BudgetExceeded);
    }
    let mut members = Vec::new();
    let mut bytes = 0usize;
    for row in rows {
        let descriptor_raw: String = row.get(0);
        let descriptor: ResultMember = serde_json::from_value(document(&descriptor_raw, 8192)?)
            .map_err(|_| PublicationError::Integrity)?;
        let content: String = row.get(1);
        let content_fingerprint: String = row.get(2);
        bytes = bytes
            .checked_add(content.len())
            .filter(|v| *v <= CONTENT_LIMIT)
            .ok_or(PublicationError::BudgetExceeded)?;
        document(&content, CONTENT_LIMIT)?;
        if digest(content.as_bytes()) != content_fingerprint {
            return Err(PublicationError::Integrity);
        }
        members.push(PreparedMember {
            descriptor,
            descriptor_raw,
            content,
            content_fingerprint,
        });
    }
    binding
        .result_plan()
        .check_inventory(
            &members
                .iter()
                .map(|m| m.descriptor.clone())
                .collect::<Vec<_>>(),
        )
        .map_err(|_| PublicationError::Integrity)?;
    if manifest(&binding, &members)? != encode(&expected, 1048576)? {
        return Err(PublicationError::Integrity);
    }
    let pins = if key.kind == JobKind::Backtest {
        "evidence_fingerprint,result_fingerprint,determinism_fingerprint"
    } else {
        "research_result_fingerprint,artifact_content_fingerprint,research_result_fingerprint"
    };
    let root=tx.query_one(&format!("SELECT state,specification_fingerprint,admission_resolution_fingerprint,{pins} FROM public.{} WHERE run_id=$1::text::uuid",table(key.kind)),&[&key.run]).await.map_err(db)?;
    let original=tx.query_one("SELECT specification_fingerprint,admission_fingerprint FROM public.job_frozen_binding WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    if root.get::<_, String>(0) != "COMPLETED"
        || root.get::<_, String>(1) != original.get::<_, String>(0)
        || root.get::<_, String>(2) != original.get::<_, String>(1)
        || (3..6).any(|i| root.get::<_, Option<String>>(i).as_deref() != Some(fp.as_str()))
    {
        return Err(PublicationError::Integrity);
    }
    let fence = if key.kind == JobKind::Backtest {
        "fencing_token"
    } else {
        "attempt_number::bigint"
    };
    let attempt=tx.query_opt(&format!("SELECT worker_instance_id::text,attempt_number,{fence},state,finished_at IS NOT NULL AND finished_at<=lease_expires_at FROM public.{} WHERE run_id=$1::text::uuid AND attempt_id=$2::text::uuid",attempt_table(key.kind)),&[&key.run,&p.get::<_,String>(3)]).await.map_err(db)?.ok_or(PublicationError::Integrity)?;
    if attempt.get::<_, String>(0) != p.get::<_, String>(4)
        || attempt.get::<_, i32>(1) != p.get::<_, i32>(5)
        || attempt.get::<_, i64>(2) != p.get::<_, i64>(6)
        || attempt.get::<_, String>(3) != "SUCCEEDED"
        || !attempt.get::<_, bool>(4)
    {
        return Err(PublicationError::Integrity);
    }
    Ok(Some(PublishedJobResult {
        binding,
        fingerprint: fp,
        members,
    }))
}
pub(super) fn manifest(binding: &FrozenJobBinding, members: &[PreparedMember]) -> Result<String> {
    encode(
        &serde_json::json!({"contract":"PG_JOB_RESULT_V1","binding_fingerprint":binding.fingerprint(),"members":members.iter().map(|m|serde_json::json!({"key":m.descriptor.key(),"descriptor_fingerprint":digest(m.descriptor_raw.as_bytes()),"content_fingerprint":m.content_fingerprint})).collect::<Vec<_>>()}),
        1048576,
    )
}
impl PublicationRepository<'_> {
    /// Read complete content in one immutable snapshot. Missing report is NOT a
    /// certificate of absence and does not authorize a retry/new Attempt.
    pub async fn read(&mut self, key: &RunLocator) -> Result<PublishedJobResult> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let (binding, _, _) = frozen(&tx, &self.namespace, &self.owner, key).await?;
        let result = load(&tx, binding, key)
            .await?
            .ok_or(PublicationError::MissingEvidence)?;
        commit(tx).await?;
        Ok(result)
    }
    /// A resolved original Run lock is mandatory before asserting unpublished.
    /// The observation is not an execution-inactive proof or a new Claim permit.
    pub async fn observe(&mut self, key: &RunLocator) -> Result<PublicationObservation> {
        if !self.writable {
            return Err(PublicationError::Denied);
        }
        let tx = self.client.transaction().await.map_err(db)?;
        bounded(&tx).await?;
        let (state, revision, spec, admission) = match locked(&tx, key, true).await {
            Err(PublicationError::OutcomeUnknown) => {
                tx.rollback().await.map_err(db)?;
                return Ok(PublicationObservation::Unresolved);
            }
            v => v?,
        };
        let (binding, s, a) = frozen(&tx, &self.namespace, &self.owner, key).await?;
        if spec != s || admission != a {
            return Err(PublicationError::Mismatch);
        }
        let result = if let Some(p) = load(&tx, binding.clone(), key).await? {
            PublicationObservation::Published(p)
        } else {
            if !matches!(
                state.as_str(),
                "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "FAILED" | "CANCELLED"
            ) {
                return Err(PublicationError::Integrity);
            }
            PublicationObservation::ConfirmedUnpublished(ConfirmedUnpublished {
                binding,
                revision,
                state,
            })
        };
        commit(tx).await?;
        Ok(result)
    }
}
