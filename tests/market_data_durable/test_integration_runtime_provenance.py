"""Integration runtime provenance, WAL backward compatibility and gap planning."""

from __future__ import annotations

import json

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange, OnlyHistoricalDataStream
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.durable import (
    OnlyBarCoverageGap,
    OnlyCoverageStatus,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataBackfillCoordinator,
    OnlyMarketDataIngress,
    OnlyMarketDataProvenance,
    OnlyMarketDataRecoveryCoordinator,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    OnlyRevisionCommitService,
    only_bar_gap_is_backfillable,
    only_plan_contiguous_bar_gaps,
)

from .conftest import BAR_TYPE, BASE, INSTRUMENT, SOURCE, VERSION, bar_update
from .test_recovery_revision_dataset import _observation

BINDING = "1" * 64
OTHER_BINDING = "2" * 64
MINUTE = 60_000_000_000


def _three_minute_scope() -> OnlyMarketDataScope:
    start = int(BASE.timestamp()) * 1_000_000_000
    return OnlyMarketDataScope(
        str(SOURCE),
        "SPOT",
        str(INSTRUMENT),
        "BAR",
        start,
        start + 3 * MINUTE,
        str(VERSION),
        only_canonical_fingerprint(BAR_TYPE.to_dict()),
    )


def _write(wal: OnlyMarketDataWal, segment_id: str, *, binding: str | None, index: int = 0) -> str:
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        integration_binding_fingerprint=binding,
    )
    ingress.begin_segment(segment_id)
    ingress.record(_observation(10 + index, "REST_BACKFILL"), bar_update(index))
    return ingress.seal().segment_id


def test_segment_and_raw_evidence_carry_exact_integration_runtime_provenance(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    segment_id = _write(wal, "binding", binding=BINDING)

    segment = wal.load_segment(segment_id)
    assert segment.integration_binding_fingerprint == BINDING
    bundles = wal.read_sealed(segment_id)
    assert {item.evidence.integration_binding_fingerprint for item in bundles} == {BINDING}

    metadata = json.loads((tmp_path / f"{segment_id}.segment.json").read_text())
    assert metadata["integration_binding_fingerprint"] == BINDING


def test_identical_provider_facts_converge_across_two_bindings(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    first = OnlyMarketDataWal(tmp_path / "first", capacity_bytes=2_000_000, now=fixed_now)
    second = OnlyMarketDataWal(tmp_path / "second", capacity_bytes=2_000_000, now=fixed_now)
    first_id = _write(first, "first", binding=BINDING)
    second_id = _write(second, "second", binding=OTHER_BINDING)

    left = first.read_sealed(first_id)[0]
    right = second.read_sealed(second_id)[0]
    assert left.evidence.raw_event_id == right.evidence.raw_event_id
    assert left.canonical_facts[0].canonical_fact_id == right.canonical_facts[0].canonical_fact_id
    assert left.canonical_facts[0].canonical_payload_hash == right.canonical_facts[0].canonical_payload_hash
    assert left.evidence.integration_binding_fingerprint != right.evidence.integration_binding_fingerprint


def test_segment_without_prior_provenance_remains_readable(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    segment_id = _write(wal, "legacy", binding=None)

    metadata = json.loads((tmp_path / f"{segment_id}.segment.json").read_text())
    assert "integration_binding_fingerprint" not in metadata
    assert wal.load_segment(segment_id).integration_binding_fingerprint is None


def test_planned_bar_gaps_coalesce_adjacent_minutes_and_keep_separate_runs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=1_000_000)
    del wal
    start = int(BASE.timestamp()) * 1_000_000_000
    gaps = tuple(
        OnlyBarCoverageGap(start + index * MINUTE, start + (index + 1) * MINUTE) for index in (0, 1, 2, 10, 11)
    )

    planned = only_plan_contiguous_bar_gaps(gaps)
    assert tuple((item.start_ns, item.end_ns) for item in planned) == (
        (start, start + 3 * MINUTE),
        (start + 10 * MINUTE, start + 12 * MINUTE),
    )
    assert only_bar_gap_is_backfillable(planned[0], gaps)
    assert only_bar_gap_is_backfillable(planned[1], gaps)
    assert only_bar_gap_is_backfillable(gaps[0], gaps)
    assert not only_bar_gap_is_backfillable(OnlyBarCoverageGap(start, start + 4 * MINUTE), gaps)
    assert not only_bar_gap_is_backfillable(OnlyBarCoverageGap(start + 2 * MINUTE, start + 11 * MINUTE), gaps)


class _RangeSource:
    """REST-like source recording one evidence bundle per requested range."""

    def __init__(self, ingress: OnlyMarketDataIngress) -> None:
        self._ingress = ingress

    @property
    def source_id(self):  # type: ignore[no-untyped-def]
        return SOURCE

    @property
    def capabilities(self):  # type: ignore[no-untyped-def]
        return frozenset()

    def load_bars(self, request):  # type: ignore[no-untyped-def]
        start = int(request.data_range.start_time.timestamp()) // 60
        end = int(request.data_range.end_time.timestamp()) // 60
        segment_id = f"range-{start}-{end}"
        self._ingress.begin_segment(segment_id)
        for ordinal, minute in enumerate(range(start, end)):
            index = minute - int(BASE.timestamp()) // 60
            self._ingress.record(_observation(20 + ordinal, "REST_BACKFILL"), bar_update(index))
        self._ingress.seal()
        return OnlyHistoricalDataStream((), request.batch_size)

    def load_trades(self, _request):  # type: ignore[no-untyped-def]
        raise AssertionError("BAR backfill must not call trade source")

    def load_quotes(self, _request):  # type: ignore[no-untyped-def]
        raise AssertionError("BAR backfill must not call quote source")


def test_backfill_accepts_one_coalesced_planned_range_for_adjacent_gaps(tmp_path, fixed_now) -> None:  # type: ignore[no-untyped-def]
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=4_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
    )
    ingress.begin_segment("initial")
    ingress.record(_observation(11, "REST_BACKFILL"), bar_update(0))
    ingress.seal()

    store = OnlyInMemoryMarketFactStore()
    catalog = OnlyInMemoryMarketDataCatalog()
    committer = OnlyRevisionCommitService(store, catalog, now=fixed_now)
    recovery = OnlyMarketDataRecoveryCoordinator(wal, store, catalog, committer)
    scope = _three_minute_scope()
    assert recovery.drain("initial", scope) == "DURABLE_ONLY:INCOMPLETE"

    source = _RangeSource(ingress)
    coordinator = OnlyMarketDataBackfillCoordinator(source, catalog, store, recovery, committer)
    acquisition = OnlyMarketDataAcquisitionIntent.build(
        str(SOURCE),
        scope,
        provenance=OnlyMarketDataProvenance.REST_BACKFILL,
        created_at=BASE,
    )
    manifest = coordinator.inspect(acquisition)
    assert [item.start_ns for item in manifest.gaps] == [
        scope.start_ns + MINUTE,
        scope.start_ns + 2 * MINUTE,
    ]
    planned = only_plan_contiguous_bar_gaps(tuple(manifest.gaps))  # type: ignore[arg-type]
    assert len(planned) == 1

    result = coordinator.backfill_bar_gap(
        acquisition,
        OnlyHistoricalBarRequest(
            "planned-range",
            frozenset({INSTRUMENT}),
            frozenset({BAR_TYPE}),
            OnlyHistoricalDataRange(
                OnlyTimestamp.from_unix_nanos(planned[0].start_ns).to_datetime(),
                OnlyTimestamp.from_unix_nanos(planned[0].end_ns).to_datetime(),
            ),
            VERSION,
        ),
        planned[0],
    )
    assert result.revision is not None
    assert result.manifest.coverage_status is OnlyCoverageStatus.COMPLETE
    assert len({item for item in result.manifest.proof if item.startswith("bar_grid_count=")}) == 1
