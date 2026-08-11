from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.identity import (
    OnlyCanonicalIdentityError,
    only_identity_fingerprint,
    only_identity_payload,
)


@dataclass(frozen=True, slots=True)
class ExplicitIdentity:
    authority_id: str
    rate: Decimal

    def canonical_identity(self) -> dict[str, object]:
        return {"authority_id": self.authority_id, "rate": self.rate}


class StringableOnly:
    def __str__(self) -> str:
        return "looks-stable"


class SerializableOnly:
    def to_dict(self) -> dict[str, str]:
        return {"looks": "stable"}


def test_formal_identity_accepts_only_explicit_supported_values() -> None:
    value = {
        "authority": ExplicitIdentity("fees", Decimal("0.0010")),
        "effective_at": datetime(2026, 1, 1, tzinfo=UTC),
        "enabled": True,
        "version": 3,
    }
    assert only_identity_payload(value) == {
        "authority": {"authority_id": "fees", "rate": "0.0010"},
        "effective_at": "2026-01-01T00:00:00Z",
        "enabled": True,
        "version": 3,
    }


def test_mapping_order_does_not_change_formal_identity() -> None:
    left = {"b": (Decimal("1.00"),), "a": "value"}
    right = {"a": "value", "b": (Decimal("1.00"),)}
    assert only_identity_fingerprint(left) == only_identity_fingerprint(right)


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        {1: "integer-key"},
        Path("reference.csv"),
        {"unordered"},
        ["mutable-sequence"],
        StringableOnly(),
        SerializableOnly(),
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_unknown_or_ambiguous_formal_identity_values_fail_closed(value: object) -> None:
    with pytest.raises(OnlyCanonicalIdentityError):
        only_identity_payload(value)
