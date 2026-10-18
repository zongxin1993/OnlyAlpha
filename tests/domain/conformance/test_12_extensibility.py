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
    values.pop("model_type")
    bond = OnlyBond.from_dict(
        {"schema_version": 2, "model_type": "OnlyBond", "instrument_type": "SYNTHETIC", "asset_class": "FUND", **values}
    )
    assert isinstance(bond, OnlyInstrument)


def test_catalog_restores_only_explicitly_declared_extension_types(equity) -> None:
    import pytest

    from onlyalpha.domain.catalog import OnlyInstrumentCatalog
    from onlyalpha.domain.errors import OnlySerializationError

    payload = equity.to_dict()
    payload.update(model_type="OnlyBond", asset_class="FUND", instrument_type="SYNTHETIC")
    bond = OnlyBond.from_dict(payload)
    catalog = OnlyInstrumentCatalog((bond,))
    with pytest.raises(OnlySerializationError):
        OnlyInstrumentCatalog.from_json(catalog.to_json())
    restored = OnlyInstrumentCatalog.from_dict(catalog.to_dict(), instrument_types=(OnlyBond,))
    assert restored == catalog
    with pytest.raises(OnlySerializationError):
        OnlyInstrumentCatalog.from_dict(catalog.to_dict(), instrument_types=(OnlyBond, OnlyBond))


def test_extension_cannot_replace_a_builtin_tag(equity) -> None:
    import pytest

    from onlyalpha.domain.catalog import OnlyInstrumentCatalog
    from onlyalpha.domain.errors import OnlySerializationError

    impostor = type("OnlyEquity", (OnlyBond,), {})
    catalog = OnlyInstrumentCatalog((equity,))
    with pytest.raises(OnlySerializationError):
        OnlyInstrumentCatalog.from_dict(catalog.to_dict(), instrument_types=(impostor,))
