"""Resolve ordinary Python imports/re-exports into P9.K.0 capabilities."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from tests.architecture._p9_k0_authority_contract import AuthorityContract, AuthorityContractError
from tests.architecture._p9_k0_guard_helpers import module_name


class ModuleIndex:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths: dict[str, Path] = {}
        for source_root in (root / "src", root / "packages"):
            for path in source_root.rglob("*.py"):
                name = module_name(path, root)
                if name is not None:
                    self.paths[_package_module(name)] = path

    def capabilities_for_file(self, path: Path, contract: AuthorityContract) -> frozenset[str]:
        module = module_name(path, self.root)
        if module is None:
            source = path.read_text(encoding="utf-8")
            if any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(ast.parse(source))):
                raise AuthorityContractError(f"cannot resolve relative imports for {path}")
            module = f"external.{path.stem}"
        return self.capabilities_for_source(path.read_text(encoding="utf-8"), module, contract, filename=str(path))

    def capabilities_for_source(
        self,
        source: str,
        module: str,
        contract: AuthorityContract,
        *,
        filename: str = "<authority-source>",
    ) -> frozenset[str]:
        tree = ast.parse(source, filename=filename)
        capabilities = self._local_definition_capabilities(module, tree, contract)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    capabilities.update(self.module_capabilities(alias.name, contract))
            elif isinstance(node, ast.ImportFrom):
                imported_module = _resolve_import_from(node, module)
                for alias in node.names:
                    if alias.name == "*":
                        capabilities.update(self.module_capabilities(imported_module, contract))
                    else:
                        capabilities.update(self.symbol_capabilities(imported_module, alias.name, contract))
        return frozenset(capabilities)

    def module_capabilities(
        self,
        module: str,
        contract: AuthorityContract,
        seen: frozenset[str] = frozenset(),
    ) -> frozenset[str]:
        if module in seen:
            return frozenset()
        path = self.paths.get(module)
        if path is None:
            return frozenset()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source_module = module_name(path, self.root) or module
        names = _public_names(tree)
        result: set[str] = set()
        for name in names:
            result.update(self.symbol_capabilities(_package_module(source_module), name, contract, seen | {module}))
        return frozenset(result)

    def symbol_capabilities(
        self,
        module: str,
        symbol: str,
        contract: AuthorityContract,
        seen: frozenset[str] = frozenset(),
    ) -> frozenset[str]:
        qualified = f"{module}.{symbol}"
        result = set(contract.symbol_capabilities.get(qualified, ()))
        marker = f"{module}:{symbol}"
        if marker in seen:
            return frozenset(result)
        path = self.paths.get(module)
        if path is None:
            return frozenset(result)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        source_module = module_name(path, self.root) or module
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imported_module = _resolve_import_from(node, source_module)
                for alias in node.names:
                    local = alias.asname or alias.name
                    if local != symbol:
                        continue
                    if alias.name == "*":
                        result.update(self.module_capabilities(imported_module, contract, seen | {marker}))
                    else:
                        result.update(self.symbol_capabilities(imported_module, alias.name, contract, seen | {marker}))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".", maxsplit=1)[0]
                    if local == symbol:
                        result.update(self.module_capabilities(alias.name, contract, seen | {marker}))
        return frozenset(result)

    @staticmethod
    def _local_definition_capabilities(module: str, tree: ast.Module, contract: AuthorityContract) -> set[str]:
        result: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                result.update(contract.symbol_capabilities.get(f"{module}.{node.name}", ()))
        return result


def actual_capabilities_by_actor(
    root: Path, contract: AuthorityContract, index: ModuleIndex
) -> dict[str, frozenset[str]]:
    result: dict[str, set[str]] = {actor: set() for actor in contract.actors}
    for path in _production_python_paths(root):
        relative = path.relative_to(root).as_posix()
        capabilities = index.capabilities_for_file(path, contract)
        if not capabilities and not contract.is_sensitive_path(relative):
            continue
        actor = contract.classify_path(relative)
        if actor.production:
            result[actor.id].update(capabilities)
    return {actor: frozenset(capabilities) for actor, capabilities in result.items()}


def actual_constructor_sites(root: Path, contract: AuthorityContract, index: ModuleIndex) -> dict[str, frozenset[str]]:
    symbols = {item.symbol: item.id for item in contract.constructors.values()}
    result: dict[str, set[str]] = {identifier: set() for identifier in contract.constructors}
    for path in _production_python_paths(root):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = module_name(path, root)
        if module is None:
            if any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(tree)):
                raise AuthorityContractError(f"cannot resolve relative imports for {path}")
            module = f"external.{path.stem}"
        bindings = _import_bindings(tree, module, index)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            qualified = _qualified_name(node.func, bindings)
            if qualified in symbols:
                result[symbols[qualified]].add(relative)
    return {identifier: frozenset(paths) for identifier, paths in result.items()}


def _production_python_paths(root: Path) -> Iterable[Path]:
    for source_root in (root / "src", root / "packages", root / "scripts", root / "examples"):
        for path in sorted(source_root.rglob("*.py")):
            if "tests" not in path.relative_to(root).parts:
                yield path


def _public_names(tree: ast.Module) -> frozenset[str]:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = node.value
        try:
            literal = ast.literal_eval(value) if value is not None else None
        except (ValueError, TypeError):
            break
        if isinstance(literal, (list, tuple)) and all(isinstance(item, str) for item in literal):
            return frozenset(literal)
        break
    result: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            result.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Import):
            result.update(alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            result.add(node.name)
    return frozenset(name for name in result if not name.startswith("_"))


def _resolve_import_from(node: ast.ImportFrom, module: str) -> str:
    if node.level == 0:
        return node.module or ""
    package = module.rpartition(".")[0]
    parts = package.split(".") if package else []
    retained = len(parts) - (node.level - 1)
    if retained <= 0:
        raise AuthorityContractError(f"relative import escapes package in {module}")
    suffix = [] if node.module is None else node.module.split(".")
    return ".".join((*parts[:retained], *suffix))


def _package_module(module: str) -> str:
    return module.removesuffix(".__init__")


def _import_bindings(tree: ast.Module, module: str, index: ModuleIndex) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", maxsplit=1)[0]
                result[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_import_from(node, module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                result[local] = _canonical_symbol(imported_module, alias.name, index)
    return result


def _canonical_symbol(module: str, symbol: str, index: ModuleIndex, seen: frozenset[str] = frozenset()) -> str:
    marker = f"{module}:{symbol}"
    if marker in seen:
        return f"{module}.{symbol}"
    path = index.paths.get(module)
    if path is None:
        return f"{module}.{symbol}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    source_module = module_name(path, index.root) or module
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        imported_module = _resolve_import_from(node, source_module)
        for alias in node.names:
            if (alias.asname or alias.name) == symbol and alias.name != "*":
                return _canonical_symbol(imported_module, alias.name, index, seen | {marker})
    return f"{module}.{symbol}"


def _qualified_name(expression: ast.expr, bindings: dict[str, str]) -> str | None:
    parts: list[str] = []
    current = expression
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    owner = bindings.get(current.id)
    if owner is None:
        return None
    return ".".join((owner, *reversed(parts)))


__all__ = ["ModuleIndex", "actual_capabilities_by_actor", "actual_constructor_sites"]
