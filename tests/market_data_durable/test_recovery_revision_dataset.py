from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyDataSequenceSemantics
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import OnlyBarUpdate
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.market_data.durable import (
    OnlyCoverageStatus,
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSealError,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
    only_build_coverage,
    only_build_seal,
)
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.market_data_materializer import (
    OnlySealedMarketDataDatasetMaterializer,
    OnlySealedMarketDataMaterializationPlan,
)

from .conftest import BAR_TYPE, BASE, INSTRUMENT, bar_update, trade_update


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
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    ingress.begin_segment()
    update = trade_update() if kind == "TRADE" else bar_update(bar_index, close=close)
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
        "1m" if kind == "BAR" else None,
        10 if kind == "TRADE" else None,
        10 if kind == "TRADE" else None,
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
    assert coordinator.recover_all() == ("RAW_ONLY_VERIFIED",)
    assert store.inspect_segment(raw_only) == "EXACT"
    assert restarted.scan_uncommitted() == ("raw-only",)
    assert coordinator.recover_all() == ("RAW_ONLY_VERIFIED",)


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

    reference_scope = replace(_scope("BAR"), data_kind="MARKET_REFERENCE", bar_type=None)
    reference_fact = replace(bundle.canonical_facts[0], data_kind="MARKET_REFERENCE")
    reference_manifest = only_build_coverage(reference_scope, (segment,), (reference_fact,) * 10_000)
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
        "1m",
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


def test_recovery_groups_finite_segments_into_one_complete_revision(tmp_path: Path, fixed_now) -> None:
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
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
        BAR_TYPE.specification,
        OnlyAggregationSource.EXTERNAL,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
        OnlyAdjustmentType.RAW,
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


def test_same_dataset_content_keeps_distinct_revision_lineage(tmp_path: Path, fixed_now) -> None:
    facts = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    commit = OnlyRevisionCommitService(facts, catalog, now=fixed_now)
    wal1, segment1, _ = _sealed(tmp_path / "r1", fixed_now, kind="BAR")
    records1 = wal1.read_sealed(segment1.segment_id)
    facts.write_segment(segment1, records1)
    _, r1, _ = commit.commit(segment1, _scope("BAR"), {segment1.segment_id: records1})

    wal2 = OnlyMarketDataWal(tmp_path / "r2", capacity_bytes=2_000_000, now=fixed_now)
    ingress2 = OnlyMarketDataIngress(
        wal2, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
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
        BAR_TYPE.specification,
        OnlyAggregationSource.EXTERNAL,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
        OnlyAdjustmentType.RAW,
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

    assert first.snapshot.snapshot_fingerprint == second.snapshot.snapshot_fingerprint
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
            wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
        )
        segment_id = ingress.begin_segment(f"segment-{name}")
        ingress.record(_observation(10), update)
        ingress.seal()
        scope = replace(_scope("BAR"), instrument_id=str(update.instrument_id))
        OnlyMarketDataRecoveryCoordinator(
            wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
        ).drain(segment_id, scope)
        revisions.append(catalog.latest_sealed_revision(scope).revision_id)
        scopes.append(scope)
    definition = OnlyResearchDatasetDefinition(
        (INSTRUMENT, eth),
        BAR_TYPE.specification,
        OnlyAggregationSource.EXTERNAL,
        OnlyTimeRange(BASE, BASE + timedelta(minutes=1, microseconds=1)),
        OnlyAdjustmentType.RAW,
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
    assert all(item.source_metadata == {} for item in materialized.snapshot.provenance)
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
