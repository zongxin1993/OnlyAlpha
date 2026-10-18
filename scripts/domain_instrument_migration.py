"""Explicit, pure Instrument record transformation; never an automatic reader fallback.

The owning storage migration must supply the authoritative original concrete type,
retain the original immutable bytes, and own reference mapping and atomic publication.
This function performs no I/O, identity substitution, database writes or type inference.
"""

from collections.abc import Mapping

from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.instrument import OnlyInstrument


def migrate_instrument_record(
    payload: Mapping[str, object], *, concrete_type: type[OnlyInstrument]
) -> dict[str, object]:
    """Transform a complete schema-1 definition with an explicit authoritative type.

    Missing subtype fields, ambiguous source types and discarded source facts cannot
    be repaired by this transform. Callers must establish those preconditions first.
    Construction may validate, but must not silently normalize any historical field.
    Original fields/IDs remain unchanged; only schema and the explicit type tag change.
    Repeated migration of schema 2 is rejected rather than interpreted as new work.
    """
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise OnlySerializationError("Instrument migration requires a schema-1 record")
    if "model_type" in payload or not issubclass(concrete_type, OnlyInstrument):
        raise OnlySerializationError("Instrument migration requires an authoritative concrete type")
    migrated = dict(payload, schema_version=2, model_type=concrete_type.__name__)
    restored = concrete_type.from_dict(migrated)
    if restored.to_dict() != migrated:
        raise OnlySerializationError("Instrument migration cannot normalize historical fields")
    return migrated
