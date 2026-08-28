from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyBinancePluginDescriptor:
    plugin_id: str = "onlyalpha-plugin-binance"
    provider: str = "BINANCE"
    capabilities: tuple[str, ...] = ("SPOT_PUBLIC_REFERENCE",)


def only_plugin_descriptor() -> OnlyBinancePluginDescriptor:
    return OnlyBinancePluginDescriptor()
