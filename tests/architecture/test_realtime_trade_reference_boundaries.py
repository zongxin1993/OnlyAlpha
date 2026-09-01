from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_realtime_reference_core_has_no_provider_or_database_latest_price_dependency() -> None:
    core_files = (
        ROOT / "src/onlyalpha/market_data/realtime_state.py",
        ROOT / "src/onlyalpha/execution/reference.py",
        ROOT / "src/onlyalpha/order/service.py",
    )

    source = "\n".join(path.read_text() for path in core_files)

    assert "onlyalpha_plugin_" not in source
    assert "BINANCE" not in source
    assert "clickhouse" not in source.lower()
    assert "SELECT " not in source


def test_trade_reference_foundation_does_not_add_tick_strategy_entry_points() -> None:
    strategy_root = ROOT / "src/onlyalpha/strategy"
    cluster_root = ROOT / "src/onlyalpha/cluster"
    source = "\n".join(
        path.read_text() for root in (strategy_root, cluster_root) for path in sorted(root.rglob("*.py"))
    )

    assert "def on_tick(" not in source
    assert "def on_trade(" not in source
    assert "TickStrategy" not in source
