"""Typed scalar and invalidity contract for Research summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .metric import OnlyResearchSummaryValueKind, only_research_summary_metric


class OnlyResearchSummaryScalarStatus(StrEnum):
    VALID = "VALID"
    NO_VALID_OBSERVATIONS = "NO_VALID_OBSERVATIONS"
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    ZERO_VARIANCE = "ZERO_VARIANCE"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class OnlyResearchSummaryScalar:
    metric_id: str
    value_kind: OnlyResearchSummaryValueKind
    status: OnlyResearchSummaryScalarStatus
    integer_value: int | None = None
    decimal_value: Decimal | None = None

    def __post_init__(self) -> None:
        descriptor = only_research_summary_metric(self.metric_id)
        if descriptor.value_kind is not self.value_kind:
            raise ValueError("Summary scalar metric value kind mismatch")
        if not isinstance(self.status, OnlyResearchSummaryScalarStatus):
            raise ValueError("Summary scalar status is invalid")
        if self.integer_value is not None and (
            isinstance(self.integer_value, bool) or not isinstance(self.integer_value, int)
        ):
            raise ValueError("Summary scalar integer value is invalid")
        if self.decimal_value is not None and (
            not isinstance(self.decimal_value, Decimal) or not self.decimal_value.is_finite()
        ):
            raise ValueError("Summary scalar decimal value must be finite")
        if self.status is not OnlyResearchSummaryScalarStatus.VALID:
            if self.integer_value is not None or self.decimal_value is not None:
                raise ValueError("non-VALID Summary scalar requires absent numeric values")
            return
        if self.value_kind is OnlyResearchSummaryValueKind.INTEGER:
            if self.integer_value is None or self.decimal_value is not None:
                raise ValueError("VALID INTEGER Summary scalar requires integer value only")
            if self.integer_value < 0:
                raise ValueError("Summary count scalar must be non-negative")
        else:
            if self.decimal_value is None or self.integer_value is not None:
                raise ValueError("VALID DECIMAL Summary scalar requires decimal value only")
            if self.decimal_value.as_tuple().exponent != -12:
                raise ValueError("Summary decimal scalar must use canonical quantum 1e-12")
            if self.decimal_value.is_zero() and self.decimal_value.is_signed():
                raise ValueError("Summary decimal zero must use the canonical positive representation")

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "value_kind": self.value_kind.value,
            "status": self.status.value,
            "integer_value": self.integer_value,
            "decimal_value": None if self.decimal_value is None else format(self.decimal_value, "f"),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchSummaryScalar:
        if set(payload) != {"metric_id", "value_kind", "status", "integer_value", "decimal_value"}:
            raise ValueError("Summary scalar fields are invalid")
        metric_id = _string(payload, "metric_id")
        integer = payload["integer_value"]
        if integer is not None and (isinstance(integer, bool) or not isinstance(integer, int)):
            raise ValueError("Summary scalar integer_value is invalid")
        raw_decimal = payload["decimal_value"]
        if raw_decimal is not None and not isinstance(raw_decimal, str):
            raise ValueError("Summary scalar decimal_value is invalid")
        return cls(
            metric_id,
            OnlyResearchSummaryValueKind(_string(payload, "value_kind")),
            OnlyResearchSummaryScalarStatus(_string(payload, "status")),
            integer,
            None if raw_decimal is None else Decimal(raw_decimal),
        )


def _string(payload: Mapping[str, object], name: str) -> str:
    value = payload[name]
    if not isinstance(value, str):
        raise ValueError(f"Summary scalar {name} must be a string")
    return value


__all__ = ["OnlyResearchSummaryScalar", "OnlyResearchSummaryScalarStatus"]
