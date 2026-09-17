"""Thin HTTP transport for the read-only Product near-duplicate advisory query."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from onlyalpha.application.product_boundary import OnlyResearchProductBoundary
from onlyalpha.application.research_advisory import (
    OnlyGetResearchNearDuplicateAdvisoryV1,
    OnlyResearchAdvisoryRequestInvalid,
    OnlyResearchNearDuplicateAdvisoryBundleV2,
)
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .schema import ResearchErrorDto, Sha256Dto


class _AdvisoryDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ResearchNearDuplicateAdvisoryRequestDto(_AdvisoryDto):
    specification: dict[str, JsonValue]
    runtime_work_id: str = Field(min_length=1)
    projection_revision: Sha256Dto | None = None
    limit: int = Field(default=10, ge=1, le=100)
    authoring_generation_fingerprint: Sha256Dto | None = None


class ResearchNearDuplicateAdvisoryEntryDto(_AdvisoryDto):
    subject_fingerprint: Sha256Dto
    representation_fingerprint: Sha256Dto
    result: dict[str, JsonValue]


class ResearchNearDuplicateAdvisoryResponseDto(_AdvisoryDto):
    schema_version: Literal[2] = 2
    specification_fingerprint: Sha256Dto
    projection_revision: Sha256Dto
    source_cut_fingerprint: Sha256Dto
    index_build_revision: Sha256Dto
    requested_result_limit: int
    retrieval_algorithm_id: str
    retrieval_algorithm_version: str
    threshold_policy: dict[str, JsonValue]
    entries: tuple[ResearchNearDuplicateAdvisoryEntryDto, ...]
    bundle_fingerprint: Sha256Dto

    @classmethod
    def from_bundle(cls, value: OnlyResearchNearDuplicateAdvisoryBundleV2) -> ResearchNearDuplicateAdvisoryResponseDto:
        payload = value.to_dict()
        payload["entries"] = tuple(cast(list[dict[str, JsonValue]], payload["entries"]))
        return cls.model_validate(cast(object, payload))


RESEARCH_ADVISORY_ROUTE_TAG = "research-advisory"
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": ResearchErrorDto} for status in (400, 404, 500, 503)
}


def _operation() -> dict[str, object]:
    return {
        "x-onlyalpha-agent-operation": {
            "schema_version": 1,
            "tool_class": "RESEARCH_NEAR_DUPLICATE_QUERY",
            "recovery_class": "MUTABLE_OBSERVATION_QUERY",
            "requires_product_command_id": False,
            "product_command_id_transport": None,
            "identity_requirements": [],
            "owning_authority_references": [],
        }
    }


def create_advisory_router(product: OnlyResearchProductBoundary) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/advisory", tags=[RESEARCH_ADVISORY_ROUTE_TAG])

    @router.post(
        "/near-duplicates",
        operation_id="get_research_near_duplicate_advisory_v1",
        response_model=ResearchNearDuplicateAdvisoryResponseDto,
        responses=_ERROR_RESPONSES,
        openapi_extra=_operation(),
    )
    def near_duplicates(
        request: ResearchNearDuplicateAdvisoryRequestDto,
    ) -> ResearchNearDuplicateAdvisoryResponseDto:
        try:
            query = OnlyGetResearchNearDuplicateAdvisoryV1(
                specification=OnlyResearchSpecification.from_dict(request.specification),
                runtime_work_id=request.runtime_work_id,
                projection_revision=request.projection_revision,
                limit=request.limit,
                authoring_generation_fingerprint=request.authoring_generation_fingerprint,
            )
        except (TypeError, ValueError) as exc:
            raise OnlyResearchAdvisoryRequestInvalid("HTTP request contains an invalid Research Specification") from exc
        result = product.queries.dispatch(query)
        if not isinstance(result, OnlyResearchNearDuplicateAdvisoryBundleV2):
            raise TypeError("Product dispatcher returned the wrong advisory response")
        return ResearchNearDuplicateAdvisoryResponseDto.from_bundle(result)

    return router


__all__ = [
    "RESEARCH_ADVISORY_ROUTE_TAG",
    "ResearchNearDuplicateAdvisoryEntryDto",
    "ResearchNearDuplicateAdvisoryRequestDto",
    "ResearchNearDuplicateAdvisoryResponseDto",
    "create_advisory_router",
]
