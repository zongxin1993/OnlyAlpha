from __future__ import annotations

from dataclasses import replace
from datetime import time, timedelta
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyDataSequenceSemantics
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import OnlyBarUpdate
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyVenueId
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.market_data.durable import (
    OnlyBarCoverageGap,
    OnlyCoverageStatus,
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataConflictError,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSealError,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
    OnlyTradeCoverageGap,
    only_build_coverage,
    only_build_seal,
)
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionIdentity,
    only_plan_bar_resolution,
)
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_snapshot_fingerprint
from onlyalpha.research.dataset.market_data_materializer import (
    OnlySealedMarketDataDatasetMaterializer,
    OnlySealedMarketDataMaterializationPlan,
)

from .conftest import (
    BAR_CONSTRUCTION,
    BAR_TYPE,
    BAR_TYPE_ID,
    BASE,
    INSTRUMENT,
    bar_construction,
    bar_update,
    reference_update,
    trade_update,
)


def _observation(event_id: int, provenance: str = "REALTIME_STREAM") -> OnlyRawProviderObservation:
    payload = f'{{"e":"trade","t":{event_id}}}'.encode()
    return OnlyRawProviderObservation(
        "BINANCE_SPOT",
        "capture-1",
        "BINANCE",
        "BINANCE",
        "SPOT",
        "trade",
        "trade",
        int(BASE.timestamp() * 1_000_000_000),
        payload,
        str(event_id),
        event_id,
        int(BASE.timestamp() * 1_000_000_000),
        provenance=provenance,
    )


def _sealed(
    tmp_path: Path,
    fixed_now,
    *,
    kind: str = "TRADE",
    close: str = "101.00000000",
    bar_index: int = 0,
):
    wal = OnlyMarketDataWal(
        tmp_path, capacity_bytes=2_000_000, now=fixed_now, identity_factory=lambda: f"segment-{close}"
    )
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION if kind == "BAR" else None,
    )
    ingress.begin_segment()
    update = (
        trade_update()
        if kind == "TRADE"
        else reference_update()
        if kind == "MARKET_REFERENCE"
        else bar_update(bar_index, close=close)
    )
    ingress.record(_observation(10), update)
    return wal, ingress.seal(), update


def _scope(kind: str) -> OnlyMarketDataScope:
    base_ns = int(BASE.timestamp() * 1_000_000_000)
    return OnlyMarketDataScope(
        "BINANCE_SPOT",
        "SPOT",
        str(INSTRUMENT),
        kind,
        base_ns,
        base_ns + 60_000_000_000,
        "BINANCE_SPOT_V1",
        BAR_TYPE_ID if kind == "BAR" else None,
        10 if kind == "TRADE" else None,
        10 if kind == "TRADE" else None,
        BAR_CONSTRUCTION if kind == "BAR" else None,
    )


def test_shifted_bar_window_excludes_prior_bar_ending_at_start(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    ingress.begin_segment("overlapping-bars")
    ingress.record(_observation(10), bar_update(0))
    ingress.record(_observation(11), bar_update(1))
    segment = ingress.seal()
    records = wal.read_sealed(segment.segment_id)
    store = OnlyInMemoryMarketFactStore()
    store.write_segment(segment, records)
    scope = replace(
        _scope("BAR"),
        start_ns=_scope("BAR").end_ns,
        end_ns=_scope("BAR").end_ns + 60_000_000_000,
    )

    facts = store.read_segment_facts((segment,), scope)

    assert len(facts) == 1
    assert facts[0].ts_event_ns == scope.end_ns
    assert only_build_coverage(scope, (segment,), facts).coverage_status is OnlyCoverageStatus.COMPLETE
    assert (
        only_build_coverage(
            scope, (segment,), tuple(fact for bundle in records for fact in bundle.canonical_facts)
        ).coverage_status
        is OnlyCoverageStatus.COMPLETE
    )


@pytest.mark.parametrize("crash_stage", ["C3", "C5", "C6", "C7"])
def test_crash_boundaries_recover_without_duplicate_semantic_truth(tmp_path: Path, fixed_now, crash_stage: str) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now)
    fired = False

    def store_fault(stage: str) -> None:
        nonlocal fired
        if crash_stage == "C4" and stage == "AFTER_RAW_WRITE" and not fired:
            fired = True
            raise RuntimeError("injected C4")

    store = OnlyInMemoryMarketFactStore(store_fault)
    catalog = OnlyInMemoryMarketDataCatalog()
    commit = OnlyRevisionCommitService(store, catalog, now=fixed_now)

    def barrier(stage) -> None:
        nonlocal fired
        if stage.value == crash_stage and not fired:
            fired = True
            raise RuntimeError(f"injected {crash_stage}")

    coordinator = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, commit, barrier=barrier)
    with pytest.raises(RuntimeError, match="injected"):
        coordinator.drain(segment.segment_id, _scope("TRADE"))
    failed_health = coordinator.health()
    assert failed_health.recovery_count == 1
    assert failed_health.last_recovery_error is not None
    recovered = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, commit).drain(
        segment.segment_id, _scope("TRADE")
    )
    assert recovered in {"COMMITTED", "ALREADY_COMMITTED"}
    assert not wal.scan_uncommitted()
    revision = catalog.latest_sealed_revision(_scope("TRADE"))
    facts = OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision.revision_id, _scope("TRADE"))
    assert len(facts) == 1


def test_partial_clickhouse_state_fails_closed_without_blind_retry(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now)
    fired = False

    def store_fault(stage: str) -> None:
        nonlocal fired
        if stage == "AFTER_RAW_WRITE" and not fired:
            fired = True
            raise RuntimeError("injected C4")

    store = OnlyInMemoryMarketFactStore(store_fault)
    catalog = OnlyInMemoryMarketDataCatalog()
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    with pytest.raises(RuntimeError, match="injected C4"):
        coordinator.drain(segment.segment_id, _scope("TRADE"))
    assert store.inspect_segment(segment) == "PARTIAL"
    with pytest.raises(RuntimeError, match="MARKET_DATA_STORE_PARTIAL"):
        OnlyMarketDataRecoveryCoordinator(
            wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).drain(segment.segment_id, _scope("TRADE"))


def test_fresh_recovery_exactly_preserves_raw_only_normalization_failure(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    ingress.begin_segment("raw-only")
    ingress.record(_observation(99), None)
    raw_only = ingress.seal()
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    coordinator = OnlyMarketDataRecoveryCoordinator(
        restarted, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    assert coordinator.recover_all() == ("DURABLE_ONLY:RAW_ONLY",)
    assert store.inspect_segment(raw_only) == "EXACT"
    assert catalog.is_segment_committed(raw_only.segment_id, raw_only.content_hash)
    assert restarted.scan_uncommitted() == ()
    assert coordinator.recover_all() == ()


def test_unknown_write_outcome_inspects_exact_before_retry(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now)
    fired = False

    def store_fault(stage: str) -> None:
        nonlocal fired
        if stage == "AFTER_CANONICAL_WRITE" and not fired:
            fired = True
            raise RuntimeError("write outcome unknown")

    store = OnlyInMemoryMarketFactStore(store_fault)
    catalog = OnlyInMemoryMarketDataCatalog()
    with pytest.raises(RuntimeError, match="write outcome unknown"):
        OnlyMarketDataRecoveryCoordinator(
            wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).drain(segment.segment_id, _scope("TRADE"))
    assert store.inspect_segment(segment) == "EXACT"

    assert (
        OnlyMarketDataRecoveryCoordinator(
            wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).drain(segment.segment_id, _scope("TRADE"))
        == "COMMITTED"
    )


def test_same_manifest_revision_fingerprint_and_repair_keeps_r1_reproducible(tmp_path: Path, fixed_now) -> None:
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    query = OnlyHistoricalMarketDataQueryService(catalog, store)

    wal1, segment1, _ = _sealed(tmp_path / "r1", fixed_now, kind="BAR", close="101.00000000")
    commit = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    OnlyMarketDataRecoveryCoordinator(wal1, store, catalog, commit).drain(segment1.segment_id, _scope("BAR"))
    r1 = catalog.latest_sealed_revision(_scope("BAR"))
    r1_facts = query.read_exact(r1.revision_id, _scope("BAR"))

    wal2, segment2, _ = _sealed(tmp_path / "r2", fixed_now, kind="BAR", close="101.50000000")
    records2 = wal2.read_sealed(segment2.segment_id)
    store.write_segment(segment2, records2)
    _, r2, _ = commit.commit(
        segment2,
        _scope("BAR"),
        {segment2.segment_id: records2},
        parent_revision_id=r1.revision_id,
        reason="REPAIR",
    )

    assert r1.revision_id != r2.revision_id
    assert query.read_exact(r1.revision_id, _scope("BAR")) == r1_facts
    assert (
        query.read_exact(r2.revision_id, _scope("BAR"))[0].canonical_payload_hash != r1_facts[0].canonical_payload_hash
    )


def test_coverage_capability_is_explicit_and_unsupported_never_seals(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    [bundle] = wal.read_sealed(segment.segment_id)
    incomplete_scope = replace(
        _scope("BAR"),
        end_ns=_scope("BAR").end_ns + 60_000_000_000,
    )
    bar_manifest = only_build_coverage(incomplete_scope, (segment,), bundle.canonical_facts)
    assert bar_manifest.coverage_status is OnlyCoverageStatus.INCOMPLETE
    assert bar_manifest.gaps == (OnlyBarCoverageGap(_scope("BAR").end_ns, incomplete_scope.end_ns),)

    reference_wal, reference_segment, _ = _sealed(tmp_path / "reference", fixed_now, kind="MARKET_REFERENCE")
    [reference_bundle] = reference_wal.read_sealed(reference_segment.segment_id)
    [reference_fact] = reference_bundle.canonical_facts
    reference_scope = _scope("MARKET_REFERENCE")
    reference_manifest = only_build_coverage(reference_scope, (reference_segment,), (reference_fact,) * 10_000)
    assert reference_manifest.coverage_status is OnlyCoverageStatus.UNPROVABLE
    revision = OnlyMarketDataRevision.build(
        reference_manifest,
        normalizers=((reference_fact.normalizer_id, reference_fact.normalizer_version),),
        creation_reason="INGEST",
    )
    with pytest.raises(OnlyMarketDataSealError, match="REVISION_COVERAGE_NOT_SEALABLE"):
        only_build_seal(revision, reference_manifest, sealed_at=fixed_now())


def test_trade_provider_sequence_gap_is_incomplete(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    ingress.begin_segment("trade-gap")
    ingress.record(_observation(10), trade_update(10))
    ingress.record(_observation(12), trade_update(12))
    segment = ingress.seal()
    facts = tuple(fact for bundle in wal.read_sealed(segment.segment_id) for fact in bundle.canonical_facts)
    scope = replace(_scope("TRADE"), first_sequence=10, last_sequence=12)
    manifest = only_build_coverage(scope, (segment,), facts)
    assert manifest.coverage_status is OnlyCoverageStatus.INCOMPLETE
    assert manifest.gaps == (OnlyTradeCoverageGap(11, 11),)


def test_incomplete_bar_is_durable_and_wal_reclaimed_without_seal(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    incomplete_scope = replace(_scope("BAR"), end_ns=_scope("BAR").end_ns + 60_000_000_000)

    assert coordinator.drain(segment.segment_id, incomplete_scope) == "DURABLE_ONLY:INCOMPLETE"
    assert catalog.is_segment_committed(segment.segment_id, segment.content_hash)
    assert wal.scan_uncommitted() == ()
    with pytest.raises(KeyError, match="SEALED_REVISION_NOT_FOUND"):
        catalog.latest_sealed_revision(incomplete_scope)


def test_market_reference_is_durable_unprovable_and_wal_reclaimed_without_seal(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="MARKET_REFERENCE")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    scope = replace(_scope("BAR"), data_kind="MARKET_REFERENCE", bar_type=None, bar_construction=None)

    assert coordinator.drain(segment.segment_id, scope) == "DURABLE_ONLY:UNPROVABLE"
    assert catalog.is_segment_committed(segment.segment_id, segment.content_hash)
    assert wal.scan_uncommitted() == ()
    with pytest.raises(KeyError, match="SEALED_REVISION_NOT_FOUND"):
        catalog.latest_sealed_revision(scope)


def test_multi_segment_revision_is_ordered_and_semantically_deterministic(tmp_path: Path, fixed_now) -> None:
    wal1, segment1, _ = _sealed(tmp_path / "s1", fixed_now, kind="BAR", close="101.00000000", bar_index=0)
    wal2, segment2, _ = _sealed(tmp_path / "s2", fixed_now, kind="BAR", close="102.00000000", bar_index=1)
    store = OnlyInMemoryMarketFactStore()
    records1 = wal1.read_sealed(segment1.segment_id)
    records2 = wal2.read_sealed(segment2.segment_id)
    store.write_segment(segment1, records1)
    store.write_segment(segment2, records2)
    scope = OnlyMarketDataScope(
        "BINANCE_SPOT",
        "SPOT",
        str(INSTRUMENT),
        "BAR",
        int(BASE.timestamp() * 1_000_000_000),
        int((BASE + timedelta(minutes=2)).timestamp() * 1_000_000_000),
        "BINANCE_SPOT_V1",
        BAR_TYPE_ID,
        bar_construction=BAR_CONSTRUCTION,
    )
    first_catalog = OnlyInMemoryMarketDataCatalog()
    second_catalog = OnlyInMemoryMarketDataCatalog()

    first = OnlyRevisionCommitService(store, first_catalog, now=fixed_now).commit(
        (segment2, segment1),
        scope,
        {segment1.segment_id: records1, segment2.segment_id: records2},
        reason="INGEST",
    )[1]
    second = OnlyRevisionCommitService(store, second_catalog, now=fixed_now).commit(
        (segment1, segment2),
        scope,
        {segment2.segment_id: records2, segment1.segment_id: records1},
        reason="INGEST",
    )[1]

    assert first.segment_refs == tuple(sorted(first.segment_refs))
    assert first.revision_id == second.revision_id
    assert first.fingerprint == second.fingerprint


def test_acquisition_reuses_sealed_ingest_revision_for_identical_manifest(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    records = wal.read_sealed(segment.segment_id)
    store = OnlyInMemoryMarketFactStore()
    store.write_segment(segment, records)
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    scope = _scope("BAR")
    manifest, ingest_revision, ingest_seal = committer.commit(segment, scope, {segment.segment_id: records})
    [fact] = records[0].canonical_facts

    replayed_manifest, acquired_revision, acquired_seal = committer.commit_durable_facts(
        (segment,), scope, (fact,), reason="REST_BACKFILL"
    )

    assert replayed_manifest == manifest
    assert acquired_revision == ingest_revision
    assert acquired_seal == ingest_seal


def test_coverage_rejects_declared_scope_that_does_not_match_segment(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    [bundle] = wal.read_sealed(segment.segment_id)

    with pytest.raises(OnlyMarketDataConflictError, match="SEGMENT_SCOPE_MISMATCH"):
        only_build_coverage(replace(_scope("BAR"), market="WRONG"), (segment,), bundle.canonical_facts)


def test_exact_read_fails_closed_when_durable_physical_segment_becomes_partial(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _scope("BAR")
    assert recovery.drain(segment.segment_id, scope) == "COMMITTED"
    revision = catalog.latest_sealed_revision(scope)
    raw_key = next(key for key in store._raw if key[0] == segment.segment_id)
    del store._raw[raw_key]

    with pytest.raises(OnlyMarketDataConflictError, match="MARKET_DATA_SEGMENT_NOT_EXACT"):
        OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision.revision_id, scope)


def test_recovery_groups_finite_segments_into_one_complete_revision(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    segment_ids = []
    for index in range(2):
        segment_ids.append(ingress.begin_segment(f"group-{index}"))
        ingress.record(_observation(10 + index), bar_update(index, close=f"10{index + 1}.00000000"))
        ingress.seal()
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    recovered_scopes = tuple(wal.load_segment(segment_id).recovery_scope() for segment_id in segment_ids)

    restarted = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    coordinator = OnlyMarketDataRecoveryCoordinator(
        restarted, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )
    assert coordinator.recover_all() == ("COMMITTED",)
    recovery_scope = replace(
        recovered_scopes[0],
        start_ns=min(item.start_ns for item in recovered_scopes),
        end_ns=max(item.end_ns for item in recovered_scopes),
    )
    revision = catalog.latest_sealed_revision(recovery_scope)
    assert len(revision.segment_refs) == 2
    assert (
        len(OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision.revision_id, recovery_scope)) == 2
    )


def test_grouped_recovery_uses_one_batch_store_verify_and_catalog_observation(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=4_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    for page in range(9):
        ingress.begin_segment(f"page-{page}")
        ingress.record(_observation(page), (bar_update(page * 2), bar_update(page * 2 + 1)))
        ingress.seal()

    class CountingStore(OnlyInMemoryMarketFactStore):
        batch_writes = 0
        batch_verifications = 0
        single_writes = 0
        single_verifications = 0

        def write_segment(self, segment, records):  # type: ignore[no-untyped-def]
            self.single_writes += 1
            return super().write_segment(segment, records)

        def verify_segment(self, segment, records):  # type: ignore[no-untyped-def]
            self.single_verifications += 1
            return super().verify_segment(segment, records)

        def write_segments(self, segments, records_by_segment):  # type: ignore[no-untyped-def]
            self.batch_writes += 1
            return super().write_segments(segments, records_by_segment)

        def verify_segments(self, segments, records_by_segment, scope=None):  # type: ignore[no-untyped-def]
            self.batch_verifications += 1
            return super().verify_segments(segments, records_by_segment, scope)

    class CountingCatalog(OnlyInMemoryMarketDataCatalog):
        batch_observations = 0
        single_observations = 0

        def segments_committed(self, segments):  # type: ignore[no-untyped-def]
            self.batch_observations += 1
            return super().segments_committed(segments)

        def is_segment_committed(self, segment_id, content_hash):  # type: ignore[no-untyped-def]
            self.single_observations += 1
            return super().is_segment_committed(segment_id, content_hash)

    store = CountingStore()
    catalog = CountingCatalog()
    scope = replace(_scope("BAR"), end_ns=_scope("BAR").start_ns + 18 * 60_000_000_000)
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )

    assert recovery.recover_all() == ("COMMITTED",)
    assert (store.batch_writes, store.batch_verifications) == (1, 1)
    assert (store.single_writes, store.single_verifications) == (0, 0)
    assert (catalog.batch_observations, catalog.single_observations) == (1, 0)
    assert len(catalog.latest_sealed_revision(scope).segment_refs) == 9


@pytest.mark.parametrize("crash_stage", ["C3", "C5", "C6", "C7"])
def test_multi_segment_crash_boundaries_retry_deterministically(tmp_path: Path, fixed_now, crash_stage: str) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    for index in range(2):
        ingress.begin_segment(f"crash-batch-{index}")
        ingress.record(_observation(index), bar_update(index))
        ingress.seal()
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    scope = replace(_scope("BAR"), end_ns=_scope("BAR").start_ns + 2 * 60_000_000_000)
    fired = False

    def barrier(stage) -> None:  # type: ignore[no-untyped-def]
        nonlocal fired
        if stage.value == crash_stage and not fired:
            fired = True
            raise RuntimeError(f"injected {crash_stage}")

    with pytest.raises(RuntimeError, match="injected"):
        OnlyMarketDataRecoveryCoordinator(
            wal,
            store,
            catalog,
            OnlyRevisionCommitService(store, catalog, now=fixed_now),
            barrier=barrier,
        ).recover_all()
    result = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    ).recover_all()
    assert result in {("COMMITTED",), ("ALREADY_COMMITTED",)}
    assert wal.scan_uncommitted() == ()
    assert len(catalog.latest_sealed_revision(scope).segment_refs) == 2


def test_multi_segment_raw_write_crash_remains_fail_closed_with_wal_preserved(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    for index in range(2):
        ingress.begin_segment(f"raw-crash-batch-{index}")
        ingress.record(_observation(index), bar_update(index))
        ingress.seal()
    fired = False

    def fault(stage: str) -> None:
        nonlocal fired
        if stage == "AFTER_RAW_WRITE" and not fired:
            fired = True
            raise RuntimeError("injected batch raw crash")

    store = OnlyInMemoryMarketFactStore(fault=fault)
    catalog = OnlyInMemoryMarketDataCatalog()
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )

    with pytest.raises(RuntimeError, match="injected batch raw crash"):
        recovery.recover_all()
    with pytest.raises(RuntimeError, match="MARKET_DATA_STORE_PARTIAL"):
        recovery.recover_all()
    assert len(wal.scan_uncommitted()) == 2


def test_multi_segment_canonical_chunk_crash_replays_exact_and_absent_segments(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    for index in range(2):
        ingress.begin_segment(f"canonical-chunk-crash-{index}")
        ingress.record(_observation(index), bar_update(index))
        ingress.seal()

    class ChunkCrashStore(OnlyInMemoryMarketFactStore):
        crashed = False

        def write_segments(self, segments, records_by_segment):  # type: ignore[no-untyped-def]
            if not self.crashed:
                self.crashed = True
                first = segments[0]
                super().write_segments((first,), {first.segment_id: records_by_segment[first.segment_id]})
                raise RuntimeError("injected canonical chunk crash")
            return super().write_segments(segments, records_by_segment)

    store = ChunkCrashStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    scope = replace(_scope("BAR"), end_ns=_scope("BAR").start_ns + 2 * 60_000_000_000)
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )

    with pytest.raises(RuntimeError, match="injected canonical chunk crash"):
        recovery.recover_all()
    assert recovery.recover_all() == ("COMMITTED",)
    assert wal.scan_uncommitted() == ()
    assert len(catalog.latest_sealed_revision(scope).segment_refs) == 2


def test_grouped_recovery_rejects_mixed_committed_catalog_state(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    segments = []
    for index in range(2):
        ingress.begin_segment(f"mixed-commit-{index}")
        ingress.record(_observation(index), bar_update(index))
        segments.append(ingress.seal())
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    catalog.commit_durable_segments((segments[0],))
    recovery = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )

    with pytest.raises(RuntimeError, match="MARKET_DATA_RECOVERY_COMMIT_SET_CONFLICT"):
        recovery.recover_all()
    assert len(wal.scan_uncommitted()) == 2


class _SnapshotStore:
    def __init__(self) -> None:
        self.snapshots = {}
        self.materializations = {}

    def commit(self, snapshot, partitions):
        prior = self.snapshots.setdefault(snapshot.snapshot_fingerprint, snapshot)
        return prior

    def commit_materialization(self, value):
        prior = self.materializations.setdefault(value.materialization_id, value)
        assert prior.semantic_payload() == value.semantic_payload()
        return prior

    def load_materialization(self, materialization_id):
        return self.materializations[materialization_id]


def test_exact_revision_dataset_materialization_is_deterministic(tmp_path: Path, fixed_now) -> None:
    wal, segment, _ = _sealed(tmp_path, fixed_now, kind="BAR")
    facts = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    commit = OnlyRevisionCommitService(facts, catalog, now=fixed_now)
    OnlyMarketDataRecoveryCoordinator(wal, facts, catalog, commit).drain(segment.segment_id, _scope("BAR"))
    revision = catalog.latest_sealed_revision(_scope("BAR"))
    definition = OnlyResearchDatasetDefinition(
        (INSTRUMENT,),
        BAR_TYPE.semantic,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
    )
    plan = OnlySealedMarketDataMaterializationPlan((revision.revision_id,), definition, (_scope("BAR"),))
    store = _SnapshotStore()
    materializer = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(catalog, facts), store, store, fixed_now
    )
    first = materializer.materialize_with_lineage(plan)
    second = materializer.materialize_with_lineage(plan)
    assert first.snapshot.snapshot_fingerprint == second.snapshot.snapshot_fingerprint
    assert first.snapshot.content_fingerprint == second.snapshot.content_fingerprint
    assert first.materialization.materialization_id == second.materialization.materialization_id
    assert first.materialization.market_data_revision_bindings[0].revision_id == revision.revision_id


def test_derived_dataset_binds_sealed_base_and_distinct_snapshot_identity(tmp_path: Path, fixed_now) -> None:
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST-24X7"),
        OnlyVenueId("BINANCE"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("continuous", time(0), time(0), OnlySessionType.CONTINUOUS),),
        weekend_days=(),
    )
    alignment = only_canonical_fingerprint(calendar.to_dict())
    capability = OnlyBarCapability(BAR_TYPE.semantic, True, True, alignment, grid_origin_ns=0)
    base_plan = only_plan_bar_resolution(
        BAR_TYPE.semantic,
        (capability,),
        calendar_fingerprint=alignment,
        source_id="BINANCE_SPOT",
        instrument_id=str(INSTRUMENT),
        integration_revision_fingerprint="a" * 64,
    )
    base_construction = OnlyBarConstructionIdentity.build(base_plan, data_version="BINANCE_SPOT_V1")
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=base_construction,
    )
    ingress.begin_segment("seven-base-bars")
    for index in range(7):
        ingress.record(_observation(20 + index), bar_update(index))
    segment = ingress.seal()
    scope = replace(
        _scope("BAR"),
        end_ns=_scope("BAR").start_ns + 7 * 60_000_000_000,
        bar_construction=base_construction,
    )
    facts = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    records = wal.read_sealed(segment.segment_id)
    facts.write_segment(segment, records)
    _, revision, seal = OnlyRevisionCommitService(facts, catalog, now=fixed_now).commit(
        segment,
        scope,
        {segment.segment_id: records},
    )
    target = OnlyBarSemantic.fixed_duration(7)
    derived_plan = only_plan_bar_resolution(
        target,
        (capability,),
        calendar_fingerprint=alignment,
        source_id="BINANCE_SPOT",
        instrument_id=str(INSTRUMENT),
        integration_revision_fingerprint="a" * 64,
    )
    derived = OnlyBarConstructionIdentity.build(
        derived_plan,
        data_version=scope.data_version,
        base_revision_id=revision.revision_id,
        base_revision_fingerprint=revision.fingerprint,
        base_seal_id=seal.seal_id,
    )
    definition = OnlyResearchDatasetDefinition(
        (INSTRUMENT,),
        target,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=7, microseconds=1)),
    )
    store = _SnapshotStore()
    materializer = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(catalog, facts),
        store,
        store,
        fixed_now,
    )
    result = materializer.materialize_with_lineage(
        OnlySealedMarketDataMaterializationPlan(
            (revision.revision_id,),
            definition,
            (scope,),
            (derived,),
            (calendar,),
        )
    )
    assert result.snapshot.row_count == 1
    assert result.snapshot.construction_fingerprint is not None
    native_plan = only_plan_bar_resolution(
        target,
        (
            capability,
            OnlyBarCapability(target, True, True, alignment, grid_origin_ns=0),
        ),
        calendar_fingerprint=alignment,
        source_id="BINANCE_SPOT",
        instrument_id=str(INSTRUMENT),
        integration_revision_fingerprint="a" * 64,
    )
    native = OnlyBarConstructionIdentity.build(native_plan, data_version=scope.data_version)
    assert result.snapshot.snapshot_fingerprint != only_snapshot_fingerprint(
        definition,
        result.snapshot.dataset_schema,
        result.snapshot.content_fingerprint,
        result.snapshot.row_count,
        native.fingerprint,
    )
    assert result.snapshot.provenance[0].source_metadata["bar_construction_fingerprint"] == derived.fingerprint
    with pytest.raises(ValueError, match="BAR_CONSTRUCTION_BASE_REVISION_REQUIRED"):
        OnlyBarConstructionIdentity.build(derived_plan, data_version=scope.data_version)


def test_same_dataset_content_keeps_distinct_revision_bound_snapshot_identity(tmp_path: Path, fixed_now) -> None:
    facts = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    commit = OnlyRevisionCommitService(facts, catalog, now=fixed_now)
    wal1, segment1, _ = _sealed(tmp_path / "r1", fixed_now, kind="BAR")
    records1 = wal1.read_sealed(segment1.segment_id)
    facts.write_segment(segment1, records1)
    _, r1, _ = commit.commit(segment1, _scope("BAR"), {segment1.segment_id: records1})

    wal2 = OnlyMarketDataWal(tmp_path / "r2", capacity_bytes=2_000_000, now=fixed_now)
    ingress2 = OnlyMarketDataIngress(
        wal2,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=BAR_CONSTRUCTION,
    )
    ingress2.begin_segment("same-content-r2")
    ingress2.record(_observation(10), bar_update())
    segment2 = ingress2.seal()
    records2 = wal2.read_sealed(segment2.segment_id)
    facts.write_segment(segment2, records2)
    _, r2, _ = commit.commit(
        segment2,
        _scope("BAR"),
        {segment2.segment_id: records2},
        parent_revision_id=r1.revision_id,
        reason="REPLAY",
    )

    definition = OnlyResearchDatasetDefinition(
        (INSTRUMENT,),
        BAR_TYPE.semantic,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
    )
    store = _SnapshotStore()
    materializer = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(catalog, facts), store, store, fixed_now
    )
    first = materializer.materialize_with_lineage(
        OnlySealedMarketDataMaterializationPlan((r1.revision_id,), definition, (_scope("BAR"),))
    )
    second = materializer.materialize_with_lineage(
        OnlySealedMarketDataMaterializationPlan((r2.revision_id,), definition, (_scope("BAR"),))
    )

    assert first.snapshot.content_fingerprint == second.snapshot.content_fingerprint
    assert first.snapshot.snapshot_fingerprint != second.snapshot.snapshot_fingerprint
    assert first.materialization.materialization_id != second.materialization.materialization_id
    assert first.materialization.market_data_revision_bindings != second.materialization.market_data_revision_bindings


def test_two_instrument_dataset_binds_one_exact_revision_per_scope(tmp_path: Path, fixed_now) -> None:
    eth = OnlyInstrumentId.parse("ETHUSDT.BINANCE")
    btc_update = bar_update()
    eth_bar_type = replace(BAR_TYPE, instrument_id=eth)
    eth_bar = replace(btc_update.payload.bar, bar_type=eth_bar_type)
    eth_update = replace(
        btc_update,
        update_id=only_bar_update_id(
            btc_update.source_id, eth, eth_bar_type, eth_bar.bar_start, btc_update.data_version
        ),
        instrument_id=eth,
        payload=OnlyBarUpdate(eth_bar),
        sequence_scope=None,
    )
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    revisions = []
    scopes = []
    for name, update in (("btc", btc_update), ("eth", eth_update)):
        wal = OnlyMarketDataWal(tmp_path / name, capacity_bytes=1_000_000, now=fixed_now)
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id="binance-spot",
            normalizer_version="1",
            ingest_clock_ns=lambda: 5,
            bar_construction=bar_construction(update.instrument_id),
        )
        segment_id = ingress.begin_segment(f"segment-{name}")
        ingress.record(_observation(10), update)
        ingress.seal()
        scope = replace(
            _scope("BAR"),
            instrument_id=str(update.instrument_id),
            bar_type=only_canonical_fingerprint(update.payload.bar.bar_type.to_dict()),
            bar_construction=bar_construction(update.instrument_id),
        )
        OnlyMarketDataRecoveryCoordinator(
            wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).drain(segment_id, scope)
        revisions.append(catalog.latest_sealed_revision(scope).revision_id)
        scopes.append(scope)
    definition = OnlyResearchDatasetDefinition(
        (INSTRUMENT, eth),
        BAR_TYPE.semantic,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
    )
    plan = OnlySealedMarketDataMaterializationPlan(tuple(revisions), definition, tuple(scopes))
    snapshot_store = _SnapshotStore()
    materializer = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(catalog, store), snapshot_store, snapshot_store, fixed_now
    )
    materialized = materializer.materialize_with_lineage(plan)
    reversed_materialized = materializer.materialize_with_lineage(
        OnlySealedMarketDataMaterializationPlan(tuple(reversed(revisions)), definition, tuple(reversed(scopes)))
    )

    assert materialized.snapshot.row_count == 2
    assert all("bar_construction_fingerprint" in item.source_metadata for item in materialized.snapshot.provenance)
    assert materialized.snapshot.snapshot_fingerprint == reversed_materialized.snapshot.snapshot_fingerprint
    assert materialized.materialization.materialization_id == reversed_materialized.materialization.materialization_id


def test_trade_coverage_requires_contiguous_sequence_semantics(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 5)
    ingress.begin_segment("monotonic-trade")
    ingress.record(
        _observation(10),
        replace(trade_update(), sequence_semantics=OnlyDataSequenceSemantics.MONOTONIC),
    )
    segment = ingress.seal()
    [bundle] = wal.read_sealed(segment.segment_id)

    manifest = only_build_coverage(_scope("TRADE"), (segment,), bundle.canonical_facts)
    assert manifest.coverage_status is OnlyCoverageStatus.INCOMPLETE
    assert "provider_sequence_contiguous=false" in manifest.proof
