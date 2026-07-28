import inspect
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.execution.transaction_store_factory import OnlyDefaultExecutionTransactionStoreFactory
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from tests.integration import (
    test_engine_execution_outbox_restart,
    test_engine_execution_store_restart,
)


def test_backtest_factory_is_the_product_store_composition_root() -> None:
    factory_source = inspect.getsource(OnlyBacktestRuntimeFactory)
    runtime_source = inspect.getsource(OnlyBacktestRuntime)
    assert "execution_transaction_stores.create" in factory_source
    assert "execution_transaction_store=execution_store" in factory_source
    assert "bootstrap_execution_transaction_before" in factory_source
    assert "execution_transaction_store or" not in runtime_source
    assert "OnlyInMemoryExecutionTransactionStore()" not in runtime_source


def test_parser_and_validate_do_not_create_store_resources(tmp_path: Path) -> None:
    parser_source = inspect.getsource(OnlyClusterRunConfig)
    validate_source = inspect.getsource(OnlyBacktestRuntimeFactory.validate)
    assert "SqliteExecution" not in parser_source
    assert "execution_transaction_stores.create" not in validate_source
    OnlyDefaultExecutionTransactionStoreFactory().validate(
        OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json").runtime.execution_store
    )
    assert tuple(tmp_path.iterdir()) == ()


def test_runtime_state_layout_is_independent_of_run_id() -> None:
    source = inspect.getsource(OnlyUserDataLayout.runtime_state_root)
    assert "run_id" not in source
    assert '"state"' in source and '"runtimes"' in source


def test_product_restart_tests_do_not_mutate_runtime_private_state() -> None:
    source = inspect.getsource(test_engine_execution_store_restart) + inspect.getsource(
        test_engine_execution_outbox_restart
    )
    for forbidden in (
        "._services",
        "._state",
        "._clusters",
        "recover_unprojected(",
        "OnlyBacktestRuntime(",
        "execution_commit_coordinator =",
        "execution_outbox_publisher =",
    ):
        assert forbidden not in source
