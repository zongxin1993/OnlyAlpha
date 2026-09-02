from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient


def only_binance_public_healthcheck(client: OnlyBinanceSpotReferenceClient) -> bool:
    return client.ping().strip() == b"{}"
