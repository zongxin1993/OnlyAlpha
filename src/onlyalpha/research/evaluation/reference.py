"""Exact immutable upstream series references."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyResearchFeatureSeriesReference:
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        _validate(self.calculation_fingerprint, self.node_fingerprint, self.output_name)

    def to_dict(self) -> dict[str, object]:
        return _to_dict(self.calculation_fingerprint, self.node_fingerprint, self.output_name)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchFeatureSeriesReference:
        return cls(*_from_dict(payload, "Feature Series Reference"))


@dataclass(frozen=True, slots=True)
class OnlyResearchTargetSeriesReference:
    calculation_fingerprint: str
    node_fingerprint: str
    output_name: str

    def __post_init__(self) -> None:
        _validate(self.calculation_fingerprint, self.node_fingerprint, self.output_name)

    def to_dict(self) -> dict[str, object]:
        return _to_dict(self.calculation_fingerprint, self.node_fingerprint, self.output_name)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchTargetSeriesReference:
        return cls(*_from_dict(payload, "Target Series Reference"))


def _validate(calculation: str, node: str, output_name: str) -> None:
    if _SHA256.fullmatch(calculation) is None or _SHA256.fullmatch(node) is None:
        raise ValueError("Series Reference fingerprints must be lower-case SHA256")
    if not output_name or any(char.isspace() for char in output_name):
        raise ValueError("Series Reference output_name is invalid")


def _to_dict(calculation: str, node: str, output_name: str) -> dict[str, object]:
    return {
        "calculation_fingerprint": calculation,
        "node_fingerprint": node,
        "output_name": output_name,
    }


def _from_dict(payload: Mapping[str, object], context: str) -> tuple[str, str, str]:
    if set(payload) != {"calculation_fingerprint", "node_fingerprint", "output_name"}:
        raise ValueError(f"{context} fields are invalid")
    values = tuple(payload[name] for name in ("calculation_fingerprint", "node_fingerprint", "output_name"))
    if any(not isinstance(value, str) for value in values):
        raise ValueError(f"{context} fields must be strings")
    return values  # type: ignore[return-value]
