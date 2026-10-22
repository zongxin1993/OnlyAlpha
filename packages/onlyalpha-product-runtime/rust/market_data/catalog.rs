//! The existing append-only PostgreSQL catalog. No connections, DSNs or fallback.
use super::*;
use std::{collections::BTreeSet, time::Duration};
use tokio_postgres::{Client, Transaction, types::ToSql};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AcquisitionIntent {
    record: Value,
    pub(super) scope: Scope,
}
impl AcquisitionIntent {
    pub fn build(scope: Scope, provenance: &str, binding: &str, admitted_at: &str) -> Result<Self> {
        let mut value = json!({"source_id":scope.record["source_id"],"requested_scope":scope.record,"provenance":provenance,"integration_binding_fingerprint":binding,"identity_version":2,"admitted_at":utc(admitted_at)?.1});
        let fp = Self::identity(&value, &scope)?;
        value["acquisition_id"] = format!("acquisition:{fp}").into();
        value["request_fingerprint"] = fp.into();
        Self::read(value)
    }
    fn identity(v: &Value, scope: &Scope) -> Result<String> {
        provenance(&v["provenance"])?;
        if v["source_id"] != scope.record["source_id"] {
            return Err(Error::Unprovable);
        }
        let mut body = json!({"source_id":v["source_id"],"requested_scope":scope.canonical(),"provenance":v["provenance"]});
        if v["identity_version"] == 2 {
            let binding = text(&v["integration_binding_fingerprint"])?;
            if !crate::is_sha256_hex(binding) {
                return Err(Error::Unprovable);
            }
            body["integration_binding_fingerprint"] = binding.into();
        } else if v["identity_version"] != 1 {
            return Err(Error::Unprovable);
        }
        fingerprint(&body)
    }
    fn read(mut v: Value) -> Result<Self> {
        exact_keys(
            &v,
            &[
                "acquisition_id",
                "request_fingerprint",
                "source_id",
                "requested_scope",
                "provenance",
                "admitted_at",
                "integration_binding_fingerprint",
                "identity_version",
            ],
        )?;
        let scope = Scope::from_record(&v["requested_scope"])?;
        let fp = Self::identity(&v, &scope)?;
        if v["request_fingerprint"] != fp || v["acquisition_id"] != format!("acquisition:{fp}") {
            return Err(Error::Unprovable);
        }
        v["admitted_at"] = utc(text(&v["admitted_at"])?)?.1.into();
        Ok(Self { record: v, scope })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn id(&self) -> &str {
        self.record["acquisition_id"].as_str().expect("validated")
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AcquisitionAttempt {
    pub(super) record: Value,
}
impl AcquisitionAttempt {
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn is_unknown(&self) -> bool {
        self.record["outcome"].is_null()
    }
    pub fn id(&self) -> &str {
        self.record["attempt_id"].as_str().expect("validated")
    }
    fn read(mut v: Value) -> Result<Self> {
        exact_keys(
            &v,
            &[
                "attempt_id",
                "acquisition_id",
                "attempt_number",
                "identity_version",
                "started_at",
                "outcome",
                "completed_at",
                "detail",
                "revision_id",
            ],
        )?;
        let number = integer(&v["attempt_number"])?;
        if number < 1 {
            return Err(Error::Unprovable);
        }
        let id = text(&v["acquisition_id"])?;
        let body = if v["identity_version"] == 2 {
            json!({"acquisition_id":id,"attempt_number":number})
        } else if v["identity_version"] == 1 {
            json!({"acquisition_id":id,"outcome":v["outcome"],"revision_id":v["revision_id"],"detail":v["detail"]})
        } else {
            return Err(Error::Unprovable);
        };
        if v["attempt_id"] != format!("acquisition-attempt:{}", fingerprint(&body)?) {
            return Err(Error::Unprovable);
        }
        v["started_at"] = utc(text(&v["started_at"])?)?.1.into();
        if v["outcome"].is_null() {
            if v["identity_version"] != 2
                || ["completed_at", "revision_id", "detail"]
                    .iter()
                    .any(|k| !v[k].is_null())
            {
                return Err(Error::Unprovable);
            }
        } else {
            v["completed_at"] = utc(text(&v["completed_at"])?)?.1.into();
            text(&v["detail"])?;
            if utc(text(&v["started_at"])?)?.0 > utc(text(&v["completed_at"])?)?.0 {
                return Err(Error::Unprovable);
            }
            match text(&v["outcome"])? {
                "COMPLETE" => {
                    text(&v["revision_id"])?;
                }
                "FAILED" if v["revision_id"].is_null() => {}
                _ => return Err(Error::Unprovable),
            }
        }
        Ok(Self { record: v })
    }
}
/// Owning catalog operations share the caller's configured physical connection.
pub struct Catalog<'a> {
    pub(super) client: &'a mut Client,
    pub(super) row_limit: usize,
    pub(super) byte_limit: usize,
}
impl<'a> Catalog<'a> {
    pub fn new(client: &'a mut Client, row_limit: usize, byte_limit: usize) -> Result<Self> {
        if row_limit == 0 || row_limit > 1_000_000 || byte_limit == 0 || byte_limit > MAX_BYTES {
            return Err(Error::Invalid);
        }
        Ok(Self {
            client,
            row_limit,
            byte_limit,
        })
    }
    pub async fn admit_intent(&mut self, intent: &AcquisitionIntent) -> Result<AcquisitionIntent> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let existing = get(
            &tx,
            "market_acquisition_intent",
            "acquisition_id",
            intent.id(),
            self.byte_limit,
        )
        .await?;
        if existing.is_none() {
            insert(&tx, "market_acquisition_intent", &intent.record).await?;
        }
        let stored = AcquisitionIntent::read(
            get(
                &tx,
                "market_acquisition_intent",
                "acquisition_id",
                intent.id(),
                self.byte_limit,
            )
            .await?
            .ok_or(Error::Unprovable)?,
        )?;
        let mut proposed = intent.record.clone();
        proposed["admitted_at"] = stored.record["admitted_at"].clone();
        if proposed != stored.record {
            return Err(Error::Conflict);
        }
        tx.commit().await.map_err(|_| Error::Unknown)?;
        Ok(stored)
    }
    pub async fn intent(&mut self, id: &str) -> Result<Option<AcquisitionIntent>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let result = get(
            &tx,
            "market_acquisition_intent",
            "acquisition_id",
            id,
            self.byte_limit,
        )
        .await?
        .map(AcquisitionIntent::read)
        .transpose()?;
        tx.commit().await?;
        Ok(result)
    }
    pub async fn latest_attempt(&mut self, id: &str) -> Result<Option<AcquisitionAttempt>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let result = attempts(&tx, id, self.row_limit, self.byte_limit)
            .await?
            .pop();
        tx.commit().await?;
        Ok(result)
    }
    pub(super) async fn submission(
        &mut self,
        segment: &Segment,
        proof: &PhysicalProof,
        at: &str,
    ) -> Result<bool> {
        proof.validate(segment)?;
        let id = format!(
            "market-data-submission:{}",
            fingerprint(&json!({"segment_id":segment.id()}))?
        );
        let detail =
            json!({"schema_version":1,"segment":segment.record,"physical_proof":proof.record});
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let created=tx.execute("INSERT INTO market_recovery_event(recovery_event_id,segment_id,crash_boundary,outcome,detail,occurred_at) VALUES($1,NULL,'C3','STORE_SUBMISSION_STARTED',$2::text::jsonb,$3::text::timestamptz) ON CONFLICT DO NOTHING",&[&id,&canonical(&detail)?,&utc(at)?.1]).await?;
        let stored = get(
            &tx,
            "market_recovery_event",
            "recovery_event_id",
            &id,
            self.byte_limit,
        )
        .await?
        .ok_or(Error::Unprovable)?;
        if stored["recovery_event_id"] != id
            || !stored["segment_id"].is_null()
            || stored["crash_boundary"] != "C3"
            || stored["outcome"] != "STORE_SUBMISSION_STARTED"
            || stored["detail"] != detail
        {
            return Err(Error::Conflict);
        }
        utc(text(&stored["occurred_at"])?)?;
        // A commit ACK failure loses the one-send privilege. Re-observation cannot
        // recreate it, even if CH currently reports ABSENT.
        tx.commit().await.map_err(|_| Error::Unknown)?;
        Ok(created == 1)
    }
    pub(super) async fn publish_segments(
        &mut self,
        segments: &[(Segment, PhysicalProof)],
    ) -> Result<()> {
        if segments.is_empty() || segments.len() > self.row_limit {
            return Err(Error::Invalid);
        }
        let mut seen = BTreeSet::new();
        for (s, p) in segments {
            if !seen.insert(s.id()) {
                return Err(Error::Invalid);
            }
            p.validate(s)?;
        }
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        for (s, p) in segments {
            let v = &s.record;
            put(&tx,"market_source","source_id",text(&v["source_id"])?,&json!({"source_id":v["source_id"],"provider":v["provider"],"venue":v["venue"],"market":v["market"],"schema_version":1}),self.byte_limit).await?;
            let session_id = text(&v["capture_session_id"])?;
            let proposed = json!({"capture_session_id":session_id,"source_id":v["source_id"],"capture_mode":v["capture_mode"],"provider_schema":v["provider_schema"],"codec":v["codec"],"started_at":v["created_at"],"ended_at":null});
            if get(
                &tx,
                "market_capture_session",
                "capture_session_id",
                session_id,
                self.byte_limit,
            )
            .await?
            .is_none()
            {
                insert(&tx, "market_capture_session", &proposed).await?;
            }
            let session = get(
                &tx,
                "market_capture_session",
                "capture_session_id",
                session_id,
                self.byte_limit,
            )
            .await?
            .ok_or(Error::Unprovable)?;
            session_matches(&session, s)?;
            put(
                &tx,
                "market_ingest_segment",
                "segment_id",
                s.id(),
                v,
                self.byte_limit,
            )
            .await?;
            let event = json!({"event_id":format!("{}:DURABLE_SEGMENT_COMMITTED",s.id()),"segment_id":s.id(),"state":"DURABLE_SEGMENT_COMMITTED","occurred_at":v["sealed_at"],"detail":{"content_hash":s.content_hash()}});
            put(
                &tx,
                "market_segment_state_event",
                "event_id",
                text(&event["event_id"])?,
                &event,
                self.byte_limit,
            )
            .await?;
            put(&tx,"market_segment_physical_proof","segment_id",s.id(),&json!({"segment_id":s.id(),"proof_fingerprint":p.record["fingerprint"],"proof":p.record}),self.byte_limit).await?;
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await?;
        for (s, p) in segments {
            let actual = load_segment(&tx, s.id(), self.byte_limit).await?;
            if actual.0 != *s || actual.1 != *p {
                return Err(Error::Conflict);
            }
        }
        tx.commit().await.map_err(|_| Error::Unknown)
    }
    pub(super) async fn published_segment(
        &mut self,
        id: &str,
    ) -> Result<Option<(Segment, PhysicalProof)>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let result = if get(
            &tx,
            "market_ingest_segment",
            "segment_id",
            id,
            self.byte_limit,
        )
        .await?
        .is_some()
        {
            Some(load_segment(&tx, id, self.byte_limit).await?)
        } else {
            for table in [
                "market_segment_physical_proof",
                "market_segment_state_event",
                "market_coverage_manifest_segment",
                "market_revision_segment",
            ] {
                if !rows(
                    &tx,
                    &format!("SELECT to_jsonb(t)::text FROM {table} t WHERE segment_id=$1"),
                    &[&id],
                    self.row_limit,
                    self.byte_limit,
                )
                .await?
                .is_empty()
                {
                    return Err(Error::Unprovable);
                }
            }
            None
        };
        tx.commit().await?;
        Ok(result)
    }
    pub async fn segment(&mut self, id: &str) -> Result<(Segment, PhysicalProof)> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let result = load_segment(&tx, id, self.byte_limit).await?;
        tx.commit().await?;
        Ok(result)
    }
    pub(super) async fn publish_coverage(
        &mut self,
        manifest: &Manifest,
        normalizers: Value,
        parent: Value,
        reason: Value,
        at: &str,
    ) -> Result<Option<SealedRevision>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let refs = refs(&manifest.record["segment_refs"])?;
        for (id, h) in &refs {
            let (s, _) = load_segment(&tx, id, self.byte_limit).await?;
            if s.content_hash() != h || !s.recovery_scope()?.family_matches(&manifest.scope) {
                return Err(Error::Unprovable);
            }
        }
        let v = &manifest.record;
        let record = json!({"manifest_id":manifest.id(),"manifest_fingerprint":v["fingerprint"],"scope":manifest.scope.record,"complete":manifest.status()==CoverageStatus::Complete,"coverage_status":v["coverage_status"],"proof":v["proof"],"issues":v["issues"],"gaps":v["gaps"],"created_at":utc(at)?.1});
        put_preserve_time(
            &tx,
            "market_coverage_manifest",
            "manifest_id",
            manifest.id(),
            &record,
            "created_at",
            self.byte_limit,
        )
        .await?;
        put_refs(
            &tx,
            "market_coverage_manifest_segment",
            "manifest_id",
            manifest.id(),
            &refs,
            self.byte_limit,
        )
        .await?;
        let mut result = None;
        if manifest.status() == CoverageStatus::Complete {
            let proposed =
                SealedRevision::build(manifest.clone(), normalizers, parent, reason, at)?;
            if let Some(parent) = optional_text(&proposed.revision["parent_revision_id"])? {
                let ancestor = load_revision(&tx, parent, self.byte_limit).await?;
                if ancestor.manifest.scope != manifest.scope || parent == proposed.id() {
                    return Err(Error::Conflict);
                }
            }
            let owners = rows(
                &tx,
                "SELECT to_jsonb(t)::text FROM market_data_revision t WHERE manifest_id=$1",
                &[&manifest.id()],
                2,
                self.byte_limit,
            )
            .await?;
            if owners.len() > 1 {
                return Err(Error::Conflict);
            }
            let committed = if let Some(owner) = owners.first() {
                let prior =
                    load_revision(&tx, text(&owner["revision_id"])?, self.byte_limit).await?;
                if prior.revision != proposed.revision || prior.manifest != *manifest {
                    return Err(Error::Conflict);
                }
                prior
            } else {
                let v = &proposed.revision;
                let stored = json!({"revision_id":v["revision_id"],"revision_fingerprint":v["fingerprint"],"manifest_id":v["manifest_id"],"scope":v["scope"],"parent_revision_id":v["parent_revision_id"],"normalizers":v["normalizers"],"creation_reason":v["creation_reason"],"created_at":proposed.seal["sealed_at"]});
                put(
                    &tx,
                    "market_data_revision",
                    "revision_id",
                    proposed.id(),
                    &stored,
                    self.byte_limit,
                )
                .await?;
                put_refs(
                    &tx,
                    "market_revision_segment",
                    "revision_id",
                    proposed.id(),
                    &refs,
                    self.byte_limit,
                )
                .await?;
                put(
                    &tx,
                    "market_revision_seal",
                    "revision_id",
                    proposed.id(),
                    &proposed.seal,
                    self.byte_limit,
                )
                .await?;
                proposed
            };
            result = Some(committed);
        }
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await?;
        if load_manifest(&tx, manifest.id(), self.byte_limit).await? != *manifest {
            return Err(Error::Conflict);
        }
        if let Some(expected) = &result
            && load_revision(&tx, expected.id(), self.byte_limit).await? != *expected
        {
            return Err(Error::Conflict);
        }
        tx.commit().await.map_err(|_| Error::Unknown)?;
        Ok(result)
    }
    pub(super) async fn gc_manifests(
        &mut self,
        segment: &Segment,
    ) -> Result<Vec<(Manifest, Option<SealedRevision>)>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let selected = rows(
            &tx,
            "SELECT to_jsonb(t)::text FROM market_coverage_manifest_segment t WHERE segment_id=$1",
            &[&segment.id()],
            self.row_limit,
            self.byte_limit,
        )
        .await?;
        if selected.is_empty() {
            return Err(Error::Unprovable);
        }
        let mut result = vec![];
        let mut used = 0;
        for row in selected {
            if row["segment_content_hash"] != segment.content_hash() {
                return Err(Error::Unprovable);
            }
            let manifest = load_manifest(&tx, text(&row["manifest_id"])?, self.byte_limit).await?;
            if !manifest.scope.family_matches(&segment.recovery_scope()?) {
                return Err(Error::Unprovable);
            }
            let revision = if manifest.status() == CoverageStatus::Complete {
                let owners = rows(
                    &tx,
                    "SELECT to_jsonb(t)::text FROM market_data_revision t WHERE manifest_id=$1",
                    &[&manifest.id()],
                    2,
                    self.byte_limit,
                )
                .await?;
                if owners.len() != 1 {
                    return Err(Error::Unprovable);
                }
                Some(load_revision(&tx, text(&owners[0]["revision_id"])?, self.byte_limit).await?)
            } else {
                None
            };
            charge(&mut used, &manifest.record, self.byte_limit)?;
            if let Some(r) = &revision {
                charge_revision(&mut used, r, self.byte_limit)?;
            }
            result.push((manifest, revision));
        }
        tx.commit().await?;
        Ok(result)
    }
    pub async fn revision(&mut self, id: &str) -> Result<SealedRevision> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let result = load_revision(&tx, id, self.byte_limit).await?;
        tx.commit().await?;
        Ok(result)
    }
    /// Bounded owning context selection for original history, independent of
    /// current executable factories. Malformed scopes never disappear by SQL filter.
    pub async fn history_families(
        &mut self,
        source: &str,
        instrument: Option<&str>,
        original_revision: &str,
    ) -> Result<Vec<Scope>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let inventory = rows(
            &tx,
            "SELECT to_jsonb(t)::text FROM market_data_revision t",
            &[],
            self.row_limit,
            self.byte_limit,
        )
        .await?;
        let mut families: Vec<Scope> = vec![];
        let mut ids = BTreeSet::new();
        let mut used = 0;
        for row in inventory {
            charge(&mut used, &row, self.byte_limit)?;
            if !ids.insert(text(&row["revision_id"])?.to_owned()) {
                return Err(Error::Unprovable);
            }
            let scope = Scope::from_record(&row["scope"])?;
            let record = scope.to_record();
            if record["source_id"] != source
                || instrument.is_some_and(|id| record["instrument_id"] != id)
                || record["data_kind"] != "BAR"
            {
                continue;
            }
            let identity =
                onlyalpha_market_data_construction::OnlyConstructionIdentity::from_record(
                    &record["bar_construction"],
                )
                .map_err(|_| Error::Unprovable)?;
            if identity.plan().to_record()["integration_revision_fingerprint"] != original_revision
            {
                continue;
            }
            let revision = load_revision(&tx, text(&row["revision_id"])?, self.byte_limit).await?;
            charge_revision(&mut used, &revision, self.byte_limit)?;
            if revision.manifest().to_record()["scope"] != record {
                return Err(Error::Unprovable);
            }
            if !families.iter().any(|f| f.family_matches(&scope)) {
                families.push(scope);
            }
        }
        tx.commit().await?;
        Ok(families)
    }
    pub(super) async fn candidates(
        &mut self,
        family: &Scope,
        start: i64,
        end: i64,
    ) -> Result<Vec<SealedRevision>> {
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        // Do not SQL-filter JSON family fields: a missing whole scope/source or
        // malformed nested relation must not disappear as certified absence.
        let inventory = rows(
            &tx,
            "SELECT to_jsonb(t)::text FROM market_data_revision t",
            &[],
            self.row_limit,
            self.byte_limit,
        )
        .await?;
        let seals = rows(
            &tx,
            "SELECT to_jsonb(t)::text FROM market_revision_seal t",
            &[],
            self.row_limit,
            self.byte_limit,
        )
        .await?;
        let revision_ids: BTreeSet<_> = inventory
            .iter()
            .map(|v| text(&v["revision_id"]))
            .collect::<Result<_>>()?;
        if seals.iter().any(|v| {
            v["revision_id"]
                .as_str()
                .is_none_or(|id| !revision_ids.contains(id))
        }) {
            return Err(Error::Unprovable);
        }
        let mut current: std::collections::BTreeMap<String, SealedRevision> =
            std::collections::BTreeMap::new();
        let mut used = 0;
        for seal in &seals {
            charge(&mut used, seal, self.byte_limit)?;
        }
        for row in &inventory {
            charge(&mut used, row, self.byte_limit)?;
        }
        for row in inventory {
            let scope = Scope::from_record(&row["scope"])?;
            if !family.family_matches(&scope) || scope.start_ns() >= end || scope.end_ns() <= start
            {
                continue;
            }
            let revision = load_revision(&tx, text(&row["revision_id"])?, self.byte_limit).await?;
            charge_revision(&mut used, &revision, self.byte_limit)?;
            let key = canonical(&scope.record)?;
            let choose = if let Some(old) = current.get(&key) {
                (utc(text(&revision.seal["sealed_at"])?)?.0, revision.id())
                    > (utc(text(&old.seal["sealed_at"])?)?.0, old.id())
            } else {
                true
            };
            if choose {
                current.insert(key, revision);
            }
        }
        // Prove correspondence with the canonical DISTINCT ON view, including
        // sealed_at/revision_id tie order; never create or update a head table.
        let latest = rows(
            &tx,
            "SELECT to_jsonb(t)::text FROM market_latest_sealed_revision t",
            &[],
            self.row_limit,
            self.byte_limit,
        )
        .await?;
        for r in current.values() {
            if !latest.iter().any(|v| {
                v["revision_id"] == r.revision["revision_id"]
                    && v["scope"] == r.manifest.scope.record
                    && v["revision_fingerprint"] == r.revision["fingerprint"]
            }) {
                return Err(Error::Unprovable);
            }
        }
        let mut result: Vec<_> = current.into_values().collect();
        result.sort_by_key(|r| {
            (
                r.manifest.scope.start_ns(),
                r.manifest.scope.end_ns(),
                r.id().to_owned(),
            )
        });
        tx.commit().await?;
        Ok(result)
    }
    pub(super) async fn finish(
        &mut self,
        attempt: &AcquisitionAttempt,
        outcome: &str,
        revision: Option<&SealedRevision>,
        detail: &str,
        at: &str,
    ) -> Result<AcquisitionAttempt> {
        if !matches!(outcome, "COMPLETE" | "FAILED")
            || detail.trim().is_empty()
            || (outcome == "COMPLETE") != revision.is_some()
        {
            return Err(Error::Invalid);
        }
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        let mut projected = attempt.record.clone();
        projected["outcome"] = outcome.into();
        projected["revision_id"] = revision.map(|r| r.id()).into();
        projected["completed_at"] = utc(at)?.1.into();
        projected["detail"] = detail.into();
        let finished = AcquisitionAttempt::read(projected)?;
        let started = get(
            &tx,
            "market_data_acquisition_attempt",
            "attempt_id",
            attempt.id(),
            self.byte_limit,
        )
        .await?
        .ok_or(Error::Unprovable)?;
        for k in [
            "attempt_id",
            "acquisition_id",
            "attempt_number",
            "identity_version",
            "started_at",
        ] {
            let expected = if k == "started_at" {
                json!(utc(text(&started[k])?)?.1)
            } else {
                started[k].clone()
            };
            if expected != attempt.record[k] {
                return Err(Error::Conflict);
            }
        }
        let intent = AcquisitionIntent::read(
            get(
                &tx,
                "market_acquisition_intent",
                "acquisition_id",
                text(&attempt.record["acquisition_id"])?,
                self.byte_limit,
            )
            .await?
            .ok_or(Error::Unprovable)?,
        )?;
        if let Some(r) = revision {
            let stored = load_revision(&tx, r.id(), self.byte_limit).await?;
            if stored != *r || intent.scope != r.manifest.scope {
                return Err(Error::Unprovable);
            }
        }
        let record = json!({"attempt_id":attempt.id(),"outcome":outcome,"completed_at":finished.record["completed_at"],"revision_id":finished.record["revision_id"],"detail":detail});
        put(
            &tx,
            "market_data_acquisition_attempt_outcome",
            "attempt_id",
            attempt.id(),
            &record,
            self.byte_limit,
        )
        .await?;
        tx.commit().await.map_err(|_| Error::Unknown)?;
        Ok(finished)
    }
    pub async fn start_attempt(
        &mut self,
        lease: &ExecutionLease,
        at: &str,
    ) -> Result<AcquisitionAttempt> {
        if !lease.held().await? {
            return Err(Error::Busy);
        }
        let tx = self.client.transaction().await?;
        bounds(&tx).await?;
        tx.query_one("SELECT acquisition_id FROM market_acquisition_intent WHERE acquisition_id=$1 FOR UPDATE",&[&lease.id]).await?;
        let prior = attempts(&tx, &lease.id, self.row_limit, self.byte_limit).await?;
        // A new lease-owned historical execution is a distinct occurrence. The
        // previous started row remains UNKNOWN; this never grants CH resend.
        let number = prior.len() + 1;
        let fp = fingerprint(&json!({"acquisition_id":lease.id,"attempt_number":number}))?;
        let started = json!({"attempt_id":format!("acquisition-attempt:{fp}"),"acquisition_id":lease.id,"attempt_number":number,"identity_version":2,"started_at":utc(at)?.1});
        insert(&tx, "market_data_acquisition_attempt", &started).await?;
        let mut full = started;
        for key in ["outcome", "completed_at", "revision_id", "detail"] {
            full[key] = Value::Null;
        }
        let result = AcquisitionAttempt::read(full)?;
        if !lease.held().await? {
            return Err(Error::Unknown);
        }
        tx.commit().await.map_err(|_| Error::Unknown)?;
        if !lease.held().await? {
            return Err(Error::Unknown);
        }
        Ok(result)
    }
    pub async fn record_failure(
        &mut self,
        attempt: &AcquisitionAttempt,
        detail: &str,
        at: &str,
    ) -> Result<AcquisitionAttempt> {
        self.finish(attempt, "FAILED", None, detail, at).await
    }
}
async fn bounds(tx: &Transaction<'_>) -> Result<()> {
    tx.batch_execute(
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE; SET LOCAL search_path=pg_catalog,public",
    )
    .await?;
    crate::postgres::bounds(tx)
        .await
        .map_err(|_| Error::Unavailable)
}
async fn rows(
    tx: &Transaction<'_>,
    sql: &str,
    params: &[&(dyn ToSql + Sync)],
    limit: usize,
    bytes: usize,
) -> Result<Vec<Value>> {
    // The same snapshot preflights cumulative encoded length before transfer.
    let preflight = format!(
        "SELECT count(*)::bigint,COALESCE(sum(octet_length(value)),0)::bigint FROM ({sql} LIMIT {}) AS q(value)",
        limit + 1
    );
    let count = tx.query_one(&preflight, params).await?;
    let n: i64 = count.try_get(0).map_err(|_| Error::Unprovable)?;
    let size: i64 = count.try_get(1).map_err(|_| Error::Unprovable)?;
    if n < 0 || n > limit as i64 || size < 0 || size > bytes as i64 {
        return Err(Error::Unavailable);
    }
    let query = format!("{sql} LIMIT {}", limit + 1);
    let result = tx.query(&query, params).await?;
    if result.len() != n as usize {
        return Err(Error::Unavailable);
    }
    let mut used = 0;
    result
        .iter()
        .map(|r| {
            let raw: String = r.try_get(0).map_err(|_| Error::Unprovable)?;
            used += raw.len();
            if used > bytes {
                return Err(Error::Unavailable);
            }
            decode(&raw)
        })
        .collect()
}
async fn get(
    tx: &Transaction<'_>,
    table: &str,
    key: &str,
    id: &str,
    bytes: usize,
) -> Result<Option<Value>> {
    let mut v = rows(
        tx,
        &format!("SELECT to_jsonb(t)::text FROM {table} t WHERE {key}=$1"),
        &[&id],
        2,
        bytes,
    )
    .await?;
    if v.len() > 1 {
        return Err(Error::Unprovable);
    }
    Ok(v.pop())
}
async fn insert(tx: &Transaction<'_>, table: &str, v: &Value) -> Result<()> {
    tx.execute(&format!("INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table},$1::text::jsonb)).* ON CONFLICT DO NOTHING"),&[&canonical(v)?]).await?;
    Ok(())
}
fn normalize_times(v: &mut Value) -> Result<()> {
    for key in [
        "created_at",
        "sealed_at",
        "occurred_at",
        "started_at",
        "completed_at",
        "admitted_at",
    ] {
        if let Some(s) = v.get(key).filter(|v| !v.is_null()) {
            let t = utc(text(s)?)?.1;
            v[key] = t.into();
        }
    }
    Ok(())
}
async fn put(
    tx: &Transaction<'_>,
    table: &str,
    key: &str,
    id: &str,
    v: &Value,
    bytes: usize,
) -> Result<()> {
    insert(tx, table, v).await?;
    let mut observed = get(tx, table, key, id, bytes)
        .await?
        .ok_or(Error::Unprovable)?;
    normalize_times(&mut observed)?;
    if observed != *v {
        return Err(Error::Conflict);
    }
    Ok(())
}
async fn put_preserve_time(
    tx: &Transaction<'_>,
    table: &str,
    key: &str,
    id: &str,
    v: &Value,
    time: &str,
    bytes: usize,
) -> Result<()> {
    let mut proposed = v.clone();
    if let Some(prior) = get(tx, table, key, id, bytes).await? {
        proposed[time] = utc(text(&prior[time])?)?.1.into();
    }
    put(tx, table, key, id, &proposed, bytes).await
}
async fn put_refs(
    tx: &Transaction<'_>,
    table: &str,
    key: &str,
    id: &str,
    refs: &[(String, String)],
    bytes: usize,
) -> Result<()> {
    for (ordinal, (segment, hash)) in refs.iter().enumerate() {
        let mut r = json!({"ordinal":ordinal,"segment_id":segment,"segment_content_hash":hash});
        r[key] = id.into();
        insert(tx, table, &r).await?;
    }
    if load_refs(tx, table, key, id, refs.len() + 1, bytes).await? != *refs {
        return Err(Error::Conflict);
    }
    Ok(())
}
async fn load_refs(
    tx: &Transaction<'_>,
    table: &str,
    key: &str,
    id: &str,
    limit: usize,
    bytes: usize,
) -> Result<Vec<(String, String)>> {
    let records = rows(
        tx,
        &format!("SELECT to_jsonb(t)::text FROM {table} t WHERE {key}=$1 ORDER BY ordinal"),
        &[&id],
        limit,
        bytes,
    )
    .await?;
    for (i, v) in records.iter().enumerate() {
        if integer(&v["ordinal"])? != i as i64 || v[key] != id {
            return Err(Error::Unprovable);
        }
    }
    let v: Value = records
        .iter()
        .map(|v| json!([v["segment_id"], v["segment_content_hash"]]))
        .collect();
    refs(&v)
}
fn session_matches(v: &Value, s: &Segment) -> Result<()> {
    let expected = &s.record;
    for k in [
        "capture_session_id",
        "source_id",
        "capture_mode",
        "provider_schema",
        "codec",
    ] {
        if v[k] != expected[k] {
            return Err(Error::Unprovable);
        }
    }
    if utc(text(&v["started_at"])?)?.0 > utc(text(&s.record["created_at"])?)?.0 {
        return Err(Error::Unprovable);
    }
    if !v["ended_at"].is_null()
        && utc(text(&v["ended_at"])?)?.0 < utc(text(&s.record["sealed_at"])?)?.0
    {
        return Err(Error::Unprovable);
    }
    Ok(())
}
async fn load_segment(
    tx: &Transaction<'_>,
    id: &str,
    bytes: usize,
) -> Result<(Segment, PhysicalProof)> {
    let segment = Segment::from_record(
        &get(tx, "market_ingest_segment", "segment_id", id, bytes)
            .await?
            .ok_or(Error::Unprovable)?,
    )?;
    let source = get(
        tx,
        "market_source",
        "source_id",
        text(&segment.record["source_id"])?,
        bytes,
    )
    .await?
    .ok_or(Error::Unprovable)?;
    if source["source_id"] != segment.record["source_id"]
        || source["schema_version"] != 1
        || ["provider", "venue", "market"]
            .iter()
            .any(|k| source[k] != segment.record[k])
    {
        return Err(Error::Unprovable);
    }
    session_matches(
        &get(
            tx,
            "market_capture_session",
            "capture_session_id",
            text(&segment.record["capture_session_id"])?,
            bytes,
        )
        .await?
        .ok_or(Error::Unprovable)?,
        &segment,
    )?;
    let committed=rows(tx,"SELECT to_jsonb(t)::text FROM market_segment_state_event t WHERE segment_id=$1 AND state IN ('COMMITTED','DURABLE_SEGMENT_COMMITTED')",&[&id],2,bytes).await?;
    if committed.is_empty() {
        return Err(Error::Unprovable);
    }
    for event in committed {
        if event["segment_id"] != id || event["detail"]["content_hash"] != segment.content_hash() {
            return Err(Error::Unprovable);
        }
        utc(text(&event["occurred_at"])?)?;
    }
    let p = get(tx, "market_segment_physical_proof", "segment_id", id, bytes)
        .await?
        .ok_or(Error::Unprovable)?;
    let proof = PhysicalProof {
        record: p["proof"].clone(),
    };
    proof.validate(&segment)?;
    if p["segment_id"] != id || p["proof_fingerprint"] != proof.record["fingerprint"] {
        return Err(Error::Unprovable);
    }
    Ok((segment, proof))
}
async fn load_manifest(tx: &Transaction<'_>, id: &str, bytes: usize) -> Result<Manifest> {
    let row = get(tx, "market_coverage_manifest", "manifest_id", id, bytes)
        .await?
        .ok_or(Error::Unprovable)?;
    let refs = load_refs(
        tx,
        "market_coverage_manifest_segment",
        "manifest_id",
        id,
        100_000,
        bytes,
    )
    .await?;
    let v = json!({"manifest_id":id,"fingerprint":row["manifest_fingerprint"],"scope":row["scope"],"segment_refs":refs,"coverage_status":row["coverage_status"],"proof":row["proof"],"issues":row["issues"],"gaps":row["gaps"]});
    let result = Manifest::read(v)?;
    if row["complete"] != (result.status() == CoverageStatus::Complete) {
        return Err(Error::Unprovable);
    }
    utc(text(&row["created_at"])?)?;
    Ok(result)
}
async fn load_revision_body(
    tx: &Transaction<'_>,
    id: &str,
    bytes: usize,
) -> Result<SealedRevision> {
    let row = get(tx, "market_data_revision", "revision_id", id, bytes)
        .await?
        .ok_or(Error::NotFound)?;
    let seal = get(tx, "market_revision_seal", "revision_id", id, bytes)
        .await?
        .ok_or(Error::Unprovable)?;
    let manifest = load_manifest(tx, text(&row["manifest_id"])?, bytes).await?;
    let refs = load_refs(
        tx,
        "market_revision_segment",
        "revision_id",
        id,
        100_000,
        bytes,
    )
    .await?;
    let revision = json!({"revision_id":id,"fingerprint":row["revision_fingerprint"],"scope":row["scope"],"manifest_id":row["manifest_id"],"segment_refs":refs,"normalizers":row["normalizers"],"parent_revision_id":row["parent_revision_id"],"creation_reason":row["creation_reason"]});
    utc(text(&row["created_at"])?)?;
    if let Some(parent) = optional_text(&row["parent_revision_id"])? {
        let p = get(tx, "market_data_revision", "revision_id", parent, bytes)
            .await?
            .ok_or(Error::Unprovable)?;
        if p["scope"] != row["scope"] || parent == id {
            return Err(Error::Unprovable);
        }
    }
    SealedRevision::read(revision, seal, manifest)
}
async fn load_revision(tx: &Transaction<'_>, id: &str, bytes: usize) -> Result<SealedRevision> {
    let result = load_revision_body(tx, id, bytes).await?;
    let mut used = 0;
    charge_revision(&mut used, &result, bytes)?;
    let mut current = result.clone();
    let mut seen = BTreeSet::new();
    seen.insert(id.to_owned());
    while let Some(parent) = optional_text(&current.revision["parent_revision_id"])? {
        if seen.len() >= 10_000 {
            return Err(Error::Unavailable);
        }
        if !seen.insert(parent.to_owned()) {
            return Err(Error::Unprovable);
        }
        current = load_revision_body(tx, parent, bytes).await?;
        charge_revision(&mut used, &current, bytes)?;
        if current.manifest.scope != result.manifest.scope {
            return Err(Error::Unprovable);
        }
    }
    Ok(result)
}
async fn attempts(
    tx: &Transaction<'_>,
    id: &str,
    limit: usize,
    bytes: usize,
) -> Result<Vec<AcquisitionAttempt>> {
    let rows=rows(tx,"SELECT jsonb_build_object('attempt_id',a.attempt_id,'acquisition_id',a.acquisition_id,'attempt_number',a.attempt_number,'identity_version',a.identity_version,'started_at',a.started_at,'outcome',o.outcome,'completed_at',o.completed_at,'revision_id',o.revision_id,'detail',o.detail)::text FROM market_data_acquisition_attempt a LEFT JOIN market_data_acquisition_attempt_outcome o USING(attempt_id) WHERE a.acquisition_id=$1 ORDER BY a.attempt_number",&[&id],limit,bytes).await?;
    let mut result = vec![];
    for (i, v) in rows.into_iter().enumerate() {
        let a = AcquisitionAttempt::read(v)?;
        if a.record["acquisition_id"] != id || integer(&a.record["attempt_number"])? != i as i64 + 1
        {
            return Err(Error::Unprovable);
        }
        result.push(a);
    }
    Ok(result)
}
/// Dedicated Host-created physical session. Drop/cancellation revokes its driver;
/// same-session reentrant locks are rejected before taking execution ownership.
pub struct ExecutionLease {
    client: Option<Client>,
    driver: Option<tokio::task::JoinHandle<std::result::Result<(), tokio_postgres::Error>>>,
    id: String,
    key: i64,
}
impl ExecutionLease {
    /// Exact immutable Intent owned by this physical execution lease.
    pub fn intent_id(&self) -> &str {
        &self.id
    }
    pub async fn acquire(
        client: Client,
        driver: tokio::task::JoinHandle<std::result::Result<(), tokio_postgres::Error>>,
        id: &str,
    ) -> Result<Self> {
        let digest = Sha256::digest(id.as_bytes());
        let key = i64::from_be_bytes(digest[..8].try_into().map_err(|_| Error::Invalid)?);
        let mut lease = Self {
            client: Some(client),
            driver: Some(driver),
            id: id.into(),
            key,
        };
        let c = lease.client.as_mut().ok_or(Error::Unavailable)?;
        let tx = c.transaction().await?;
        bounds(&tx).await?;
        let intent = get(
            &tx,
            "market_acquisition_intent",
            "acquisition_id",
            id,
            MAX_BYTES,
        )
        .await?
        .ok_or(Error::Unprovable)?;
        AcquisitionIntent::read(intent)?;
        let mapping = json!({"lock_key":key,"acquisition_id":id});
        insert(&tx, "market_acquisition_execution_lock_key", &mapping).await?;
        let row=tx.query_one("SELECT acquisition_id FROM market_acquisition_execution_lock_key WHERE lock_key=$1",&[&key]).await?;
        let observed: String = row.try_get(0).map_err(|_| Error::Unprovable)?;
        if observed != id {
            return Err(Error::Conflict);
        }
        tx.commit().await.map_err(|_| Error::Unknown)?;
        if lease.held().await? {
            return Err(Error::Busy);
        }
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            lease
                .client
                .as_ref()
                .ok_or(Error::Unavailable)?
                .query_one("SELECT pg_try_advisory_lock($1)", &[&key]),
        )
        .await
        .map_err(|_| Error::Unavailable)??;
        if !result
            .try_get::<_, bool>(0)
            .map_err(|_| Error::Unprovable)?
            || !lease.held().await?
        {
            return Err(Error::Busy);
        }
        Ok(lease)
    }
    async fn held(&self) -> Result<bool> {
        if self.driver.as_ref().is_none_or(|h| h.is_finished()) {
            return Err(Error::Unavailable);
        }
        let row=tokio::time::timeout(Duration::from_secs(5),self.client.as_ref().ok_or(Error::Unavailable)?.query_one("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) AND pid=pg_backend_pid() AND classid=(($1::bigint >> 32)&4294967295)::oid AND objid=($1::bigint & 4294967295)::oid AND objsubid=1 AND mode='ExclusiveLock')",&[&self.key])).await.map_err(|_|Error::Unavailable)??;
        row.try_get(0).map_err(|_| Error::Unprovable)
    }
    pub async fn verify(&self) -> Result<()> {
        if self.held().await? {
            Ok(())
        } else {
            Err(Error::Busy)
        }
    }
    pub async fn close(mut self) -> Result<()> {
        if !self.held().await? {
            return Err(Error::Busy);
        }
        let row = tokio::time::timeout(
            Duration::from_secs(5),
            self.client
                .as_ref()
                .ok_or(Error::Unavailable)?
                .query_one("SELECT pg_advisory_unlock($1)", &[&self.key]),
        )
        .await
        .map_err(|_| Error::Unavailable)??;
        if !row.try_get::<_, bool>(0).map_err(|_| Error::Unprovable)? || self.held().await? {
            return Err(Error::Unavailable);
        }
        self.client.take();
        if let Some(mut driver) = self.driver.take() {
            match tokio::time::timeout(Duration::from_secs(5), &mut driver).await {
                Ok(Ok(Ok(()))) => {}
                _ => {
                    driver.abort();
                    return Err(Error::Unavailable);
                }
            }
        }
        Ok(())
    }
}
impl Drop for ExecutionLease {
    fn drop(&mut self) {
        self.client.take();
        if let Some(driver) = self.driver.take() {
            driver.abort();
        }
    }
}
