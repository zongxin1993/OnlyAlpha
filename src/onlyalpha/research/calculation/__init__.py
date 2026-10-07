"""Public deterministic Research Calculation execution contracts."""
# ruff: noqa: F401

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

from .backend import (
    OnlyResearchCalculationBackend,
    OnlyResearchCalculationBackendExecutionV2,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchReadinessCalculationBackend,
    OnlyResolvedResearchCalculationBackend,
    OnlyResolvedResearchReadinessCalculationBackend,
)
from .binding import (
    OnlyResearchDatasetSourceContractV1,
    only_bind_research_dataset_source,
    only_research_dataset_source_contract,
    only_research_dataset_source_contracts,
    only_research_dataset_source_output,
)
from .errors import OnlyResearchCalculationError, OnlyResearchCalculationResultStoreError
from .execution import (
    OnlyResearchCalculationExecution,
    OnlyResearchCalculationExecutionPlan,
    OnlyResearchCalculationExecutionPlanBinding,
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationImplementationBinding,
    OnlyResearchCalculationNodeOutput,
)
from .execution_evidence import (
    OnlyResearchCalculationExecutionEvidence,
    OnlyResearchCalculationExecutionEvidenceStore,
)
from .identity import only_research_calculation_fingerprint
from .predicate import (
    PREDICATE_SEMANTIC_VERSION,
    PREDICATE_VALUE_SEMANTIC_TYPE,
    only_predicate_type_reference,
    only_register_research_predicate_primitives,
)
from .publication import (
    RESEARCH_CALCULATION_PUBLICATION_CONTRACT_SCHEMA_VERSION,
    OnlyResearchCalculationPublicationContract,
    OnlyResearchCalculationPublicationSelectionV1,
)
from .readiness import (
    RESEARCH_CALCULATION_READINESS_CONTRACT_VERSION,
    OnlyResearchOutputReadiness,
    OnlyResearchReadinessReason,
    OnlyResearchReadinessState,
    only_validate_research_output_readiness,
)
from .result import (
    OnlyResearchCalculationResult,
    OnlyResearchCalculationResultManifest,
    OnlyResearchCalculationResultPartitionManifest,
    OnlyResearchCalculationResultVerification,
)
from .result_identity import (
    only_research_calculation_partition_fingerprint,
    only_research_calculation_result_content_fingerprint,
    only_research_calculation_result_fingerprint,
)
from .result_ports import OnlyResearchCalculationResultStore
from .result_store import OnlyParquetResearchCalculationResultStore

if _TYPE_CHECKING:
    from .execution_evidence_v2 import (
        OnlyResearchCalculationExecutionEvidenceStoreV2,
        OnlyResearchCalculationExecutionEvidenceV2,
    )
    from .result_v2 import (
        OnlyResearchCalculationResultManifestV2,
        OnlyResearchCalculationResultV2,
        OnlyResearchCalculationResultVerificationV2,
    )
    from .result_v2_identity import (
        RESEARCH_CALCULATION_RESULT_V2_SCHEMA_VERSION,
        only_research_calculation_readiness_partition_fingerprint,
        only_research_calculation_result_content_fingerprint_v2,
        only_research_calculation_result_fingerprint_v2,
        only_research_calculation_value_projection_fingerprint,
    )
    from .result_v2_ports import OnlyResearchCalculationResultStoreV2
    from .result_v2_store import OnlyParquetResearchCalculationResultStoreV2

_V2_EXPORTS = {
    "OnlyResearchCalculationExecutionEvidenceV2": "execution_evidence_v2",
    "OnlyResearchCalculationExecutionEvidenceStoreV2": "execution_evidence_v2",
    "OnlyResearchCalculationResultManifestV2": "result_v2",
    "OnlyResearchCalculationResultV2": "result_v2",
    "OnlyResearchCalculationResultVerificationV2": "result_v2",
    "OnlyResearchCalculationResultStoreV2": "result_v2_ports",
    "OnlyParquetResearchCalculationResultStoreV2": "result_v2_store",
    "RESEARCH_CALCULATION_RESULT_V2_SCHEMA_VERSION": "result_v2_identity",
    "only_research_calculation_readiness_partition_fingerprint": "result_v2_identity",
    "only_research_calculation_value_projection_fingerprint": "result_v2_identity",
    "only_research_calculation_result_content_fingerprint_v2": "result_v2_identity",
    "only_research_calculation_result_fingerprint_v2": "result_v2_identity",
}

__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")] + list(_V2_EXPORTS)


def __getattr__(name: str) -> object:
    if name not in _V2_EXPORTS:
        raise AttributeError(name)
    value = getattr(_import_module(f"{__name__}.{_V2_EXPORTS[name]}"), name)
    globals()[name] = value
    return value
