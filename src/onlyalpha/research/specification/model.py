"""Strict, portable and canonical Research Specification V1 document."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_payload
from onlyalpha.research.dataset.strict import require_sha256
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsDefinition
from onlyalpha.research.sweep.definition import OnlyResearchSweepParameterDimension
from onlyalpha.research.sweep.errors import OnlyResearchSweepError
from onlyalpha.research.sweep.template import OnlyResearchGraphTemplate

from .errors import OnlyResearchSpecificationError, OnlyResearchSpecificationPhase

RESEARCH_SPECIFICATION_SCHEMA_VERSION = 1


class OnlyResearchStatisticsExpansion(StrEnum):
    BROADCAST_SINGLETON = "BROADCAST_SINGLETON"


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise ValueError(f"{context} must be non-empty without whitespace")
    return value


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - set(payload))}, "
            f"unknown={sorted(set(payload) - expected)}"
        )


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchSeriesSelector:
    calculation_id: str
    template_node_id: str
    output_name: str

    def __post_init__(self) -> None:
        _identifier(self.calculation_id, "selector calculation_id")
        _identifier(self.template_node_id, "selector template_node_id")
        _identifier(self.output_name, "selector output_name")

    def to_dict(self) -> Mapping[str, object]:
        return cast(
            Mapping[str, object],
            only_canonical_payload(
                {
                    "calculation_id": self.calculation_id,
                    "template_node_id": self.template_node_id,
                    "output_name": self.output_name,
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSeriesSelector:
        _exact(payload, {"calculation_id", "template_node_id", "output_name"}, "series selector")
        return cls(payload["calculation_id"], payload["template_node_id"], payload["output_name"])  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationSpec:
    calculation_id: str
    graph_template: OnlyResearchGraphTemplate
    sweep_dimensions: tuple[OnlyResearchSweepParameterDimension, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.calculation_id, "calculation_id")
        if not isinstance(self.graph_template, OnlyResearchGraphTemplate):
            raise ValueError("calculation graph_template is invalid")
        if not isinstance(self.sweep_dimensions, tuple) or any(
            not isinstance(item, OnlyResearchSweepParameterDimension) for item in self.sweep_dimensions
        ):
            raise ValueError("calculation sweep_dimensions are invalid")
        targets = tuple(item.target for item in self.sweep_dimensions)
        if len(targets) != len(set(targets)):
            raise ValueError("calculation contains duplicate Sweep parameter target")
        object.__setattr__(self, "sweep_dimensions", tuple(sorted(self.sweep_dimensions, key=lambda item: item.target)))

    def to_dict(self) -> Mapping[str, object]:
        return cast(
            Mapping[str, object],
            only_canonical_payload(
                {
                    "calculation_id": self.calculation_id,
                    "graph_template": self.graph_template.to_dict(),
                    "sweep_dimensions": [item.to_dict() for item in self.sweep_dimensions],
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationSpec:
        _exact(payload, {"calculation_id", "graph_template", "sweep_dimensions"}, "calculation spec")
        dimensions = payload["sweep_dimensions"]
        if not isinstance(dimensions, list):
            raise ValueError("calculation sweep_dimensions must be an array")
        return cls(
            payload["calculation_id"],  # type: ignore[arg-type]
            OnlyResearchGraphTemplate.from_dict(_mapping(payload["graph_template"], "graph_template")),
            tuple(
                OnlyResearchSweepParameterDimension.from_dict(_mapping(item, "sweep dimension")) for item in dimensions
            ),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchStatisticsSpec:
    feature: OnlyResearchSeriesSelector
    target: OnlyResearchSeriesSelector
    definition: OnlyResearchStatisticsDefinition
    expansion: OnlyResearchStatisticsExpansion = OnlyResearchStatisticsExpansion.BROADCAST_SINGLETON

    def __post_init__(self) -> None:
        if not isinstance(self.feature, OnlyResearchSeriesSelector) or not isinstance(
            self.target, OnlyResearchSeriesSelector
        ):
            raise ValueError("Statistics selectors are invalid")
        if not isinstance(self.definition, OnlyResearchStatisticsDefinition):
            raise ValueError("Statistics definition is invalid")
        if self.expansion is not OnlyResearchStatisticsExpansion.BROADCAST_SINGLETON:
            raise ValueError("Specification V1 requires BROADCAST_SINGLETON")

    def to_dict(self) -> Mapping[str, object]:
        return cast(
            Mapping[str, object],
            only_canonical_payload(
                {
                    "feature": self.feature.to_dict(),
                    "target": self.target.to_dict(),
                    "definition": self.definition.to_dict(),
                    "expansion": self.expansion.value,
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchStatisticsSpec:
        _exact(payload, {"feature", "target", "definition", "expansion"}, "statistics spec")
        expansion = payload["expansion"]
        if not isinstance(expansion, str):
            raise ValueError("statistics expansion must be a string")
        return cls(
            OnlyResearchSeriesSelector.from_dict(_mapping(payload["feature"], "feature selector")),
            OnlyResearchSeriesSelector.from_dict(_mapping(payload["target"], "target selector")),
            OnlyResearchStatisticsDefinition.from_dict(_mapping(payload["definition"], "statistics definition")),
            OnlyResearchStatisticsExpansion(expansion),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSpecification:
    dataset_snapshot_fingerprint: str
    calculations: tuple[OnlyResearchCalculationSpec, ...]
    statistics: tuple[OnlyResearchStatisticsSpec, ...]
    schema_version: int = RESEARCH_SPECIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            if isinstance(self.schema_version, bool) or self.schema_version != RESEARCH_SPECIFICATION_SCHEMA_VERSION:
                raise ValueError(f"unsupported Research Specification schema version: {self.schema_version!r}")
            require_sha256(
                {"dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint},
                "dataset_snapshot_fingerprint",
                "Research Specification",
            )
            if not self.calculations or any(
                not isinstance(item, OnlyResearchCalculationSpec) for item in self.calculations
            ):
                raise ValueError("Specification requires Calculation Specs")
            if not self.statistics or any(not isinstance(item, OnlyResearchStatisticsSpec) for item in self.statistics):
                raise ValueError("Specification requires Statistics Specs")
            ids = tuple(item.calculation_id for item in self.calculations)
            if len(ids) != len(set(ids)):
                raise OnlyResearchSpecificationError(
                    OnlyResearchSpecificationPhase.SCHEMA,
                    "RESEARCH_SPEC_DUPLICATE_CALCULATION_ID",
                    "calculation_id must be unique within the Specification",
                )
            object.__setattr__(
                self, "calculations", tuple(sorted(self.calculations, key=lambda item: item.calculation_id))
            )
            object.__setattr__(
                self,
                "statistics",
                tuple(sorted(self.statistics, key=lambda item: str(dict(item.to_dict())))),
            )
        except OnlyResearchSpecificationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            code = (
                "RESEARCH_SPEC_SCHEMA_VERSION_UNSUPPORTED"
                if "schema version" in str(exc)
                else "RESEARCH_SPEC_DATASET_INVALID"
                if "fingerprint" in str(exc)
                else "RESEARCH_SPEC_INVALID"
            )
            raise OnlyResearchSpecificationError(OnlyResearchSpecificationPhase.SCHEMA, code, str(exc)) from exc

    @property
    def specification_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> Mapping[str, object]:
        return cast(
            Mapping[str, object],
            only_canonical_payload(
                {
                    "schema_version": self.schema_version,
                    "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
                    "calculations": [item.to_dict() for item in self.calculations],
                    "statistics": [item.to_dict() for item in self.statistics],
                }
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSpecification:
        try:
            _exact(
                payload,
                {"schema_version", "dataset_snapshot_fingerprint", "calculations", "statistics"},
                "Research Specification",
            )
            version, dataset = payload["schema_version"], payload["dataset_snapshot_fingerprint"]
            calculations, statistics = payload["calculations"], payload["statistics"]
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or not isinstance(dataset, str)
                or not isinstance(calculations, list)
                or not isinstance(statistics, list)
            ):
                raise ValueError("Research Specification fields are invalid")
            return cls(
                dataset,
                tuple(
                    OnlyResearchCalculationSpec.from_dict(_mapping(item, "calculation spec")) for item in calculations
                ),
                tuple(OnlyResearchStatisticsSpec.from_dict(_mapping(item, "statistics spec")) for item in statistics),
                version,
            )
        except OnlyResearchSpecificationError:
            raise
        except (KeyError, TypeError, ValueError, OnlyResearchSweepError) as exc:
            raise OnlyResearchSpecificationError(
                OnlyResearchSpecificationPhase.SCHEMA, "RESEARCH_SPEC_INVALID", str(exc)
            ) from exc
