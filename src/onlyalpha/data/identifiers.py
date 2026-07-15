"""Strong identifiers for market-data sources and updates."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSourceId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("market-data source id cannot be blank")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyMarketDataGatewayId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("market-data gateway id cannot be blank")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyMarketDataUpdateId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("market-data update id cannot be blank")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyDataVersion:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("data version cannot be blank")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class OnlyDataSequence:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError("data sequence cannot be negative")

    def __int__(self) -> int:
        return self.value
