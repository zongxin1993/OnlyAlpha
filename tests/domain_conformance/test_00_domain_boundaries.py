import ast
from pathlib import Path


def test_domain_has_no_forbidden_outer_imports() -> None:
    forbidden = {
        "onlyalpha.engine",
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.gateway",
        "onlyalpha.storage",
        "onlyalpha.cache",
        "onlyalpha.web",
        "onlyalpha.api",
        "onlyalpha.backtest",
        "onlyalpha.live",
        "onlyalpha.research",
    }
    imports: set[str] = set()
    for path in Path("src/onlyalpha/domain").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
    assert not {name for name in imports if any(name.startswith(prefix) for prefix in forbidden)}
