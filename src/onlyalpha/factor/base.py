"""Factor lifecycle and time-series/cross-section separation."""

from abc import ABC, abstractmethod

from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType
from onlyalpha.factor.context import OnlyCrossSectionFactorContext, OnlyFactorBarContext, OnlyFactorContext
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorScore
from onlyalpha.factor.snapshot import OnlyFactorSnapshot


class OnlyFactorContextError(RuntimeError):
    pass


class OnlyFactor(ABC):
    def __init__(self, config: OnlyFactorConfig) -> None:
        self.config = config
        self._context: OnlyFactorContext | None = None

    @property
    def factor_id(self) -> OnlyFactorId:
        return self.config.factor_id

    @property
    def factor_type(self) -> OnlyFactorType:
        return self.config.factor_type

    @property
    def ready(self) -> bool:
        return self.snapshot().ready

    @property
    def context(self) -> OnlyFactorContext:
        if self._context is None:
            raise OnlyFactorContextError("Factor Context is unavailable outside its bound lifecycle")
        return self._context

    def _only_cluster_bind(self, context: OnlyFactorContext) -> None:
        if self._context is not None:
            raise OnlyFactorContextError("Factor Context can be bound only once")
        self._context = context

    @abstractmethod
    def on_initialize(self) -> None: ...

    @abstractmethod
    def snapshot(self) -> OnlyFactorSnapshot: ...

    @abstractmethod
    def score(self) -> OnlyFactorScore: ...

    def on_start(self) -> None:
        """Optional lifecycle hook."""
        return None

    def on_stop(self) -> None:
        """Optional lifecycle hook."""
        return None


class OnlyTimeSeriesFactor(OnlyFactor, ABC):
    def __init__(self, config: OnlyFactorConfig) -> None:
        if config.factor_type is not OnlyFactorType.TIME_SERIES:
            raise ValueError("TimeSeriesFactor requires TIME_SERIES config")
        super().__init__(config)

    @abstractmethod
    def on_bar(self, context: OnlyFactorBarContext) -> None: ...


class OnlyCrossSectionFactor(OnlyFactor, ABC):
    def __init__(self, config: OnlyFactorConfig) -> None:
        if config.factor_type is not OnlyFactorType.CROSS_SECTION:
            raise ValueError("CrossSectionFactor requires CROSS_SECTION config")
        super().__init__(config)

    @abstractmethod
    def on_cross_section(self, context: OnlyCrossSectionFactorContext) -> None: ...
