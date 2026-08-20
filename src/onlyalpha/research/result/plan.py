"""Canonical Research Result composition plan V1/V2."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.calculation import OnlyCalculationScalar
from onlyalpha.canonical import only_canonical_payload

from .identity import (
    RESEARCH_RESULT_PLAN_SCHEMA_VERSION,
    RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION,
    only_research_result_plan_fingerprint,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchResultCalculationPlan:
    calculation_fingerprint: str
    graph_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.calculation_fingerprint, "Calculation identity")
        _sha(self.graph_fingerprint, "Graph identity")

    def to_dict(self) -> dict[str, str]:
        return {"calculation_fingerprint": self.calculation_fingerprint, "graph_fingerprint": self.graph_fingerprint}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchResultCalculationPlan:
        _exact(payload, {"calculation_fingerprint", "graph_fingerprint"}, "Calculation Plan")
        return cls(
            _sha(payload["calculation_fingerprint"], "Calculation identity"),
            _sha(payload["graph_fingerprint"], "Graph identity"),
        )


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchResultCandidatePlan:
    candidate_fingerprint: str
    candidate_calculation_id: str
    assignment: tuple[tuple[str, OnlyCalculationScalar], ...]
    calculation_fingerprint: str
    graph_fingerprint: str
    statistics_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha(self.candidate_fingerprint, "Candidate identity")
        if not isinstance(self.candidate_calculation_id, str) or not self.candidate_calculation_id:
            raise ValueError("candidate_calculation_id is invalid")
        if self.assignment != tuple(sorted(self.assignment)) or len(dict(self.assignment)) != len(self.assignment):
            raise ValueError("Candidate assignment is not canonical")
        _sha(self.calculation_fingerprint, "Calculation identity")
        _sha(self.graph_fingerprint, "Graph identity")
        _canonical_sha_tuple(self.statistics_fingerprints, "Candidate Statistics identities")
        object.__setattr__(self, "statistics_fingerprints", tuple(sorted(self.statistics_fingerprints)))

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "candidate_calculation_id": self.candidate_calculation_id,
            "assignment": only_canonical_payload(dict(self.assignment)),
            "calculation_fingerprint": self.calculation_fingerprint,
            "graph_fingerprint": self.graph_fingerprint,
            "statistics_fingerprints": list(self.statistics_fingerprints),
        }


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchResultSeriesPlan:
    candidate_fingerprint: str | None
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        if self.candidate_fingerprint is not None:
            _sha(self.candidate_fingerprint, "Candidate identity")
        _sha(self.calculation_fingerprint, "Calculation identity")
        _sha(self.node_fingerprint, "Node identity")
        if not isinstance(self.output_name, str) or not self.output_name:
            raise ValueError("output_name is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "calculation_fingerprint": self.calculation_fingerprint,
            "node_fingerprint": self.node_fingerprint,
            "output_name": self.output_name,
        }


@dataclass(frozen=True, slots=True, order=True)
class OnlyResearchResultSignalPlan:
    role: str
    candidate_fingerprint: str
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        if self.role not in {"ELIGIBILITY", "ENTRY_SIGNAL", "EXIT_SIGNAL"}:
            raise ValueError("Signal role is invalid")
        _sha(self.candidate_fingerprint, "Candidate identity")
        _sha(self.calculation_fingerprint, "Calculation identity")
        _sha(self.node_fingerprint, "Node identity")
        if not isinstance(self.output_name, str) or not self.output_name:
            raise ValueError("output_name is invalid")

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "candidate_fingerprint": self.candidate_fingerprint,
            "calculation_fingerprint": self.calculation_fingerprint,
            "node_fingerprint": self.node_fingerprint,
            "output_name": self.output_name,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchResultPlan:
    statistics_fingerprints: tuple[str, ...]
    schema_version: int = RESEARCH_RESULT_PLAN_SCHEMA_VERSION
    dataset_snapshot_fingerprint: str | None = None
    calculations: tuple[OnlyResearchResultCalculationPlan, ...] = ()
    candidates: tuple[OnlyResearchResultCandidatePlan, ...] = ()
    published_series: tuple[OnlyResearchResultSeriesPlan, ...] = ()
    signals: tuple[OnlyResearchResultSignalPlan, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version not in {
            RESEARCH_RESULT_PLAN_SCHEMA_VERSION,
            RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION,
        }:
            raise ValueError(f"unsupported Research Result Plan schema version: {self.schema_version}")
        _canonical_sha_tuple(self.statistics_fingerprints, "Research Result Plan Statistics identities", nonempty=True)
        object.__setattr__(self, "statistics_fingerprints", tuple(sorted(self.statistics_fingerprints)))
        if self.schema_version == RESEARCH_RESULT_PLAN_SCHEMA_VERSION:
            if any(
                (
                    self.dataset_snapshot_fingerprint is not None,
                    self.calculations,
                    self.candidates,
                    self.published_series,
                    self.signals,
                )
            ):
                raise ValueError("Research Result Plan V1 cannot contain scientific composition")
            return
        _sha(self.dataset_snapshot_fingerprint, "Dataset Snapshot identity")
        for name, values, expected in (
            ("calculations", self.calculations, OnlyResearchResultCalculationPlan),
            ("candidates", self.candidates, OnlyResearchResultCandidatePlan),
            ("published_series", self.published_series, OnlyResearchResultSeriesPlan),
            ("signals", self.signals, OnlyResearchResultSignalPlan),
        ):
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise ValueError(f"Research Result Plan {name} are invalid")
            canonical = (
                tuple(
                    sorted(
                        values,
                        key=lambda item: (
                            item.candidate_fingerprint or "",
                            item.calculation_fingerprint,
                            item.node_fingerprint,
                            item.output_name,
                        ),
                    )
                )
                if name == "published_series"
                else tuple(sorted(values))
            )
            if values != canonical or len(values) != len(set(values)):
                raise ValueError(f"Research Result Plan {name} are not canonical and unique")
        calculation_identity_keys = tuple(item.calculation_fingerprint for item in self.calculations)
        if len(calculation_identity_keys) != len(set(calculation_identity_keys)):
            raise ValueError("Scientific Result Plan Calculation identities are not unique")
        candidate_identity_keys = tuple(item.candidate_fingerprint for item in self.candidates)
        if len(candidate_identity_keys) != len(set(candidate_identity_keys)):
            raise ValueError("Scientific Result Plan Candidate identities are not unique")
        calculation_ids = {item.calculation_fingerprint for item in self.calculations}
        if not calculation_ids:
            raise ValueError("Scientific Result Plan requires Calculation members")
        if (
            any(item.calculation_fingerprint not in calculation_ids for item in self.candidates)
            or any(item.calculation_fingerprint not in calculation_ids for item in self.published_series)
            or any(item.calculation_fingerprint not in calculation_ids for item in self.signals)
        ):
            raise ValueError("Scientific Result Plan references an unknown Calculation member")
        candidate_ids = {item.candidate_fingerprint for item in self.candidates}
        if any(item.candidate_fingerprint not in candidate_ids for item in (*self.signals,)) or any(
            item.candidate_fingerprint is not None and item.candidate_fingerprint not in candidate_ids
            for item in self.published_series
        ):
            raise ValueError("Scientific Result Plan references an unknown Candidate member")
        if {value for item in self.candidates for value in item.statistics_fingerprints} - set(
            self.statistics_fingerprints
        ):
            raise ValueError("Candidate references an unknown Statistics member")
        signal_keys = tuple((item.candidate_fingerprint, item.role) for item in self.signals)
        if len(signal_keys) != len(set(signal_keys)):
            raise ValueError("Scientific Result Plan Candidate and role identify more than one Signal series")

    @property
    def fingerprint(self) -> str:
        return only_research_result_plan_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "statistics_fingerprints": list(self.statistics_fingerprints),
        }
        if self.schema_version == RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION:
            payload.update(
                dataset_snapshot_fingerprint=self.dataset_snapshot_fingerprint,
                calculations=[item.to_dict() for item in self.calculations],
                candidates=[item.to_dict() for item in self.candidates],
                published_series=[item.to_dict() for item in self.published_series],
                signals=[item.to_dict() for item in self.signals],
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchResultPlan:
        version = payload.get("schema_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Research Result Plan schema_version must be an integer")
        if version == RESEARCH_RESULT_PLAN_SCHEMA_VERSION:
            _exact(payload, {"schema_version", "statistics_fingerprints"}, "Research Result Plan")
            return cls(_sha_array(payload["statistics_fingerprints"], "Statistics identities"), version)
        if version != RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION:
            raise ValueError(f"unsupported Research Result Plan schema version: {version}")
        expected = {
            "schema_version",
            "dataset_snapshot_fingerprint",
            "calculations",
            "candidates",
            "published_series",
            "signals",
            "statistics_fingerprints",
        }
        _exact(payload, expected, "Research Result Plan")
        return cls(
            _sha_array(payload["statistics_fingerprints"], "Statistics identities"),
            version,
            _sha(payload["dataset_snapshot_fingerprint"], "Dataset Snapshot identity"),
            tuple(
                OnlyResearchResultCalculationPlan.from_dict(_mapping(item)) for item in _array(payload["calculations"])
            ),
            tuple(_candidate_from_dict(_mapping(item)) for item in _array(payload["candidates"])),
            tuple(_series_from_dict(_mapping(item)) for item in _array(payload["published_series"])),
            tuple(_signal_from_dict(_mapping(item)) for item in _array(payload["signals"])),
        )


def _candidate_from_dict(payload: Mapping[str, object]) -> OnlyResearchResultCandidatePlan:
    _exact(
        payload,
        {
            "candidate_fingerprint",
            "candidate_calculation_id",
            "assignment",
            "calculation_fingerprint",
            "graph_fingerprint",
            "statistics_fingerprints",
        },
        "Candidate Plan",
    )
    assignment = cast(Mapping[str, OnlyCalculationScalar], _mapping(payload["assignment"]))
    return OnlyResearchResultCandidatePlan(
        _sha(payload["candidate_fingerprint"], "Candidate identity"),
        _string(payload["candidate_calculation_id"]),
        tuple(sorted(assignment.items())),
        _sha(payload["calculation_fingerprint"], "Calculation identity"),
        _sha(payload["graph_fingerprint"], "Graph identity"),
        _sha_array(payload["statistics_fingerprints"], "Statistics identities"),
    )


def _series_from_dict(payload: Mapping[str, object]) -> OnlyResearchResultSeriesPlan:
    _exact(
        payload, {"candidate_fingerprint", "calculation_fingerprint", "node_fingerprint", "output_name"}, "Series Plan"
    )
    candidate = payload["candidate_fingerprint"]
    return OnlyResearchResultSeriesPlan(
        None if candidate is None else _sha(candidate, "Candidate identity"),
        _sha(payload["calculation_fingerprint"], "Calculation identity"),
        _sha(payload["node_fingerprint"], "Node identity"),
        _string(payload["output_name"]),
    )


def _signal_from_dict(payload: Mapping[str, object]) -> OnlyResearchResultSignalPlan:
    _exact(
        payload,
        {"role", "candidate_fingerprint", "calculation_fingerprint", "node_fingerprint", "output_name"},
        "Signal Plan",
    )
    return OnlyResearchResultSignalPlan(
        _string(payload["role"]),
        _sha(payload["candidate_fingerprint"], "Candidate identity"),
        _sha(payload["calculation_fingerprint"], "Calculation identity"),
        _sha(payload["node_fingerprint"], "Node identity"),
        _string(payload["output_name"]),
    )


def _canonical_sha_tuple(values: tuple[str, ...], name: str, *, nonempty: bool = False) -> None:
    if nonempty and not values:
        raise ValueError("Research Result Plan requires at least one Statistics identity")
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in values
    ):
        raise ValueError(f"{name} must be {'a non-empty ' if nonempty else ''}tuple of lower-case SHA256")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} contain duplicate identity")


def _exact(payload: Mapping[str, object], expected: set[str], context: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{context} fields are invalid")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("value must be an object")
    return value


def _array(value: object, name: str = "value") -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _sha_array(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array of strings")
    values = value
    if any(not isinstance(item, str) for item in values):
        raise ValueError(f"{name} must be an array of strings")
    return tuple(cast(list[str], values))


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("value must be a non-empty string")
    return value
