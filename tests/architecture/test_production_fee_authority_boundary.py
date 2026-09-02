from pathlib import Path

from onlyalpha_plugin_cn_ashare.fee_pack import only_cn_a_share_market_fee_pack
from onlyalpha_plugin_cn_ashare.fee_sources import (
    CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID,
)

from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeType


def test_test_fee_pack_is_absent_from_production_defaults_examples_and_public_exports() -> None:
    targets = (
        Path("src/onlyalpha/runtime/defaults.py"),
        Path("src/onlyalpha/fee/__init__.py"),
        Path("src/onlyalpha/fee/packs/__init__.py"),
        *Path("examples").rglob("*.yaml"),
        Path("README.md"),
    )
    offenders = tuple(str(path) for path in targets if "CN_A_SHARE_TEST_MARKET_FEE_PACK" in path.read_text())
    assert offenders == ()


def test_production_pack_contains_no_broker_authority_or_commission() -> None:
    pack = only_cn_a_share_market_fee_pack()
    rules = tuple(rule for schedule in pack.schedules for rule in schedule.rules)
    assert all(rule.authority not in {OnlyFeeAuthority.BROKER, OnlyFeeAuthority.PLATFORM} for rule in rules)
    assert all(rule.fee_type is not OnlyFeeType.BROKER_COMMISSION for rule in rules)


def test_production_sources_are_registered_and_not_test_placeholders() -> None:
    forbidden = ("test", "todo", "unknown", "generic conformance")
    for schedule in only_cn_a_share_market_fee_pack().schedules:
        assert schedule.source in CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID
        assert not any(value in schedule.source.lower() for value in forbidden)
        assert schedule.effective_from.year != 1970
        assert not any(value in schedule.schedule_id for value in ("CURRENT", "LATEST", "DEFAULT_CURRENT"))
    known = frozenset(CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID)
    assert all(set(source.supporting_source_ids) <= known for source in CN_A_SHARE_FEE_AUTHORITY_SOURCE_BY_ID.values())


def test_fee_kernel_has_no_cn_a_share_branch_or_symbol_prefix_selection() -> None:
    paths = (
        Path("src/onlyalpha/fee/engine.py"),
        Path("src/onlyalpha/fee/formula.py"),
        Path("src/onlyalpha/fee/accrual.py"),
        Path("src/onlyalpha/fee/reconciliation.py"),
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "CN_A_SHARE" not in text
        assert not any(
            value in text
            for value in (
                'symbol.startswith("',
                "symbol.startswith('",
                'instrument_id.startswith("',
                "instrument_id.startswith('",
            )
        )
