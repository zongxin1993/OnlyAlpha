"""P6.4 streaming recovery must remain outside every trading economic authority."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_streaming_recovery_module_has_no_trading_authority_imports() -> None:
    path = Path("src/onlyalpha/runtime/streaming/recovery.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    forbidden = (
        "onlyalpha.account",
        "onlyalpha.execution",
        "onlyalpha.fee",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.settlement",
        "onlyalpha.strategy_ledger",
        "onlyalpha.transaction",
    )
    assert not any(module.startswith(prefix) for module in imports for prefix in forbidden)
    assert "RuntimeMode" not in path.read_text(encoding="utf-8")


def test_unexpected_gap_cutoff_precedes_market_pipeline_in_source() -> None:
    source = Path("src/onlyalpha/data/processor.py").read_text(encoding="utf-8")
    cutoff = source.index("if OnlyMarketDataQualityFlag.UNEXPECTED_GAP in quality.flags:")
    pipeline = source.index("self._pipeline.process_bar", cutoff)
    assert cutoff < pipeline
