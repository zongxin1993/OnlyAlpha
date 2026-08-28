from dataclasses import dataclass

from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment


@dataclass(frozen=True, slots=True)
class OnlyBinancePublicReferenceConfig:
    environment: OnlyBinanceEnvironment
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.symbols or any(not value.isalnum() or value != value.upper() for value in self.symbols):
            raise ValueError("BINANCE_REFERENCE_SYMBOLS_INVALID")
