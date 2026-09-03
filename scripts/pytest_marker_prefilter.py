"""Conservative pre-collection isolation for positive-marker canonical lanes."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.pytest_layering import path_concerns

_OPTION = "onlyalpha_prefilter_marker"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--onlyalpha-prefilter-marker",
        action="store",
        dest=_OPTION,
        default=None,
        help="ignore test modules without a statically discoverable target marker before import",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    marker = config.getoption(_OPTION)
    if marker is None or collection_path.suffix != ".py" or collection_path.name in {"conftest.py", "__init__.py"}:
        return None
    return not module_may_contain_marker(collection_path, marker)


def module_may_contain_marker(path: Path, marker: str) -> bool:
    """Fail open on unreadable/invalid syntax so pytest reports the real collection failure."""

    if marker in path_concerns(path):
        return True
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return True
    return any(_marker_name(node) == marker for node in ast.walk(tree))


def _marker_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    value = node.value
    if not isinstance(value, ast.Attribute) or value.attr != "mark":
        return None
    if not isinstance(value.value, ast.Name) or value.value.id != "pytest":
        return None
    return node.attr
