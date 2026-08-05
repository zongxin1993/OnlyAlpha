from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.reference import (
    OnlyAshareBoard,
    OnlyAshareExchange,
    OnlyAshareInstrumentReference,
    OnlyAshareReferenceError,
    OnlyAshareReferenceRegistry,
    OnlyAshareReferenceResolutionStatus,
    OnlyAshareSecurityType,
    OnlyReferenceDataSource,
)


def _record(
    *,
    instrument_id: str = "600000.XSHG",
    effective_from: date = date(2025, 1, 2),
    effective_to: date | None = date(2025, 1, 3),
    previous_close: str = "10.00",
    source_version: str = "fixture-v1",
) -> OnlyAshareInstrumentReference:
    return OnlyAshareInstrumentReference(
        OnlyInstrumentId.parse(instrument_id),
        OnlyAshareExchange.SSE,
        OnlyAshareSecurityType.COMMON_STOCK,
        OnlyAshareBoard.SSE_MAIN,
        OnlyQuantity(Decimal("100"), 0),
        OnlyPrice(Decimal("0.01"), 2),
        False,
        False,
        OnlyPrice(Decimal(previous_close), 2),
        OnlyTradingDay(effective_from),
        None if effective_to is None else OnlyTradingDay(effective_to),
        OnlyReferenceDataSource.GOLDEN_DATASET,
        source_version,
        "cn-a-share-reference-v1",
    )


def test_record_is_immutable_exact_and_has_stable_canonical_fingerprint() -> None:
    record = _record()
    assert record.record_fingerprint == _record().record_fingerprint
    assert record.to_dict()["previous_close"] == "10.00"
    with pytest.raises(FrozenInstanceError):
        record.suspended = True  # type: ignore[misc]
    with pytest.raises(OnlyValidationError, match="binary float"):
        OnlyPrice(0.01, 2)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"lot_size": OnlyQuantity(Decimal(0), 0)}, "REFERENCE_LOT_SIZE_INVALID"),
        ({"price_tick": OnlyPrice(Decimal(0), 2)}, "REFERENCE_PRICE_TICK_INVALID"),
        ({"previous_close": OnlyPrice(Decimal(0), 2)}, "REFERENCE_PREVIOUS_CLOSE_INVALID"),
        (
            {"effective_to": OnlyTradingDay(date(2025, 1, 2))},
            "REFERENCE_EFFECTIVE_RANGE_INVALID",
        ),
        ({"source_version": " "}, "REFERENCE_SOURCE_VERSION_MISSING"),
        ({"data_version": " "}, "REFERENCE_DATA_VERSION_MISSING"),
    ],
)
def test_record_rejects_incomplete_or_invalid_authority(change: dict[str, object], code: str) -> None:
    with pytest.raises(OnlyAshareReferenceError, match=code):
        replace(_record(), **change)


def test_record_rejects_supplied_fingerprint_mismatch() -> None:
    with pytest.raises(OnlyAshareReferenceError, match="REFERENCE_FINGERPRINT_MISMATCH"):
        replace(_record(), record_fingerprint="0" * 64)


def test_registry_is_order_independent_idempotent_and_resolves_half_open_ranges() -> None:
    first = _record()
    second = _record(
        effective_from=date(2025, 1, 3),
        effective_to=date(2025, 1, 4),
        previous_close="10.10",
        source_version="fixture-v2",
    )
    left = OnlyAshareReferenceRegistry((first, second, first))
    right = OnlyAshareReferenceRegistry((second, first))
    assert left.fingerprint == right.fingerprint
    assert len(left.records) == 2
    assert left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 2))).snapshot == first
    assert left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 3))).snapshot == second
    missing = left.resolve(first.instrument_id, OnlyTradingDay(date(2025, 1, 4)))
    assert missing.status is OnlyAshareReferenceResolutionStatus.NOT_FOUND
    assert missing.failure_code == "REFERENCE_NOT_FOUND"


def test_registry_rejects_overlap_and_conflicting_source_identity() -> None:
    first = _record(effective_to=date(2025, 1, 4))
    overlap = _record(
        effective_from=date(2025, 1, 3),
        effective_to=date(2025, 1, 5),
        source_version="fixture-v2",
    )
    with pytest.raises(OnlyAshareReferenceError, match="REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        OnlyAshareReferenceRegistry((first, overlap))
    conflict = replace(first, previous_close=OnlyPrice(Decimal("9.99"), 2), record_fingerprint="")
    with pytest.raises(OnlyAshareReferenceError, match="REFERENCE_RUNTIME_CONFLICT"):
        OnlyAshareReferenceRegistry((first, conflict))


def test_exchange_is_explicit_and_must_match_instrument_venue() -> None:
    with pytest.raises(OnlyAshareReferenceError, match="REFERENCE_EXCHANGE_UNSUPPORTED"):
        replace(_record(), exchange=OnlyAshareExchange.SZSE, record_fingerprint="")
    with pytest.raises(OnlyAshareReferenceError, match="REFERENCE_BOARD_UNSUPPORTED"):
        replace(_record(), board=OnlyAshareBoard.CHINEXT, record_fingerprint="")


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
    payload = _record().to_dict()
    payload[field] = value  # type: ignore[assignment]
    payload.pop("record_fingerprint")
    with pytest.raises(OnlyAshareReferenceError) as error:
        OnlyAshareInstrumentReference.from_mapping(payload)
    assert error.value.code == code
