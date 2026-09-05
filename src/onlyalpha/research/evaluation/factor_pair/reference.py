"""Exact Candidate and Factor-series operand binding."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ..reference import OnlyResearchFeatureSeriesReference

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchFactorPairOperand:
    candidate_fingerprint: str
    series: OnlyResearchFeatureSeriesReference

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.candidate_fingerprint) is None:
            raise ValueError("Factor-Pair Candidate fingerprint must be lower-case SHA256")
        if not isinstance(self.series, OnlyResearchFeatureSeriesReference):
            raise ValueError("Factor-Pair series reference is invalid")

    @property
    def canonical_key(self) -> tuple[str, str, str, str]:
        return (
            self.candidate_fingerprint,
            self.series.calculation_fingerprint,
            self.series.node_fingerprint,
            self.series.output_name,
        )

    def to_dict(self) -> dict[str, object]:
        return {"candidate_fingerprint": self.candidate_fingerprint, "series": self.series.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchFactorPairOperand:
        if set(payload) != {"candidate_fingerprint", "series"}:
            raise ValueError("Factor-Pair Operand fields are invalid")
        candidate = payload["candidate_fingerprint"]
        series = payload["series"]
        if not isinstance(candidate, str):
            raise ValueError("Factor-Pair Candidate fingerprint must be a string")
        if not isinstance(series, Mapping) or any(not isinstance(key, str) for key in series):
            raise ValueError("Factor-Pair series must be an object")
        return cls(candidate, OnlyResearchFeatureSeriesReference.from_dict(series))
