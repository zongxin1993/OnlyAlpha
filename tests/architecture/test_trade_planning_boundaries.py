import ast
from pathlib import Path


def test_trade_planning_modules_do_not_cross_runtime_mutation_boundaries() -> None:
    root = Path("src/onlyalpha/execution")
    files = [
        root / "planning_context.py",
        root / "planned_trade.py",
        root / "trade_planner.py",
        *sorted((root / "reducers").glob("*.py")),
    ]
    forbidden_modules = (
        "onlyalpha.runtime",
        "onlyalpha.event.bus",
        "onlyalpha.execution.transaction_store",
    )
    forbidden_calls = {"uuid4", "new", "apply_trade", "reserve", "consume", "release"}
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]
        modules = tuple(
            node.module or "" if isinstance(node, ast.ImportFrom) else alias.name
            for node in imports
            for alias in node.names
        )
        assert not any(
            module.startswith(forbidden_modules) or module.endswith(".manager") or ".repositories" in module
            for module in modules
        ), path
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls, (path, node.func.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"uuid4", "time", "time_ns"}, (path, node.func.id)
        assert not any(name in source for name in ("test_only", "skip_validation", "unsafe_dump", "debug_state"))
