"""Keep transport adapters outside Core and semantic Application code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
FORBIDDEN_TRANSPORT_IMPORTS = ("fastapi", "starlette", "uvicorn", "onlyalpha_api")


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            result.append(node.module)
    return tuple(result)


def test_core_and_semantic_application_are_transport_neutral() -> None:
    for path in sorted((ROOT / "src/onlyalpha").rglob("*.py")):
        for imported in _imports(path):
            assert not imported.startswith(FORBIDDEN_TRANSPORT_IMPORTS), (
                f"{path.relative_to(ROOT)} imports transport dependency {imported}"
            )


def test_web_is_an_http_client_and_cannot_import_kernel_mutation_capabilities() -> None:
    forbidden_symbols = (
        "OnlyEngine",
        "OnlyRuntime",
        "OnlyStrategyFreezeApplicationService",
        "OnlyStrategyPromotionApplicationService",
        "OnlyFrozenStrategyRevisionStore",
        "OnlyPostgres",
    )
    import_pattern = re.compile(r"(?:from\s+|import\s*\()(?P<quote>['\"])(?P<module>[^'\"]+)(?P=quote)")
    for path in sorted((ROOT / "apps/onlyalpha-web/src").rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        modules = tuple(match.group("module") for match in import_pattern.finditer(source))
        assert all(not module.startswith(("onlyalpha", "onlyalpha_api")) for module in modules), path
        for symbol in forbidden_symbols:
            assert symbol not in source, f"{path.relative_to(ROOT)} reaches Kernel capability {symbol}"
