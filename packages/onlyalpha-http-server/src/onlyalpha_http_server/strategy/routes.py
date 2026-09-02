"""HTTP adapter for Strategy Product commands and queries."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.strategy_product import (
    OnlyStrategyFreezeProductService,
    OnlyStrategyPromotionProductService,
    OnlyStrategyQueryService,
)
from onlyalpha.research.run import OnlyResearchRunId
from onlyalpha.strategy.freeze import OnlyStrategyFreezeRequest

from .schema import (
    StrategyDto,
    StrategyFreezeRequest,
    StrategyFreezeResponse,
    StrategyPromotionRequest,
    StrategyPromotionResponse,
)

STRATEGY_ROUTE_TAG = "strategies"
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key")]
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {status: {} for status in (400, 404, 409, 500, 503)}


def _command_id(value: str) -> OnlyProductCommandId:
    try:
        return OnlyProductCommandId(value)
    except ValueError as exc:
        raise ValueError("Idempotency-Key must be a canonical UUID4") from exc


def create_strategy_router(
    freeze: OnlyStrategyFreezeProductService,
    promotion: OnlyStrategyPromotionProductService,
    query: OnlyStrategyQueryService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2", tags=[STRATEGY_ROUTE_TAG])

    @router.post(
        "/strategy-freezes", status_code=202, response_model=StrategyFreezeResponse, responses=_ERROR_RESPONSES
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

    @router.get("/strategies/{strategy_fingerprint}", response_model=StrategyDto, responses=_ERROR_RESPONSES)
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
        "/strategies/{strategy_fingerprint}/promotions",
        status_code=202,
        response_model=StrategyPromotionResponse,
        responses=_ERROR_RESPONSES,
    )
    def promote_strategy(
        strategy_fingerprint: str,
        request: StrategyPromotionRequest,
        idempotency_key: IdempotencyKeyHeader,
    ) -> StrategyPromotionResponse:
        record, replayed = promotion.promote_to_backtest(
            command_id=_command_id(idempotency_key),
            strategy_fingerprint=strategy_fingerprint,
            freeze_relation_fingerprint=request.freeze_relation_fingerprint,
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
