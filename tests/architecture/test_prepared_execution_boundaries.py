import ast
from pathlib import Path


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }


def test_prepared_transaction_projection_and_store_do_not_import_runtime_managers_or_event_bus() -> None:
    for path in (
        "src/onlyalpha/execution/transaction.py",
        "src/onlyalpha/execution/projection.py",
        "src/onlyalpha/execution/transaction_store.py",
        "src/onlyalpha/execution/projection_applier.py",
    ):
        imports = _imports(path)
        assert not any("runtime" in name for name in imports)
        assert not any(name.endswith(".manager") for name in imports)
        assert "onlyalpha.event.bus" not in imports


def test_new_transaction_commit_port_has_no_two_step_sequence_or_append_contract() -> None:
    source = Path("src/onlyalpha/execution/transaction_store.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    protocol = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "OnlyExecutionTransactionCommitPort"
    )
    methods = {node.name for node in protocol.body if isinstance(node, ast.FunctionDef)}
    assert methods == {"commit"}
    assert "pickle" not in source
    assert "deepcopy" not in source
