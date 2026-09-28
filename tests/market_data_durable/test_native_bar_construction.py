from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import OnlyBarUpdate
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.durable import (
    OnlyBarCoverageGap,
    OnlyCoverageStatus,
    OnlyMarketDataConflictError,
    OnlyMarketDataIngress,
    OnlyMarketDataScope,
    OnlyMarketDataWal,
    only_build_coverage,
)
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionIdentity,
    OnlyBarIntervalKind,
    only_plan_bar_resolution,
)

from .conftest import BASE, INSTRUMENT, SOURCE, VERSION, bar_update
from .test_recovery_revision_dataset import _observation


def test_native_fifteen_minute_coverage_survives_wal_reload(tmp_path: Path, fixed_now) -> None:
    specification = OnlyBarSpecification(15, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    bar_type = OnlyBarType(INSTRUMENT, specification, OnlyAggregationSource.EXTERNAL)
    plan = only_plan_bar_resolution(
        specification,
        (OnlyBarCapability(specification, OnlyBarIntervalKind.FIXED_DURATION, "UTC", True, True, grid_origin_ns=0),),
        alignment_id="UTC",
        source_id=str(SOURCE),
        instrument_id=str(INSTRUMENT),
        integration_revision_fingerprint="a" * 64,
    )
    construction = OnlyBarConstructionIdentity.build(plan, data_version=str(VERSION))
    wal = OnlyMarketDataWal(tmp_path, capacity_bytes=2_000_000, now=fixed_now)
    ingress = OnlyMarketDataIngress(
        wal,
        normalizer_id="binance-spot",
        normalizer_version="1",
        ingest_clock_ns=lambda: 5,
        bar_construction=construction,
    )
    ingress.begin_segment("native-15m")
    for index in range(4):
        base = bar_update(index * 15)
        start = BASE + timedelta(minutes=index * 15)
        end = start + timedelta(minutes=15)
        bar = replace(base.payload.bar, bar_type=bar_type, bar_end=end, ts_event=end, ts_init=end)
        update = replace(
            base,
            update_id=only_bar_update_id(SOURCE, INSTRUMENT, bar_type, start, VERSION),
            payload=OnlyBarUpdate(bar),
            ts_event=OnlyTimestamp.from_datetime(end),
            ts_init=OnlyTimestamp.from_datetime(end),
            sequence_scope=None,
        )
        ingress.record(_observation(index), update)
    segment = ingress.seal()
    restored = wal.load_segment(segment.segment_id)
    scope = OnlyMarketDataScope(
        str(SOURCE),
        "SPOT",
        str(INSTRUMENT),
        "BAR",
        OnlyTimestamp.from_datetime(BASE).unix_nanos,
        OnlyTimestamp.from_datetime(BASE + timedelta(hours=1)).unix_nanos,
        str(VERSION),
        only_canonical_fingerprint(bar_type.to_dict()),
        bar_construction=construction,
    )
    facts = tuple(fact for bundle in wal.read_sealed(segment.segment_id) for fact in bundle.canonical_facts)
    assert restored.recovery_scope().bar_construction == construction
    assert not wal.verify_sealed(replace(restored, bar_construction=None))
    with pytest.raises(ValueError, match="SEGMENT_BAR_CONSTRUCTION_UNPROVABLE"):
        replace(restored, bar_construction=None).recovery_scope()
    manifest = only_build_coverage(scope, (restored,), facts)
    assert manifest.coverage_status is OnlyCoverageStatus.COMPLETE
    assert "bar_grid_count=4" in manifest.proof
    missing = only_build_coverage(scope, (restored,), facts[:1] + facts[2:])
    assert missing.gaps == (
        OnlyBarCoverageGap(scope.start_ns + 15 * 60_000_000_000, scope.start_ns + 30 * 60_000_000_000),
    )
    with pytest.raises(OnlyMarketDataConflictError, match="SEGMENT_SCOPE_MISMATCH"):
        only_build_coverage(replace(scope, bar_construction=None), (restored,), facts)
