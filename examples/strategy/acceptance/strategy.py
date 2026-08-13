"""Runtime-neutral first-bar intent strategy used by SIM certification."""

from __future__ import annotations

from examples.strategy.observation.config import OnlyFirstBarIntentStrategyConfig
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.context import OnlyStrategyBarContext


class OnlySimCertificationIntentStrategy(OnlyStrategy):
    """Submit one ordinary intent through the canonical Strategy Order Port."""

    def __init__(self, config: OnlyFirstBarIntentStrategyConfig) -> None:
        super().__init__(config)
        self.intent_config = config
        self._attempt_count = 0
        self._completed = False

    def on_initialize(self) -> None:
        if any(
            item is None
            for item in (
                self.intent_config.cluster_id,
                self.intent_config.account_id,
                self.intent_config.instrument_id,
                self.intent_config.quantity,
            )
        ):
            raise ValueError("SIM certification strategy configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        if self._completed:
            return
        bar = context.primary_bar
        if not isinstance(bar, OnlyBar):
            raise TypeError("SIM certification strategy requires a Bar")
        instrument_id = self.intent_config.instrument_id
        account_id = self.intent_config.account_id
        quantity = self.intent_config.quantity
        cluster_id = self.intent_config.cluster_id
        if instrument_id is None or account_id is None or quantity is None or cluster_id is None:
            raise RuntimeError("SIM certification strategy is not initialized")
        orders = context.strategy.orders
        if not isinstance(orders, OnlyOrderServiceView):
            raise TypeError("Strategy Order Port is unavailable")
        self._attempt_count += 1
        result = orders.submit(
            OnlyOrderRequest(
                OnlyOrderRequestId(f"{cluster_id}-sim-certification-{bar.bar_start.isoformat()}"),
                instrument_id,
                OnlyOrderSide.BUY,
                OnlyOrderType.LIMIT,
                quantity,
                price=bar.close,
                account_id=account_id,
                offset=OnlyOffset.OPEN,
                tags=("SIM_CERTIFICATION_INTENT",),
            )
        )
        self._completed = result.created

    def build_result_extension(self) -> dict[str, object]:
        return {"sim_certification": {"attempt_count": self._attempt_count, "completed": self._completed}}

    @property
    def checkpoint_schema_version(self) -> int | None:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability | None:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return {"attempt_count": self._attempt_count, "completed": self._completed}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("SIM certification strategy checkpoint must be an object")
        self._attempt_count = int(payload.get("attempt_count", 0))
        self._completed = bool(payload.get("completed", False))
