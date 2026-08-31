from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange, OnlyHistoricalDataStream
from onlyalpha.market_data.durable import (
    OnlyHistoricalMarketDataQueryService,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataBackfillCoordinator,
    OnlyMarketDataCorrectionComposer,
    OnlyMarketDataIngress,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
)

from .conftest import BAR_TYPE, BAR_TYPE_ID, BASE, INSTRUMENT, SOURCE, VERSION, bar_update
from .test_recovery_revision_dataset import _observation


class _HistoricalSource:
    def __init__(self, ingress: OnlyMarketDataIngress) -> None:
        self._ingress = ingress
        self.requests: list[OnlyHistoricalBarRequest] = []

    @property
    def source_id(self):  # type: ignore[no-untyped-def]
        return SOURCE

    @property
    def capabilities(self):  # type: ignore[no-untyped-def]
        return frozenset()

    def load_bars(self, request: OnlyHistoricalBarRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        update = bar_update(1, close="102.00000000")
        self._ingress.begin_segment("backfill-gap")
        observation = replace(
            _observation(11, "REST_BACKFILL"),
            capture_session_id="capture-rest-backfill",
        )
        self._ingress.record(observation, update)
        self._ingress.seal()
        return OnlyHistoricalDataStream((update,), request.batch_size)

    def load_trades(self, _request):  # type: ignore[no-untyped-def]
        raise AssertionError("BAR backfill must not call trade source")

    def load_quotes(self, _request):  # type: ignore[no-untyped-def]
        raise AssertionError("BAR backfill must not call quote source")


class _NonDurableHistoricalSource(_HistoricalSource):
    def load_bars(self, request: OnlyHistoricalBarRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return OnlyHistoricalDataStream((bar_update(1),), request.batch_size)


def _two_minute_scope() -> OnlyMarketDataScope:
    base_ns = int(BASE.timestamp() * 1_000_000_000)
    return OnlyMarketDataScope(
        str(SOURCE),
        "SPOT",
        str(INSTRUMENT),
        "BAR",
        base_ns,
        base_ns + 120_000_000_000,
        str(VERSION),
        BAR_TYPE_ID,
    )


def _write_bar(
    ingress: OnlyMarketDataIngress,
    segment_id: str,
    index: int,
    close: str,
    provenance: str = "REALTIME_STREAM",
) -> str:
    ingress.begin_segment(segment_id)
    ingress.record(_observation(10 + index, provenance), bar_update(index, close=close))
    return ingress.seal().segment_id


def test_backfill_uses_exact_typed_gap_same_wal_and_creates_complete_child_revision(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    first_id = _write_bar(ingress, "initial", 0, "101.00000000")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _two_minute_scope()
    assert recovery.drain(first_id, scope) == "DURABLE_ONLY:INCOMPLETE"

    source = _HistoricalSource(ingress)
    coordinator = OnlyMarketDataBackfillCoordinator(source, catalog, store, recovery, committer)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        str(SOURCE),
        scope,
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        created_at=fixed_now(),
    )
    initial = coordinator.inspect(acquisition)
    [gap] = initial.gaps
    request = OnlyHistoricalBarRequest(
        "gap-request",
        frozenset({INSTRUMENT}),
        frozenset({BAR_TYPE}),
        OnlyHistoricalDataRange(BASE + timedelta(minutes=1), BASE + timedelta(minutes=2)),
        VERSION,
    )

    result = coordinator.backfill_bar_gap(acquisition, request, gap)  # type: ignore[arg-type]

    assert source.requests == [request]
    assert result.manifest.complete
    assert result.manifest.gaps == ()
    assert result.revision is not None and result.seal is not None
    assert result.revision.creation_reason == "BACKFILL"
    assert wal.scan_uncommitted() == ()
    assert len(OnlyHistoricalMarketDataQueryService(catalog, store).read_exact(result.revision.revision_id, scope)) == 2


def test_backfill_rejects_source_stream_that_bypasses_durable_recorder(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal, normalizer_id="binance-spot", normalizer_version="1", ingest_clock_ns=lambda: 5
    )
    first_id = _write_bar(ingress, "initial", 0, "101.00000000")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _two_minute_scope()
    assert recovery.drain(first_id, scope) == "DURABLE_ONLY:INCOMPLETE"
    source = _NonDurableHistoricalSource(ingress)
    coordinator = OnlyMarketDataBackfillCoordinator(source, catalog, store, recovery, committer)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        str(SOURCE), scope, provenance=OnlyMarketDataProvenance.REST_BACKFILL, created_at=fixed_now()
    )
    [gap] = coordinator.inspect(acquisition).gaps
    request = OnlyHistoricalBarRequest(
        "gap-request",
        frozenset({INSTRUMENT}),
        frozenset({BAR_TYPE}),
        OnlyHistoricalDataRange(BASE + timedelta(minutes=1), BASE + timedelta(minutes=2)),
        VERSION,
    )

    with pytest.raises(RuntimeError, match="BACKFILL_DURABLE_SEGMENT_NOT_CREATED"):
        coordinator.backfill_bar_gap(acquisition, request, gap)  # type: ignore[arg-type]


def test_correction_composes_from_durable_parent_without_old_wal_and_is_deterministic(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(wal, normalizer_id="n", normalizer_version="1", ingest_clock_ns=lambda: 5)
    first_id = _write_bar(ingress, "s1", 0, "101.00000000")
    second_id = _write_bar(ingress, "s-bad", 1, "101.50000000")
    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _two_minute_scope()
    assert recovery.drain_revision((first_id, second_id), scope) == "COMMITTED"
    parent = catalog.latest_sealed_revision(scope)
    query = OnlyHistoricalMarketDataQueryService(catalog, store)
    old_facts = query.read_exact(parent.revision_id, scope)
    assert wal.scan_uncommitted() == ()

    fixed_id = _write_bar(ingress, "s-fixed", 1, "102.00000000", "REPAIR")
    fixed_scope = replace(scope, start_ns=scope.start_ns + 60_000_000_000)
    assert recovery.drain(fixed_id, fixed_scope) == "COMMITTED"
    composer = OnlyMarketDataCorrectionComposer(catalog, store, committer)
    _, corrected, _ = composer.compose(parent.revision_id, ((second_id, fixed_id),))
    _, repeated, _ = composer.compose(parent.revision_id, ((second_id, fixed_id),))

    assert corrected.revision_id == repeated.revision_id
    assert corrected.parent_revision_id == parent.revision_id
    assert corrected.creation_reason == "CORRECTION"
    assert query.read_exact(parent.revision_id, scope) == old_facts
    new_facts = query.read_exact(corrected.revision_id, scope)
    assert new_facts != old_facts
    assert len(new_facts) == 2
