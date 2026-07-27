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
    forbidden_imports = ("manager", "repository", "event_bus", "transaction_store", "runtime")
    forbidden_calls = {"uuid4", "new", "apply_trade", "reserve", "consume", "release"}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]
        names = " ".join(alias.name for node in imports for alias in node.names)
        assert not any(item in names for item in forbidden_imports), path
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls, (path, node.func.attr)
