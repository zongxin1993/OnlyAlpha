from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import OnlyBarUpdate
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataIngress,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
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


@pytest.mark.parametrize("crash_stage", ["C3", "C5", "C6", "C7", "C4"])
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
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    coordinator = OnlyMarketDataRecoveryCoordinator(
        wal, store, catalog, OnlyRevisionCommitService(store, catalog, now=fixed_now)
    )

    assert coordinator.recover_all({segment_id: scope for segment_id in segment_ids}) == ("COMMITTED",)
    revision = catalog.latest_sealed_revision(scope)
    assert len(revision.segment_refs) == 2
    assert len(OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(revision.revision_id, scope)) == 2


class _SnapshotStore:
    def __init__(self) -> None:
        self.snapshots = {}

    def commit(self, snapshot, partitions):
        prior = self.snapshots.setdefault(snapshot.snapshot_fingerprint, snapshot)
        return prior


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
        OnlyHistoricalMarketDataQueryService(catalog, facts), store, fixed_now
    )
    first = materializer.materialize(plan)
    second = materializer.materialize(plan)
    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert first.content_fingerprint == second.content_fingerprint
    assert first.provenance[0].source_metadata["market_data_revision_id"] == revision.revision_id


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
    materialized = OnlySealedMarketDataDatasetMaterializer(
        OnlyHistoricalMarketDataQueryService(catalog, store), _SnapshotStore(), fixed_now
    ).materialize(plan)

    assert materialized.row_count == 2
    assert {item.source_metadata["market_data_revision_id"] for item in materialized.provenance} == set(revisions)
