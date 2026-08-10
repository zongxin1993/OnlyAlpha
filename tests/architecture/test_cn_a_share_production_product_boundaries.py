from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_ROOT = ROOT / "src" / "onlyalpha" / "execution"
PRODUCTION_ROOT = ROOT / "src" / "onlyalpha"
PRODUCT_CONFORMANCE_ROOT = ROOT / "tests" / "conformance" / "cn_a_share_production"

FORBIDDEN_PRODUCT_FRAMEWORK_IDENTIFIERS = frozenset(
    {
        "OnlyProductFramework",
        "OnlyMarketProductRegistry",
        "OnlyProductCapabilityDSL",
        "OnlyConformancePluginRegistry",
        "OnlyProductProviderSPI",
    }
)
FORBIDDEN_COMPATIBILITY_IDENTIFIERS = (
    "legacy_ashare",
    "ashare_v1_compat",
    "generic_t0_compat",
    "fallback_fee_pack",
    "fallback_reference",
)
FORBIDDEN_HARNESS_INTERNAL_MODULES = (
    "onlyalpha.execution.accepted_planner",
    "onlyalpha.execution.processor",
    "onlyalpha.execution.projection_targets",
    "onlyalpha.execution.terminal_planner",
    "onlyalpha.execution.trade_planner",
    "onlyalpha.transaction.coordinator",
    "onlyalpha.transaction.projection_applier",
)
FORBIDDEN_DIRECT_MUTATION_CALLS = frozenset(
    {
        "apply_execution_projection",
        "apply_fill",
        "apply_trade",
        "commit_transaction",
        "mark_projection_ready",
        "prepare_trade",
        "restore_sellable_quantity",
        "set_sellable_quantity",
    }
)


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def _imported_names(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                yield alias.name
                if alias.asname is not None:
                    yield alias.asname


def _identifiers(tree: ast.AST) -> Iterator[str]:
    yield from _imported_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.name
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield node.arg


def _docstring_node_ids(tree: ast.AST) -> frozenset[int]:
    values: set[int] = set()
    owners = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, owners) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            values.add(id(first.value))
    return frozenset(values)


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _is_negative_membership_guard(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> bool:
    comparison = parents.get(node)
    if not isinstance(comparison, ast.Compare) or comparison.left is not node:
        return False
    if len(comparison.ops) != 1 or not isinstance(comparison.ops[0], ast.NotIn):
        return False
    return isinstance(parents.get(comparison), ast.Assert)


def _executable_strings(tree: ast.AST) -> Iterator[tuple[ast.Constant, str]]:
    docstrings = _docstring_node_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node, node.value


def _attribute_chain(value: ast.expr) -> tuple[str, ...]:
    if isinstance(value, ast.Name):
        return (value.id,)
    if isinstance(value, ast.Attribute):
        return (*_attribute_chain(value.value), value.attr)
    return ()


def _is_direct_authority_type(name: str) -> bool:
    normalized = name.lower()
    return (
        name.endswith("Manager")
        or normalized == "manager"
        or normalized.endswith("_manager")
        or "projection_target" in normalized
        or "trade_planner" in normalized
        or name.endswith("ExecutionTransactionPlanner")
        or normalized
        in {
            "onlyexecutionprocessor",
            "onlyruntimeprojectionapplier",
            "onlyruntimetransactioncoordinator",
            "execution_processor",
            "projection_applier",
            "transaction_coordinator",
        }
    )


def _is_sensitive_private_chain(chain: tuple[str, ...]) -> bool:
    sensitive = (
        "execution_processor",
        "accepted_planner",
        "terminal_planner",
        "trade_planner",
        "projection_target",
        "projection_applier",
        "transaction_coordinator",
    )
    return any(part.startswith("_") and any(value in part.lower() for value in sensitive) for part in chain)


def _is_manager_chain(chain: tuple[str, ...]) -> bool:
    return any(part.lower() == "manager" or part.lower().endswith("_manager") for part in chain)


def test_execution_kernel_has_no_a_share_reference_rule_import_or_routing_literal() -> None:
    violations: list[tuple[str, str]] = []
    for path in _python_files(EXECUTION_ROOT):
        tree = _tree(path)
        for module in _imported_modules(tree):
            if module == "onlyalpha.reference.ashare" or module.startswith("onlyalpha.reference.ashare."):
                violations.append((str(path.relative_to(ROOT)), f"import:{module}"))
            if module == "onlyalpha.market.ashare_rules" or module.startswith("onlyalpha.market.ashare_rules."):
                violations.append((str(path.relative_to(ROOT)), f"import:{module}"))
        for _, value in _executable_strings(tree):
            for token in ("CN_A_SHARE_CASH", "XSHG", "XSHE"):
                if token in value:
                    violations.append((str(path.relative_to(ROOT)), f"literal:{token}"))
        for identifier in _identifiers(tree):
            if "ashare" in identifier.lower():
                violations.append((str(path.relative_to(ROOT)), f"identifier:{identifier}"))

    assert not violations, violations


def test_production_conformance_cannot_bind_test_fee_authority() -> None:
    files = _python_files(PRODUCT_CONFORMANCE_ROOT)
    assert files, "CN A-share Production Product Conformance tests must exist"
    violations: list[tuple[str, str]] = []
    for path in files:
        tree = _tree(path)
        parents = _parent_map(tree)
        for module in _imported_modules(tree):
            if module == "onlyalpha.fee.testing" or module.startswith("onlyalpha.fee.testing."):
                violations.append((str(path.relative_to(ROOT)), f"import:{module}"))
        for identifier in _identifiers(tree):
            if identifier in {"CN_A_SHARE_TEST_MARKET_FEE_PACK", "only_cn_a_share_conformance_fee_pack"}:
                violations.append((str(path.relative_to(ROOT)), f"identifier:{identifier}"))
        for node, value in _executable_strings(tree):
            if value == "CN_A_SHARE_TEST_MARKET_FEE_PACK" and not _is_negative_membership_guard(node, parents):
                violations.append((str(path.relative_to(ROOT)), f"literal:{value}"))

    assert not violations, violations


def test_product_harness_cannot_reach_durable_execution_or_manager_internals() -> None:
    files = _python_files(PRODUCT_CONFORMANCE_ROOT)
    assert files, "Product boundary guard must dynamically cover the conformance harness"
    violations: list[tuple[str, str]] = []
    for path in files:
        tree = _tree(path)
        for module in _imported_modules(tree):
            if any(
                module == forbidden or module.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_HARNESS_INTERNAL_MODULES
            ):
                violations.append((str(path.relative_to(ROOT)), f"internal-import:{module}"))
            if module.endswith(".manager") or module.endswith("_manager"):
                violations.append((str(path.relative_to(ROOT)), f"manager-import:{module}"))
        for identifier in _identifiers(tree):
            if _is_direct_authority_type(identifier):
                violations.append((str(path.relative_to(ROOT)), f"internal-type:{identifier}"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_DIRECT_MUTATION_CALLS:
                violations.append((str(path.relative_to(ROOT)), f"direct-call:{node.func.id}"))
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            chain = _attribute_chain(node.func)
            if _is_manager_chain(chain):
                violations.append((str(path.relative_to(ROOT)), f"manager-call:{'.'.join(chain)}"))
            if _is_sensitive_private_chain(chain):
                violations.append((str(path.relative_to(ROOT)), f"private-execution-call:{'.'.join(chain)}"))
            if node.func.attr in FORBIDDEN_DIRECT_MUTATION_CALLS:
                violations.append((str(path.relative_to(ROOT)), f"direct-call:{'.'.join(chain)}"))

    assert not violations, violations


def test_no_product_framework_or_a_share_compatibility_layer_exists() -> None:
    files = (*_python_files(PRODUCTION_ROOT), *_python_files(PRODUCT_CONFORMANCE_ROOT))
    violations: list[tuple[str, str]] = []
    for path in files:
        relative = str(path.relative_to(ROOT))
        if any(value in relative.lower() for value in FORBIDDEN_COMPATIBILITY_IDENTIFIERS):
            violations.append((relative, "compatibility-path"))
        tree = _tree(path)
        parents = _parent_map(tree)
        for identifier in _identifiers(tree):
            if identifier in FORBIDDEN_PRODUCT_FRAMEWORK_IDENTIFIERS:
                violations.append((relative, f"framework:{identifier}"))
            if any(value in identifier.lower() for value in FORBIDDEN_COMPATIBILITY_IDENTIFIERS):
                violations.append((relative, f"compatibility-identifier:{identifier}"))
        for node, value in _executable_strings(tree):
            forbidden = next(
                (
                    item
                    for item in (*FORBIDDEN_PRODUCT_FRAMEWORK_IDENTIFIERS, *FORBIDDEN_COMPATIBILITY_IDENTIFIERS)
                    if item in value
                ),
                None,
            )
            if forbidden is not None and not _is_negative_membership_guard(node, parents):
                violations.append((relative, f"forbidden-literal:{forbidden}"))

    assert not violations, violations
