"""Strategy decision contract, separate from Cluster ownership."""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext, OnlyStrategyContext, OnlyStrategyTimerContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyStrategyContextError(RuntimeError):
    pass


class OnlyStrategy(ABC):
    def __init__(self, config: OnlyStrategyConfig) -> None:
        self.config = config
        self._context: OnlyStrategyContext | None = None

    @property
    def strategy_id(self) -> OnlyStrategyId:
        return self.config.strategy_id

    @property
    def context(self) -> OnlyStrategyContext:
        if self._context is None:
            raise OnlyStrategyContextError("Strategy Context is unavailable outside its bound lifecycle")
        return self._context

    def _only_cluster_bind(self, context: OnlyStrategyContext) -> None:
        if self._context is not None:
            raise OnlyStrategyContextError("Strategy Context can be bound only once")
        self._context = context

    @abstractmethod
    def on_initialize(self) -> None: ...

    def on_start(self) -> None:
        """Optional lifecycle hook."""
        return None

    @abstractmethod
    def on_bar(self, context: OnlyStrategyBarContext) -> None: ...

    def on_timer(self, context: OnlyStrategyTimerContext) -> None:
        """Optional timer hook."""
        return None

    def on_order_update(self, update: object) -> None:
        """Optional order fact hook."""
        return None

    def on_trade(self, trade: object) -> None:
        """Optional trade fact hook."""
        return None

    def on_pause(self) -> None:
        """Optional pause hook."""
        return None

    def on_resume(self) -> None:
        """Optional resume hook."""
        return None

    def on_stop(self) -> None:
        """Optional stop hook."""
        return None

    def build_result_extension(self) -> Mapping[str, object]:
        return {}


class OnlyNoopStrategy(OnlyStrategy):
    """Explicit inert Strategy for infrastructure-only Cluster tests and services."""

    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        del context
