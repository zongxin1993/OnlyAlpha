"""Provider-neutral, immutable construction choice for intraday chart bars."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.market import OnlyBarSpecification


class OnlyBarIntervalKind(StrEnum):
    FIXED_DURATION = "FIXED_DURATION"
    CALENDAR_SESSION = "CALENDAR_SESSION"


class OnlyCalendarBarUnit(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


class OnlyBarResolutionMode(StrEnum):
    EXTERNAL_NATIVE = "EXTERNAL_NATIVE"
    INTERNAL_DERIVED = "INTERNAL_DERIVED"


@dataclass(frozen=True, slots=True)
class OnlyFixedDurationBarSemantic:
    """Canonical fixed-duration Bar meaning; emission stride is independent of window."""

    aggregation: OnlyBarAggregation
    interval_kind: OnlyBarIntervalKind
    window_minutes: int
    stride_minutes: int
    price_type: OnlyPriceType

    def __post_init__(self) -> None:
        if (
            self.aggregation is not OnlyBarAggregation.TIME
            or self.interval_kind is not OnlyBarIntervalKind.FIXED_DURATION
            or type(self.window_minutes) is not int
            or type(self.stride_minutes) is not int
            or not 1 <= self.window_minutes <= 240
            or not 1 <= self.stride_minutes <= self.window_minutes
        ):
            raise ValueError("FIXED_DURATION_BAR_SEMANTIC_INVALID")

    @classmethod
    def from_legacy(cls, value: OnlyBarSpecification) -> OnlyFixedDurationBarSemantic:
        return cls(
            value.aggregation,
            OnlyBarIntervalKind.FIXED_DURATION,
            value.step,
            value.step,
            value.price_type,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyFixedDurationBarSemantic:
        semantic = cls(
            OnlyBarAggregation(str(value["aggregation"])),
            OnlyBarIntervalKind(str(value["interval_kind"])),
            int(str(value["window_minutes"])),
            int(str(value["stride_minutes"])),
            OnlyPriceType(str(value["price_type"])),
        )
        if semantic.to_dict() != dict(value):
            raise ValueError("FIXED_DURATION_BAR_SEMANTIC_INVALID")
        return semantic

    def to_dict(self) -> dict[str, object]:
        return {
            "aggregation": self.aggregation.value,
            "interval_kind": self.interval_kind.value,
            "window_minutes": self.window_minutes,
            "stride_minutes": self.stride_minutes,
            "price_type": self.price_type.value,
        }

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    @property
    def is_aligned(self) -> bool:
        return self.window_minutes == self.stride_minutes

    def aligned_specification(self) -> OnlyBarSpecification:
        if not self.is_aligned:
            raise ValueError("BAR_RESOLUTION_CONSTRUCTION_UNIMPLEMENTED")
        return OnlyBarSpecification(self.window_minutes, self.aggregation, self.price_type)


@dataclass(frozen=True, slots=True)
class OnlyCalendarBarSpecification:
    """Session-aligned bars are distinct from elapsed minutes."""

    unit: OnlyCalendarBarUnit
    count: int
    price_type: OnlyPriceType

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("CALENDAR_BAR_SPECIFICATION_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBarCapability:
    """One exact provider bar, including alignment and both delivery channels."""

    semantic: OnlyFixedDurationBarSemantic | OnlyBarSpecification | OnlyCalendarBarSpecification
    interval_kind: OnlyBarIntervalKind
    alignment_id: str
    historical_supported: bool
    realtime_supported: bool
    adjustment: str = "RAW"
    grid_origin_ns: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.semantic, OnlyBarSpecification):
            object.__setattr__(self, "semantic", OnlyFixedDurationBarSemantic.from_legacy(self.semantic))
        if (
            not self.alignment_id
            or self.adjustment != "RAW"
            or (self.interval_kind is OnlyBarIntervalKind.FIXED_DURATION)
            != isinstance(self.semantic, OnlyFixedDurationBarSemantic)
            or (self.grid_origin_ns is not None and self.interval_kind is not OnlyBarIntervalKind.FIXED_DURATION)
            or (self.grid_origin_ns is not None and type(self.grid_origin_ns) is not int)
        ):
            raise ValueError("BAR_CAPABILITY_INVALID")

    @property
    def specification(self) -> OnlyBarSpecification | OnlyCalendarBarSpecification:
        if isinstance(self.semantic, OnlyCalendarBarSpecification):
            return self.semantic
        if isinstance(self.semantic, OnlyBarSpecification):
            return self.semantic
        return self.semantic.aligned_specification()


@dataclass(frozen=True, slots=True)
class OnlyBarResolutionPlan:
    target_semantic: OnlyFixedDurationBarSemantic
    mode: OnlyBarResolutionMode
    provider_semantic: OnlyFixedDurationBarSemantic | None
    base_semantic: OnlyFixedDurationBarSemantic | None
    aggregation_semantics_version: str | None
    alignment_id: str
    source_id: str
    instrument_id: str
    integration_revision_fingerprint: str
    grid_origin_ns: int
    fingerprint: str

    @property
    def target_specification(self) -> OnlyBarSpecification:
        return self.target_semantic.aligned_specification()

    @property
    def provider_specification(self) -> OnlyBarSpecification | None:
        return None if self.provider_semantic is None else self.provider_semantic.aligned_specification()

    @property
    def base_specification(self) -> OnlyBarSpecification | None:
        return None if self.base_semantic is None else self.base_semantic.aligned_specification()

    def to_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 2,
            "target": self.target_semantic.to_dict(),
            "mode": self.mode.value,
            "provider": None if self.provider_semantic is None else self.provider_semantic.to_dict(),
            "base": None if self.base_semantic is None else self.base_semantic.to_dict(),
            "aggregation_semantics_version": self.aggregation_semantics_version,
            "alignment_id": self.alignment_id,
            "source_id": self.source_id,
            "instrument_id": self.instrument_id,
            "integration_revision_fingerprint": self.integration_revision_fingerprint,
            "grid_origin_ns": self.grid_origin_ns,
        }
        return {**payload, "fingerprint": only_canonical_fingerprint(payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarResolutionPlan:
        def semantic(key: str) -> OnlyFixedDurationBarSemantic | None:
            item = value[key]
            if item is not None and not isinstance(item, Mapping):
                raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
            return None if item is None else OnlyFixedDurationBarSemantic.from_dict(item)

        if value.get("schema_version") != 2:
            raise ValueError("BAR_RESOLUTION_PLAN_REBUILD_REQUIRED")
        if not isinstance(value["target"], Mapping):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        plan = cls(
            OnlyFixedDurationBarSemantic.from_dict(value["target"]),
            OnlyBarResolutionMode(str(value["mode"])),
            semantic("provider"),
            semantic("base"),
            None if value["aggregation_semantics_version"] is None else str(value["aggregation_semantics_version"]),
            str(value["alignment_id"]),
            str(value["source_id"]),
            str(value["instrument_id"]),
            str(value["integration_revision_fingerprint"]),
            int(str(value["grid_origin_ns"])),
            str(value["fingerprint"]),
        )
        if plan.to_dict() != dict(value):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        if plan.mode is OnlyBarResolutionMode.EXTERNAL_NATIVE:
            valid = (
                plan.provider_semantic == plan.target_semantic
                and plan.base_semantic is None
                and plan.aggregation_semantics_version is None
            )
        else:
            valid = (
                plan.provider_semantic is None
                and plan.base_semantic is not None
                and plan.aggregation_semantics_version
                == ("TIME_BAR_V1" if plan.target_semantic.is_aligned else "ROLLING_TIME_BAR_V1")
            )
        if not valid:
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        grid_semantic = plan.provider_semantic or plan.base_semantic
        if (
            grid_semantic is None
            or not 0 <= plan.grid_origin_ns < grid_semantic.stride_minutes * 60_000_000_000
            or len(plan.integration_revision_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in plan.integration_revision_fingerprint)
        ):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        return plan

    @classmethod
    def from_canonical_payload(cls, value: Mapping[str, object]) -> OnlyBarResolutionPlan:
        """Read the canonical dataclass projection persisted inside a scope JSONB."""

        if "target_semantic" not in value:
            raise ValueError("BAR_RESOLUTION_PLAN_REBUILD_REQUIRED")

        def semantic(key: str) -> dict[str, object] | None:
            item = value[key]
            if item is None:
                return None
            if not isinstance(item, Mapping):
                raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
            return OnlyFixedDurationBarSemantic.from_dict(item).to_dict()

        return cls.from_dict(
            {
                "schema_version": 2,
                "target": semantic("target_semantic"),
                "mode": value["mode"],
                "provider": semantic("provider_semantic"),
                "base": semantic("base_semantic"),
                "aggregation_semantics_version": value["aggregation_semantics_version"],
                "alignment_id": value["alignment_id"],
                "source_id": value["source_id"],
                "instrument_id": value["instrument_id"],
                "integration_revision_fingerprint": value["integration_revision_fingerprint"],
                "grid_origin_ns": value["grid_origin_ns"],
                "fingerprint": value["fingerprint"],
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyBarConstructionIdentity:
    """Immutable provenance of native bars or a projection over one sealed base revision."""

    plan: OnlyBarResolutionPlan
    data_version: str
    adjustment: str
    base_revision_id: str | None
    base_revision_fingerprint: str | None
    base_seal_id: str | None
    fingerprint: str

    @classmethod
    def build(
        cls,
        plan: OnlyBarResolutionPlan,
        *,
        data_version: str,
        base_revision_id: str | None = None,
        base_revision_fingerprint: str | None = None,
        base_seal_id: str | None = None,
    ) -> OnlyBarConstructionIdentity:
        if not data_version or plan.to_dict()["fingerprint"] != plan.fingerprint:
            raise ValueError("BAR_CONSTRUCTION_INVALID")
        if plan.aggregation_semantics_version == "TIME_BAR_V1" and not plan.target_semantic.is_aligned:
            raise ValueError("BAR_RESOLUTION_CONSTRUCTION_UNIMPLEMENTED")
        base = (base_revision_id, base_revision_fingerprint, base_seal_id)
        if (plan.mode is OnlyBarResolutionMode.EXTERNAL_NATIVE and any(base)) or (
            plan.mode is OnlyBarResolutionMode.INTERNAL_DERIVED and not all(base)
        ):
            raise ValueError("BAR_CONSTRUCTION_BASE_REVISION_REQUIRED")
        payload = {
            "plan": plan.to_dict(),
            "data_version": data_version,
            "adjustment": "RAW",
            "base_revision_id": base_revision_id,
            "base_revision_fingerprint": base_revision_fingerprint,
            "base_seal_id": base_seal_id,
        }
        return cls(plan, data_version, "RAW", *base, only_canonical_fingerprint(payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "plan": self.plan.to_dict(),
            "data_version": self.data_version,
            "adjustment": self.adjustment,
            "base_revision_id": self.base_revision_id,
            "base_revision_fingerprint": self.base_revision_fingerprint,
            "base_seal_id": self.base_seal_id,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarConstructionIdentity:
        if not isinstance(value["plan"], Mapping):
            raise ValueError("BAR_CONSTRUCTION_INVALID")

        def optional_string(key: str) -> str | None:
            item = value[key]
            if item is not None and not isinstance(item, str):
                raise ValueError("BAR_CONSTRUCTION_INVALID")
            return item

        plan = OnlyBarResolutionPlan.from_dict(value["plan"])
        identity = cls.build(
            plan,
            data_version=str(value["data_version"]),
            base_revision_id=optional_string("base_revision_id"),
            base_revision_fingerprint=optional_string("base_revision_fingerprint"),
            base_seal_id=optional_string("base_seal_id"),
        )
        if identity.to_dict() != dict(value):
            raise ValueError("BAR_CONSTRUCTION_INVALID")
        return identity

    @classmethod
    def from_canonical_payload(cls, value: Mapping[str, object]) -> OnlyBarConstructionIdentity:
        plan = value["plan"]
        if not isinstance(plan, Mapping):
            raise ValueError("BAR_CONSTRUCTION_INVALID")
        return cls.from_dict({**value, "plan": OnlyBarResolutionPlan.from_canonical_payload(plan).to_dict()})


def only_plan_bar_resolution(
    target: OnlyBarSpecification | OnlyFixedDurationBarSemantic,
    capabilities: tuple[OnlyBarCapability, ...],
    *,
    alignment_id: str,
    source_id: str,
    instrument_id: str,
    integration_revision_fingerprint: str,
) -> OnlyBarResolutionPlan:
    """Choose exact compatible native or deterministic 1m aggregation, never a silent fallback."""

    target_semantic = (
        OnlyFixedDurationBarSemantic.from_legacy(target) if isinstance(target, OnlyBarSpecification) else target
    )
    if (
        target_semantic.aggregation is not OnlyBarAggregation.TIME
        or target_semantic.price_type is not OnlyPriceType.LAST
        or not alignment_id
        or not source_id
        or not instrument_id
        or not integration_revision_fingerprint
        or len(integration_revision_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in integration_revision_fingerprint)
    ):
        raise ValueError("BAR_RESOLUTION_UNSUPPORTED")
    base = OnlyFixedDurationBarSemantic(
        OnlyBarAggregation.TIME, OnlyBarIntervalKind.FIXED_DURATION, 1, 1, OnlyPriceType.LAST
    )
    usable = tuple(
        capability
        for capability in capabilities
        if capability.interval_kind is OnlyBarIntervalKind.FIXED_DURATION
        and capability.semantic == target_semantic
        and capability.alignment_id == alignment_id
        and capability.historical_supported
        and capability.realtime_supported
        and capability.adjustment == "RAW"
        and capability.grid_origin_ns is not None
    )
    if len(usable) > 1:
        raise ValueError("BAR_RESOLUTION_AMBIGUOUS")
    if usable:
        mode = OnlyBarResolutionMode.EXTERNAL_NATIVE
        provider, derived_base, version = target_semantic, None, None
        grid_origin_ns = usable[0].grid_origin_ns
    else:
        base_usable = tuple(
            capability
            for capability in capabilities
            if capability.interval_kind is OnlyBarIntervalKind.FIXED_DURATION
            and capability.semantic == base
            and capability.alignment_id == alignment_id
            and capability.historical_supported
            and capability.realtime_supported
            and capability.adjustment == "RAW"
            and capability.grid_origin_ns is not None
        )
        if not base_usable:
            raise ValueError("BAR_RESOLUTION_BASE_UNAVAILABLE")
        if len(base_usable) != 1:
            raise ValueError("BAR_RESOLUTION_AMBIGUOUS")
        mode = OnlyBarResolutionMode.INTERNAL_DERIVED
        provider, derived_base = None, base
        version = "TIME_BAR_V1" if target_semantic.is_aligned else "ROLLING_TIME_BAR_V1"
        grid_origin_ns = base_usable[0].grid_origin_ns
    assert grid_origin_ns is not None
    grid_semantic = provider or derived_base
    assert grid_semantic is not None
    grid_origin_ns %= grid_semantic.stride_minutes * 60_000_000_000
    fingerprint = only_canonical_fingerprint(
        {
            "schema_version": 2,
            "target": target_semantic.to_dict(),
            "mode": mode.value,
            "provider": None if provider is None else provider.to_dict(),
            "base": None if derived_base is None else derived_base.to_dict(),
            "aggregation_semantics_version": version,
            "alignment_id": alignment_id,
            "source_id": source_id,
            "instrument_id": instrument_id,
            "integration_revision_fingerprint": integration_revision_fingerprint,
            "grid_origin_ns": grid_origin_ns,
        }
    )
    return OnlyBarResolutionPlan(
        target_semantic,
        mode,
        provider,
        derived_base,
        version,
        alignment_id,
        source_id,
        instrument_id,
        integration_revision_fingerprint,
        grid_origin_ns,
        fingerprint,
    )


def only_expected_fixed_duration_bar_ends(
    semantic: OnlyFixedDurationBarSemantic,
    *,
    start_ns: int,
    end_ns: int,
    grid_origin_ns: int,
) -> tuple[int, ...]:
    """Return an output grid using stride while keeping Bar duration as window."""

    stride_ns = semantic.stride_minutes * 60_000_000_000
    window_ns = semantic.window_minutes * 60_000_000_000
    if start_ns >= end_ns or (start_ns - grid_origin_ns) % stride_ns or (end_ns - grid_origin_ns) % stride_ns:
        return ()
    return tuple(range(start_ns + window_ns, end_ns + 1, stride_ns))
