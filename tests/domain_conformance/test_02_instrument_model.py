from examples.domain_conformance.fixtures.instruments import build_instruments
from onlyalpha.domain.instrument import (
    OnlyCryptoPerpetual,
    OnlyCryptoSpot,
    OnlyEquity,
    OnlyETF,
    OnlyFuture,
    OnlyFxPair,
    OnlyOption,
)


def test_all_target_market_instruments_are_describable_and_round_trip() -> None:
    instruments = build_instruments()
    assert set(instruments) == {
        "a_share",
        "a_share_etf",
        "hong_kong_equity",
        "us_fractional",
        "china_future",
        "option",
        "fx_pair",
        "crypto_spot",
        "linear_perpetual",
        "inverse_perpetual",
    }
    expected = (
        OnlyEquity,
        OnlyETF,
        OnlyEquity,
        OnlyEquity,
        OnlyFuture,
        OnlyOption,
        OnlyFxPair,
        OnlyCryptoSpot,
        OnlyCryptoPerpetual,
        OnlyCryptoPerpetual,
    )
    for instrument, instrument_type in zip(instruments.values(), expected, strict=True):
        assert isinstance(instrument, instrument_type)
        assert type(instrument).from_json(instrument.to_json()) == instrument
