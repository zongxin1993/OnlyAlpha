"""Durable Product commands and stable query projection over Strategy authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)
from onlyalpha.strategy.errors import OnlyStrategyFreezeError, OnlyStrategyPromotionError
from onlyalpha.strategy.freeze import (
    OnlyStrategyFreezeOutcome,
    OnlyStrategyFreezeRequest,
)
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
)
from onlyalpha.strategy.revision import OnlyStrategyRevision
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .strategy_authority import OnlyStrategyFreezeApplicationService


class OnlyStrategyFreezeAdmissionState(StrEnum):
    PREPARED = "PREPARED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeCommandAdmission:
    command_id: OnlyProductCommandId
    command_fingerprint: str
    request: OnlyStrategyFreezeRequest
    state: OnlyStrategyFreezeAdmissionState
    prepared_at: datetime
    strategy_fingerprint: str | None = None
    freeze_relation_fingerprint: str | None = None
    completed_at: datetime | None = None


class OnlyStrategyProductStore(Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def prepare_freeze_admission(
        self,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        request: OnlyStrategyFreezeRequest,
        prepared_at: datetime,
    ) -> OnlyStrategyFreezeCommandAdmission: ...

    def load_freeze_admission(self, command_id: OnlyProductCommandId) -> OnlyStrategyFreezeCommandAdmission: ...

    def complete_freeze_admission(
        self,
        admission: OnlyStrategyFreezeCommandAdmission,
        outcome: OnlyStrategyFreezeOutcome,
        completed_at: datetime,
    ) -> OnlyProductCommandReceipt: ...

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]: ...

    def append_promotion_with_receipt(
        self,
        record: OnlyStrategyPromotionRecord,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
    ) -> OnlyProductCommandReceipt: ...

    def load_promotion(self, record_fingerprint: str) -> OnlyStrategyPromotionRecord: ...


@dataclass(frozen=True, slots=True)
class OnlyStrategyFreezeProductOutcome:
    freeze: OnlyStrategyFreezeOutcome
    replayed: bool


@dataclass(frozen=True, slots=True)
class OnlyStrategyProductView:
    revision: OnlyStrategyRevision
    freeze_relation_fingerprints: tuple[str, ...]
    current_stage: OnlyStrategyPromotionStage
    promotion_records: tuple[OnlyStrategyPromotionRecord, ...]


class OnlyStrategyFreezeProductService:
    def __init__(
        self,
        *,
        freeze: OnlyStrategyFreezeApplicationService,
        strategies: OnlyFrozenStrategyRevisionStore,
        store: OnlyStrategyProductStore,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._freeze = freeze
        self._strategies = strategies
        self._store = store
        self._now_utc = now_utc

    def execute(
        self,
        command_id: OnlyProductCommandId,
        request: OnlyStrategyFreezeRequest,
    ) -> OnlyStrategyFreezeProductOutcome:
        fingerprint = only_product_command_fingerprint(
            {
                "research_run_id": request.research_run_id.value,
                "candidate_fingerprint": request.candidate_fingerprint,
                "actor": request.actor,
                "comment": request.comment,
            }
        )
        receipt = self._store.find_product_command_receipt(command_id)
        if receipt is not None:
            return self._replay(receipt, fingerprint)
        admission = self._store.prepare_freeze_admission(command_id, fingerprint, request, self._now_utc())
        if admission.command_fingerprint != fingerprint or admission.request != request:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", command_id.value)
        outcome = self._freeze.freeze(request)
        receipt = self._store.complete_freeze_admission(admission, outcome, self._now_utc())
        if receipt.outcome_ref.outcome_id != outcome.strategy_fingerprint:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", command_id.value)
        return OnlyStrategyFreezeProductOutcome(outcome, admission.state is OnlyStrategyFreezeAdmissionState.COMPLETED)

    def _replay(self, receipt: OnlyProductCommandReceipt, fingerprint: str) -> OnlyStrategyFreezeProductOutcome:
        if (
            receipt.command_kind is not OnlyProductCommandKind.FREEZE_STRATEGY
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.STRATEGY
            or receipt.command_fingerprint != fingerprint
        ):
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_CONFLICT", receipt.command_id.value)
        strategy_fingerprint = receipt.outcome_ref.outcome_id
        self._strategies.load_verified(strategy_fingerprint)
        admission = self._store.load_freeze_admission(receipt.command_id)
        if (
            admission.state is not OnlyStrategyFreezeAdmissionState.COMPLETED
            or admission.strategy_fingerprint != strategy_fingerprint
            or admission.command_fingerprint != fingerprint
        ):
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", receipt.command_id.value)
        outcome = self._freeze.freeze(admission.request)
        if outcome.freeze_record.record_fingerprint != admission.freeze_relation_fingerprint:
            raise OnlyStrategyFreezeError("PRODUCT_COMMAND_RECEIPT_CORRUPT", receipt.command_id.value)
        return OnlyStrategyFreezeProductOutcome(outcome, True)


class _ReceiptPromotionLedger:
    def __init__(
        self,
        store: OnlyStrategyProductStore,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
    ) -> None:
        self._store = store
        self._command_id = command_id
        self._command_fingerprint = command_fingerprint

    def records(self, strategy_fingerprint: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
        return self._store.records(strategy_fingerprint)

    def append(self, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
        receipt = self._store.append_promotion_with_receipt(
            record,
            self._command_id,
            self._command_fingerprint,
        )
        if receipt.outcome_ref.outcome_id == record.record_fingerprint:
            return record
        return self._store.load_promotion(receipt.outcome_ref.outcome_id)


class OnlyStrategyPromotionProductService:
    def __init__(
        self,
        *,
        strategies: OnlyFrozenStrategyRevisionStore,
        store: OnlyStrategyProductStore,
        audit_time: Callable[[], datetime],
    ) -> None:
        self._strategies = strategies
        self._store = store
        self._audit_time = audit_time

    def promote_to_backtest(
        self,
        *,
        command_id: OnlyProductCommandId,
        strategy_fingerprint: str,
        freeze_relation_fingerprint: str,
        reason: str,
        actor: str,
    ) -> tuple[OnlyStrategyPromotionRecord, bool]:
        fingerprint = only_product_command_fingerprint(
            {
                "strategy_fingerprint": strategy_fingerprint,
                "to_stage": OnlyStrategyPromotionStage.BACKTEST.value,
                "freeze_relation_fingerprint": freeze_relation_fingerprint,
                "decision": OnlyStrategyPromotionDecision.APPROVED.value,
                "reason": reason,
                "actor": actor,
            }
        )
        receipt = self._store.find_product_command_receipt(command_id)
        if receipt is not None:
            if (
                receipt.command_kind is not OnlyProductCommandKind.PROMOTE_STRATEGY
                or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.STRATEGY_PROMOTION
                or receipt.command_fingerprint != fingerprint
            ):
                raise OnlyStrategyPromotionError("PRODUCT_COMMAND_CONFLICT", command_id.value)
            return self._store.load_promotion(receipt.outcome_ref.outcome_id), True
        relations = self._strategies.freeze_relations(strategy_fingerprint)
        if freeze_relation_fingerprint not in {item.relation_fingerprint for item in relations}:
            raise OnlyStrategyPromotionError("STRATEGY_FREEZE_EVIDENCE_INVALID", freeze_relation_fingerprint)
        ledger = _ReceiptPromotionLedger(self._store, command_id, fingerprint)
        record = OnlyStrategyPromotionService(self._strategies, ledger, self._audit_time).record(
            strategy_fingerprint=strategy_fingerprint,
            to_stage=OnlyStrategyPromotionStage.BACKTEST,
            evidence_fingerprints=(freeze_relation_fingerprint,),
            decision=OnlyStrategyPromotionDecision.APPROVED,
            reason=reason,
            actor=actor,
        )
        return record, False


class OnlyStrategyQueryService:
    def __init__(self, strategies: OnlyFrozenStrategyRevisionStore, promotions: OnlyStrategyProductStore) -> None:
        self._strategies = strategies
        self._promotions = promotions

    def get(self, strategy_fingerprint: str) -> OnlyStrategyProductView:
        revision = self._strategies.load_verified(strategy_fingerprint)
        relations = self._strategies.freeze_relations(strategy_fingerprint)
        records = self._promotions.records(strategy_fingerprint)

        class _QueryLedger:
            def records(_, value: str) -> tuple[OnlyStrategyPromotionRecord, ...]:
                return self._promotions.records(value)

            def append(_, record: OnlyStrategyPromotionRecord) -> OnlyStrategyPromotionRecord:
                raise RuntimeError("query must not produce Promotion facts")

        stage = OnlyStrategyPromotionService(
            self._strategies,
            _QueryLedger(),
            self._audit_time_unreachable,
        ).current_stage(strategy_fingerprint)
        return OnlyStrategyProductView(
            revision,
            tuple(item.relation_fingerprint for item in relations),
            stage,
            records,
        )

    @staticmethod
    def _audit_time_unreachable() -> datetime:
        raise RuntimeError("query must not produce Promotion facts")


__all__ = [name for name in globals() if name.startswith("Only")]
