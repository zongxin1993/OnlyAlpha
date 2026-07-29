import ast
from pathlib import Path


def _imports(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }


def test_prepared_transaction_projection_and_store_do_not_import_runtime_managers_or_event_bus() -> None:
    for path in (
        "src/onlyalpha/execution/identity.py",
        "src/onlyalpha/execution/event_identity.py",
        "src/onlyalpha/execution/transaction.py",
        "src/onlyalpha/execution/execution_state.py",
        "src/onlyalpha/execution/state_hash.py",
        "src/onlyalpha/execution/economic_invariants.py",
        "src/onlyalpha/execution/projection.py",
        "src/onlyalpha/execution/codec.py",
        "src/onlyalpha/execution/projection_applier.py",
    ):
        imports = _imports(path)
        assert not any("runtime" in name for name in imports)
        assert not any(name.endswith(".manager") for name in imports)
        assert "onlyalpha.event.bus" not in imports
    store_imports = _imports("src/onlyalpha/runtime/persistence/store.py")
    assert not any(name.endswith(".manager") or ".backtest" in name or ".engine" in name for name in store_imports)
    assert "onlyalpha.event.bus" not in store_imports


def test_new_transaction_commit_port_has_no_two_step_sequence_or_append_contract() -> None:
    source = Path("src/onlyalpha/execution/persistence_ports.py").read_text(encoding="utf-8")
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


def test_prepared_transaction_fixture_is_independent_and_deterministic() -> None:
    source = Path("tests/execution/factories/transaction_factory.py").read_text(encoding="utf-8")
    assert "test_committed_execution_journal" not in source
    assert "test_execution_outbox" not in source
    assert "uuid4" not in source
    assert "OnlyEventId.new" not in source
    assert "only_test_all_projection_types_transaction" not in source
    assert "skip_economic_validation" not in source
    assert "unsafe_create" not in source


def test_replay_correctness_rules_have_no_manager_dependency_or_legacy_formula() -> None:
    presence = Path("src/onlyalpha/execution/reservation_presence.py").read_text(encoding="utf-8")
    invariants = Path("src/onlyalpha/execution/economic_invariants.py").read_text(encoding="utf-8")
    state = Path("src/onlyalpha/execution/execution_state.py").read_text(encoding="utf-8")
    assert not any(name.endswith(".manager") for name in _imports("src/onlyalpha/execution/reservation_presence.py"))
    assert not any(name.endswith(".manager") for name in _imports("src/onlyalpha/execution/economic_invariants.py"))
    assert "reserved_margin.amount - self.occupied_margin.amount" not in state
    assert "skip_economic_validation" not in presence + invariants + state
    assert "OnlyExecutionProcessor" not in presence + invariants + state


def test_replaced_prepared_contract_names_and_loose_projection_payloads_are_absent() -> None:
    paths = (
        "src/onlyalpha/execution/transaction.py",
        "src/onlyalpha/execution/projection.py",
        "src/onlyalpha/execution/codec.py",
        "src/onlyalpha/execution/persistence_ports.py",
        "src/onlyalpha/runtime/persistence/store.py",
        "src/onlyalpha/execution/__init__.py",
    )
    source = "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)
    for replaced in (
        "OnlyReservationExecutionProjection",
        "OnlyExecutionReservationKind",
        "OnlyCashReservationExecutionProjection",
        "owner_scope",
        "before_status",
        "after_status",
        "before_filled_quantity",
        "after_filled_quantity",
        "external_update_id",
        "only_prepared_execution_transaction_hash",
        "prepared_hash",
    ):
        assert replaced not in source
    projection = Path("src/onlyalpha/execution/projection.py").read_text(encoding="utf-8")
    assert "instruction: str\n    before_state: str" not in projection
    assert "fee_records: tuple[str" not in projection
    assert "reservation_state_before: str" not in projection


def test_execution_authority_states_are_strongly_typed_and_store_errors_are_distinct() -> None:
    state = Path("src/onlyalpha/execution/execution_state.py").read_text(encoding="utf-8")
    projection = Path("src/onlyalpha/execution/projection.py").read_text(encoding="utf-8")
    assert "Any" not in state + projection
    assert "dict[str, object]" not in state + projection
    assert "expected_state_hash: str | None" not in Path("src/onlyalpha/execution/transaction.py").read_text(
        encoding="utf-8"
    )

    from onlyalpha.execution import OnlyExecutionTransactionConflict, OnlyRuntimePersistenceStoreError

    assert not issubclass(OnlyRuntimePersistenceStoreError, OnlyExecutionTransactionConflict)
    assert not issubclass(OnlyExecutionTransactionConflict, OnlyRuntimePersistenceStoreError)
