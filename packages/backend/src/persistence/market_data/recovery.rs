//! One protocol for normal sealed drain and exclusive startup recovery.
use super::physical::{self, PhysicalState};
use super::*;
use crate::persistence::market_data_wal::{Recovery, SealedWal, Wal};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DrainBoundary {
    BeforeStore,
    RawWritten,
    StoreWritten,
    Verified,
    CatalogCommitted,
}
/// Explicit immutable publication parent/reason and caller-supplied UTC audit time.
#[derive(Clone, Copy, Debug)]
pub struct RevisionPublication<'a> {
    pub parent: Option<&'a str>,
    pub reason: &'a str,
    pub at: &'a str,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DrainOutcome {
    pub coverage: Option<Manifest>,
    pub revision: Option<SealedRevision>,
    pub segment_ids: Vec<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedRange {
    pub coverage_status: CoverageStatus,
    pub facts: Vec<Value>,
    pub evidence: Vec<Value>,
    pub gaps: Vec<Value>,
    pub issues: Vec<String>,
    pub expected_base_fact_count: usize,
    pub complete_interval_count: usize,
}
/// Actual storage capability. The Host retains access policy, deployment admission
/// and singleton lifecycle; this module never creates a provider or HTTP ingress.
pub struct Storage<'a> {
    catalog: Catalog<'a>,
    clickhouse: &'a ClickHouse,
    limit: usize,
}
impl<'a> Storage<'a> {
    pub fn new(catalog: Catalog<'a>, clickhouse: &'a ClickHouse, limit: usize) -> Result<Self> {
        if limit == 0 || limit > 1_000_000 {
            return Err(Error::Invalid);
        }
        Ok(Self {
            catalog,
            clickhouse,
            limit,
        })
    }
    pub fn catalog(&mut self) -> &mut Catalog<'a> {
        &mut self.catalog
    }
    pub async fn drain(
        &mut self,
        wal: &mut SealedWal,
        segment_ids: &[String],
        scope: Option<&Scope>,
        publication: RevisionPublication<'_>,
        mut proceed: impl FnMut(DrainBoundary) -> bool,
    ) -> Result<DrainOutcome> {
        let RevisionPublication { parent, reason, at } = publication;
        if segment_ids.is_empty() || segment_ids.len() > self.limit {
            return Err(Error::Invalid);
        }
        let mut ids = segment_ids.to_vec();
        ids.sort();
        if ids.windows(2).any(|p| p[0] == p[1]) {
            return Err(Error::Invalid);
        }
        let mut used = 0;
        let mut batches = vec![];
        let mut facts = vec![];
        for id in &ids {
            let segment = Segment::from_record(&wal.load_segment(id)?)?;
            charge(&mut used, &segment.record, self.catalog.byte_limit)?;
            let records = wal.read_sealed(id)?;
            for record in &records {
                charge(&mut used, record, self.catalog.byte_limit)?;
            }
            let added = records
                .iter()
                .map(|b| b["canonical_facts"].as_array().map_or(0, Vec::len))
                .sum::<usize>();
            if facts
                .len()
                .checked_add(added)
                .is_none_or(|n| n > self.limit)
            {
                return Err(Error::Unavailable);
            }
            let expected = physical::expected(&segment, &records)?;
            let fresh_proof = physical::proof(&segment, &expected, false)?;
            charge(&mut used, &fresh_proof.record, self.catalog.byte_limit)?;
            facts.extend(
                records
                    .iter()
                    .flat_map(|b| b["canonical_facts"].as_array().into_iter().flatten())
                    .cloned(),
            );
            let published = self.catalog.published_segment(segment.id()).await?;
            let actual = self.clickhouse.snapshot(&segment).await?;
            charge_rows(&mut used, &actual, self.catalog.byte_limit)?;
            let (proof, state, retained) = if let Some((stored, proof)) = published {
                if stored != segment {
                    return Err(Error::Conflict);
                }
                physical::verify_published(&segment, &expected, &actual, &proof)?;
                (proof, PhysicalState::Exact, true)
            } else {
                let state = physical::classify(&expected, &actual)?;
                if !matches!(state, PhysicalState::Absent | PhysicalState::Exact) {
                    return Err(Error::Conflict);
                }
                (fresh_proof, state, false)
            };
            batches.push((segment, proof, expected, state, retained));
        }
        if facts.len() > self.limit {
            return Err(Error::Unavailable);
        }
        let segments = batches
            .iter()
            .map(|(s, _, _, _, _)| s.clone())
            .collect::<Vec<_>>();
        // Validate all scopes and coverage before the first mutation. COMPLETE is
        // still only a candidate until all physical and catalog proof is durable.
        if scope.is_none() && !facts.is_empty() {
            return Err(Error::Invalid);
        }
        utc(at)?;
        text(&json!(reason))?;
        if let Some(parent) = parent {
            text(&json!(parent))?;
        }
        let manifest = scope
            .map(|scope| coverage(scope, &segments, &facts, self.limit))
            .transpose()?;
        let normalizers = normalizers(&facts)?;
        for (segment, proof, expected, state, _) in &batches {
            if !proceed(DrainBoundary::BeforeStore) {
                return Err(Error::Stopped);
            }
            if *state == PhysicalState::Absent {
                if !self.catalog.submission(segment, proof, at).await? {
                    return Err(Error::Unknown);
                }
                for table in TABLES {
                    let rows = expected.get(table).ok_or(Error::Unprovable)?;
                    if !rows.is_empty() {
                        self.clickhouse.insert(table, rows).await?;
                    }
                    if table == TABLES[0] && !proceed(DrainBoundary::RawWritten) {
                        return Err(Error::Stopped);
                    }
                }
            }
        }
        if !proceed(DrainBoundary::StoreWritten) {
            return Err(Error::Stopped);
        }
        for (segment, expected_proof, expected, _, retained) in &batches {
            let actual = self.clickhouse.snapshot(segment).await?;
            if *retained {
                physical::verify_published(segment, expected, &actual, expected_proof)?;
            } else if physical::classify(expected, &actual)? != PhysicalState::Exact
                || physical::proof(segment, &actual, true)? != *expected_proof
            {
                return Err(Error::Conflict);
            }
        }
        if !proceed(DrainBoundary::Verified) {
            return Err(Error::Stopped);
        }
        let durable = batches
            .iter()
            .map(|(s, p, _, _, _)| (s.clone(), p.clone()))
            .collect::<Vec<_>>();
        self.catalog.publish_segments(&durable).await?;
        let revision = if let Some(manifest) = &manifest {
            self.catalog
                .publish_coverage(manifest, normalizers, parent.into(), reason.into(), at)
                .await?
        } else {
            if !facts.is_empty() {
                return Err(Error::Invalid);
            }
            None
        };
        if !proceed(DrainBoundary::CatalogCommitted) {
            return Err(Error::Stopped);
        }
        for (s, _) in &durable {
            wal.collect_verified(&s.record)?;
        }
        Ok(DrainOutcome {
            coverage: manifest,
            revision,
            segment_ids: ids,
        })
    }
    /// Compose only explicitly selected original durable occurrences. This is
    /// acquisition/correction publication, never the range reader's membership rule.
    pub async fn commit_scope(
        &mut self,
        scope: &Scope,
        selected: &[(String, String)],
        publication: RevisionPublication<'_>,
    ) -> Result<(Manifest, Option<SealedRevision>)> {
        let RevisionPublication { parent, reason, at } = publication;
        let selected = refs(&json!(selected))?;
        let mut used = 0;
        let (segments, facts) = self.durable_facts(&selected, scope, &mut used).await?;
        let manifest = coverage(scope, &segments, &facts, self.limit)?;
        let revision = self
            .catalog
            .publish_coverage(
                &manifest,
                normalizers(&facts)?,
                parent.into(),
                reason.into(),
                at,
            )
            .await?;
        Ok((manifest, revision))
    }
    async fn durable_facts(
        &mut self,
        selected: &[(String, String)],
        scope: &Scope,
        used: &mut usize,
    ) -> Result<(Vec<Segment>, Vec<Value>)> {
        if selected.is_empty() || selected.len() > self.limit {
            return Err(Error::Invalid);
        }
        let mut segments = vec![];
        let mut facts = vec![];
        for (id, hash) in selected {
            let (segment, proof) = self.catalog.segment(id).await?;
            if segment.content_hash() != hash.as_str()
                || !segment.recovery_scope()?.family_matches(scope)
            {
                return Err(Error::Unprovable);
            }
            charge(used, &segment.record, self.catalog.byte_limit)?;
            charge(used, &proof.record, self.catalog.byte_limit)?;
            let rows = self.clickhouse.snapshot(&segment).await?;
            charge_rows(used, &rows, self.catalog.byte_limit)?;
            if physical::proof(&segment, &rows, true)? != proof {
                return Err(Error::Unprovable);
            }
            let batch = physical::facts(&segment, &rows)?;
            if facts
                .len()
                .checked_add(batch.len())
                .is_none_or(|n| n > self.limit)
            {
                return Err(Error::Unavailable);
            }
            facts.extend(batch);
            segments.push(segment);
        }
        Ok((segments, facts))
    }
    /// Select latest current sealed metadata in the exact BAR family, then
    /// certify that exact occurrence physically. Bounds on the family template
    /// do not invent a window relative to an ambient clock. No older fallback.
    pub async fn read_latest(&mut self, family: &Scope) -> Result<(SealedRevision, Vec<Value>)> {
        if family.kind() != "BAR" {
            return Err(Error::Invalid);
        }
        let candidates = self.catalog.candidates(family, i64::MIN, i64::MAX).await?;
        let mut best = None;
        for candidate in candidates {
            let key = (
                candidate.manifest.scope.end_ns(),
                candidate.manifest.scope.start_ns(),
                utc(text(&candidate.seal["sealed_at"])?)?.0,
                candidate.id().to_owned(),
            );
            if best.as_ref().is_none_or(|(old, _)| key > *old) {
                best = Some((key, candidate));
            }
        }
        let (_, selected) = best.ok_or(Error::NotFound)?;
        let (actual, facts) = self.read_exact(selected.id()).await?;
        if actual != selected {
            return Err(Error::Unprovable);
        }
        Ok((actual, facts))
    }
    pub async fn read_exact(&mut self, id: &str) -> Result<(SealedRevision, Vec<Value>)> {
        let mut used = 0;
        self.read_exact_budget(id, &mut used).await
    }
    async fn read_exact_budget(
        &mut self,
        id: &str,
        used: &mut usize,
    ) -> Result<(SealedRevision, Vec<Value>)> {
        let revision = self.catalog.revision(id).await?;
        charge_revision(used, &revision, self.catalog.byte_limit)?;
        let (segments, facts) = self
            .durable_facts(
                &refs(&revision.revision["segment_refs"])?,
                &revision.manifest.scope,
                used,
            )
            .await?;
        let manifest = coverage(&revision.manifest.scope, &segments, &facts, self.limit)?;
        if manifest != revision.manifest || normalizers(&facts)? != revision.revision["normalizers"]
        {
            return Err(Error::Unprovable);
        }
        let facts = deduplicate_facts(&facts)?
            .into_iter()
            .filter_map(|f| match revision.manifest.scope.contains(&f) {
                Ok(true) => Some(Ok(f)),
                Ok(false) => None,
                Err(e) => Some(Err(e)),
            })
            .collect::<Result<Vec<_>>>()?;
        Ok((revision, facts))
    }
    /// A query is read-only. Only current exact Revision occurrences own facts;
    /// unrelated overlapping durable Segments cannot supply coverage.
    pub async fn read_range(
        &mut self,
        family: &Scope,
        intervals: &[(i64, i64)],
    ) -> Result<VerifiedRange> {
        if family.kind() != "BAR" || intervals.is_empty() || intervals.len() > self.limit {
            return Err(Error::Invalid);
        }
        let mut intervals = intervals.to_vec();
        intervals.sort();
        if intervals.iter().any(|(s, e)| s >= e) || intervals.windows(2).any(|p| p[0].1 > p[1].0) {
            return Err(Error::Invalid);
        }
        let start = intervals.first().ok_or(Error::Invalid)?.0;
        let end = intervals.last().ok_or(Error::Invalid)?.1;
        let candidates = self.catalog.candidates(family, start, end).await?;
        let mut used = 0;
        let mut all = vec![];
        let mut segments: BTreeMap<String, Segment> = BTreeMap::new();
        let mut evidence = vec![];
        for candidate in candidates {
            let (revision, facts) = self.read_exact_budget(candidate.id(), &mut used).await?;
            if revision != candidate {
                return Err(Error::Unprovable);
            }
            let owner = &revision.manifest.scope;
            if !intervals
                .iter()
                .any(|(s, e)| owner.start_ns() < *e && owner.end_ns() > *s)
            {
                continue;
            }
            for (id, _) in refs(&revision.revision["segment_refs"])? {
                let (segment, _) = self.catalog.segment(&id).await?;
                if let Some(prior) = segments.insert(id, segment.clone())
                    && prior != segment
                {
                    return Err(Error::Conflict);
                }
            }
            // read_exact already filters facts to this owner's complete scope.
            if all
                .len()
                .checked_add(facts.len())
                .is_none_or(|n| n > self.limit)
            {
                return Err(Error::Unavailable);
            }
            all.extend(facts);
            evidence.push(json!({"revision_id":revision.id(),"revision_fingerprint":revision.revision["fingerprint"],"manifest_id":revision.manifest.id(),"manifest_fingerprint":revision.manifest.record["fingerprint"],"seal_id":revision.seal["seal_id"],"covered_start_ns":start.max(owner.start_ns()),"covered_end_ns":end.min(owner.end_ns())}));
        }
        if all.len() > self.limit {
            return Err(Error::Unavailable);
        }
        let facts = deduplicate_facts(&all)?;
        // Full selected Revision/physical verification and global conflict checks
        // above precede indexing. deduplicate_facts orders by timestamp, so each
        // closed-bar interval can inspect only its (start, end] slice. This index
        // is local to this read and never substitutes for a fresh owning proof.
        let times = facts
            .iter()
            .map(|fact| integer(&fact["ts_event_ns"]))
            .collect::<Result<Vec<_>>>()?;
        let mut issues = BTreeSet::new();
        let mut gaps = vec![];
        let mut status = CoverageStatus::Complete;
        let mut complete = 0;
        let mut expected_count = 0;
        for (s, e) in &intervals {
            let scope = family.with_range(*s, *e)?;
            let selected = segments
                .values()
                .filter(|segment| {
                    segment.record["start_ns"].as_i64().is_some_and(|n| n < *e)
                        && segment.record["end_ns"].as_i64().is_some_and(|n| n > *s)
                })
                .cloned()
                .collect::<Vec<_>>();
            let ids: BTreeSet<_> = selected.iter().map(|s| s.id()).collect();
            // Full physical reads and global deduplication above already check every
            // candidate fact. Preserve fallible containment before cloning only this
            // interval's inputs into the original coverage verifier.
            let inputs = facts[bar_fact_bounds(&times, *s, *e)]
                .iter()
                .filter(|f| ids.contains(f["segment_id"].as_str().unwrap_or_default()))
                .filter_map(|f| match scope.contains(f) {
                    Ok(true) => Some(Ok(f.clone())),
                    Ok(false) => None,
                    Err(error) => Some(Err(error)),
                })
                .collect::<Result<Vec<_>>>()?;
            let c = coverage(&scope, &selected, &inputs, self.limit)?;
            if c.status() == CoverageStatus::Unprovable {
                status = CoverageStatus::Unprovable;
            } else if c.status() == CoverageStatus::Incomplete
                && status != CoverageStatus::Unprovable
            {
                status = CoverageStatus::Incomplete;
            }
            if c.status() == CoverageStatus::Complete {
                complete += 1;
            }
            for p in strings(&c.record["proof"])? {
                if let Some(n) = p.strip_prefix("bar_grid_count=") {
                    expected_count += n.parse::<usize>().map_err(|_| Error::Unprovable)?;
                }
            }
            issues.extend(strings(&c.record["issues"])?.into_iter().map(str::to_owned));
            gaps.extend(array(&c.record["gaps"])?.iter().cloned());
        }
        let facts = if status == CoverageStatus::Complete {
            facts
                .into_iter()
                .zip(times)
                .filter_map(|(fact, time)| {
                    let index = intervals.partition_point(|(_, end)| *end < time);
                    intervals
                        .get(index)
                        .is_some_and(|(start, _)| *start < time)
                        .then_some(fact)
                })
                .collect()
        } else {
            vec![]
        };
        evidence.sort_by_key(|v| {
            (
                v["covered_start_ns"].as_i64(),
                v["covered_end_ns"].as_i64(),
                v["revision_id"].as_str().unwrap_or_default().to_owned(),
            )
        });
        gaps.sort_by_key(|v| (v["start_ns"].as_i64(), v["end_ns"].as_i64()));
        gaps.dedup();
        Ok(VerifiedRange {
            coverage_status: status,
            facts,
            evidence,
            gaps,
            issues: issues.into_iter().collect(),
            expected_base_fact_count: expected_count,
            complete_interval_count: complete,
        })
    }
    async fn verify_gc_authority(&mut self, segment: &Segment) -> Result<()> {
        if segment.record["canonical_count"] == 0 {
            return Ok(());
        }
        let mut used = 0;
        for (manifest, revision) in self.catalog.gc_manifests(segment).await? {
            charge(&mut used, &manifest.record, self.catalog.byte_limit)?;
            let (segments, facts) = self
                .durable_facts(
                    &refs(&manifest.record["segment_refs"])?,
                    &manifest.scope,
                    &mut used,
                )
                .await?;
            if coverage(&manifest.scope, &segments, &facts, self.limit)? != manifest {
                return Err(Error::Unprovable);
            }
            if let Some(revision) = revision
                && (revision.manifest != manifest
                    || normalizers(&facts)? != revision.revision["normalizers"])
            {
                return Err(Error::Unprovable);
            }
        }
        Ok(())
    }
    /// Startup alone may resolve unpublished/open WAL. Normal drain only enumerates
    /// fully published sealed records and never repairs a live recorder's open file.
    /// Exclusive Host startup recovers filesystem/GC inputs without publishing
    /// any new canonical facts; the caller then selects the owning semantic drain.
    pub async fn recover_wal_inputs(&mut self, wal: &mut Wal) -> Result<()> {
        for id in wal.gc_pending()? {
            let (segment, proof) = self.catalog.segment(&id).await?;
            let rows = self.clickhouse.snapshot(&segment).await?;
            if physical::proof(&segment, &rows, true)? != proof {
                return Err(Error::Unprovable);
            }
            self.verify_gc_authority(&segment).await?;
            wal.collect_verified(&segment.record)?;
        }
        for id in wal.recovery_pending()? {
            match wal.recover_segment(&id)? {
                Recovery::Sealed { .. } | Recovery::Abandoned { .. } => {}
            }
        }
        Ok(())
    }
    pub async fn recover(
        &mut self,
        wal: &mut Wal,
        startup: bool,
        at: &str,
        mut proceed: impl FnMut(DrainBoundary) -> bool,
    ) -> Result<Vec<DrainOutcome>> {
        if startup {
            self.recover_wal_inputs(wal).await?;
        }
        let mut sealed = wal.sealed_handle()?;
        let mut groups: BTreeMap<String, (Vec<String>, Vec<Scope>)> = BTreeMap::new();
        let mut result = vec![];
        for id in wal.published_sealed()? {
            let segment = Segment::from_record(&wal.load_segment(&id)?)?;
            if segment.record["canonical_count"] == 0 {
                result.push(
                    self.drain(
                        &mut sealed,
                        &[id],
                        None,
                        RevisionPublication {
                            parent: None,
                            reason: "INGEST",
                            at,
                        },
                        &mut proceed,
                    )
                    .await?,
                );
                continue;
            }
            let scope = segment.recovery_scope()?;
            let mut key = segment.record.clone();
            for field in [
                "segment_id",
                "record_count",
                "raw_count",
                "canonical_count",
                "content_hash",
                "created_at",
                "sealed_at",
                "start_ns",
                "end_ns",
                "first_sequence",
                "last_sequence",
            ] {
                key.as_object_mut().ok_or(Error::Unprovable)?.remove(field);
            }
            let group = groups.entry(canonical(&key)?).or_default();
            group.0.push(id);
            group.1.push(scope);
        }
        for (_, (ids, scopes)) in groups {
            let first = scopes.first().ok_or(Error::Invalid)?;
            let start = scopes
                .iter()
                .map(Scope::start_ns)
                .min()
                .ok_or(Error::Invalid)?;
            let end = scopes
                .iter()
                .map(Scope::end_ns)
                .max()
                .ok_or(Error::Invalid)?;
            let mut scope = first.with_range(start, end)?;
            if scopes.iter().all(|s| s.record["first_sequence"].is_i64()) {
                scope.record["first_sequence"] = scopes
                    .iter()
                    .filter_map(|s| s.record["first_sequence"].as_i64())
                    .min()
                    .into();
                scope.record["last_sequence"] = scopes
                    .iter()
                    .filter_map(|s| s.record["last_sequence"].as_i64())
                    .max()
                    .into();
            }
            let segment = Segment::from_record(&wal.load_segment(&ids[0])?)?;
            let reason = match segment.record["capture_mode"].as_str() {
                Some("REST_BACKFILL") => "BACKFILL",
                Some("REPAIR") => "CORRECTION",
                Some("REPLAY") => "REPLAY",
                _ => "INGEST",
            };
            result.push(
                self.drain(
                    &mut sealed,
                    &ids,
                    Some(&scope),
                    RevisionPublication {
                        parent: None,
                        reason,
                        at,
                    },
                    &mut proceed,
                )
                .await?,
            );
        }
        Ok(result)
    }
    pub async fn complete_acquisition(
        &mut self,
        attempt: &AcquisitionAttempt,
        revision_id: &str,
        detail: &str,
        at: &str,
    ) -> Result<AcquisitionAttempt> {
        let (revision, _) = self.read_exact(revision_id).await?;
        let intent = self
            .catalog
            .intent(text(&attempt.record["acquisition_id"])?)
            .await?
            .ok_or(Error::Unprovable)?;
        if intent.scope != revision.manifest.scope {
            return Err(Error::Unprovable);
        }
        self.catalog
            .finish(attempt, "COMPLETE", Some(&revision), detail, at)
            .await
    }
}
/// Timestamp order is established by deduplicate_facts before this lookup.
fn bar_fact_bounds(times: &[i64], start: i64, end: i64) -> std::ops::Range<usize> {
    times.partition_point(|time| *time <= start)..times.partition_point(|time| *time <= end)
}
fn normalizers(facts: &[Value]) -> Result<Value> {
    let pairs = facts
        .iter()
        .map(|f| {
            Ok((
                text(&f["normalizer_id"])?.to_owned(),
                text(&f["normalizer_version"])?.to_owned(),
            ))
        })
        .collect::<Result<BTreeSet<_>>>()?;
    Ok(json!(pairs))
}

fn charge_rows(used: &mut usize, rows: &physical::Rows, limit: usize) -> Result<()> {
    for batch in rows.values() {
        for row in batch {
            charge(used, row, limit)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod range_index_tests {
    use super::bar_fact_bounds;

    #[test]
    fn closed_bar_range_excludes_start_includes_end_and_keeps_equal_time_occurrences() {
        let times = [-1, 0, 1, 1, 2, 3, 5];
        assert_eq!(bar_fact_bounds(&times, 0, 1), 2..4);
        assert_eq!(bar_fact_bounds(&times, 1, 3), 4..6);
        assert_eq!(bar_fact_bounds(&times, 3, 4), 6..6);
        assert_eq!(bar_fact_bounds(&times, i64::MIN, i64::MAX), 0..7);
        assert_eq!(bar_fact_bounds(&[], 0, 1), 0..0);
    }

    #[test]
    fn disjoint_windows_select_exactly_the_independent_bar_containment_reference() {
        let times: Vec<_> = (0..14_000).map(|n| n * 60).collect();
        for (start, end) in [(0, 420), (840, 1260), (60, 120), (840_000, 840_420)] {
            let expected: Vec<_> = times
                .iter()
                .copied()
                .filter(|t| start < *t && *t <= end)
                .collect();
            assert_eq!(&times[bar_fact_bounds(&times, start, end)], expected);
        }
    }
}
