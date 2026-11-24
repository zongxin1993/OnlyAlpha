use super::*;
use crate::application::job_contract::fact_partition_rows;
use tokio_postgres::IsolationLevel;

impl ConfirmedUnpublished {
    /// Revalidate the observation in the owning claim/cancellation transaction.
    /// The Run lock remains held by `tx` through that caller's CAS and commit.
    /// A stale observation grants neither a claim nor permission to recompute.
    pub(crate) async fn recheck(
        &self,
        tx: &Transaction<'_>,
        key: &RunLocator,
        namespace: &SemanticStoreId,
        owner: &str,
    ) -> Result<bool> {
        if self.binding.kind() != key.kind
            || self.binding.run_id() != key.run
            || self.binding.namespace() != namespace.value()
            || self.binding.owner() != owner
            || self.active_attempts != 0
        {
            return Ok(false);
        }
        let (state, revision, specification, admission) = locked(tx, key, false).await?;
        if state != self.state || revision != self.revision {
            return Ok(false);
        }
        let (binding, s, a) = frozen(tx, namespace, owner, key).await?;
        if s != specification || a != admission {
            return Err(PublicationError::Mismatch);
        }
        if binding.fingerprint() != self.binding.fingerprint() {
            return Err(PublicationError::Mismatch);
        }
        let published = tx.query_one(
            "SELECT EXISTS(SELECT 1 FROM public.job_publication WHERE job_kind=$1 AND run_id=$2::text::uuid),EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid)",
            &[&kind(key.kind), &key.run],
        ).await.map_err(db)?;
        if published.get::<_, bool>(0) {
            return Ok(false);
        }
        if published.get::<_, bool>(1) {
            return Err(PublicationError::Integrity);
        }
        let (attempts, active) = unpublished_attempts(tx, key).await?;
        Ok(attempts == self.attempts && active == 0)
    }
}

pub(crate) async fn backtest_attempt_history(
    tx: &Transaction<'_>, run: &str, published: bool,
) -> Result<(i32, i64)> {
    let limit = crate::application::job_recovery::RetryBudget::finite_job().max_attempts();
    let root = tx.query_opt(
        "SELECT state, started_at IS NOT NULL, failure_code, last_attempt_number FROM public.backtest_run WHERE run_id=$1::text::uuid",
        &[&run],
    ).await.map_err(db)?.ok_or(PublicationError::MissingEvidence)?;
    let state: &str = root.get(0);
    let started: bool = root.get(1);
    let exhausted = root.get::<_, Option<&str>>(2) == Some("BACKTEST_ATTEMPTS_EXHAUSTED");
    let last: i32 = root.get(3);
    if (state == "COMPLETED") != published || !(0..=limit).contains(&last) || started != (last > 0) {
        return Err(PublicationError::Integrity);
    }
    let rows = tx.query(
        "SELECT attempt_number, fencing_token, state, \
         state <> 'EXPIRED' OR (finished_at >= lease_expires_at AND failure_code = 'LEASE_EXPIRED') IS TRUE AS valid_expiry \
         FROM public.backtest_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number LIMIT $2",
        &[&run, &(i64::from(limit) + 1)],
    ).await.map_err(db)?;
    if rows.len() < last as usize {
        return Err(PublicationError::MissingEvidence);
    }
    if rows.len() != last as usize {
        return Err(PublicationError::Integrity);
    }
    let mut latest = None;
    for (index, row) in rows.iter().enumerate() {
        let number = index as i32 + 1;
        let status: &str = row.get(2);
        if row.get::<_, i32>(0) != number || row.get::<_, i64>(1) != i64::from(number)
            || !row.get::<_, bool>("valid_expiry") || (number < last && status != "EXPIRED") {
            return Err(PublicationError::Integrity);
        }
        latest = Some(status);
    }
    let valid = match state {
        "QUEUED" => latest.is_none(),
        "RUNNING" | "CANCEL_REQUESTED" => matches!(latest, Some("ACTIVE" | "EXPIRED")),
        "COMPLETED" => latest == Some("SUCCEEDED"),
        "CANCELLED" => matches!(latest, None | Some("EXPIRED" | "CANCELLED")),
        "FAILED" if exhausted => last == limit && latest == Some("EXPIRED"),
        "FAILED" => latest == Some("FAILED"),
        _ => false,
    };
    if !valid {
        return Err(PublicationError::Integrity);
    }
    Ok((last, i64::from(latest == Some("ACTIVE"))))
}

pub(super) async fn unpublished_attempts(
    tx: &Transaction<'_>,
    key: &RunLocator,
) -> Result<(i32, i64)> {
    if key.kind == JobKind::Backtest {
        return backtest_attempt_history(tx, &key.run, false).await;
    }
    let query = format!(
        "SELECT COALESCE(max(attempt_number),0),count(*) FILTER(WHERE state='ACTIVE'),\
         COALESCE(bool_or(state='SUCCEEDED'),false) FROM public.{} WHERE run_id=$1::text::uuid",
        attempt_table(key.kind),
    );
    let row = tx.query_one(&query, &[&key.run]).await.map_err(db)?;
    if row.get::<_, bool>(2) {
        return Err(PublicationError::Integrity);
    }
    Ok((row.get(0), row.get(1)))
}

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
    if b.namespace() != scope.value() || b.owner() != owner {
        return Err(PublicationError::Mismatch);
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
            use tokio_postgres::error::SqlState;
            if e.code() == Some(&SqlState::LOCK_NOT_AVAILABLE)
                || (nowait && e.code() == Some(&SqlState::T_R_SERIALIZATION_FAILURE))
            {
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
    guard: MutationGuard,
    origin: Option<backtest::Origin<'_, '_>>,
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
    let rows=tx.query("SELECT descriptor,content,content_fingerprint,member_key FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid ORDER BY member_key COLLATE \"C\"",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    if rows.len() > 1024 {
        return Err(PublicationError::BudgetExceeded);
    }
    let verify_backtest = key.kind == JobKind::Backtest && matches!(guard, MutationGuard::Node);
    let mut members = Vec::new();
    let mut bodies = Vec::new();
    let mut bytes = 0usize;
    let mut facts = 0;
    let mut fact_partitions = Vec::new();
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
        let value = document(&content, CONTENT_LIMIT)?;
        if descriptor.key() != row.get::<_, &str>(3)
            || digest(content.as_bytes()) != content_fingerprint
        {
            return Err(PublicationError::Integrity);
        }
        match descriptor.kind() {
            MemberKind::CloseCurve => descriptor
                .verify_close_curve(&value)
                .map_err(|_| PublicationError::Integrity)?,
            MemberKind::ExecutionFacts => {
                let count = descriptor
                    .verify_execution_facts(&value, facts)
                    .map_err(|_| PublicationError::Integrity)?;
                facts += count;
                fact_partitions.push(count);
            }
            _ => {}
        }
        if verify_backtest {
            bodies.push(value);
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
    if key.kind == JobKind::Backtest
        && (facts == 0
            || fact_partitions.iter().enumerate().any(|(index, count)| {
                *count != fact_partition_rows(facts, fact_partitions.len(), index)
            }))
    {
        return Err(PublicationError::Integrity);
    }
    if manifest(&binding, &members)? != encode(&expected, 1048576)? {
        return Err(PublicationError::Integrity);
    }
    let pins = if key.kind == JobKind::Backtest {
        "evidence_fingerprint,result_fingerprint,determinism_fingerprint"
    } else {
        "artifact_content_fingerprint"
    };
    // 与发布身份逐项相等的列数；Research 另取科学结果身份列与因果引用列。
    let pinned = if key.kind == JobKind::Backtest { 3 } else { 1 };
    let references = if key.kind == JobKind::Research {
        ",research_result_fingerprint,CASE WHEN cardinality(calculation_execution_evidence_fingerprints)<=1024 THEN calculation_execution_evidence_fingerprints ELSE NULL END"
    } else {
        ""
    };
    let root=tx.query_one(&format!("SELECT state,specification_fingerprint,admission_resolution_fingerprint,{pins}{references} FROM public.{} WHERE run_id=$1::text::uuid",table(key.kind)),&[&key.run]).await.map_err(db)?;
    let original=tx.query_one("SELECT specification_fingerprint,admission_fingerprint FROM public.job_frozen_binding WHERE job_kind=$1 AND run_id=$2::text::uuid",&[&kind(key.kind),&key.run]).await.map_err(db)?;
    // 正式 Run 结果列逐项核对，口径与迁移 0084 的守卫一致：Backtest 三列与 Research 的
    // artifact_content_fingerprint 等于本发布的 publication_fingerprint（发布身份）。
    // Research 的 research_result_fingerprint 是科学结果身份，此处只取出并核对格式；
    // research_evidence::publication 在成员正文上用同一科学域公式重算并核对相等。
    if root.get::<_, String>(0) != "COMPLETED"
        || root.get::<_, String>(1) != original.get::<_, String>(0)
        || root.get::<_, String>(2) != original.get::<_, String>(1)
        || (3..3 + pinned)
            .any(|i| root.get::<_, Option<String>>(i).as_deref() != Some(fp.as_str()))
    {
        return Err(PublicationError::Integrity);
    }
    let mut research_result = None;
    if key.kind == JobKind::Research {
        let result = root
            .get::<_, Option<String>>(4)
            .filter(|value| crate::is_sha256_hex(value))
            .ok_or(PublicationError::Integrity)?;
        research_result = Some(result);
        let actual = root
            .get::<_, Option<Vec<String>>>(5)
            .ok_or(PublicationError::BudgetExceeded)?;
        if actual != research_execution_references(&members)? {
            return Err(PublicationError::Integrity);
        }
    }
    if key.kind == JobKind::Backtest {
        backtest_attempt_history(tx, &key.run, true).await?;
    }
    let fence = if key.kind == JobKind::Backtest {
        "fencing_token"
    } else {
        "attempt_number::bigint"
    };
    let attempts = tx.query(
        &format!("SELECT attempt_id::text,worker_instance_id::text,attempt_number,{fence},\
                  finished_at IS NOT NULL AND finished_at<=lease_expires_at \
                  FROM public.{} WHERE run_id=$1::text::uuid AND state='SUCCEEDED' LIMIT 2", attempt_table(key.kind)),
        &[&key.run],
    ).await.map_err(db)?;
    let [attempt] = attempts.as_slice() else {
        return Err(PublicationError::Integrity);
    };
    let winner = PublicationAttempt {
        attempt: p.get(3),
        worker: p.get(4),
        number: p.get(5),
        fence: p.get(6),
    };
    if winner.attempt != attempt.get::<_, &str>(0)
        || winner.worker != attempt.get::<_, &str>(1)
        || winner.number != attempt.get::<_, i32>(2)
        || winner.fence != attempt.get::<_, i64>(3)
        || !attempt.get::<_, bool>(4)
    {
        return Err(PublicationError::Integrity);
    }
    if verify_backtest {
        backtest::verify(tx, origin.ok_or(PublicationError::Denied)?, &binding, &members, &bodies).await?;
    }
    Ok(Some(PublishedJobResult {
        binding,
        winner,
        specification: root.get(1),
        admission: root.get(2),
        fingerprint: fp,
        manifest: expected,
        research_result,
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
    /// Immutable admitted input values only: no READY, loaded input, Claim or
    /// completion permission. Run and binding are observed in one snapshot.
    pub async fn frozen_binding(&mut self, key: &RunLocator) -> Result<FrozenJobBinding> {
        let tx = self
            .client
            .build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(db)?;
        bounded(&tx).await?;
        let (binding, specification, admission) =
            frozen(&tx, &self.namespace, &self.owner, key).await?;
        let row = tx.query_opt(&format!("SELECT specification_fingerprint,admission_resolution_fingerprint FROM public.{} WHERE run_id=$1::text::uuid",table(key.kind)),&[&key.run]).await.map_err(db)?.ok_or(PublicationError::Integrity)?;
        if row.get::<_, String>(0) != specification || row.get::<_, String>(1) != admission {
            return Err(PublicationError::Integrity);
        }
        commit(tx).await?;
        Ok(binding)
    }
    /// Read complete content in one immutable snapshot. Missing report is NOT a
    /// certificate of absence and does not authorize a retry/new Attempt.
    pub async fn read(&mut self, key: &RunLocator) -> Result<PublishedJobResult> {
        self.read_if_present(key)
            .await?
            .ok_or(PublicationError::MissingEvidence)
    }
    /// 同一不可变快照读取，但把"没有发布行"如实报告为 `Ok(None)`：本 Run 使用哪种结果证据
    /// 由调用方决定。存在发布行而任一项校验失败仍是硬错误，不得据此改用其他证据来源。
    pub async fn read_if_present(
        &mut self,
        key: &RunLocator,
    ) -> Result<Option<PublishedJobResult>> {
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
        let result = load(&tx, binding, key, self.mutation_guard, None).await?;
        commit(tx).await?;
        Ok(result)
    }

    pub(crate) async fn read_backtest(
        &mut self,
        key: &RunLocator,
        metadata: &mut Client,
    ) -> Result<PublishedJobResult> {
        if key.kind != JobKind::Backtest || self.writable {
            return Err(PublicationError::Denied);
        }
        let facts = self.client.build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(db)?;
        bounded(&facts).await?;
        let (binding, _, _) = frozen(&facts, &self.namespace, &self.owner, key).await?;
        // Establish the metadata snapshot after the fixed reader has established its cut.
        let metadata = metadata.build_transaction()
            .isolation_level(IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(db)?;
        bounded(&metadata).await?;
        let result = load(&facts, binding, key, self.mutation_guard, Some(backtest::Origin::Reader(&metadata)))
            .await?.ok_or(PublicationError::MissingEvidence)?;
        commit(metadata).await?;
        commit(facts).await?;
        Ok(result)
    }

    /// A resolved original Run lock is mandatory before asserting unpublished.
    /// The observation is not an execution-inactive proof or a new Claim permit.
    pub async fn observe(&mut self, key: &RunLocator) -> Result<PublicationObservation> {
        if !self.writable {
            return Err(PublicationError::Denied);
        }
        let mut builder = self.client.build_transaction();
        if key.kind == JobKind::Backtest && self.control.is_some() {
            builder = builder.isolation_level(IsolationLevel::RepeatableRead);
        }
        let tx = builder.start().await.map_err(db)?;
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
        let origin = self.control.map(backtest::Origin::Control);
        let result = if let Some(p) = load(&tx, binding.clone(), key, self.mutation_guard, origin).await? {
            PublicationObservation::Published(p)
        } else {
            if !matches!(
                state.as_str(),
                "QUEUED" | "RUNNING" | "CANCEL_REQUESTED" | "FAILED" | "CANCELLED"
            ) {
                return Err(PublicationError::Integrity);
            }
            // A missing root cannot certify absence while any partial result
            // survives. Check this even when normal deferred constraints would
            // have rejected that storage state at insertion.
            if tx.query_one(
                "SELECT EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind=$1 AND run_id=$2::text::uuid)",
                &[&kind(key.kind), &key.run],
            ).await.map_err(db)?.get::<_, bool>(0) {
                return Err(PublicationError::Integrity);
            }
            // The original Run lock serializes claim, expiry and publication.
            // ACTIVE includes expired-but-not-yet-relinquished owners: expiry
            // is a separate existing authority operation, never inferred here.
            let (attempts, active_attempts) = unpublished_attempts(&tx, key).await?;
            PublicationObservation::ConfirmedUnpublished(ConfirmedUnpublished {
                binding,
                revision,
                state,
                attempts,
                active_attempts,
            })
        };
        commit(tx).await?;
        Ok(result)
    }
}
