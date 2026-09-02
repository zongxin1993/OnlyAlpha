"""In-memory Product command adapter used only by hermetic command tests."""

from __future__ import annotations

from datetime import datetime

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandReceipt,
)

from .command import OnlyBacktestCommandStore
from .model import OnlyBacktestRun, OnlyBacktestRunId


class OnlyInMemoryBacktestCommandStore(OnlyBacktestCommandStore):
    def __init__(self) -> None:
        self.runs: dict[OnlyBacktestRunId, OnlyBacktestRun] = {}
        self.receipts: dict[OnlyProductCommandId, OnlyProductCommandReceipt] = {}

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        return self.receipts.get(command_id)

    def create_queued_with_receipt(
        self, run: OnlyBacktestRun, receipt: OnlyProductCommandReceipt
    ) -> OnlyProductCommandReceipt:
        existing = self.receipts.get(receipt.command_id)
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

        existing = self.receipts.get(command_id)
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
        receipt = OnlyProductCommandReceipt(
            command_id,
            OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
            command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.BACKTEST_RUN, run_id.value),
            at,
        )
        self.receipts[command_id] = receipt
        return updated, receipt


__all__ = ["OnlyInMemoryBacktestCommandStore"]
