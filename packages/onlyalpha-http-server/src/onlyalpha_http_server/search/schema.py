"""Strict Search Product transport DTOs and application-facing port."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

_SHA = r"^[0-9a-f]{64}$"


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SymbolicSearchSubmitRequestDto(_Dto):
    schema_version: Literal[2]
    hypothesis: dict[str, JsonValue]
    search_space: dict[str, JsonValue]
    evaluation_contract: dict[str, JsonValue]
    search_budget: dict[str, JsonValue]
    algorithm_manifest: dict[str, JsonValue]
    workflow_binding: dict[str, JsonValue]
    decision_engine_binding: dict[str, JsonValue]
    catalog_generation_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "CATALOG_GENERATION",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    dataset_snapshot_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "DATASET_SNAPSHOT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    runtime_generation_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "RUNTIME_GENERATION",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    parent_experiment_fingerprint: str | None = Field(default=None, pattern=_SHA)


class ParameterSearchSubmitRequestDto(SymbolicSearchSubmitRequestDto):
    search_policy: dict[str, JsonValue]


class SearchAdvanceRequestDto(_Dto):
    schema_version: Literal[1]
    method: Literal["SYMBOLIC", "PARAMETER"]
    operation: Literal[
        "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
        "RECONCILE_ONE_SYMBOLIC_OCCURRENCE",
        "ADVANCE_ONE_PARAMETER_DECISION",
        "RECONCILE_OPEN_PARAMETER_BATCH",
    ]
    experiment_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    expected_state: dict[str, JsonValue]


class SearchCommandResponseDto(_Dto):
    schema_version: Literal[1] = 1
    product_command_id: str
    experiment_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    method: Literal["SYMBOLIC", "PARAMETER"]
    receipt: dict[str, JsonValue]
    ledger: dict[str, JsonValue]
    terminal: dict[str, JsonValue]
    replayed: bool


class SearchExperimentResponseDto(_Dto):
    schema_version: Literal[1] = 1
    experiment_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    method: Literal["SYMBOLIC", "PARAMETER"]
    experiment: dict[str, JsonValue]


class SearchLedgerResponseDto(_Dto):
    schema_version: Literal[1] = 1
    experiment_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    method: Literal["SYMBOLIC", "PARAMETER"]
    ledger: dict[str, JsonValue]


class SearchTerminalResponseDto(_Dto):
    schema_version: Literal[1] = 1
    experiment_fingerprint: str = Field(
        pattern=_SHA,
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    )
    method: Literal["SYMBOLIC", "PARAMETER"]
    terminal_kind: Literal["NON_TERMINAL", "TERMINAL_SYMBOLIC_COMPLETION", "TERMINAL_PARAMETER_STOP"]
    terminal_fact: dict[str, JsonValue] | None
    stop_reason: str | None


class SearchErrorDto(_Dto):
    code: str
    detail: str


class SearchErrorEnvelopeDto(_Dto):
    error: SearchErrorDto


class OnlySearchProductHttpBoundary(Protocol):
    def submit_symbolic(
        self, product_command_id: str, request: SymbolicSearchSubmitRequestDto
    ) -> SearchCommandResponseDto: ...

    def submit_parameter(
        self, product_command_id: str, request: ParameterSearchSubmitRequestDto
    ) -> SearchCommandResponseDto: ...

    def advance_symbolic(
        self, product_command_id: str, request: SearchAdvanceRequestDto
    ) -> SearchCommandResponseDto: ...

    def advance_parameter(
        self, product_command_id: str, request: SearchAdvanceRequestDto
    ) -> SearchCommandResponseDto: ...

    def get_experiment(self, experiment_fingerprint: str) -> SearchExperimentResponseDto: ...

    def get_ledger(self, experiment_fingerprint: str) -> SearchLedgerResponseDto: ...

    def get_terminal(self, experiment_fingerprint: str) -> SearchTerminalResponseDto: ...


__all__ = [name for name in globals() if name.startswith(("Only", "Search", "Symbolic", "Parameter"))]
