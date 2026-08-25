"""Small canonical import scanner shared by the P9.K.0 architecture guards."""

from __future__ import annotations

import ast
from pathlib import Path

type CanonicalImport = tuple[str, ...]


def module_name(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    parts = relative.parts
    if "src" not in parts:
        return None
    source_index = len(parts) - 1 - tuple(reversed(parts)).index("src")
    module_parts = list(parts[source_index + 1 :])
    module_parts[-1] = Path(module_parts[-1]).stem
    return ".".join(module_parts)


def canonical_imports(source: str, *, module: str | None = None) -> frozenset[CanonicalImport]:
    """Return alias-independent module and symbol capabilities from Python source."""
    tree = ast.parse(source)
    result: set[CanonicalImport] = set()
    package = None if module is None else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(("module", alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(node, package)
            result.update(("symbol", imported_module, alias.name) for alias in node.names)
    return frozenset(result)


def onlyalpha_imports(source: str, *, module: str | None = None) -> frozenset[CanonicalImport]:
    return frozenset(
        capability
        for capability in canonical_imports(source, module=module)
        if len(capability) >= 2 and capability[1].startswith("onlyalpha")
    )


def _resolve_import_from(node: ast.ImportFrom, package: str | None) -> str:
    if node.level == 0:
        return node.module or ""
    if package is None:
        return f"{'.' * node.level}{node.module or ''}"
    package_parts = package.split(".") if package else []
    retained = len(package_parts) - (node.level - 1)
    if retained < 0:
        return f"{'.' * node.level}{node.module or ''}"
    suffix = [] if node.module is None else node.module.split(".")
    return ".".join((*package_parts[:retained], *suffix))


__all__ = ["CanonicalImport", "canonical_imports", "module_name", "onlyalpha_imports"]
