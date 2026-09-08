"""In-memory Product command adapter used only by hermetic command tests."""

from __future__ import annotations

from datetime import datetime

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandReceipt,
)

from .command import OnlyBacktestCommandStore
from .model import OnlyBacktestRun, OnlyBacktestRunId


class OnlyInMemoryBacktestCommandStore(OnlyBacktestCommandStore):
    def __init__(self) -> None:
        self.runs: dict[OnlyBacktestRunId, OnlyBacktestRun] = {}
        self.admissions: dict[OnlyProductCommandId, OnlyProductCommandAdmissionV1] = {}
        self.receipts: dict[OnlyProductCommandId, OnlyProductCommandReceipt] = {}

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        receipt = self.receipts.get(command_id)
        if receipt is None:
            return None
        self._verify_receipt(receipt)
        return receipt

    def create_queued_with_receipt(
        self, run: OnlyBacktestRun, receipt: OnlyProductCommandReceipt
    ) -> OnlyProductCommandReceipt:
        self._admit(receipt)
        existing = self.find_product_command_receipt(receipt.command_id)
        if existing is not None:
            return existing
        self.runs[run.run_id] = run
        self.receipts[receipt.command_id] = receipt
        return receipt

    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun:
        from .errors import OnlyBacktestNotFoundError

        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise OnlyBacktestNotFoundError(run_id.value) from exc

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyBacktestRunId,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        at: datetime,
    ) -> tuple[OnlyBacktestRun, OnlyProductCommandReceipt]:
        from onlyalpha.application.product_command_receipt import (
            OnlyProductCommandKind,
            OnlyProductCommandOutcomeKind,
            OnlyProductCommandOutcomeRef,
        )

        from .model import OnlyBacktestRunState

        requested = OnlyProductCommandReceipt(
            command_id,
            OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
            command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.BACKTEST_RUN, run_id.value),
            at,
        )
        self._admit(requested)
        existing = self.find_product_command_receipt(command_id)
        if existing is not None:
            return self.load(run_id), existing
        current = self.load(run_id)
        if current.state is OnlyBacktestRunState.QUEUED:
            updated = current.transition(OnlyBacktestRunState.CANCELLED, at=at)
        elif current.state is OnlyBacktestRunState.RUNNING:
            updated = current.transition(OnlyBacktestRunState.CANCEL_REQUESTED, at=at)
        else:
            updated = current
        self.runs[run_id] = updated
        receipt = requested
        self.receipts[command_id] = receipt
        return updated, receipt

    def _admit(self, receipt: OnlyProductCommandReceipt) -> None:
        from .command import _conflict

        requested = OnlyProductCommandAdmissionV1(
            receipt.command_id,
            receipt.command_kind,
            receipt.command_fingerprint,
        )
        existing = self.admissions.get(receipt.command_id)
        if existing is not None and existing != requested:
            _conflict("Product Command ID is already bound to another intent")
        self.admissions.setdefault(receipt.command_id, requested)

    def _verify_receipt(self, receipt: OnlyProductCommandReceipt) -> None:
        from .command import _conflict

        admission = self.admissions.get(receipt.command_id)
        if admission is None or (
            admission.command_kind is not receipt.command_kind
            or admission.command_fingerprint != receipt.command_fingerprint
        ):
            _conflict("Product Command Receipt does not exact-match Admission")


__all__ = ["OnlyInMemoryBacktestCommandStore"]
