"""Chart-only native publication DTOs; parsing/comparison never grants execution authority.

This is deliberately not an extension of the compute-only Search/E1 protocol.
No host advertises or dispatches this contract until its owning-reader composition
and fenced Run/Attempt consumer are implemented and verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1
from onlyalpha.research.dataset.strict import (
    require_exact_fields,
    require_int,
    require_mapping,
    require_sha256,
    require_str,
)
from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.run.model import OnlyResearchRunId

ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION = "ONLYALPHA_CHART_NATIVE_PUBLICATION_V1"
_CONTEXT = "Chart native publication protocol"


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationNativePublicationProfileV1:
    """Exact version family, not a readiness claim or positive Claim permission."""

    publication: OnlyResearchCalculationPublicationSelectionV1 = OnlyResearchCalculationPublicationSelectionV1()
    origin_kind: str = "CHART_CALCULATION"
    specification_schema_version: int = 3
    job_plan_schema_version: int = 2
    result_plan_schema_version: int = 4
    research_result_schema_version: int = 4
    artifact_schema_version: int = 2
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.origin_kind) is not str or self.origin_kind != "CHART_CALCULATION":
            raise ValueError("Chart native publication requires its exact origin")
        if type(self.publication) is not OnlyResearchCalculationPublicationSelectionV1:
            raise ValueError("Chart native publication selection is invalid")
        self.publication.__post_init__()
        for name, expected in (
            ("schema_version", 1),
            ("specification_schema_version", 3),
            ("job_plan_schema_version", 2),
            ("result_plan_schema_version", 4),
            ("research_result_schema_version", 4),
            ("artifact_schema_version", 2),
        ):
            value = getattr(self, name)
            if type(value) is not int or value != expected:
                raise ValueError(f"unsupported Chart native publication {name}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "origin_kind": self.origin_kind,
            "specification_schema_version": self.specification_schema_version,
            "job_plan_schema_version": self.job_plan_schema_version,
            "result_plan_schema_version": self.result_plan_schema_version,
            "research_result_schema_version": self.research_result_schema_version,
            "artifact_schema_version": self.artifact_schema_version,
            "publication": self.publication.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyChartCalculationNativePublicationProfileV1:
        raw = require_mapping(raw, _CONTEXT)
        require_exact_fields(raw, set(cls.__dataclass_fields__), _CONTEXT)
        return cls(
            publication=OnlyResearchCalculationPublicationSelectionV1.from_dict(
                require_mapping(raw["publication"], _CONTEXT)
            ),
            origin_kind=require_str(raw, "origin_kind", _CONTEXT),
            specification_schema_version=require_int(raw, "specification_schema_version", _CONTEXT),
            job_plan_schema_version=require_int(raw, "job_plan_schema_version", _CONTEXT),
            result_plan_schema_version=require_int(raw, "result_plan_schema_version", _CONTEXT),
            research_result_schema_version=require_int(raw, "research_result_schema_version", _CONTEXT),
            artifact_schema_version=require_int(raw, "artifact_schema_version", _CONTEXT),
            schema_version=require_int(raw, "schema_version", _CONTEXT),
        )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationNativeExecutionRequestV1:
    """Bounded locators to re-read, never caller Graph/rows, credentials or issued objects."""

    operation_id: OnlyProductCommandId
    run_id: OnlyResearchRunId
    attempt_id: OnlyResearchRunAttemptId
    worker_instance_id: OnlyResearchWorkerInstanceId
    attempt_number: int
    run_revision: int
    compilation_fingerprint: str
    runtime_generation_fingerprint: str
    profile: OnlyChartCalculationNativePublicationProfileV1 = OnlyChartCalculationNativePublicationProfileV1()
    execution_contract_version: str = ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name, expected in (
            ("operation_id", OnlyProductCommandId),
            ("run_id", OnlyResearchRunId),
            ("attempt_id", OnlyResearchRunAttemptId),
            ("worker_instance_id", OnlyResearchWorkerInstanceId),
        ):
            value = getattr(self, name)
            if type(value) is not expected:
                raise ValueError(f"Chart native publication {name} is invalid")
            value.__post_init__()
        if self.operation_id.value == self.run_id.value:
            raise ValueError("Chart Operation cannot replace its reserved Run")
        for name in ("attempt_number", "run_revision"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"Chart native publication {name} must be positive")
        for name in ("compilation_fingerprint", "runtime_generation_fingerprint"):
            require_sha256({name: getattr(self, name)}, name, _CONTEXT)
        if type(self.profile) is not OnlyChartCalculationNativePublicationProfileV1:
            raise ValueError("Chart native publication profile is invalid")
        self.profile.__post_init__()
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.execution_contract_version) is not str
            or self.execution_contract_version != ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION
        ):
            raise ValueError("unsupported Chart native publication protocol")

    def verify_compilation(self, frozen: OnlyChartCalculationCompilationV1) -> None:
        """Structural equality ONLY; caller must obtain frozen from its owning reader."""
        self.__post_init__()
        if type(frozen) is not OnlyChartCalculationCompilationV1:
            raise ValueError("Chart native publication compilation is invalid")
        frozen.__post_init__()
        if (
            self.operation_id != frozen.operation_id
            or self.run_id.value != frozen.runtime_work_id
            or self.compilation_fingerprint != frozen.compilation_fingerprint
            or self.runtime_generation_fingerprint != frozen.runtime_generation_fingerprint
            or self.profile.publication != frozen.specification.publication
        ):
            raise ValueError("Chart native publication frozen relation differs")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "operation_id": self.operation_id.value,
            "run_id": self.run_id.value,
            "attempt_id": self.attempt_id.value,
            "worker_instance_id": self.worker_instance_id.value,
            "attempt_number": self.attempt_number,
            "run_revision": self.run_revision,
            "compilation_fingerprint": self.compilation_fingerprint,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "profile": self.profile.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyChartCalculationNativeExecutionRequestV1:
        raw = require_mapping(raw, _CONTEXT)
        require_exact_fields(raw, set(cls.__dataclass_fields__), _CONTEXT)
        return cls(
            operation_id=OnlyProductCommandId(require_str(raw, "operation_id", _CONTEXT)),
            run_id=OnlyResearchRunId(require_str(raw, "run_id", _CONTEXT)),
            attempt_id=OnlyResearchRunAttemptId(require_str(raw, "attempt_id", _CONTEXT)),
            worker_instance_id=OnlyResearchWorkerInstanceId(require_str(raw, "worker_instance_id", _CONTEXT)),
            attempt_number=require_int(raw, "attempt_number", _CONTEXT),
            run_revision=require_int(raw, "run_revision", _CONTEXT),
            compilation_fingerprint=require_sha256(raw, "compilation_fingerprint", _CONTEXT),
            runtime_generation_fingerprint=require_sha256(raw, "runtime_generation_fingerprint", _CONTEXT),
            profile=OnlyChartCalculationNativePublicationProfileV1.from_dict(require_mapping(raw["profile"], _CONTEXT)),
            execution_contract_version=require_str(raw, "execution_contract_version", _CONTEXT),
            schema_version=require_int(raw, "schema_version", _CONTEXT),
        )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationNativeWorkerHandshakeV1:
    """Expected Chart host declaration. A parsed declaration is not verified readiness."""

    runtime_provenance: OnlyResearchRuntimeExecutionProvenanceV1
    profile: OnlyChartCalculationNativePublicationProfileV1 = OnlyChartCalculationNativePublicationProfileV1()
    execution_contract_version: str = ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.runtime_provenance) is not OnlyResearchRuntimeExecutionProvenanceV1:
            raise ValueError("Chart native publication Runtime provenance is invalid")
        self.runtime_provenance.__post_init__()
        if type(self.profile) is not OnlyChartCalculationNativePublicationProfileV1:
            raise ValueError("Chart native publication profile is invalid")
        self.profile.__post_init__()
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or type(self.execution_contract_version) is not str
            or self.execution_contract_version != ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION
        ):
            raise ValueError("unsupported Chart native publication protocol")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "execution_contract_version": self.execution_contract_version,
            "runtime_provenance": self.runtime_provenance.to_dict(),
            "profile": self.profile.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyChartCalculationNativeWorkerHandshakeV1:
        raw = require_mapping(raw, _CONTEXT)
        require_exact_fields(raw, set(cls.__dataclass_fields__), _CONTEXT)
        return cls(
            runtime_provenance=OnlyResearchRuntimeExecutionProvenanceV1.from_dict(
                require_mapping(raw["runtime_provenance"], _CONTEXT)
            ),
            profile=OnlyChartCalculationNativePublicationProfileV1.from_dict(require_mapping(raw["profile"], _CONTEXT)),
            execution_contract_version=require_str(raw, "execution_contract_version", _CONTEXT),
            schema_version=require_int(raw, "schema_version", _CONTEXT),
        )
