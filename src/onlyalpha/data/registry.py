"""Market-data-only source registry and explicit factory."""

from collections.abc import Callable

from onlyalpha.data.identifiers import OnlyMarketDataSourceId
from onlyalpha.data.ports import OnlyHistoricalDataSource, OnlyMarketDataCapabilities, OnlyMarketDataGateway

OnlyMarketDataSource = OnlyHistoricalDataSource | OnlyMarketDataGateway


class OnlyMarketDataSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[OnlyMarketDataSourceId, OnlyMarketDataSource] = {}
        self._priorities: dict[OnlyMarketDataSourceId, int] = {}

    def register(self, source: OnlyMarketDataSource, *, priority: int = 100) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"duplicate market-data source: {source.source_id}")
        self._sources[source.source_id] = source
        self._priorities[source.source_id] = priority

    def contains(self, source_id: OnlyMarketDataSourceId) -> bool:
        return source_id in self._sources

    def capabilities(self, source_id: OnlyMarketDataSourceId) -> OnlyMarketDataCapabilities:
        return self._sources[source_id].capabilities

    def priority(self, source_id: OnlyMarketDataSourceId) -> int:
        return self._priorities[source_id]


class OnlyMarketDataSourceFactory:
    def __init__(self) -> None:
        self._builders: dict[str, Callable[[], OnlyMarketDataSource]] = {}

    def register(self, kind: str, builder: Callable[[], OnlyMarketDataSource]) -> None:
        if not kind.strip() or kind in self._builders:
            raise ValueError("source factory kind must be non-blank and unique")
        self._builders[kind] = builder

    def create(self, kind: str) -> OnlyMarketDataSource:
        try:
            return self._builders[kind]()
        except KeyError as exc:
            raise ValueError(f"unknown market-data source kind: {kind}") from exc
