"""Production provider-neutral WAL ownership boundary."""

from __future__ import annotations

import threading

from onlyalpha.data.evidence import OnlyDurableRecordReceipt, OnlyRawProviderObservation
from onlyalpha.data.models import OnlyMarketDataInboundUpdate

from .ingress import OnlyMarketDataIngress
from .models import OnlyMarketDataHealth


class OnlyDurableMarketDataRecorder:
    """Accept one provider observation only after its WAL frame is fsynced."""

    def __init__(self, ingress: OnlyMarketDataIngress) -> None:
        self._ingress = ingress
        self._lock = threading.Lock()

    def __call__(
        self,
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> OnlyDurableRecordReceipt:
        with self._lock:
            self._ingress.begin_segment()
            receipt = self._ingress.record(observation, canonical_update)
            self._ingress.seal()
            return receipt

    def health(self) -> OnlyMarketDataHealth:
        return self._ingress.health()


__all__ = ["OnlyDurableMarketDataRecorder"]
