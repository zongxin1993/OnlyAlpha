"""Guards the single product interface and configuration path."""

import inspect
from dataclasses import fields
from pathlib import Path

import pytest

import onlyalpha
from onlyalpha.config import OnlyOutputConfig
from onlyalpha.engine import OnlyEngine


def test_engine_requires_engine_config_and_string_constructor_is_removed() -> None:
    with pytest.raises(TypeError, match="OnlyEngineConfig"):
        OnlyEngine("engine")  # type: ignore[arg-type]
    assert inspect.signature(OnlyEngine).parameters["config"].annotation == "OnlyEngineConfig"


def test_removed_product_interfaces_are_not_public() -> None:
    assert not hasattr(OnlyEngine, "register_runtime")
    assert not hasattr(onlyalpha, "OnlyRunConfig")
    assert not hasattr(onlyalpha, "OnlyEngineRunService")
    assert not hasattr(onlyalpha, "only_default_run_service")


def test_internal_orchestration_types_are_not_publicly_reexported() -> None:
    for name in (
        "OnlyClusterManager",
        "OnlyRuntimeAssemblyConfig",
        "OnlyRuntimeManager",
        "OnlyStrategyBarDispatcher",
    ):
        assert not hasattr(onlyalpha, name)

    import onlyalpha.engine as engine_api
    import onlyalpha.runtime as runtime_api

    for name in (
        "OnlyClusterSession",
        "OnlyEngineExecutionPlan",
        "OnlyInfrastructureRegistry",
        "OnlyRuntimeCompatibilityKey",
        "OnlyRuntimePlan",
        "OnlyRuntimePlanner",
        "OnlyRuntimeSession",
    ):
        assert name not in engine_api.__all__
        assert name not in runtime_api.__all__


def test_output_configuration_has_no_independent_root() -> None:
    assert {item.name for item in fields(OnlyOutputConfig)} == {"formats", "overwrite"}


def test_removed_interface_tokens_do_not_return_to_source() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    for token in (
        "_product_mode",
        "_legacy_runtimes",
        "OnlyEngineRunService",
        "only_default_run_service",
        "OnlyRuntimeResultExporter",
        "DeprecationWarning",
    ):
        assert token not in source


def test_core_source_does_not_depend_on_sibling_repositories_or_tests() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    for token in ("OnlyAlpha-examples", "OnlyAlpha-plugins", "onlyalpha_examples", "from tests", "import tests"):
        assert token not in source
