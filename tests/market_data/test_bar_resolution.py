from __future__ import annotations

import subprocess
import sys

import pytest

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.market_data.durable.models import OnlyMarketDataScope
from onlyalpha.market_data.resolution import (
    OnlyBarCapability,
    OnlyBarConstructionIdentity,
    OnlyBarIntervalKind,
    OnlyBarResolutionMode,
    OnlyBarResolutionPlan,
    OnlyCalendarBarSpecification,
    OnlyCalendarBarUnit,
    OnlyFixedDurationBarSemantic,
    only_expected_fixed_duration_bar_ends,
    only_plan_bar_resolution,
)


def _bar(minutes: int) -> OnlyBarSpecification:
    return OnlyBarSpecification(minutes, OnlyBarAggregation.TIME, OnlyPriceType.LAST)


def _capability(minutes: int, alignment: str = "UTC") -> OnlyBarCapability:
    return OnlyBarCapability(_bar(minutes), OnlyBarIntervalKind.FIXED_DURATION, alignment, True, True, grid_origin_ns=0)


def _semantic(window: int, stride: int) -> OnlyFixedDurationBarSemantic:
    return OnlyFixedDurationBarSemantic(
        OnlyBarAggregation.TIME,
        OnlyBarIntervalKind.FIXED_DURATION,
        window,
        stride,
        OnlyPriceType.LAST,
    )


def _plan(minutes: int, capabilities: tuple[OnlyBarCapability, ...]):
    return only_plan_bar_resolution(
        _bar(minutes),
        capabilities,
        alignment_id="UTC",
        source_id="source",
        instrument_id="BTCUSDT.TEST",
        integration_revision_fingerprint="a" * 64,
    )


def _semantic_plan(window: int, stride: int, capabilities: tuple[OnlyBarCapability, ...]):
    return only_plan_bar_resolution(
        _semantic(window, stride),
        capabilities,
        alignment_id="UTC",
        source_id="source",
        instrument_id="BTCUSDT.TEST",
        integration_revision_fingerprint="a" * 64,
    )


def test_exact_compatible_native_and_derived_have_distinct_lineage() -> None:
    native = _plan(5, (_capability(1), _capability(5)))
    derived = _plan(5, (_capability(1),))
    assert native.mode is OnlyBarResolutionMode.EXTERNAL_NATIVE
    assert native.provider_specification == _bar(5)
    assert derived.mode is OnlyBarResolutionMode.INTERNAL_DERIVED
    assert derived.base_specification == _bar(1)
    assert derived.aggregation_semantics_version == "TIME_BAR_V1"
    assert native.fingerprint != derived.fingerprint
    assert native == _plan(5, (_capability(1), _capability(5)))


def test_incompatible_alignment_or_realtime_cannot_select_native() -> None:
    unavailable_live = OnlyBarCapability(_bar(5), OnlyBarIntervalKind.FIXED_DURATION, "UTC", True, False)
    plan = _plan(5, (_capability(1), _capability(5, "SESSION"), unavailable_live))
    assert plan.mode is OnlyBarResolutionMode.INTERNAL_DERIVED


def test_missing_base_fails_closed_and_calendar_unit_is_not_minutes() -> None:
    with pytest.raises(ValueError, match="BAR_RESOLUTION_BASE_UNAVAILABLE"):
        _plan(7, (_capability(5),))
    calendar = OnlyBarCapability(
        OnlyCalendarBarSpecification(OnlyCalendarBarUnit.DAY, 1, OnlyPriceType.LAST),
        OnlyBarIntervalKind.CALENDAR_SESSION,
        "SESSION",
        True,
        True,
    )
    assert calendar.specification != _bar(1440)
    with pytest.raises(ValueError, match="BAR_RESOLUTION_BASE_UNAVAILABLE"):
        _plan(7, (calendar,))


def test_construction_identity_roundtrip_and_capability_evolution() -> None:
    derived = _plan(7, (_capability(1),))
    native = _plan(7, (_capability(1), _capability(7)))
    assert type(derived).from_dict(derived.to_dict()) == derived
    old = OnlyBarConstructionIdentity.build(
        derived,
        data_version="v1",
        base_revision_id="revision:old",
        base_revision_fingerprint="b" * 64,
        base_seal_id="seal:old",
    )
    assert OnlyBarConstructionIdentity.from_dict(old.to_dict()) == old
    assert OnlyBarConstructionIdentity.from_canonical_payload(only_canonical_payload(old)) == old
    assert old.fingerprint != OnlyBarConstructionIdentity.build(native, data_version="v1").fingerprint
    with pytest.raises(ValueError, match="BAR_CONSTRUCTION_BASE_REVISION_REQUIRED"):
        OnlyBarConstructionIdentity.build(derived, data_version="v1")
    with pytest.raises(ValueError, match="BAR_CONSTRUCTION_INVALID"):
        OnlyBarConstructionIdentity.from_dict({**old.to_dict(), "fingerprint": "0" * 64})


def test_native_and_derived_fifteen_minute_scopes_never_collide() -> None:
    native_plan = _plan(15, (_capability(1), _capability(15)))
    derived_plan = _plan(15, (_capability(1),))
    native = OnlyBarConstructionIdentity.build(native_plan, data_version="v1")
    derived = OnlyBarConstructionIdentity.build(
        derived_plan,
        data_version="v1",
        base_revision_id="revision:base",
        base_revision_fingerprint="b" * 64,
        base_seal_id="seal:base",
    )
    kwargs = dict(
        source_id="source",
        market="SPOT",
        instrument_id="BTCUSDT.TEST",
        data_kind="BAR",
        start_ns=0,
        end_ns=15 * 60_000_000_000,
        data_version="v1",
    )
    assert native.fingerprint != derived.fingerprint
    instrument = OnlyInstrumentId.parse("BTCUSDT.TEST")
    native_type = only_canonical_fingerprint(
        OnlyBarType(instrument, _bar(15), OnlyAggregationSource.EXTERNAL).to_dict()
    )
    derived_type = only_canonical_fingerprint(
        OnlyBarType(instrument, _bar(15), OnlyAggregationSource.INTERNAL).to_dict()
    )
    assert OnlyMarketDataScope(**kwargs, bar_type=native_type, bar_construction=native) != OnlyMarketDataScope(
        **kwargs, bar_type=derived_type, bar_construction=derived
    )


def test_fixed_duration_semantic_represents_aligned_and_rolling_windows() -> None:
    semantics = tuple(_semantic(window, stride) for window, stride in ((1, 1), (15, 15), (7, 7), (15, 1), (60, 5)))
    assert [(item.window_minutes, item.stride_minutes) for item in semantics] == [
        (1, 1),
        (15, 15),
        (7, 7),
        (15, 1),
        (60, 5),
    ]
    assert OnlyFixedDurationBarSemantic.from_legacy(_bar(15)) == _semantic(15, 15)
    assert _capability(15).semantic == _semantic(15, 15)
    assert OnlyFixedDurationBarSemantic.from_dict(_semantic(15, 1).to_dict()) == _semantic(15, 1)
    assert len({item.fingerprint for item in (_semantic(15, 15), _semantic(15, 1), _semantic(15, 5))}) == 3

    fresh_process = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from onlyalpha.market_data.resolution import *; "
            "from onlyalpha.domain.enums import OnlyBarAggregation, OnlyPriceType; "
            "print(OnlyFixedDurationBarSemantic(OnlyBarAggregation.TIME, "
            "OnlyBarIntervalKind.FIXED_DURATION, 15, 1, OnlyPriceType.LAST).fingerprint)",
        ],
        text=True,
    ).strip()
    assert fresh_process == _semantic(15, 1).fingerprint


def test_rolling_semantic_never_matches_native_and_has_distinct_lineage() -> None:
    capabilities = (_capability(1), _capability(15))
    plans = tuple(_semantic_plan(15, stride, capabilities) for stride in (15, 1, 5))
    aligned, rolling_one, rolling_five = plans
    assert aligned.mode is OnlyBarResolutionMode.EXTERNAL_NATIVE
    assert rolling_one.mode is rolling_five.mode is OnlyBarResolutionMode.INTERNAL_DERIVED
    assert (
        rolling_one.aggregation_semantics_version == rolling_five.aggregation_semantics_version == "ROLLING_TIME_BAR_V1"
    )
    assert len({item.fingerprint for item in plans}) == 3
    assert all(OnlyBarResolutionPlan.from_dict(item.to_dict()) == item for item in plans)

    constructions = (
        OnlyBarConstructionIdentity.build(aligned, data_version="v1"),
        OnlyBarConstructionIdentity.build(
            rolling_one,
            data_version="v1",
            base_revision_id="revision:base",
            base_revision_fingerprint="b" * 64,
            base_seal_id="seal:base",
        ),
        OnlyBarConstructionIdentity.build(
            rolling_five,
            data_version="v1",
            base_revision_id="revision:base",
            base_revision_fingerprint="b" * 64,
            base_seal_id="seal:base",
        ),
    )
    assert len({item.fingerprint for item in constructions}) == 3
    dataset_binding_identities = {
        only_canonical_fingerprint(("BTCUSDT.TEST", item.fingerprint, "c" * 64, "seal:base")) for item in constructions
    }
    assert len(dataset_binding_identities) == 3
    with pytest.raises(ValueError, match="BAR_RESOLUTION_CONSTRUCTION_UNIMPLEMENTED"):
        _ = rolling_one.target_specification


def test_time_bar_v1_rejects_rolling_semantic() -> None:
    rolling = _semantic_plan(15, 1, (_capability(1), _capability(15)))
    payload = {**rolling.to_dict(), "aggregation_semantics_version": "TIME_BAR_V1"}
    payload.pop("fingerprint")
    forged = OnlyBarResolutionPlan(
        rolling.target_semantic,
        rolling.mode,
        rolling.provider_semantic,
        rolling.base_semantic,
        "TIME_BAR_V1",
        rolling.alignment_id,
        rolling.source_id,
        rolling.instrument_id,
        rolling.integration_revision_fingerprint,
        rolling.grid_origin_ns,
        only_canonical_fingerprint(payload),
    )
    with pytest.raises(ValueError, match="BAR_RESOLUTION_CONSTRUCTION_UNIMPLEMENTED"):
        OnlyBarConstructionIdentity.build(
            forged,
            data_version="v1",
            base_revision_id="revision:base",
            base_revision_fingerprint="b" * 64,
            base_seal_id="seal:base",
        )


def test_expected_fixed_duration_grid_uses_stride_not_window() -> None:
    minute = 60_000_000_000
    assert only_expected_fixed_duration_bar_ends(
        _semantic(15, 5), start_ns=0, end_ns=30 * minute, grid_origin_ns=0
    ) == (15 * minute, 20 * minute, 25 * minute, 30 * minute)


def test_legacy_persisted_plan_requires_explicit_rebuild() -> None:
    with pytest.raises(ValueError, match="BAR_RESOLUTION_PLAN_REBUILD_REQUIRED"):
        OnlyBarResolutionPlan.from_dict({})
    with pytest.raises(ValueError, match="BAR_RESOLUTION_PLAN_REBUILD_REQUIRED"):
        OnlyBarResolutionPlan.from_canonical_payload({"target_specification": _bar(15).to_dict()})
