from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json, only_canonical_payload
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity


@st.composite
def exact_decimals(draw: st.DrawFn, *, max_places: int = 6, non_negative: bool = False) -> Decimal:
    places = draw(st.integers(min_value=0, max_value=max_places))
    minimum = 0 if non_negative else -1_000_000
    coefficient = draw(st.integers(min_value=minimum, max_value=1_000_000))
    return Decimal(coefficient).scaleb(-places)


@given(exact_decimals(max_places=6))
def test_money_serialization_round_trip_preserves_exact_decimal(amount: Decimal) -> None:
    currency = OnlyCurrency("CNY", 6)
    value = OnlyMoney(amount, currency)

    restored = OnlyMoney.from_json(value.to_json())

    assert restored == value
    assert isinstance(restored.amount, Decimal)


@given(
    exact_decimals(max_places=6, non_negative=True),
    exact_decimals(max_places=6, non_negative=True),
)
def test_quantity_add_then_subtract_restores_original(left: Decimal, right: Decimal) -> None:
    original = OnlyQuantity(left, 6)
    increment = OnlyQuantity(right, 6)

    assert original + increment - increment == original


@given(st.integers(min_value=-2_000_000_000_000_000, max_value=2_000_000_000_000_000))
def test_timestamp_datetime_round_trip_preserves_microsecond_precision(unix_micros: int) -> None:
    timestamp = OnlyTimestamp.from_unix_micros(unix_micros)

    restored = OnlyTimestamp.from_datetime(timestamp.to_datetime())

    assert restored == timestamp
    assert restored.to_datetime().tzinfo is UTC


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=12),
        st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20)),
        max_size=12,
    )
)
def test_canonicalization_is_idempotent_and_fingerprint_stable(payload: dict[str, object]) -> None:
    canonical = only_canonical_payload(payload)

    assert only_canonical_payload(canonical) == canonical
    assert only_canonical_json(dict(reversed(payload.items()))) == only_canonical_json(payload)
    assert only_canonical_fingerprint(canonical) == only_canonical_fingerprint(payload)


@given(
    st.from_regex(r"[A-Z0-9]{1,16}", fullmatch=True),
    st.from_regex(r"[A-Z0-9]{1,12}", fullmatch=True),
)
def test_instrument_identifier_text_round_trip(symbol: str, venue: str) -> None:
    identifier = OnlyInstrumentId(OnlySymbol(symbol), OnlyVenueId(venue))

    assert OnlyInstrumentId.parse(str(identifier)) == identifier
