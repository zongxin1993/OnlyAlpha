from __future__ import annotations

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
    OnlyCalendarBarSpecification,
    OnlyCalendarBarUnit,
    only_plan_bar_resolution,
)


def _bar(minutes: int) -> OnlyBarSpecification:
    return OnlyBarSpecification(minutes, OnlyBarAggregation.TIME, OnlyPriceType.LAST)


def _capability(minutes: int, alignment: str = "UTC") -> OnlyBarCapability:
    return OnlyBarCapability(_bar(minutes), OnlyBarIntervalKind.FIXED_DURATION, alignment, True, True, grid_origin_ns=0)


def _plan(minutes: int, capabilities: tuple[OnlyBarCapability, ...]):
    return only_plan_bar_resolution(
        _bar(minutes),
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
