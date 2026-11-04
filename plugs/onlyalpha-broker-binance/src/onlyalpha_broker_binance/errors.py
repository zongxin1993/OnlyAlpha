"""Failures decoding or communicating with the private Binance API."""


class OnlyBinanceError(RuntimeError):
    pass


class OnlyBinanceSchemaError(OnlyBinanceError):
    pass
