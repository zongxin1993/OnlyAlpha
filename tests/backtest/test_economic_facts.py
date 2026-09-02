from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.backtest import OnlyBacktestEconomicFactStore
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import OnlyFundingRateUpdate, OnlyMarketDataInboundUpdate, OnlyReferencePriceUpdate
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.research.dataset import OnlyEconomicFactManifest, OnlyResearchDatasetEconomicBinding

NOW = datetime(2024, 1, 1, tzinfo=UTC)
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT-PERP.BINANCE")


def _updates(version: str = "golden-v1") -> tuple[OnlyMarketDataInboundUpdate, ...]:
    mark = OnlyReferencePriceFact(
        "mark-1",
        INSTRUMENT,
        OnlyReferencePriceKind.MARK,
        OnlyPrice(Decimal("42000.00"), 2),
        NOW,
        NOW,
        "BINANCE_USDM",
        1,
        "1",
    )
    funding = OnlyFundingRateFact(
        "funding-1",
        INSTRUMENT,
        Decimal("0.0001"),
        NOW,
        NOW,
        "BINANCE_USDM",
        2,
        "1",
    )
    timestamp = OnlyTimestamp.from_datetime(NOW)
    runtime_id = OnlyRuntimeId("golden-runtime")
    source_id = OnlyMarketDataSourceId("golden-source")
    data_version = OnlyDataVersion(version)
    return (
        OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId("funding-update"),
            runtime_id=runtime_id,
            source_id=source_id,
            source_sequence=OnlyDataSequence(2),
            data_version=data_version,
            instrument_id=INSTRUMENT,
            data_type=OnlyMarketDataType.FUNDING_RATE,
            payload=OnlyFundingRateUpdate(funding),
            ts_event=timestamp,
            ts_init=timestamp,
        ),
        OnlyMarketDataInboundUpdate(
            update_id=OnlyMarketDataUpdateId("mark-update"),
            runtime_id=runtime_id,
            source_id=source_id,
            source_sequence=OnlyDataSequence(1),
            data_version=data_version,
            instrument_id=INSTRUMENT,
            data_type=OnlyMarketDataType.REFERENCE_PRICE,
            payload=OnlyReferencePriceUpdate(mark),
            ts_event=timestamp,
            ts_init=timestamp,
        ),
    )


def _binding(
    updates: tuple[OnlyMarketDataInboundUpdate, ...], version: str = "golden-v1"
) -> OnlyResearchDatasetEconomicBinding:
    funding = tuple(item for item in updates if item.data_type is OnlyMarketDataType.FUNDING_RATE)
    marks = tuple(item for item in updates if item.data_type is OnlyMarketDataType.REFERENCE_PRICE)
    return OnlyResearchDatasetEconomicBinding(
        "a" * 64,
        "b" * 64,
        (
            OnlyEconomicFactManifest(
                OnlyMarketDataType.FUNDING_RATE,
                only_canonical_fingerprint([item.to_dict() for item in funding]),
                len(funding),
                version,
            ),
            OnlyEconomicFactManifest(
                OnlyMarketDataType.REFERENCE_PRICE,
                only_canonical_fingerprint([item.to_dict() for item in marks]),
                len(marks),
                version,
                OnlyReferencePriceKind.MARK,
            ),
        ),
    )


def test_spot_empty_economic_fact_set_is_immutable_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    binding = OnlyResearchDatasetEconomicBinding("a" * 64, "b" * 64, ())
    store = OnlyBacktestEconomicFactStore(tmp_path)

    store.publish(binding, ())
    store.publish(binding, ())

    assert store.load_for_binding(binding.fingerprint) == ()


def test_usdm_mark_and_funding_round_trip_and_tamper_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    updates = _updates()
    binding = _binding(updates)
    store = OnlyBacktestEconomicFactStore(tmp_path)
    store.publish(binding, tuple(reversed(updates)))
    assert store.load_for_binding(binding.fingerprint) == updates

    path = (
        tmp_path
        / "backtest"
        / "economic-facts"
        / "sha256"
        / binding.fingerprint[:2]
        / binding.fingerprint
        / "facts.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["updates"][0]["data_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="BACKTEST_ECONOMIC_FACT_CORRUPT"):
        store.load_for_binding(binding.fingerprint)


def test_manifest_data_version_must_match_bound_updates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    updates = _updates()
    binding = _binding(updates, version="different-version")

    with pytest.raises(ValueError, match="BACKTEST_ECONOMIC_FACT_MANIFEST_MISMATCH"):
        OnlyBacktestEconomicFactStore(tmp_path).publish(binding, updates)
