"""Business-shaped persistence port for Research submission and operational reads."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandReceipt
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.run.store import OnlyResearchRunTransitionStore

from .model import OnlyResearchRunPageCursor
from .novelty_admission import OnlyResearchNoveltyAdmissionV1, OnlyResearchNoveltyAdmissionV2


class OnlyResearchRunReader(Protocol):
    def list_recent(
        self, *, limit: int, after: OnlyResearchRunPageCursor | None = None
    ) -> tuple[OnlyResearchRun, ...]: ...

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class OnlyResearchCommandStore(OnlyResearchRunTransitionStore, OnlyResearchRunReader, Protocol):
    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None: ...

    def load_novelty_admission(
        self, command_id: OnlyProductCommandId
    ) -> OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2 | None: ...

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyResearchRunId,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt: ...


class _OnlyVerifiedNoveltyAdmissionStore(OnlyResearchCommandStore, Protocol):
    """Internal persistence capability held only by the verified Read-to-Act service."""

    def _create_queued_with_verified_novelty_admission(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
        admission: OnlyResearchNoveltyAdmissionV1 | OnlyResearchNoveltyAdmissionV2,
        *,
        expected_source_frontier: int,
    ) -> OnlyProductCommandReceipt: ...


class _OnlyHistoricalResearchRunSeeder(Protocol):
    """Explicit test/historical capability, never supplied by production composition."""

    def seed_queued_with_receipt(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt: ...


__all__ = ["OnlyResearchCommandStore", "OnlyResearchRunReader"]
