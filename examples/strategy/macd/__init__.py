from .config import OnlyMacdStrategyConfig
from .result import OnlyMacdSignal
from .strategy import OnlyMacdStrategy

__all__ = [name for name in globals() if name.startswith("Only")]
# ruff: noqa: F401
