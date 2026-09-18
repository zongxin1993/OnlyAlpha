from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from onlyalpha.quant_assets import OnlyPrivateAssetKind, only_load_private_asset_example_bundle

FACTOR = Path("examples/private-assets/factor/simple_momentum")
STRATEGY = Path("examples/private-assets/strategy/simple_momentum")


def test_portable_example_bundles_are_strict_and_deterministic() -> None:
    factor = only_load_private_asset_example_bundle(FACTOR)
    strategy = only_load_private_asset_example_bundle(STRATEGY)

    assert factor.asset_kind is OnlyPrivateAssetKind.FACTOR
    assert strategy.asset_kind is OnlyPrivateAssetKind.STRATEGY
    assert strategy.dependencies == (factor.example_id,)
    assert len(factor.bundle_fingerprint) == len(strategy.bundle_fingerprint) == 64
    assert only_load_private_asset_example_bundle(FACTOR).bundle_fingerprint == factor.bundle_fingerprint


def test_example_source_is_input_only_and_importer_has_no_execution_or_sql_path() -> None:
    importer = Path("src/onlyalpha/quant_assets/example_seed.py").read_text(encoding="utf-8")
    calls = {
        node.func.id
        for node in ast.walk(ast.parse(importer))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint({"eval", "exec", "compile", "__import__"})
    assert all(token not in importer.upper() for token in ("INSERT INTO", "UPDATE PRIVATE_", "DELETE FROM"))


def test_old_numbered_kind_and_factor_namespace_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "factor" / "legacy"
    root.mkdir(parents=True)
    root.joinpath("asset.json").write_text(
        FACTOR.joinpath("asset.json")
        .read_text(encoding="utf-8")
        .replace('"FACTOR"', '"L3_FACTOR"')
        .replace("private.factor.", "private.factor."),
        encoding="utf-8",
    )
    root.joinpath("source.py").write_text(FACTOR.joinpath("source.py").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError):
        only_load_private_asset_example_bundle(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", True), ("example_id", 1), ("display_name", 1), ("description", 1), ("dependencies", [1])],
)
def test_example_bundle_rejects_type_coercion(tmp_path: Path, field: str, value: object) -> None:
    root = tmp_path / "factor" / "malformed"
    root.mkdir(parents=True)
    payload = json.loads(FACTOR.joinpath("asset.json").read_text(encoding="utf-8"))
    payload[field] = value
    root.joinpath("asset.json").write_text(json.dumps(payload), encoding="utf-8")
    root.joinpath("source.py").write_text(FACTOR.joinpath("source.py").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError):
        only_load_private_asset_example_bundle(root)
