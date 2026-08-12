"""Single serialized authority for streaming MarketData semantic processing."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult
from onlyalpha.data.processor import OnlyMarketDataProcessor


@dataclass(frozen=True, slots=True)
class OnlyStreamingProcessingOutcome:
    started: bool
    result: OnlyMarketDataProcessingResult | None = None


OnlyStreamingProcessingCommit = Callable[
    [OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult],
    None,
]


class OnlyStreamingProcessingLane:
    """Own the atomic permission to process and commit one streaming update."""

    def __init__(self, processor: OnlyMarketDataProcessor) -> None:
        self._processor = processor
        self._permission = Lock()
        self._revoked = False

    def process(
        self,
        update: OnlyMarketDataInboundUpdate,
        commit_result: OnlyStreamingProcessingCommit,
    ) -> OnlyStreamingProcessingOutcome:
        with self._permission:
            if self._revoked:
                return OnlyStreamingProcessingOutcome(False)
            result = self._processor.process(update)
            commit_result(update, result)
            return OnlyStreamingProcessingOutcome(True, result)

    def revoke(self, establish_cutoff: Callable[[], object] | None = None) -> None:
        """Establish the cutoff after any already-started atomic update completes."""
        with self._permission:
            if establish_cutoff is not None:
                establish_cutoff()
            self._revoked = True

    @property
    def revoked(self) -> bool:
        with self._permission:
            return self._revoked
