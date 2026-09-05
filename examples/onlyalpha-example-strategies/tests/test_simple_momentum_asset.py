import ast
import subprocess
import sys
from pathlib import Path

from onlyalpha_example_strategies import load_strategy_definition, read_strategy_definition
from onlyalpha_example_strategies.provider import quant_asset_provider

from onlyalpha.quant_assets import only_quant_asset_distribution_artifact_manifest
from onlyalpha.research.definition import OnlyResearchDefinition
from onlyalpha.runtime.generation import OnlyCoreExecutionIdentity

ASSET = Path("examples/onlyalpha-example-strategies/simple_momentum/research-definition.json")


def test_simple_momentum_is_a_canonical_authoring_document_without_runtime_authority() -> None:
    payload = load_strategy_definition("simple_momentum", library_root=ASSET.parents[1])
    definition = OnlyResearchDefinition.from_dict(payload)
    assert definition.display_metadata["name"] == "Simple Momentum Signal"
    assert {item.type_reference.type_id for item in definition.calculations} == {
        "onlyalpha.indicator.rolling_return",
        "example.factor.momentum",
    }
    assert (
        sum(item.type_reference.type_id == "onlyalpha.indicator.rolling_return" for item in definition.calculations)
        == 2
    )
    assert set(payload["signals"]) == {"entry", "exit"}
    serialized = read_strategy_definition("simple_momentum", library_root=ASSET.parents[1]).lower()
    assert not any(token in serialized for token in ("order_quantity", "position_size", "broker", "engine"))
    assert "strategy_id" not in payload


def test_strategy_helper_is_read_only_and_imports_no_onlyalpha_runtime() -> None:
    source = Path("examples/onlyalpha-example-strategies/src/onlyalpha_example_strategies/__init__.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }
    assert not any(name.startswith("onlyalpha") for name in imports)


def test_installed_resource_and_explicit_checkout_path_are_identical() -> None:
    installed = read_strategy_definition("simple_momentum")
    checkout = read_strategy_definition("simple_momentum", library_root=ASSET.parents[1])
    assert installed == checkout


def test_example_strategy_can_bind_the_public_immutable_distribution_contract() -> None:
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    manifest = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-example-strategies",
        source_revision="b" * 40,
        artifact_logical_name="onlyalpha_example_strategies-0.9.9-py3-none-any.whl",
        artifact_bytes=b"example strategy wheel",
        tested_core_execution_fingerprint=core.fingerprint,
        provider=quant_asset_provider(),
    )
    assert manifest.provider_id == "example.strategy.library"
    assert not manifest.implementations
    assert manifest.assets[0].content_fingerprint == quant_asset_provider().strategy_assets[0].content_fingerprint


def test_strategy_asset_path_fails_closed_on_traversal_or_missing_asset() -> None:
    for name in ("../simple_momentum", "missing"):
        try:
            load_strategy_definition(name, library_root=ASSET.parents[1])
        except (ValueError, FileNotFoundError):
            continue
        raise AssertionError(f"invalid asset unexpectedly loaded: {name}")


def test_l4_checkout_supports_explicit_source_path_import(tmp_path: Path) -> None:
    source = Path("examples/onlyalpha-example-strategies/src").resolve()
    script = f"""
import pathlib
import sys
sys.path.insert(0, {str(source)!r})
import onlyalpha_example_strategies
from onlyalpha_example_strategies.provider import quant_asset_provider
assert pathlib.Path(onlyalpha_example_strategies.__file__).resolve().is_relative_to(pathlib.Path({str(source)!r}))
payload = onlyalpha_example_strategies.load_strategy_definition('simple_momentum')
assert payload['display_metadata']['name'] == 'Simple Momentum Signal'
assert quant_asset_provider().strategy_assets[0].semantic_version == '1'
"""
    subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path, check=True)
