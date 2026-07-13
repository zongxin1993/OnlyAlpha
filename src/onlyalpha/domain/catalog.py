"""Pure effective-dated catalogs for historical domain definitions."""

from dataclasses import dataclass
from datetime import datetime

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument


@dataclass(frozen=True, slots=True)
class OnlyInstrumentCatalog(OnlyDomainModel):
    """Immutable collection resolving one Instrument definition at an as-of time."""

    instruments: tuple[OnlyInstrument, ...]

    def __post_init__(self) -> None:
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
