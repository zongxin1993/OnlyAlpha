from dataclasses import dataclass, field

from onlyalpha.domain.enums import OnlyAssetClass, OnlyInstrumentType
from onlyalpha.domain.instrument import OnlyInstrument


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyBond(OnlyInstrument):
    instrument_type: OnlyInstrumentType = field(default=OnlyInstrumentType.SYNTHETIC, init=False)
    asset_class: OnlyAssetClass = field(default=OnlyAssetClass.FUND, init=False)


def test_new_asset_can_extend_instrument_without_outer_modules(equity) -> None:
    values = equity.to_dict()
    values.pop("schema_version")
    values.pop("instrument_type")
    values.pop("asset_class")
    bond = OnlyBond.from_dict({"schema_version": 1, "instrument_type": "SYNTHETIC", "asset_class": "FUND", **values})
    assert isinstance(bond, OnlyInstrument)
