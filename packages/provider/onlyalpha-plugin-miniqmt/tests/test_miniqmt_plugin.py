from pathlib import Path

import pytest
from onlyalpha_plugin_miniqmt.config import (
    DEFAULT_USERDATA_MINI_PATH,
    OnlyMiniQmtConfig,
)
from onlyalpha_plugin_miniqmt.data_source.reference import ashare_reference
from onlyalpha_plugin_miniqmt.descriptor import BROKER_CAPABILITIES
from onlyalpha_plugin_miniqmt.errors import OnlyMiniQmtError
from onlyalpha_plugin_miniqmt.mapping.exchange import from_xt_symbol, to_xt_symbol
from onlyalpha_plugin_miniqmt.mapping.order import (
    FIX_PRICE,
    STOCK_BUY,
    map_side,
    require_limit,
)
from onlyalpha_plugin_miniqmt.mapping.status import map_order_status

from onlyalpha.broker.enums import OnlyBrokerCapability
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.identifiers import OnlyInstrumentId


def test_strict_config_and_default_path(tmp_path: Path) -> None:
    assert OnlyMiniQmtConfig.parse({}).userdata_mini_path == DEFAULT_USERDATA_MINI_PATH
    assert OnlyMiniQmtConfig.parse({"userdata_mini_path": str(tmp_path)}).require_path() == tmp_path
    with pytest.raises(OnlyMiniQmtError, match="unknown fields") as error:
        OnlyMiniQmtConfig.parse({"qmt_path": "bad"})
    assert error.value.code == "MINIQMT_CONFIG_INVALID"


def test_missing_path_is_structured(tmp_path: Path) -> None:
    with pytest.raises(OnlyMiniQmtError) as error:
        OnlyMiniQmtConfig(tmp_path / "missing").require_path()
    assert error.value.code == "MINIQMT_PATH_NOT_FOUND"


def test_exchange_order_and_status_mappings() -> None:
    instrument = OnlyInstrumentId.parse("600000.XSHG")
    assert from_xt_symbol("600000.SH") == instrument and to_xt_symbol(instrument) == "600000.SH"
    assert map_side(OnlyOrderSide.BUY) == STOCK_BUY and require_limit(OnlyOrderType.LIMIT) == FIX_PRICE
    assert map_order_status(52) is OnlyOrderStatus.PARTIALLY_FILLED


def test_import_does_not_require_xtquant() -> None:
    import onlyalpha_plugin_miniqmt

    assert onlyalpha_plugin_miniqmt.PLUGIN_ID == "miniqmt"


def test_miniqmt_does_not_claim_unimplemented_fee_evidence_query() -> None:
    assert not BROKER_CAPABILITIES.query_fee_evidence
    assert OnlyBrokerCapability.QUERY_FEE_EVIDENCE.value == "QUERY_FEE_EVIDENCE"


def test_enriched_frozen_reference_maps_without_xtquant_import() -> None:
    reference = ashare_reference(
        {
            "instrument_id": "300001.XSHE",
            "exchange": "SZSE",
            "security_type": "COMMON_STOCK",
            "board": "CHINEXT",
            "MinLimitOrderVolume": "100",
            "PriceTick": "0.01",
            "st_status": False,
            "suspended": False,
            "preClose": "20.00",
            "trading_day": "2025-01-02",
            "effective_to": "2025-01-03",
            "source_version": "miniqmt-fixture-v1",
            "data_version": "reference-v1",
        }
    )
    assert reference.board.value == "CHINEXT"


def test_plain_instrument_detail_cannot_fabricate_historical_reference() -> None:
    with pytest.raises(ValueError, match="MINIQMT_REFERENCE_INVALID"):
        ashare_reference(
            {
                "instrument_id": "300001.XSHE",
                "exchange": "SZSE",
                "MinLimitOrderVolume": "100",
                "PriceTick": "0.01",
            }
        )
