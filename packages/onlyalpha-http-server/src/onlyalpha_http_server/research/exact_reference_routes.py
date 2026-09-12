"""Read-only Product projections for exact Research Brief identities."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from onlyalpha.research.agent.model import OnlyAgentEvaluationContextReferenceV1

from .exact_reference_schema import (
    ExactDatasetSnapshotDto,
    ExactEvaluationContextDto,
    OnlyDatasetSnapshotIdentityReader,
    OnlyEvaluationContextIdentityReader,
)

EXACT_REFERENCE_ROUTE_TAG = "research-exact-reference"
ShaPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
KindPath = Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")]
VersionPath = Annotated[int, Path()]


def create_exact_reference_router(
    datasets: OnlyDatasetSnapshotIdentityReader,
    evaluations: OnlyEvaluationContextIdentityReader,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research", tags=[EXACT_REFERENCE_ROUTE_TAG])

    @router.get(
        "/datasets/{snapshot_fingerprint}",
        operation_id="get_exact_dataset_snapshot_identity_v2",
        response_model=ExactDatasetSnapshotDto,
    )
    def get_dataset(snapshot_fingerprint: ShaPath) -> ExactDatasetSnapshotDto:
        return ExactDatasetSnapshotDto.from_model(datasets.load(snapshot_fingerprint))

    @router.get(
        "/evaluations/{evaluation_kind}/{evaluation_schema_version}/{evaluation_fingerprint}",
        operation_id="get_exact_evaluation_context_identity_v2",
        response_model=ExactEvaluationContextDto,
    )
    def get_evaluation(
        evaluation_kind: KindPath,
        evaluation_schema_version: VersionPath,
        evaluation_fingerprint: ShaPath,
    ) -> ExactEvaluationContextDto:
        reference = OnlyAgentEvaluationContextReferenceV1(
            evaluation_kind,
            evaluation_schema_version,
            evaluation_fingerprint,
        )
        return ExactEvaluationContextDto.from_model(
            reference,
            evaluations.load_evaluation_contract_intrinsic_verified(evaluation_fingerprint),
        )

    return router


__all__ = ["EXACT_REFERENCE_ROUTE_TAG", "create_exact_reference_router"]
