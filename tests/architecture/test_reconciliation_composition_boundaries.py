import ast
from pathlib import Path

_FACTORIES = (
    Path("src/onlyalpha/runtime/backtest/factory.py"),
    Path("src/onlyalpha/runtime/paper/factory.py"),
    Path("src/onlyalpha/runtime/live/factory.py"),
)


def _imported_names(tree: ast.AST) -> set[str]:
    return {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom) for alias in node.names
    }


def test_runtime_factories_select_but_do_not_install_reconciliation_authority() -> None:
    for path in _FACTORIES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = _imported_names(tree)
        calls = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "OnlyFeeReconciliationPolicyRegistry" not in imports | calls
        assert "only_standard_fee_reconciliation_policy" not in imports | calls


def test_default_composition_is_the_only_runtime_policy_registry_installer() -> None:
    runtime_root = Path("src/onlyalpha/runtime")
    constructors = []
    for path in sorted(runtime_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "OnlyFeeReconciliationPolicyRegistry"
            for node in ast.walk(tree)
        ):
            constructors.append(path)
    assert constructors == [Path("src/onlyalpha/runtime/defaults.py")]


def test_product_code_does_not_reflectively_guess_fee_evidence_capability() -> None:
    for path in sorted(Path("src/onlyalpha").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "hasattr"
                and len(node.args) >= 2
            ):
                continue
            attribute = node.args[1]
            assert not (isinstance(attribute, ast.Constant) and attribute.value == "query_fee_evidence")
