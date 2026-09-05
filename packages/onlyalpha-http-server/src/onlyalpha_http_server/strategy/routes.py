"""HTTP adapter for Strategy Product commands and queries."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.qualification_product import (
    OnlyQualificationProductService,
    OnlyQualificationQueryService,
)
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeProductService,
    OnlyStrategyPromotionProductService,
    OnlyStrategyQueryService,
)
from onlyalpha.research.run import OnlyResearchRunId
from onlyalpha.strategy.errors import OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest
from onlyalpha.strategy.qualification import (
    OnlyQualificationEvidenceKind,
    OnlyQualificationEvidenceReference,
)

from ..backtest.schema import PRODUCT_ERROR_RESPONSES
from .schema import (
    QualificationDecisionListResponse,
    QualificationDecisionResponse,
    QualificationEvaluationRequest,
    QualificationPolicyListResponse,
    QualificationPolicyResponse,
    QualifiedStrategyPromotionRequest,
    StrategyDto,
    StrategyFreezeRequest,
    StrategyFreezeResponse,
    StrategyPromotionRequest,
    StrategyPromotionResponse,
)

STRATEGY_ROUTE_TAG = "strategies"
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key")]


def _command_id(value: str) -> OnlyProductCommandId:
    try:
        return OnlyProductCommandId(value)
    except ValueError as exc:
        raise ValueError("Idempotency-Key must be a canonical UUID4") from exc


def create_strategy_router(
    freeze: OnlyStrategyFreezeProductService,
    promotion: OnlyStrategyPromotionProductService,
    query: OnlyStrategyQueryService,
    qualification: OnlyQualificationProductService,
    qualification_query: OnlyQualificationQueryService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2", tags=[STRATEGY_ROUTE_TAG])

    @router.post(
        "/strategy-freezes", status_code=202, response_model=StrategyFreezeResponse, responses=PRODUCT_ERROR_RESPONSES
    )
    def freeze_strategy(
        request: StrategyFreezeRequest, idempotency_key: IdempotencyKeyHeader
    ) -> StrategyFreezeResponse:
        result = freeze.execute(
            _command_id(idempotency_key),
            OnlyStrategyFreezeRequest(
                research_run_id=OnlyResearchRunId(request.research_run_id),
                candidate_fingerprint=request.candidate_fingerprint,
                actor=request.actor,
                comment=request.comment,
            ),
        )
        return StrategyFreezeResponse(
            strategy_fingerprint=result.freeze.strategy_fingerprint,
            disposition=result.freeze.disposition.value,
            freeze_record_fingerprint=result.freeze.freeze_record.record_fingerprint,
            replayed=result.replayed,
        )

    @router.get("/strategies/{strategy_fingerprint}", response_model=StrategyDto, responses=PRODUCT_ERROR_RESPONSES)
    def get_strategy(strategy_fingerprint: str) -> StrategyDto:
        value = query.get(strategy_fingerprint)
        revision = value.revision
        return StrategyDto(
            strategy_fingerprint=str(revision.strategy_fingerprint),
            revision=revision.to_dict(),
            freeze_relation_fingerprints=value.freeze_relation_fingerprints,
            current_stage=value.current_stage.value,
            promotion_records=tuple(item.to_dict() for item in value.promotion_records),
        )

    @router.post(
        "/strategies/{strategy_fingerprint}/qualifications",
        status_code=202,
        response_model=QualificationDecisionResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def evaluate_qualification(
        strategy_fingerprint: str,
        request: QualificationEvaluationRequest,
        idempotency_key: IdempotencyKeyHeader,
    ) -> QualificationDecisionResponse:
        outcome = qualification.evaluate(
            command_id=_command_id(idempotency_key),
            subject_strategy_fingerprint=strategy_fingerprint,
            policy_id=request.policy_id,
            policy_version=request.policy_version,
            evidence=tuple(
                OnlyQualificationEvidenceReference(
                    OnlyQualificationEvidenceKind(item.kind),
                    item.evidence_fingerprint,
                    item.locator_fingerprint,
                    item.subject_binding_fingerprint,
                )
                for item in request.evidence
            ),
        )
        return QualificationDecisionResponse(
            decision=outcome.decision.to_dict(),
            replayed=outcome.replayed,
        )

    @router.get(
        "/qualification-policies",
        response_model=QualificationPolicyListResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def list_qualification_policies() -> QualificationPolicyListResponse:
        return QualificationPolicyListResponse(
            policies=tuple(item.to_dict() for item in qualification_query.policies())
        )

    @router.get(
        "/qualification-policies/{policy_id}/revisions/{policy_version}",
        response_model=QualificationPolicyResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def get_qualification_policy(policy_id: str, policy_version: str) -> QualificationPolicyResponse:
        return QualificationPolicyResponse(policy=qualification_query.policy(policy_id, policy_version).to_dict())

    @router.get(
        "/qualification-decisions/{decision_fingerprint}",
        response_model=QualificationDecisionResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def get_qualification_decision(decision_fingerprint: str) -> QualificationDecisionResponse:
        return QualificationDecisionResponse(decision=qualification_query.decision(decision_fingerprint).to_dict())

    @router.get(
        "/strategies/{strategy_fingerprint}/qualification-decisions",
        response_model=QualificationDecisionListResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def list_qualification_decisions(strategy_fingerprint: str) -> QualificationDecisionListResponse:
        return QualificationDecisionListResponse(
            decisions=tuple(item.to_dict() for item in qualification_query.decisions_for_subject(strategy_fingerprint))
        )

    @router.post(
        "/strategies/{strategy_fingerprint}/promotions",
        status_code=202,
        response_model=StrategyPromotionResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def promote_strategy(
        strategy_fingerprint: str,
        request: StrategyPromotionRequest,
        idempotency_key: IdempotencyKeyHeader,
    ) -> StrategyPromotionResponse:
        del strategy_fingerprint, request, idempotency_key
        raise OnlyStrategyPromotionError(
            "QUALIFICATION_DECISION_NOT_APPROVED",
            "legacy Freeze-only Promotion is forbidden; use the qualification-backed command",
        )

    @router.post(
        "/strategies/{strategy_fingerprint}/qualification-promotions",
        status_code=202,
        response_model=StrategyPromotionResponse,
        responses=PRODUCT_ERROR_RESPONSES,
    )
    def promote_qualified_strategy(
        strategy_fingerprint: str,
        request: QualifiedStrategyPromotionRequest,
        idempotency_key: IdempotencyKeyHeader,
    ) -> StrategyPromotionResponse:
        promote = promotion.promote_to_backtest if request.to_stage == "BACKTEST" else promotion.promote_to_sim
        record, replayed = promote(
            command_id=_command_id(idempotency_key),
            strategy_fingerprint=strategy_fingerprint,
            qualification_decision_fingerprint=request.qualification_decision_fingerprint,
            policy_fingerprint=request.policy_fingerprint,
            reason=request.reason,
            actor=request.actor,
        )
        return StrategyPromotionResponse(
            strategy_fingerprint=record.strategy_fingerprint,
            promotion_record_fingerprint=record.record_fingerprint,
            from_stage=record.from_stage.value,
            to_stage=record.to_stage.value,
            decision=record.decision.value,
            replayed=replayed,
        )

    return router


__all__ = ["STRATEGY_ROUTE_TAG", "create_strategy_router"]
