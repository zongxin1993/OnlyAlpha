"""P6.4 streaming recovery must remain outside every trading economic authority."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


@pytest.mark.parametrize("name", ("recovery.py", "recovery_loader.py"))
def test_streaming_recovery_modules_have_no_trading_authority_imports(name: str) -> None:
    path = Path("src/onlyalpha/runtime/streaming") / name
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


def test_streaming_semantic_lane_is_the_only_processor_call_authority() -> None:
    root = Path("src/onlyalpha/runtime/streaming")
    bypasses: list[tuple[Path, int]] = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "process" and isinstance(node.func.value, ast.Attribute):
                if node.func.value.attr in {"_processor", "market_data_processor"}:
                    bypasses.append((path, node.lineno))
    assert [path for path, _line in bypasses] == [root / "semantic_lane.py"]


def test_streaming_phase_state_is_owned_only_by_the_phase_controller() -> None:
    root = Path("src/onlyalpha/runtime/streaming")
    owners: set[Path] = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: tuple[ast.expr, ...]
            if isinstance(node, ast.Assign):
                targets = tuple(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
            else:
                continue
            if any(isinstance(target, ast.Attribute) and target.attr == "_phase" for target in targets):
                owners.add(path)
    assert owners == {root / "phase_controller.py"}


def test_recovery_diagnostic_stage_never_controls_runtime_behavior() -> None:
    path = Path("src/onlyalpha/runtime/streaming/runtime.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    decision_reads = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.While, ast.IfExp)):
            continue
        if any(
            isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load) and child.attr == "_recovery_stage"
            for child in ast.walk(node.test)
        ):
            decision_reads.append(node.lineno)
    assert decision_reads == []


def test_worker_reaction_does_not_commit_processing_result_twice() -> None:
    path = Path("src/onlyalpha/runtime/streaming/runtime.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_handle_worker_result"
    )
    calls = {
        node.func.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "_record_processing_result" not in calls


def test_streaming_runtime_has_one_continuity_authority_and_no_full_history_identity_set() -> None:
    source = Path("src/onlyalpha/runtime/streaming/runtime.py").read_text(encoding="utf-8")
    assert "OnlyStreamingContinuityTracker" in source
    assert "_processed_bar_identities" not in source
    assert "_accepted_market_sequences" not in source
    continuity = Path("src/onlyalpha/runtime/streaming/continuity.py").read_text(encoding="utf-8")
    assert "dedup_capacity" in continuity
    assert "partial" not in continuity.lower()
