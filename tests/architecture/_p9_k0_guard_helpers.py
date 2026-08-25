"""Small canonical import scanner shared by the P9.K.0 architecture guards."""

from __future__ import annotations

import ast
from pathlib import Path

type CanonicalImport = tuple[str, ...]


def module_name(path: Path, root: Path) -> str | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if "src" not in parts:
        package_parts: list[str] = []
        parent = path.parent
        while parent != root and (parent / "__init__.py").is_file():
            package_parts.append(parent.name)
            parent = parent.parent
        if not package_parts:
            return None
        return ".".join((*reversed(package_parts), path.stem))
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
        if len(capability) >= 2 and (capability[1] == "onlyalpha" or capability[1].startswith("onlyalpha."))
    )


def canonical_imports_for_path(path: Path, root: Path) -> frozenset[CanonicalImport]:
    """Return canonical imports using the repository path as module authority."""
    module = module_name(path, root)
    source = path.read_text(encoding="utf-8")
    if module is None and any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(ast.parse(source))):
        raise ValueError(f"cannot resolve relative import module for {path}")
    return canonical_imports(source, module=module)


def onlyalpha_imports_for_path(path: Path, root: Path) -> frozenset[CanonicalImport]:
    return frozenset(
        capability
        for capability in canonical_imports_for_path(path, root)
        if len(capability) >= 2 and (capability[1] == "onlyalpha" or capability[1].startswith("onlyalpha."))
    )


def _resolve_import_from(node: ast.ImportFrom, package: str | None) -> str:
    if node.level == 0:
        return node.module or ""
    if package is None:
        raise ValueError("relative import requires a canonical module identity")
    package_parts = package.split(".") if package else []
    retained = len(package_parts) - (node.level - 1)
    if retained <= 0:
        raise ValueError("relative import escapes the canonical top-level package")
    suffix = [] if node.module is None else node.module.split(".")
    return ".".join((*package_parts[:retained], *suffix))


__all__ = [
    "CanonicalImport",
    "canonical_imports",
    "canonical_imports_for_path",
    "module_name",
    "onlyalpha_imports",
    "onlyalpha_imports_for_path",
]
