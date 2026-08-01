import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
EXECUTION = ROOT / "src/onlyalpha/execution"


def _calls(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    )


def test_only_close_authority_builder_calls_cost_reduction() -> None:
    production_files = tuple(EXECUTION.rglob("*.py"))
    callers = tuple(
        path.relative_to(ROOT).as_posix() for path in production_files if _calls(path, "only_reduce_average_cost_close")
    )

    assert callers == ("src/onlyalpha/execution/close_cost_authority.py",)


def test_position_and_allocation_reducers_consume_shared_authority() -> None:
    source = (EXECUTION / "reducers/trade_state.py").read_text(encoding="utf-8")

    assert source.count("close_authority: OnlyAttributedCloseCostAuthority | None") == 2
    assert "only_reduce_average_cost_close" not in source
    assert "legacy_close" not in source
    assert "compatibility_mode" not in source


def test_close_authority_adds_no_store_coordinator_or_recovery_phase() -> None:
    source = (EXECUTION / "close_cost_authority.py").read_text(encoding="utf-8")

    assert "Store" not in source
    assert "Coordinator" not in source
    assert "RecoveryPhase" not in source
