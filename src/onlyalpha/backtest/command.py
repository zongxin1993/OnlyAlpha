"""Durable Backtest Product command admission and retry convergence."""

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
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)

from .admission import OnlyBacktestAdmissionService
from .errors import OnlyBacktestError, OnlyBacktestErrorPhase
from .model import OnlyBacktestRun, OnlyBacktestRunId, OnlyBacktestSpecification


class OnlyBacktestSubmissionDisposition(StrEnum):
    CREATED = "CREATED"
    REPLAYED = "REPLAYED"


@dataclass(frozen=True, slots=True)
class OnlyBacktestSubmitOutcome:
    run: OnlyBacktestRun
    disposition: OnlyBacktestSubmissionDisposition


class OnlyBacktestCommandStore(Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def create_queued_with_receipt(
        self, run: OnlyBacktestRun, receipt: OnlyProductCommandReceipt
    ) -> OnlyProductCommandReceipt: ...

    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun: ...

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyBacktestRunId,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        at: datetime,
    ) -> tuple[OnlyBacktestRun, OnlyProductCommandReceipt]: ...


class OnlyBacktestCommandService:
    def __init__(
        self,
        *,
        admission: OnlyBacktestAdmissionService,
        store: OnlyBacktestCommandStore,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._admission = admission
        self._store = store
        self._now_utc = now_utc

    def submit(
        self,
        command_id: OnlyProductCommandId,
        specification: OnlyBacktestSpecification,
    ) -> OnlyBacktestSubmitOutcome:
        fingerprint = only_product_command_fingerprint({"specification": specification.to_dict()})
        existing = self._store.find_product_command_receipt(command_id)
        if existing is not None:
            return self._replay_create(existing, fingerprint)
        resolution = self._admission.resolve(specification)
        queued_at = self._now_utc()
        run = OnlyBacktestRun.queued(
            run_id=OnlyBacktestRunId.new(),
            specification=specification,
            admission_resolution_fingerprint=resolution.admission_resolution_fingerprint,
            queued_at=queued_at,
        )
        prepared = OnlyProductCommandReceipt(
            command_id=command_id,
            command_kind=OnlyProductCommandKind.CREATE_BACKTEST_RUN,
            command_fingerprint=fingerprint,
            outcome_ref=OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind.BACKTEST_RUN,
                run.run_id.value,
            ),
            accepted_at=queued_at,
        )
        receipt = self._store.create_queued_with_receipt(run, prepared)
        if receipt == prepared:
            return OnlyBacktestSubmitOutcome(run, OnlyBacktestSubmissionDisposition.CREATED)
        return self._replay_create(receipt, fingerprint)

    def cancel(
        self,
        run_id: OnlyBacktestRunId,
        command_id: OnlyProductCommandId,
    ) -> OnlyBacktestRun:
        fingerprint = only_product_command_fingerprint({"run_id": run_id.value})
        existing = self._store.find_product_command_receipt(command_id)
        if existing is not None:
            return self._replay_cancel(existing, fingerprint, run_id)
        run, receipt = self._store.request_cancellation_with_receipt(
            run_id,
            command_id,
            fingerprint,
            self._now_utc(),
        )
        if receipt.command_id != command_id:
            raise AssertionError("Backtest cancellation receipt identity differs")
        return run

    def _replay_create(self, receipt: OnlyProductCommandReceipt, fingerprint: str) -> OnlyBacktestSubmitOutcome:
        self._assert_receipt(
            receipt,
            OnlyProductCommandKind.CREATE_BACKTEST_RUN,
            OnlyProductCommandOutcomeKind.BACKTEST_RUN,
            fingerprint,
        )
        run = self._store.load(OnlyBacktestRunId(receipt.outcome_ref.outcome_id))
        return OnlyBacktestSubmitOutcome(run, OnlyBacktestSubmissionDisposition.REPLAYED)

    def _replay_cancel(
        self,
        receipt: OnlyProductCommandReceipt,
        fingerprint: str,
        run_id: OnlyBacktestRunId,
    ) -> OnlyBacktestRun:
        self._assert_receipt(
            receipt,
            OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
            OnlyProductCommandOutcomeKind.BACKTEST_RUN,
            fingerprint,
        )
        if receipt.outcome_ref.outcome_id != run_id.value:
            _conflict("Backtest cancellation receipt outcome differs")
        return self._store.load(run_id)

    @staticmethod
    def _assert_receipt(
        receipt: OnlyProductCommandReceipt,
        kind: OnlyProductCommandKind,
        outcome: OnlyProductCommandOutcomeKind,
        fingerprint: str,
    ) -> None:
        if (
            receipt.command_kind is not kind
            or receipt.outcome_ref.kind is not outcome
            or receipt.command_fingerprint != fingerprint
        ):
            _conflict("Product Command ID is already bound to another intent")


def _conflict(detail: str) -> None:
    raise OnlyBacktestError(OnlyBacktestErrorPhase.COMMAND, "PRODUCT_COMMAND_CONFLICT", detail)


__all__ = [name for name in globals() if name.startswith("Only")]
