"""Explicit migration preserves old bytes and requires authoritative concrete types."""

from copy import deepcopy

import pytest

from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.instrument import OnlyInstrument
from tests.domain.conformance.support.instruments import build_instruments


def test_migration_preserves_every_old_field_without_inference() -> None:
    from scripts.domain_instrument_migration import migrate_instrument_record

    for instrument in build_instruments().values():
        expected = instrument.to_dict()
        old = deepcopy(expected)
        old.pop("model_type")
        old["schema_version"] = 1
        original = deepcopy(old)
        migrated = migrate_instrument_record(old, concrete_type=type(instrument))
        assert old == original
        assert migrated == expected
        assert OnlyInstrument.from_dict(migrated) == instrument


def test_migration_refuses_missing_derivative_fields_and_current_format() -> None:
    from scripts.domain_instrument_migration import migrate_instrument_record

    future = build_instruments()["china_future"]
    old = future.to_dict()
    with pytest.raises(OnlySerializationError):
        migrate_instrument_record(old, concrete_type=type(future))
    old.pop("model_type")
    old["schema_version"] = 1
    old.pop("expiration_time")
    with pytest.raises(OnlySerializationError):
        migrate_instrument_record(old, concrete_type=type(future))


def test_migration_refuses_normalizing_historical_field_values() -> None:
    from scripts.domain_instrument_migration import migrate_instrument_record

    instrument = next(iter(build_instruments().values()))
    old = instrument.to_dict()
    old.pop("model_type")
    old["schema_version"] = 1
    old["quote_currency"]["code"] = "cny"
    with pytest.raises(OnlySerializationError):
        migrate_instrument_record(old, concrete_type=type(instrument))
