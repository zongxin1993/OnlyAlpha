"""Runtime-owned mutable Bar cache hidden behind immutable snapshots."""

from __future__ import annotations

from onlyalpha.domain.market import OnlyBar, OnlyBarType


class OnlyMarketDataCacheError(Exception):
    pass


class OnlyBarCache:
    """Closed-Bar history and monotonically increasing per-type versions."""

    def __init__(self, history_limit: int = 1024) -> None:
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self._history_limit = history_limit
        self._closed: dict[OnlyBarType, list[OnlyBar]] = {}
        self._partials: dict[OnlyBarType, OnlyBar] = {}
        self._versions: dict[OnlyBarType, int] = {}

    def update_closed(self, bar: OnlyBar) -> int:
        if not bar.is_closed:
            raise OnlyMarketDataCacheError("closed Bar cache rejects updating Bars")
        history = self._closed.setdefault(bar.bar_type, [])
        if history and bar.bar_end <= history[-1].bar_end:
            raise OnlyMarketDataCacheError("closed Bar cache requires increasing bar_end")
        history.append(bar)
        if len(history) > self._history_limit:
            del history[: len(history) - self._history_limit]
        version = self._versions.get(bar.bar_type, 0) + 1
        self._versions[bar.bar_type] = version
        return version

    def latest_closed(self, bar_type: OnlyBarType) -> OnlyBar | None:
        history = self._closed.get(bar_type, ())
        return history[-1] if history else None

    def current_partial(self, bar_type: OnlyBarType) -> OnlyBar | None:
        return self._partials.get(bar_type)

    def history(self, bar_type: OnlyBarType, count: int) -> tuple[OnlyBar, ...]:
        if count <= 0:
            raise ValueError("history count must be positive")
        return tuple(self._closed.get(bar_type, ())[-count:])

    def version(self, bar_type: OnlyBarType) -> int:
        return self._versions.get(bar_type, 0)

    def latest_all(self) -> dict[OnlyBarType, OnlyBar]:
        return {bar_type: bars[-1] for bar_type, bars in self._closed.items() if bars}

    def histories_all(self) -> dict[OnlyBarType, tuple[OnlyBar, ...]]:
        return {bar_type: tuple(bars) for bar_type, bars in self._closed.items()}

    def versions_all(self) -> dict[OnlyBarType, int]:
        return dict(self._versions)


class OnlyMarketDataCache(OnlyBarCache):
    """Named first-phase Runtime market-data cache."""
