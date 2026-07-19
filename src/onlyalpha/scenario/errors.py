"""Stable public errors for deterministic market scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OnlyScenarioErrorCode(StrEnum):
    SCENARIO_SCHEMA_UNSUPPORTED = "SCENARIO_SCHEMA_UNSUPPORTED"
    SCENARIO_FIELD_UNKNOWN = "SCENARIO_FIELD_UNKNOWN"
    SCENARIO_DECIMAL_INVALID = "SCENARIO_DECIMAL_INVALID"
    SCENARIO_TIMESTAMP_INVALID = "SCENARIO_TIMESTAMP_INVALID"
    SCENARIO_REFERENCE_MISSING = "SCENARIO_REFERENCE_MISSING"
    SCENARIO_ACTION_DUPLICATE = "SCENARIO_ACTION_DUPLICATE"
    SCENARIO_TRIGGER_INVALID = "SCENARIO_TRIGGER_INVALID"
    SCENARIO_EXPECTATION_INVALID = "SCENARIO_EXPECTATION_INVALID"
    SCENARIO_RUNTIME_MODE_UNSUPPORTED = "SCENARIO_RUNTIME_MODE_UNSUPPORTED"
    SCENARIO_PLAN_FAILED = "SCENARIO_PLAN_FAILED"
    SCENARIO_RUNTIME_BUILD_FAILED = "SCENARIO_RUNTIME_BUILD_FAILED"
    SCENARIO_RUNTIME_EXECUTION_FAILED = "SCENARIO_RUNTIME_EXECUTION_FAILED"
    SCENARIO_ASSERTION_FAILED = "SCENARIO_ASSERTION_FAILED"
    SCENARIO_ARTIFACT_FAILED = "SCENARIO_ARTIFACT_FAILED"


@dataclass(frozen=True, slots=True)
class OnlyScenarioValidationIssue:
    code: OnlyScenarioErrorCode
    path: str
    message: str


class OnlyScenarioError(ValueError):
    def __init__(self, code: OnlyScenarioErrorCode, message: str, *, path: str = "$") -> None:
        super().__init__(f"{code.value}: {path}: {message}")
        self.code = code
        self.path = path
        self.message = message
