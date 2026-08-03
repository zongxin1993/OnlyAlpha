from __future__ import annotations

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.order.views import OnlyOrderServiceView
from onlyalpha.plugin.capabilities import OnlyCheckpointCapability
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.context import OnlyStrategyBarContext

from .config import OnlyFirstBarIntentStrategyConfig


class OnlyFirstBarIntentStrategy(OnlyStrategy):
    """Mode-agnostic probe that submits one ordinary Limit intent on its first Bar."""

    def __init__(self, config: OnlyFirstBarIntentStrategyConfig) -> None:
        super().__init__(config)
        self.intent_config = config
        self._attempt: dict[str, object] | None = None

    @property
    def attempt(self) -> dict[str, object] | None:
        return None if self._attempt is None else dict(self._attempt)

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
            raise ValueError("First Bar Intent Strategy configuration is incomplete")

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        if self._attempt is not None:
            return
        bar = context.primary_bar
        if not isinstance(bar, OnlyBar):
            raise TypeError("First Bar Intent Strategy requires a Bar")
        instrument_id = self.intent_config.instrument_id
        account_id = self.intent_config.account_id
        quantity = self.intent_config.quantity
        if instrument_id is None or account_id is None or quantity is None:
            raise RuntimeError("First Bar Intent Strategy is not initialized")
        result = context.strategy.orders
        if not isinstance(result, OnlyOrderServiceView):
            raise TypeError("Strategy Order Port is unavailable")
        submission = result.submit(
            OnlyOrderRequest(
                OnlyOrderRequestId(f"{self.intent_config.cluster_id}-first-bar-intent"),
                instrument_id,
                OnlyOrderSide.BUY,
                OnlyOrderType.LIMIT,
                quantity,
                price=bar.close,
                account_id=account_id,
                offset=OnlyOffset.OPEN,
                tags=("FIRST_BAR_INTENT",),
            )
        )
        self._attempt = {
            "created": submission.created,
            "submitted": submission.submitted,
            "order_id": None if submission.order_id is None else str(submission.order_id),
            "error": submission.error,
            "risk_accepted": submission.risk_decision is not None and submission.risk_decision.is_accepted,
        }

    def build_result_extension(self) -> dict[str, object]:
        return {"first_bar_intent": self.attempt}

    @property
    def checkpoint_schema_version(self) -> int | None:
        return 1

    @property
    def checkpoint_capability(self) -> OnlyCheckpointCapability | None:
        return OnlyCheckpointCapability.CHECKPOINTABLE

    def capture_checkpoint(self) -> object:
        return {"attempt": self.attempt}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("First Bar Intent Strategy checkpoint must be an object")
        attempt = payload.get("attempt")
        if attempt is not None and not isinstance(attempt, dict):
            raise ValueError("First Bar Intent Strategy attempt must be an object")
        self._attempt = attempt
