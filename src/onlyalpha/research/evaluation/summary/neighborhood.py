"""Canonical explicit Candidate bindings for parameter-neighborhood summaries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from onlyalpha.calculation import (
    OnlyCalculationScalar,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchParameterNeighborhoodCandidateBinding:
    candidate_fingerprint: str
    assignment: Mapping[str, OnlyCalculationScalar]
    source_statistics_fingerprint: str
    source_statistics_result_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "candidate_fingerprint",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
        ):
            if _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"Neighborhood Candidate {name} must be a lower-case SHA256")
        if not isinstance(self.assignment, Mapping):
            raise ValueError("Neighborhood Candidate assignment must be a mapping")
        canonical: dict[str, OnlyCalculationScalar] = {}
        for name, value in self.assignment.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Neighborhood Candidate parameter names must be exact non-empty strings")
            canonical[name] = only_calculation_scalar_from_dict(
                only_calculation_scalar_to_dict(value), f"Neighborhood assignment {name}"
            )
        object.__setattr__(self, "assignment", MappingProxyType(dict(sorted(canonical.items()))))

    def logical_dict(self) -> dict[str, object]:
        return {
            "candidate_fingerprint": self.candidate_fingerprint,
            "assignment": {name: only_calculation_scalar_to_dict(value) for name, value in self.assignment.items()},
            "source_statistics_fingerprint": self.source_statistics_fingerprint,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.logical_dict(),
            "source_statistics_result_fingerprint": self.source_statistics_result_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchParameterNeighborhoodCandidateBinding:
        expected = {
            "candidate_fingerprint",
            "assignment",
            "source_statistics_fingerprint",
            "source_statistics_result_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("Neighborhood Candidate binding fields are invalid")
        assignment = payload["assignment"]
        if not isinstance(assignment, Mapping) or any(not isinstance(key, str) for key in assignment):
            raise ValueError("Neighborhood Candidate assignment must be an object")
        return cls(
            _string(payload, "candidate_fingerprint"),
            {
                name: only_calculation_scalar_from_dict(value, f"Neighborhood assignment {name}")
                for name, value in assignment.items()
            },
            _string(payload, "source_statistics_fingerprint"),
            _string(payload, "source_statistics_result_fingerprint"),
        )


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Neighborhood Candidate {name} must be a string")
    return value


__all__ = ["OnlyResearchParameterNeighborhoodCandidateBinding"]
