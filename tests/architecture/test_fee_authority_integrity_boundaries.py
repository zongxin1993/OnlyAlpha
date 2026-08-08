import ast
import re
from pathlib import Path

ROOT = Path("src/onlyalpha")


def _production_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(ROOT.rglob("*.py")))


def test_deleted_fee_authority_vocabulary_cannot_return() -> None:
    text = _production_text()
    forbidden = (
        "class OnlyFeePolicyPack",
        "class OnlyFeePolicyPackRegistry",
        "fill_effective_schedule_ids",
        "del binding_fingerprint",
        "contracts = quantity",
    )
    assert not tuple(value for value in forbidden if value in text)
    assert re.search(r"\bmarket_fee_schedule_id\b", text) is None


def test_fee_engine_has_no_runtime_broker_account_or_persistence_imports() -> None:
    tree = ast.parse(Path("src/onlyalpha/fee/engine.py").read_text(encoding="utf-8"))
    imported = tuple(
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert not tuple(
        value
        for value in imported
        if value.startswith(("onlyalpha.runtime", "onlyalpha.broker", "onlyalpha.account", "onlyalpha.persistence"))
    )


def test_market_pack_cannot_import_broker_schedule_or_contract() -> None:
    text = Path("src/onlyalpha/fee/market_pack.py").read_text(encoding="utf-8")
    assert "OnlyBrokerFeeSchedule" not in text
    assert "OnlyBrokerFeeContract" not in text


def test_recovery_never_rebinds_restored_orders() -> None:
    recovery = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path("src/onlyalpha/runtime/recovery").rglob("*.py"))
    )
    assert ".bind_order(" not in recovery
