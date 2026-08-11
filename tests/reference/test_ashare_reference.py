from dataclasses import FrozenInstanceError
from datetime import date

import pytest
from onlyalpha_market_cn_ashare.reference import (
    OnlyCnAshareBoard,
    OnlyCnAshareInstrumentReference,
    OnlyCnAshareReferenceAuthority,
    OnlyCnAshareReferenceError,
)

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay


def _payload(
    *,
    instrument_id: str = "600000.XSHG",
    effective_from: date = date(2025, 1, 2),
    effective_to: date | None = date(2025, 1, 3),
    previous_close: str = "10.00",
    source_version: str = "fixture-v1",
) -> dict[str, object]:
    return {
        "instrument_id": instrument_id,
        "exchange": "SSE",
        "security_type": "COMMON_STOCK",
        "board": "SSE_MAIN",
        "lot_size": "100",
        "price_tick": "0.01",
        "st_status": False,
        "suspended": False,
        "previous_close": previous_close,
        "effective_from": effective_from.isoformat(),
        "effective_to": None if effective_to is None else effective_to.isoformat(),
        "source": "GOLDEN_DATASET",
        "source_version": source_version,
        "data_version": "cn-a-share-reference-v1",
    }


def _record(**changes: object) -> OnlyCnAshareInstrumentReference:
    payload = _payload()
    payload.update(changes)
    return OnlyCnAshareInstrumentReference.from_mapping(payload)


def test_record_is_immutable_exact_and_has_stable_canonical_fingerprint() -> None:
    record = _record()
    assert record.content_fingerprint == _record().content_fingerprint
    assert record.to_dict()["previous_close"] == "10.00"
    with pytest.raises(FrozenInstanceError):
        record.suspended = True  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("lot_size", "0", "REFERENCE_LOT_SIZE_INVALID"),
        ("price_tick", "0", "REFERENCE_PRICE_TICK_INVALID"),
        ("previous_close", "0", "REFERENCE_PREVIOUS_CLOSE_INVALID"),
        ("effective_to", "2025-01-02", "REFERENCE_EFFECTIVE_RANGE_INVALID"),
        ("source_version", " ", "REFERENCE_SOURCE_VERSION_MISSING"),
        ("data_version", " ", "REFERENCE_DATA_VERSION_MISSING"),
    ],
)
def test_record_rejects_incomplete_or_invalid_authority(field: str, value: object, code: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(OnlyCnAshareReferenceError, match=code):
        OnlyCnAshareInstrumentReference.from_mapping(payload)


def test_record_rejects_supplied_fingerprint_mismatch() -> None:
    payload = _payload()
    payload["record_fingerprint"] = "0" * 64
    with pytest.raises(OnlyCnAshareReferenceError, match="REFERENCE_FINGERPRINT_MISMATCH"):
        OnlyCnAshareInstrumentReference.from_mapping(payload)


def test_authority_is_order_independent_and_resolves_half_open_ranges() -> None:
    first = _record()
    second = OnlyCnAshareInstrumentReference.from_mapping(
        _payload(
            effective_from=date(2025, 1, 3),
            effective_to=date(2025, 1, 4),
            previous_close="10.10",
            source_version="fixture-v2",
        )
    )
    left = OnlyCnAshareReferenceAuthority.create((first, second))
    right = OnlyCnAshareReferenceAuthority.create((second, first))
    assert left.identity == right.identity
    assert left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 2))) == first
    assert left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 3))) == second
    with pytest.raises(OnlyCnAshareReferenceError, match="REFERENCE_NOT_FOUND"):
        left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 4)))


def test_authority_rejects_overlapping_reference_ranges() -> None:
    first = OnlyCnAshareInstrumentReference.from_mapping(_payload(effective_to=date(2025, 1, 4)))
    overlap = OnlyCnAshareInstrumentReference.from_mapping(
        _payload(
            effective_from=date(2025, 1, 3),
            effective_to=date(2025, 1, 5),
            source_version="fixture-v2",
        )
    )
    with pytest.raises(OnlyCnAshareReferenceError, match="REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        OnlyCnAshareReferenceAuthority.create((first, overlap))


def test_exchange_and_board_are_explicit_and_match_instrument_venue() -> None:
    with pytest.raises(OnlyCnAshareReferenceError, match="REFERENCE_EXCHANGE_UNSUPPORTED"):
        _record(exchange="SZSE")
    with pytest.raises(OnlyCnAshareReferenceError, match="REFERENCE_BOARD_UNSUPPORTED"):
        _record(board="CHINEXT")


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("board", None, "REFERENCE_BOARD_MISSING"),
        ("board", "BSE", "REFERENCE_BOARD_UNSUPPORTED"),
        ("exchange", "BSE", "REFERENCE_EXCHANGE_UNSUPPORTED"),
        ("security_type", "ETF", "REFERENCE_SECURITY_TYPE_UNSUPPORTED"),
        ("st_status", None, "REFERENCE_ST_STATUS_UNKNOWN"),
        ("suspended", None, "REFERENCE_SUSPENSION_STATUS_UNKNOWN"),
        ("previous_close", None, "REFERENCE_PREVIOUS_CLOSE_MISSING"),
        ("previous_close", 10.0, "REFERENCE_PREVIOUS_CLOSE_INVALID"),
        ("source_version", "", "REFERENCE_SOURCE_VERSION_MISSING"),
        ("data_version", "", "REFERENCE_DATA_VERSION_MISSING"),
    ],
)
def test_mapping_reports_stable_failure_codes(field: str, value: object, code: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(OnlyCnAshareReferenceError) as error:
        OnlyCnAshareInstrumentReference.from_mapping(payload)
    assert error.value.code == code


def test_reference_board_is_plugin_owned() -> None:
    assert _record().board is OnlyCnAshareBoard.SSE_MAIN
    assert _record().instrument_id == OnlyInstrumentId.parse("600000.XSHG")
