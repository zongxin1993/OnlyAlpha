import ast
from pathlib import Path


def test_domain_does_not_import_infrastructure_modules() -> None:
    domain_root = Path("src/onlyalpha/domain")
    forbidden = {
        "engine",
        "runtime",
        "cluster",
        "gateway",
        "web",
        "database",
        "cache",
        "event",
        "backtest",
        "live",
        "research",
    }
    violations: list[str] = []
    for path in domain_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                parts = set(module.split("."))
                if parts & forbidden:
                    violations.append(f"{path}:{node.lineno}:{module}")
    assert not violations, "forbidden Domain imports: " + ", ".join(violations)
