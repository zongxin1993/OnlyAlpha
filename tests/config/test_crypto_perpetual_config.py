from __future__ import annotations

from copy import deepcopy

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.enums import OnlyContractType, OnlyInstrumentType
from onlyalpha.domain.instrument import OnlyCryptoPerpetual


def _payload() -> dict[str, object]:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = deepcopy(dict(baseline.normalized_payload))
    payload["runtime"]["base_currency"] = "USDT"  # type: ignore[index]
    payload["reference_data"]["calendars"] = [  # type: ignore[index]
        {
            "calendar_id": "BINANCE-24X7",
            "venue": "BINANCE",
            "timezone": "UTC",
            "sessions": [
                {
                    "name": "continuous",
                    "opens_at": "00:00:00",
                    "closes_at": "23:59:59",
                    "session_type": "CONTINUOUS",
                }
            ],
            "holidays": [],
            "weekend_days": [],
        }
    ]
    payload["reference_data"]["instruments"] = [  # type: ignore[index]
        {
            "instrument_id": "BTCUSDT-PERP.BINANCE",
            "asset_class": "CRYPTO_PERPETUAL",
            "base_currency": "BTC",
            "margin_currency": "USDT",
            "contract_type": "LINEAR",
            "timezone": "UTC",
            "trading_calendar_id": "BINANCE-24X7",
            "price_precision": 2,
            "quantity_precision": 3,
            "price_increment": "0.10",
            "quantity_increment": "0.001",
            "lot_size": "0.001",
            "minimum_quantity": "0.001",
            "maximum_quantity": "1000.000",
            "contract_multiplier": "1",
        }
    ]
    payload["universes"] = [
        {
            "universe_id": "binance-usdm",
            "type": "STATIC",
            "instruments": ["BTCUSDT-PERP.BINANCE"],
        }
    ]
    payload["data_sources"][0]["coverage"] = {"universe_ids": ["binance-usdm"]}  # type: ignore[index]
    payload["accounts"][0]["initial_cash"] = {"value": "100000.00", "currency": "USDT"}  # type: ignore[index]
    payload["factors"] = []
    return payload


def test_cluster_document_maps_crypto_perpetual_to_canonical_instrument() -> None:
    config = OnlyClusterRunConfig.from_mapping(_payload(), source_path="<crypto-perpetual-test>")

    [instrument] = config.reference_data.instruments
    assert isinstance(instrument, OnlyCryptoPerpetual)
    assert instrument.instrument_type is OnlyInstrumentType.CRYPTO_PERPETUAL
    assert instrument.contract_type is OnlyContractType.LINEAR
    assert instrument.base_currency is not None and instrument.base_currency.code == "BTC"
    assert instrument.margin_currency is not None and instrument.margin_currency.code == "USDT"


def test_crypto_perpetual_requires_explicit_margin_currency() -> None:
    payload = _payload()
    del payload["reference_data"]["instruments"][0]["margin_currency"]  # type: ignore[index]

    with pytest.raises(ValueError, match="margin_currency"):
        OnlyClusterRunConfig.from_mapping(payload, source_path="<crypto-perpetual-test>")
