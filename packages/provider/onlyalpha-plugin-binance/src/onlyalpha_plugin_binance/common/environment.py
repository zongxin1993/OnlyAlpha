from enum import StrEnum


class OnlyBinanceEnvironment(StrEnum):
    LIVE = "LIVE"
    SPOT_TESTNET = "SPOT_TESTNET"

    @property
    def rest_base_url(self) -> str:
        return "https://api.binance.com" if self is self.LIVE else "https://testnet.binance.vision"
