"""Durable ordered Proposal-stream authority for one symbolic Experiment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint

SYMBOLIC_ENUMERATION_RESULT_SCHEMA_VERSION = 1


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lower-case SHA-256")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicEnumerationResultV1:
    """Exact immutable output emitted for an Experiment's deterministic budget."""

    experiment_fingerprint: str
    algorithm_implementation_fingerprint: str
    search_space_fingerprint: str
    proposal_limit: int
    ordered_proposal_fingerprints: tuple[str, ...]
    proposal_limit_reached: bool
    search_space_exhausted: bool
    schema_version: int = SYMBOLIC_ENUMERATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SYMBOLIC_ENUMERATION_RESULT_SCHEMA_VERSION:
            raise ValueError("SEARCH_ENUMERATION_RESULT_SCHEMA_UNSUPPORTED")
        _sha(self.experiment_fingerprint, "experiment_fingerprint")
        _sha(self.algorithm_implementation_fingerprint, "algorithm_implementation_fingerprint")
        _sha(self.search_space_fingerprint, "search_space_fingerprint")
        if (
            isinstance(self.proposal_limit, bool)
            or not isinstance(self.proposal_limit, int)
            or self.proposal_limit <= 0
        ):
            raise ValueError("proposal_limit must be a positive integer")
        if not isinstance(self.ordered_proposal_fingerprints, tuple):
            raise ValueError("ordered_proposal_fingerprints must be a tuple")
        for fingerprint in self.ordered_proposal_fingerprints:
            _sha(fingerprint, "ordered_proposal_fingerprint")
        if len(self.ordered_proposal_fingerprints) != len(set(self.ordered_proposal_fingerprints)):
            raise ValueError("ordered Proposal fingerprints must be unique")
        if not isinstance(self.proposal_limit_reached, bool) or not isinstance(self.search_space_exhausted, bool):
            raise ValueError("enumeration completion flags must be booleans")
        count = len(self.ordered_proposal_fingerprints)
        if count > self.proposal_limit:
            raise ValueError("ordered Proposal stream exceeds proposal_limit")
        if self.proposal_limit_reached != (count == self.proposal_limit):
            raise ValueError("proposal_limit_reached contradicts ordered Proposal count")
        if not self.proposal_limit_reached and not self.search_space_exhausted:
            raise ValueError("incomplete Enumeration Result has no exact completion state")

    @property
    def enumeration_result_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.research.symbolic-enumeration-result", **self.to_dict(include_fingerprint=False)}
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "algorithm_implementation_fingerprint": self.algorithm_implementation_fingerprint,
            "search_space_fingerprint": self.search_space_fingerprint,
            "proposal_limit": self.proposal_limit,
            "ordered_proposal_fingerprints": list(self.ordered_proposal_fingerprints),
            "proposal_limit_reached": self.proposal_limit_reached,
            "search_space_exhausted": self.search_space_exhausted,
        }
        if include_fingerprint:
            payload["enumeration_result_fingerprint"] = self.enumeration_result_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicEnumerationResultV1:
        expected = {
            "schema_version",
            "experiment_fingerprint",
            "algorithm_implementation_fingerprint",
            "search_space_fingerprint",
            "proposal_limit",
            "ordered_proposal_fingerprints",
            "proposal_limit_reached",
            "search_space_exhausted",
            "enumeration_result_fingerprint",
        }
        if set(payload) != expected:
            raise ValueError("SEARCH_ENUMERATION_RESULT_FIELDS_INVALID")
        ordered = payload["ordered_proposal_fingerprints"]
        if not isinstance(ordered, list):
            raise ValueError("ordered_proposal_fingerprints must be an array")
        value = cls(
            _sha(payload["experiment_fingerprint"], "experiment_fingerprint"),
            _sha(payload["algorithm_implementation_fingerprint"], "algorithm_implementation_fingerprint"),
            _sha(payload["search_space_fingerprint"], "search_space_fingerprint"),
            _integer(payload["proposal_limit"], "proposal_limit"),
            tuple(_sha(item, "ordered_proposal_fingerprint") for item in ordered),
            payload["proposal_limit_reached"],  # type: ignore[arg-type]
            payload["search_space_exhausted"],  # type: ignore[arg-type]
            _integer(payload["schema_version"], "schema_version"),
        )
        if payload["enumeration_result_fingerprint"] != value.enumeration_result_fingerprint:
            raise ValueError("SEARCH_ENUMERATION_RESULT_IDENTITY_DIFFERS")
        return value


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "SYMBOLIC_"))]
