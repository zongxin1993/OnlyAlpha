from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
from onlyalpha_test_plugin.research_calculation import EXTERNAL_IDENTITY

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.calculation import OnlyCalculationKind, OnlyCalculationTypeReference
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import OnlyResearchCalculationInput, OnlyResearchCalculationInstance
from onlyalpha.research.evaluation import OnlyExactEvaluationIntentResolverV1
from onlyalpha.research.memory.projector import OnlyExperimentMemoryProjectionV1
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.novelty import (
    OnlyNoveltyDecisionAuthority,
    OnlyNoveltyDecisionRequestV2,
    OnlyNoveltyPolicyStore,
)
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.research.specification import OnlyResearchSpecification, OnlyResearchSpecificationResolver
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.research.definition.support import definition
from tests.research.novelty.test_policy import policy


def external_definition(dataset_definition):  # type: ignore[no-untyped-def]
    """Use the external Indicator in the ordinary research product surface."""

    base = definition(dataset_definition)
    external = OnlyResearchCalculationInstance(
        "rsi",
        OnlyCalculationTypeReference(
            OnlyCalculationKind.INDICATOR,
            EXTERNAL_IDENTITY.type_id,
            EXTERNAL_IDENTITY.semantic_version,
        ),
        {},
        ("value",),
        (OnlyResearchCalculationInput("value", "bar.close"),),
    )
    return replace(
        base,
        calculations=tuple(external if item.instance_key == "rsi" else item for item in base.calculations),
    )


class _ResolutionEvidenceReader:
    def __init__(self, evidence: OnlyResearchAdmissionResolutionEvidence) -> None:
        self.evidence = evidence

    def resolve(self, _generation: str, _specification: OnlyResearchSpecification) -> object:
        return self.evidence


def _closed_manifest() -> OnlyExperimentMemorySourceCutManifestV1:
    postgres = {
        "RESEARCH_RUN",
        "RESEARCH_ATTEMPT",
        "PRODUCT_COMMAND_ADMISSION",
        "PRODUCT_COMMAND_RECEIPT",
    }
    return OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        [
            OnlySourceClosedCutV1(
                family,
                1,
                (),
                "JOURNAL_INDEX:0" if family in postgres else "CERTIFICATION_CLOSED_CUT_V1",
                "SOURCE_TRANSACTIONAL_JOURNAL_V1" if family in postgres else "CERTIFICATION_COMPLETE_V1",
            )
            for family in MANDATORY_FAMILIES
        ]
    )


def authorize_research_specification(
    user_data_root: Path,
    runtime_generation_root: Path,
    command_id: str,
    specification_payload: object,
) -> None:
    """Test-only canonical preauthorization; production admission still exact-loads the sealed group."""
    if not isinstance(specification_payload, dict):
        raise TypeError("exact Specification payload is required")
    specification = OnlyResearchSpecification.from_dict(specification_payload)
    runtime = OnlyRuntimeGenerationRegistry(runtime_generation_root)
    temporary_work = f"certification-preauthorization-{command_id}"
    runtime.bind_new_work(
        temporary_work,
        actor="certification-preauthorization",
        occurred_at=datetime(2026, 9, 16, tzinfo=UTC),
    )
    try:
        resolution = OnlyResearchSpecificationResolver(
            only_default_engine_services(fail_fast=True).assembler.components.calculations
        ).resolve(specification)
        evidence = OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution)
        subjects = OnlyExactEvaluationIntentResolverV1(
            runtime_generations=runtime,
            runtime_resolution=_ResolutionEvidenceReader(evidence),
        ).resolve_all(specification, runtime_work_id=temporary_work)
    finally:
        runtime.release_work(
            temporary_work,
            actor="certification-preauthorization",
            occurred_at=datetime(2026, 9, 16, 0, 0, 1, tzinfo=UTC),
        )
    layout = OnlyUserDataLayout(user_data_root)
    revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
    projection = OnlyExperimentMemoryProjectionV1(_closed_manifest(), ())
    revisions._publish_and_activate(projection)
    policies = OnlyNoveltyPolicyStore(layout.research_root)
    policies.put(policy())
    product_command_id = OnlyProductCommandId(command_id)
    OnlyNoveltyDecisionAuthority(layout.research_root).seal_group_from_requests(
        tuple(
            OnlyNoveltyDecisionRequestV2(product_command_id, "default-novelty", "1", subject) for subject in subjects
        ),
        projection.revision_fingerprint,
        revisions,
        policies,
    )


__all__ = ["authorize_research_specification", "external_definition"]
