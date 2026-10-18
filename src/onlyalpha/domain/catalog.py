"""Pure effective-dated catalogs for historical domain definitions."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from onlyalpha.domain.base import OnlyDomainModel, only_require_immutable_tuple
from onlyalpha.domain.errors import OnlySerializationError, OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import ONLY_INSTRUMENT_MODEL_TYPES, OnlyInstrument


@dataclass(frozen=True, slots=True)
class OnlyInstrumentCatalog(OnlyDomainModel):
    """Immutable collection resolving one Instrument definition at an as-of time."""

    instruments: tuple[OnlyInstrument, ...]

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object], *, instrument_types: tuple[type[OnlyInstrument], ...] = ()
    ) -> Self:
        if not instrument_types:
            return super(OnlyInstrumentCatalog, cls).from_dict(payload)
        readers = {model.__name__: model for model in instrument_types}
        if len(readers) != len(instrument_types) or any(
            not issubclass(model, OnlyInstrument)
            or model.__name__ in {builtin.__name__ for builtin in ONLY_INSTRUMENT_MODEL_TYPES}
            for model in instrument_types
        ):
            raise OnlySerializationError("extension Instrument types must be unique and cannot replace builtins")
        if (
            type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != cls.schema_version
            or set(payload) != {"schema_version", "instruments"}
            or not isinstance(payload["instruments"], list)
        ):
            raise OnlySerializationError("invalid InstrumentCatalog payload")
        instruments = []
        for item in payload["instruments"]:
            if not isinstance(item, Mapping):
                raise OnlySerializationError("catalog instrument must be a mapping")
            tag = item.get("model_type")
            target = readers.get(tag) if isinstance(tag, str) else None
            instruments.append((target or OnlyInstrument).from_dict(item))
        return cls(tuple(instruments))

    def __post_init__(self) -> None:
        only_require_immutable_tuple(self.instruments)
        keys = [(item.instrument_id, item.instrument_version) for item in self.instruments]
        if len(keys) != len(set(keys)):
            raise OnlyValidationError("instrument catalog contains a duplicate version")

    def resolve(self, instrument_id: OnlyInstrumentId, as_of: datetime) -> OnlyInstrument:
        matches = [
            item for item in self.instruments if item.instrument_id == instrument_id and item.is_effective_at(as_of)
        ]
        if len(matches) != 1:
            raise OnlyValidationError(
                f"expected exactly one effective version for {instrument_id} at {as_of.isoformat()}"
            )
        return matches[0]
