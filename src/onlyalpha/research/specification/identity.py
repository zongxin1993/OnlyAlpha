"""Canonical identities owned by the Research Specification boundary."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.calculation import OnlyCalculationScalar
from onlyalpha.canonical import only_canonical_fingerprint


def only_research_candidate_fingerprint(
    specification_fingerprint: str,
    candidate_calculation_id: str,
    assignment: Mapping[str, OnlyCalculationScalar],
    calculation_fingerprint: str,
) -> str:
    """Identify one exact candidate in one exact Research product request."""

    return only_canonical_fingerprint(
        {
            "schema_version": 1,
            "specification_fingerprint": specification_fingerprint,
            "candidate_calculation_id": candidate_calculation_id,
            "assignment": dict(sorted(assignment.items())),
            "calculation_fingerprint": calculation_fingerprint,
        }
    )


__all__ = ["only_research_candidate_fingerprint"]
