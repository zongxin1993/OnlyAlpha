"""Single permission authority for every Streaming semantic mutation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import TypeVar

from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult
from onlyalpha.data.processor import OnlyMarketDataProcessor, OnlyTradeProcessingConsequence

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class OnlyStreamingSemanticOutcome[T]:
    started: bool
    result: T | None = None


@dataclass(frozen=True, slots=True)
class OnlyStreamingSemanticLaneDiagnostics:
    revoked: bool | None
    busy: bool


OnlyStreamingProcessingCommit = Callable[
    [OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult],
    None,
]


class OnlyStreamingSemanticLane:
    """Own permission to complete exactly one mutation action before another starts."""

    def __init__(
        self,
        processor: OnlyMarketDataProcessor,
        trade_consequence: OnlyTradeProcessingConsequence | None = None,
    ) -> None:
        self._processor = processor
        self._trade_consequence = trade_consequence
        self._permission = RLock()
        self._revoked = False

    def execute(self, action: Callable[[], T]) -> OnlyStreamingSemanticOutcome[T]:
        with self._permission:
            if self._revoked:
                return OnlyStreamingSemanticOutcome(False)
            return OnlyStreamingSemanticOutcome(True, action())

    def process(
        self,
        update: OnlyMarketDataInboundUpdate,
        commit_result: OnlyStreamingProcessingCommit,
        *,
        trade_consequence: OnlyTradeProcessingConsequence | None = None,
    ) -> OnlyStreamingSemanticOutcome[OnlyMarketDataProcessingResult]:
        def action() -> OnlyMarketDataProcessingResult:
            selected = trade_consequence or self._trade_consequence
            process_kwargs = {} if selected is None else {"trade_consequence": selected}
            result = self._processor.process(update, **process_kwargs)
            commit_result(update, result)
            return result

        return self.execute(action)

    def revoke(self, establish_cutoff: Callable[[], object] | None = None) -> None:
        with self._permission:
            if establish_cutoff is not None:
                establish_cutoff()
            self._revoked = True

    @property
    def revoked(self) -> bool:
        with self._permission:
            return self._revoked

    def diagnostics(self) -> OnlyStreamingSemanticLaneDiagnostics:
        """Return immediately even when a semantic action owns the Lane."""

        if not self._permission.acquire(blocking=False):
            return OnlyStreamingSemanticLaneDiagnostics(revoked=None, busy=True)
        try:
            return OnlyStreamingSemanticLaneDiagnostics(revoked=self._revoked, busy=False)
        finally:
            self._permission.release()


__all__ = [
    "OnlyStreamingProcessingCommit",
    "OnlyStreamingSemanticLane",
    "OnlyStreamingSemanticLaneDiagnostics",
    "OnlyStreamingSemanticOutcome",
]
