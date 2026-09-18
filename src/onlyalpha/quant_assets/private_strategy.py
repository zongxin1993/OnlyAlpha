"""Strict database-native Private Strategy Definition V1."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast

from onlyalpha.calculation import OnlyCalculationKind
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.research.definition.expression import (
    OnlyResearchAnd,
    OnlyResearchBooleanExpression,
    OnlyResearchComparison,
    OnlyResearchNot,
    OnlyResearchOr,
    only_research_expression_from_dict,
)
from onlyalpha.research.definition.model import (
    OnlyResearchCalculationInstance,
    OnlyResearchFixedParameter,
    OnlyResearchSignals,
    OnlyResearchStatisticsRequest,
)
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract, OnlyStrategyUniverse

_FACTOR_ID = re.compile(r"^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_STRATEGY_DEFINITION_SCHEMA_VERSION = 1
PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_VERSION = 1
_BOOLEAN_EXPRESSION_TYPES = (OnlyResearchComparison, OnlyResearchNot, OnlyResearchAnd, OnlyResearchOr)


@dataclass(frozen=True, order=True, slots=True)
class OnlyPrivateStrategyFactorRevisionDependencyV1:
    factor_id: str
    revision_fingerprint: str

    def __post_init__(self) -> None:
        if _FACTOR_ID.fullmatch(self.factor_id) is None:
            raise ValueError("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_INVALID")
        if _SHA256.fullmatch(self.revision_fingerprint) is None:
            raise ValueError("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {"factor_id": self.factor_id, "revision_fingerprint": self.revision_fingerprint}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyFactorRevisionDependencyV1:
        _exact(payload, {"factor_id", "revision_fingerprint"}, "Factor Revision dependency")
        return cls(_string(payload["factor_id"]), _string(payload["revision_fingerprint"]))


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyDefinitionV1:
    schema_version: int
    universe: OnlyStrategyUniverse
    market_input: OnlyStrategyMarketInputContract
    calculations: tuple[OnlyResearchCalculationInstance, ...]
    factor_revision_dependencies: tuple[OnlyPrivateStrategyFactorRevisionDependencyV1, ...]
    eligibility: OnlyResearchBooleanExpression
    signals: OnlyResearchSignals

    def __post_init__(self) -> None:
        if self.schema_version != PRIVATE_STRATEGY_DEFINITION_SCHEMA_VERSION:
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_SCHEMA_UNSUPPORTED")
        if not self.calculations or any(
            not isinstance(item, OnlyResearchCalculationInstance) for item in self.calculations
        ):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_CALCULATIONS_INVALID")
        if any(
            item.type_reference.kind not in {OnlyCalculationKind.INDICATOR, OnlyCalculationKind.FACTOR}
            for item in self.calculations
        ):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_CALCULATIONS_INVALID")
        if any(
            item.type_reference.type_id.startswith("private.factor.")
            and item.type_reference.kind is not OnlyCalculationKind.FACTOR
            for item in self.calculations
        ):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_CALCULATIONS_INVALID")
        keys = tuple(item.instance_key for item in self.calculations)
        if len(keys) != len(set(keys)):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_CALCULATION_DUPLICATE")
        if any(
            not isinstance(binding, OnlyResearchFixedParameter)
            for item in self.calculations
            for binding in item.parameters.values()
        ):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_SWEEP_FORBIDDEN")
        if not isinstance(self.eligibility, _BOOLEAN_EXPRESSION_TYPES):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_ELIGIBILITY_INVALID")
        if not isinstance(self.signals, OnlyResearchSignals):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_SIGNALS_INVALID")
        if self.signals.entry is None or self.signals.exit is None:
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_SIGNALS_INVALID")
        dependencies = tuple(sorted(self.factor_revision_dependencies))
        if dependencies != self.factor_revision_dependencies or len(dependencies) != len(set(dependencies)):
            raise ValueError("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_DUPLICATE")
        private_factors = {
            item.type_reference.type_id
            for item in self.calculations
            if item.type_reference.kind is OnlyCalculationKind.FACTOR
            and _FACTOR_ID.fullmatch(item.type_reference.type_id) is not None
        }
        declared = {item.factor_id for item in dependencies}
        if private_factors != declared:
            raise ValueError("PRIVATE_STRATEGY_FACTOR_DEPENDENCY_CLOSURE")
        object.__setattr__(self, "calculations", tuple(sorted(self.calculations, key=lambda item: item.instance_key)))

    @property
    def definition_fingerprint(self) -> str:
        return only_canonical_fingerprint({"contract": "ONLYALPHA_PRIVATE_STRATEGY_DEFINITION_V1", **self.to_dict()})

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            only_canonical_payload(
                {
                    "schema_version": self.schema_version,
                    "universe": self.universe.to_dict(),
                    "market_input": self.market_input.to_dict(),
                    "calculations": [item.to_dict() for item in self.calculations],
                    "factor_revision_dependencies": [item.to_dict() for item in self.factor_revision_dependencies],
                    "eligibility": self.eligibility.to_dict(),
                    "signals": self.signals.to_dict(),
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyDefinitionV1:
        _exact(
            payload,
            {
                "schema_version",
                "universe",
                "market_input",
                "calculations",
                "factor_revision_dependencies",
                "eligibility",
                "signals",
            },
            "Private Strategy Definition",
        )
        calculations = _array(payload["calculations"], "calculations")
        dependencies = _array(payload["factor_revision_dependencies"], "factor_revision_dependencies")
        signals = _mapping(payload["signals"], "signals")
        _exact(signals, {"entry", "exit"}, "Strategy signals")
        entry = signals["entry"]
        exit_ = signals["exit"]
        if not isinstance(entry, Mapping) or not isinstance(exit_, Mapping):
            raise ValueError("PRIVATE_STRATEGY_DEFINITION_SIGNALS_INVALID")
        return cls(
            _integer(payload["schema_version"]),
            OnlyStrategyUniverse.from_dict(_mapping(payload["universe"], "universe")),
            OnlyStrategyMarketInputContract.from_dict(_mapping(payload["market_input"], "market_input")),
            tuple(OnlyResearchCalculationInstance.from_dict(_mapping(item, "calculation")) for item in calculations),
            tuple(
                OnlyPrivateStrategyFactorRevisionDependencyV1.from_dict(_mapping(item, "factor dependency"))
                for item in dependencies
            ),
            only_research_expression_from_dict(_mapping(payload["eligibility"], "eligibility")),
            OnlyResearchSignals(
                only_research_expression_from_dict(cast(Mapping[str, object], entry)),
                only_research_expression_from_dict(cast(Mapping[str, object], exit_)),
            ),
        )


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyResearchContextV1:
    """Research-only inputs; it cannot override Strategy-owned semantics."""

    start: str
    end: str
    targets: tuple[OnlyResearchCalculationInstance, ...]
    statistics: tuple[OnlyResearchStatisticsRequest, ...]
    display_metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_VERSION:
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_SCHEMA_UNSUPPORTED")
        _utc_range(self.start, self.end)
        if not self.targets or any(not isinstance(item, OnlyResearchCalculationInstance) for item in self.targets):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TARGETS_INVALID")
        if any(item.type_reference.kind is not OnlyCalculationKind.TARGET for item in self.targets):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TARGETS_INVALID")
        keys = tuple(item.instance_key for item in self.targets)
        if len(keys) != len(set(keys)):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TARGET_DUPLICATE")
        if any(
            any(not isinstance(binding, OnlyResearchFixedParameter) for binding in item.parameters.values())
            for item in self.targets
        ):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_SWEEP_FORBIDDEN")
        if not self.statistics or any(not isinstance(item, OnlyResearchStatisticsRequest) for item in self.statistics):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_STATISTICS_INVALID")
        if any(item.target_instance_key not in keys for item in self.statistics):
            raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TARGET_UNKNOWN")
        object.__setattr__(self, "targets", tuple(sorted(self.targets, key=lambda item: item.instance_key)))
        object.__setattr__(self, "statistics", tuple(sorted(self.statistics, key=lambda item: str(item.to_dict()))))
        object.__setattr__(self, "display_metadata", _freeze_context_json(self.display_metadata))

    @property
    def research_context_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"contract": "ONLYALPHA_PRIVATE_STRATEGY_RESEARCH_CONTEXT_V1", **self.to_dict()}
        )

    def to_dict(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            only_canonical_payload(
                {
                    "schema_version": self.schema_version,
                    "start": self.start,
                    "end": self.end,
                    "targets": [item.to_dict() for item in self.targets],
                    "statistics": [item.to_dict() for item in self.statistics],
                    "display_metadata": _thaw_context_json(self.display_metadata),
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyResearchContextV1:
        _exact(
            payload,
            {"schema_version", "start", "end", "targets", "statistics", "display_metadata"},
            "Private Strategy Research Context",
        )
        targets = _array(payload["targets"], "targets")
        statistics = _array(payload["statistics"], "statistics")
        return cls(
            _string(payload["start"]),
            _string(payload["end"]),
            tuple(OnlyResearchCalculationInstance.from_dict(_mapping(item, "target")) for item in targets),
            tuple(OnlyResearchStatisticsRequest.from_dict(_mapping(item, "statistics")) for item in statistics),
            _mapping(payload["display_metadata"], "display_metadata"),
            _integer(payload["schema_version"]),
        )


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be an integer")
    return value


def _utc_range(start: str, end: str) -> None:
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TIME_INVALID") from exc
    if (
        first.tzinfo is None
        or last.tzinfo is None
        or first.utcoffset() != UTC.utcoffset(first)
        or last.utcoffset() != UTC.utcoffset(last)
        or first >= last
    ):
        raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_TIME_INVALID")


def _freeze_context_json(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_METADATA_INVALID")

    def freeze(item: object) -> object:
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, Mapping) and all(isinstance(key, str) for key in item):
            return MappingProxyType({key: freeze(child) for key, child in sorted(item.items())})
        if isinstance(item, (list, tuple)):
            return tuple(freeze(child) for child in item)
        raise ValueError("PRIVATE_STRATEGY_RESEARCH_CONTEXT_METADATA_INVALID")

    return MappingProxyType(cast(dict[str, object], freeze(value)))


def _thaw_context_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_context_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_context_json(item) for item in value]
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "PRIVATE_"))]
