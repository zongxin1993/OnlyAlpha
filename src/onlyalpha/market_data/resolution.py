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

    specification: OnlyBarSpecification | OnlyCalendarBarSpecification
    interval_kind: OnlyBarIntervalKind
    alignment_id: str
    historical_supported: bool
    realtime_supported: bool
    adjustment: str = "RAW"
    grid_origin_ns: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.alignment_id
            or self.adjustment != "RAW"
            or (self.interval_kind is OnlyBarIntervalKind.FIXED_DURATION)
            != isinstance(self.specification, OnlyBarSpecification)
            or (self.grid_origin_ns is not None and self.interval_kind is not OnlyBarIntervalKind.FIXED_DURATION)
            or (self.grid_origin_ns is not None and type(self.grid_origin_ns) is not int)
        ):
            raise ValueError("BAR_CAPABILITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBarResolutionPlan:
    target_specification: OnlyBarSpecification
    mode: OnlyBarResolutionMode
    provider_specification: OnlyBarSpecification | None
    base_specification: OnlyBarSpecification | None
    aggregation_semantics_version: str | None
    alignment_id: str
    source_id: str
    instrument_id: str
    integration_revision_fingerprint: str
    grid_origin_ns: int
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        payload = {
            "target": self.target_specification.to_dict(),
            "mode": self.mode.value,
            "provider": None if self.provider_specification is None else self.provider_specification.to_dict(),
            "base": None if self.base_specification is None else self.base_specification.to_dict(),
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
        def specification(key: str) -> OnlyBarSpecification | None:
            item = value[key]
            if item is not None and not isinstance(item, Mapping):
                raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
            return None if item is None else OnlyBarSpecification.from_dict(item)

        if not isinstance(value["target"], Mapping):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        plan = cls(
            OnlyBarSpecification.from_dict(value["target"]),
            OnlyBarResolutionMode(str(value["mode"])),
            specification("provider"),
            specification("base"),
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
                plan.provider_specification == plan.target_specification
                and plan.base_specification is None
                and plan.aggregation_semantics_version is None
            )
        else:
            valid = (
                plan.provider_specification is None
                and plan.base_specification is not None
                and plan.aggregation_semantics_version == "TIME_BAR_V1"
            )
        if not valid:
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        grid_specification = plan.provider_specification or plan.base_specification
        if (
            grid_specification is None
            or not 0 <= plan.grid_origin_ns < grid_specification.step * 60_000_000_000
            or len(plan.integration_revision_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in plan.integration_revision_fingerprint)
        ):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        return plan

    @classmethod
    def from_canonical_payload(cls, value: Mapping[str, object]) -> OnlyBarResolutionPlan:
        """Read the canonical dataclass projection persisted inside a scope JSONB."""

        def specification(key: str) -> dict[str, object] | None:
            item = value[key]
            if item is None:
                return None
            if not isinstance(item, Mapping):
                raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
            return OnlyBarSpecification(
                int(str(item["step"])),
                OnlyBarAggregation(str(item["aggregation"])),
                OnlyPriceType(str(item["price_type"])),
            ).to_dict()

        return cls.from_dict(
            {
                "target": specification("target_specification"),
                "mode": value["mode"],
                "provider": specification("provider_specification"),
                "base": specification("base_specification"),
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
    target: OnlyBarSpecification,
    capabilities: tuple[OnlyBarCapability, ...],
    *,
    alignment_id: str,
    source_id: str,
    instrument_id: str,
    integration_revision_fingerprint: str,
) -> OnlyBarResolutionPlan:
    """Choose exact compatible native or deterministic 1m aggregation, never a silent fallback."""

    if (
        target.aggregation is not OnlyBarAggregation.TIME
        or target.price_type is not OnlyPriceType.LAST
        or not 1 <= target.step <= 240
        or not alignment_id
        or not source_id
        or not instrument_id
        or not integration_revision_fingerprint
        or len(integration_revision_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in integration_revision_fingerprint)
    ):
        raise ValueError("BAR_RESOLUTION_UNSUPPORTED")
    base = OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    usable = tuple(
        capability
        for capability in capabilities
        if capability.interval_kind is OnlyBarIntervalKind.FIXED_DURATION
        and capability.specification == target
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
        provider, derived_base, version = target, None, None
        grid_origin_ns = usable[0].grid_origin_ns
    else:
        base_usable = tuple(
            capability
            for capability in capabilities
            if capability.interval_kind is OnlyBarIntervalKind.FIXED_DURATION
            and capability.specification == base
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
        provider, derived_base, version = None, base, "TIME_BAR_V1"
        grid_origin_ns = base_usable[0].grid_origin_ns
    assert grid_origin_ns is not None
    grid_specification = provider or derived_base
    assert grid_specification is not None
    grid_origin_ns %= grid_specification.step * 60_000_000_000
    fingerprint = only_canonical_fingerprint(
        {
            "target": target.to_dict(),
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
        target,
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
