"""Business-shaped persistence port for Research submission and operational reads."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandReceipt
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.run.store import OnlyResearchRunStore

from .model import OnlyResearchRunPageCursor


class OnlyResearchRunReader(Protocol):
    def list_recent(
        self, *, limit: int, after: OnlyResearchRunPageCursor | None = None
    ) -> tuple[OnlyResearchRun, ...]: ...

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class OnlyResearchCommandStore(OnlyResearchRunStore, OnlyResearchRunReader, Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def create_queued_with_receipt(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt: ...

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyResearchRunId,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt: ...


__all__ = ["OnlyResearchCommandStore", "OnlyResearchRunReader"]
