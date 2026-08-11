import inspect
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.persistence.factory import OnlyDefaultRuntimePersistenceStoreFactory
from onlyalpha.runtime.trading_facade import OnlyTradingRuntimeFacade


def test_backtest_factory_is_the_product_persistence_composition_root() -> None:
    factory_source = inspect.getsource(OnlyBacktestRuntimeFactory)
    runtime_source = inspect.getsource(OnlyTradingRuntimeFacade)
    assert "runtime_persistence_stores.create" in factory_source
    assert "runtime_persistence_store=persistence_store" in factory_source
    assert "OnlyRuntimeRecoveryOrchestrator" in runtime_source
    assert "OnlyInMemoryRuntimePersistenceStore()" not in runtime_source


def test_parser_and_validate_do_not_create_store_resources(tmp_path: Path) -> None:
    parser_source = inspect.getsource(OnlyClusterRunConfig)
    validate_source = inspect.getsource(OnlyBacktestRuntimeFactory.validate)
    assert "execution_store" not in parser_source
    assert "runtime_persistence_stores.create" not in validate_source
    OnlyDefaultRuntimePersistenceStoreFactory().validate(
        OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json").runtime.persistence
    )
    assert tuple(tmp_path.iterdir()) == ()


def test_runtime_state_layout_is_independent_of_run_id() -> None:
    source = inspect.getsource(OnlyUserDataLayout.runtime_state_root)
    assert "run_id" not in source
    assert '"state"' in source and '"runtimes"' in source


def test_product_restart_tests_do_not_mutate_runtime_private_state() -> None:
    integration = Path(__file__).parents[1] / "integration"
    source = (integration / "test_engine_continuous_restart.py").read_text(encoding="utf-8")
    source += (integration / "test_engine_execution_outbox_restart.py").read_text(encoding="utf-8")
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


def test_removed_restart_bootstrap_and_unsafe_checkpoint_shortcuts_are_absent() -> None:
    root = Path(__file__).parents[2]
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for base in (root / "src", root / "packages", root / "examples")
        for path in base.rglob("*.py")
    )
    for forbidden in (
        "bootstrap_execution_transaction_before",
        "_execution_replay_resume_after",
        "OnlyExecutionStoreConfig",
        "OnlyExecutionTransactionStoreFactory",
        "OnlySqliteExecutionTransactionStore",
    ):
        assert forbidden not in production
    checkpoint_source = "\n".join(
        path.read_text(encoding="utf-8")
        for base in (root / "src" / "onlyalpha" / "runtime" / "checkpoint", root / "packages" / "fake")
        for path in base.rglob("*.py")
    )
    assert "pickle" not in checkpoint_source
    assert ".__dict__" not in checkpoint_source


def test_runtime_factory_does_not_restore_managers_or_analyze_tail() -> None:
    source = inspect.getsource(OnlyBacktestRuntimeFactory)
    assert "restore_checkpoint" not in source
    assert "TailAnalyzer" not in source
    assert "sqlite3" not in source


def test_sqlite_assembly_requires_explicit_plugin_and_cluster_component_capabilities() -> None:
    factory_source = inspect.getsource(OnlyBacktestRuntimeFactory)
    runtime_source = inspect.getsource(OnlyTradingRuntimeFacade)
    assert "_require_checkpoint_capability" in factory_source
    assert "supports_runtime_checkpoint" in factory_source
    assert "checkpoint_capability is None" in runtime_source
    assert "OnlyStatelessRuntimeCheckpointParticipant" in runtime_source
