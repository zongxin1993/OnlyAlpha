import ast
from pathlib import Path

FORBIDDEN = {
    "datetime.now",
    "datetime.utcnow",
    "date.today",
    "time.time",
    "time.time_ns",
    "time.monotonic",
    "time.monotonic_ns",
    "asyncio.get_event_loop.time",
}
ALLOWLIST = {Path("core/clock.py")}


def test_business_code_does_not_read_system_time_directly() -> None:
    source_root = Path(__file__).parents[2] / "src" / "onlyalpha"
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _attribute_name(node.func)
            if name in FORBIDDEN and relative not in ALLOWLIST:
                violations.append(f"{relative}:{node.lineno}:{name}")
    assert violations == []


def _attribute_name(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))
