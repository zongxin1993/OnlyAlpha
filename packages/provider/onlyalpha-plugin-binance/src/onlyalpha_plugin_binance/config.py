from dataclasses import dataclass

from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment


@dataclass(frozen=True, slots=True)
class OnlyBinancePublicReferenceConfig:
    environment: OnlyBinanceEnvironment
    symbols: tuple[str, ...]
    max_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.symbols or any(not value.isalnum() or value != value.upper() for value in self.symbols):
            raise ValueError("BINANCE_REFERENCE_SYMBOLS_INVALID")
        if self.max_response_bytes <= 0:
            raise ValueError("BINANCE_PUBLIC_MAX_RESPONSE_BYTES_INVALID")
