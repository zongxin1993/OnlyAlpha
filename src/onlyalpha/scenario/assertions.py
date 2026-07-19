"""Read-only comparisons over standard result fact mappings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from onlyalpha.scenario.models import OnlyScenarioAssertionOperator, OnlyScenarioExpectation, OnlyScenarioFactType


class OnlyScenarioAssertionStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class OnlyScenarioAssertionResult:
    assertion_id: str
    status: OnlyScenarioAssertionStatus
    message: str
    actual: object = None


@dataclass(frozen=True, slots=True)
class OnlyScenarioAssertionSummary:
    results: tuple[OnlyScenarioAssertionResult, ...]

    @property
    def passed(self) -> bool:
        return all(item.status is OnlyScenarioAssertionStatus.PASSED for item in self.results)


class OnlyScenarioAssertionEngine:
    def evaluate(
        self,
        expectations: Sequence[OnlyScenarioExpectation],
        facts: Mapping[OnlyScenarioFactType, Sequence[Mapping[str, object]]],
    ) -> OnlyScenarioAssertionSummary:
        return OnlyScenarioAssertionSummary(
            tuple(self._evaluate(item, facts.get(item.fact, ())) for item in expectations)
        )

    def _evaluate(
        self, expectation: OnlyScenarioExpectation, records: Sequence[Mapping[str, object]]
    ) -> OnlyScenarioAssertionResult:
        selected = tuple(item for item in records if self._matches(item, expectation.selector))
        operator = expectation.operator
        if operator is OnlyScenarioAssertionOperator.COUNT_EQUALS:
            return self._result(expectation, len(selected), len(selected) == int(str(expectation.expected)))
        if operator is OnlyScenarioAssertionOperator.EXISTS:
            return self._result(expectation, bool(selected), bool(selected))
        if operator is OnlyScenarioAssertionOperator.NOT_EXISTS:
            return self._result(expectation, bool(selected), not selected)
        if not selected:
            return OnlyScenarioAssertionResult(
                expectation.assertion_id, OnlyScenarioAssertionStatus.FAILED, "selector matched no facts"
            )
        try:
            actual: object = selected[0] if expectation.field is None else selected[0][expectation.field]
            passed = self._compare(operator, actual, expectation.expected, expectation.tolerance)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return OnlyScenarioAssertionResult(expectation.assertion_id, OnlyScenarioAssertionStatus.ERROR, str(exc))
        return self._result(expectation, actual, passed)

    @staticmethod
    def _matches(record: Mapping[str, object], selector: Mapping[str, object]) -> bool:
        return all(str(record.get(key)) == str(value) for key, value in selector.items())

    @staticmethod
    def _compare(
        operator: OnlyScenarioAssertionOperator, actual: object, expected: object, tolerance: Decimal | None
    ) -> bool:
        if operator is OnlyScenarioAssertionOperator.EQUALS:
            return actual == expected or str(actual) == str(expected)
        if operator is OnlyScenarioAssertionOperator.NOT_EQUALS:
            return actual != expected and str(actual) != str(expected)
        if operator is OnlyScenarioAssertionOperator.CONTAINS:
            return expected in actual  # type: ignore[operator]
        if operator is OnlyScenarioAssertionOperator.SEQUENCE_EQUALS:
            if not isinstance(actual, Sequence) or isinstance(actual, str):
                raise TypeError("actual value is not a sequence")
            if not isinstance(expected, Sequence) or isinstance(expected, str):
                raise TypeError("expected value is not a sequence")
            return tuple(actual) == tuple(expected)
        if operator in {OnlyScenarioAssertionOperator.DECIMAL_EQUALS, OnlyScenarioAssertionOperator.DECIMAL_APPROX}:
            difference = abs(Decimal(str(actual)) - Decimal(str(expected)))
            return difference == 0 if tolerance is None else difference <= tolerance
        left, right = Decimal(str(actual)), Decimal(str(expected))
        return {
            OnlyScenarioAssertionOperator.GREATER_THAN: left > right,
            OnlyScenarioAssertionOperator.GREATER_THAN_OR_EQUAL: left >= right,
            OnlyScenarioAssertionOperator.LESS_THAN: left < right,
            OnlyScenarioAssertionOperator.LESS_THAN_OR_EQUAL: left <= right,
        }[operator]

    @staticmethod
    def _result(expectation: OnlyScenarioExpectation, actual: object, passed: bool) -> OnlyScenarioAssertionResult:
        status = OnlyScenarioAssertionStatus.PASSED if passed else OnlyScenarioAssertionStatus.FAILED
        message = "matched" if passed else f"expected {expectation.expected!r}, got {actual!r}"
        return OnlyScenarioAssertionResult(expectation.assertion_id, status, message, actual)
