import inspect
from dataclasses import fields
from pathlib import Path

from onlyalpha.engine.infrastructure import OnlyInfrastructureRegistry
from onlyalpha.runtime.defaults import OnlyEngineServices
from onlyalpha.runtime.planning import OnlyRuntimePlanner


def test_planner_only_groups_canonical_environment_identity() -> None:
    source = inspect.getsource(OnlyRuntimePlanner)
    for forbidden in (
        ".broker_fee_contract.",
        ".fee_reconciliation_policy.",
        "reference_registry",
        "data_version",
        "market.fee_pack",
    ):
        assert forbidden not in source


def test_infrastructure_does_not_reinterpret_resource_configs() -> None:
    source = inspect.getsource(OnlyInfrastructureRegistry)
    for forbidden in (
        "OnlyClusterRunConfig",
        "OnlyAccountRuntimeConfig",
        "OnlyBrokerRuntimeConfig",
        "OnlyDataSourceRuntimeConfig",
        "extensions",
        "initial_cash",
    ):
        assert forbidden not in source


def test_engine_services_has_one_registry_owner_by_construction() -> None:
    assert {item.name for item in fields(OnlyEngineServices)} == {"assembler", "plugin_discovery"}


def test_removed_runtime_and_execution_sources_do_not_return() -> None:
    production = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    for forbidden in (
        "OnlyRuntimeCompatibilityKey",
        "LEGACY_UNMIGRATED",
        "_unmigrated_trade",
        "_removed_fee_resolution_path",
        "removed non-durable trade",
        "legacy Trade mutation path",
    ):
        assert forbidden not in production
