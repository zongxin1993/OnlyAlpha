"""Strong identifiers and continuity scopes for market-data facts."""

from dataclasses import dataclass

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType


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


@dataclass(frozen=True, slots=True)
class OnlyDataSequenceScope:
    source_id: OnlyMarketDataSourceId
    instrument_id: OnlyInstrumentId
    data_type: OnlyMarketDataType
    bar_type: OnlyBarType | None = None

    def __post_init__(self) -> None:
        if self.data_type is OnlyMarketDataType.BAR and self.bar_type is None:
            raise ValueError("Bar sequence scope requires bar_type")
        if self.data_type is not OnlyMarketDataType.BAR and self.bar_type is not None:
            raise ValueError("only Bar sequence scope may include bar_type")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "instrument_id": self.instrument_id.to_json(),
            "data_type": self.data_type.value,
            "bar_type": None if self.bar_type is None else self.bar_type.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "OnlyDataSequenceScope":
        bar_raw = raw.get("bar_type")
        return cls(
            OnlyMarketDataSourceId(str(raw["source_id"])),
            OnlyInstrumentId.from_json(str(raw["instrument_id"])),
            OnlyMarketDataType(str(raw["data_type"])),
            OnlyBarType.from_dict(bar_raw) if isinstance(bar_raw, dict) else None,
        )
