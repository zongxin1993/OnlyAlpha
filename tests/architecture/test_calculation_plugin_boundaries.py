import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_core_does_not_import_calculation_plugins_or_own_concrete_algorithms() -> None:
    for path in Path("src/onlyalpha").rglob("*.py"):
        imports = _imports(path)
        assert not any(
            name.startswith(
                (
                    "onlyalpha_plugin_indicators",
                    "onlyalpha_plugin_operators",
                    "onlyalpha_example_alpha",
                    "onlyalpha_example_strategies",
                    "onlyalpha_plugin_targets",
                    "onlyalpha_test_plugin",
                )
            )
            for name in imports
        ), path
    forbidden = {
        "macd",
        "ema",
        "sma",
        "rsi",
        "atr",
        "bollinger",
        "rolling_return",
        "rolling_volatility",
        "zscore",
        "rolling_mean",
        "cross_section_percentile",
    }
    assert not forbidden.intersection(
        path.name for path in Path("src/onlyalpha/indicator").iterdir() if any(path.glob("*.py"))
    )


def test_semantic_definition_layer_has_no_runtime_or_trading_authority_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.account",
        "onlyalpha.broker",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.transaction",
    )
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_calculation_semantic_identity_is_separate_from_explicit_implementation_identity() -> None:
    calculation = Path("src/onlyalpha/calculation")
    fingerprint_calls: list[Path] = []
    for path in calculation.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "only_canonical_fingerprint"
            ):
                fingerprint_calls.append(path)
    assert set(fingerprint_calls) == {
        calculation / "definition.py",
        calculation / "equivalence.py",
        calculation / "graph.py",
        calculation / "implementation.py",
    }
    semantic_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in calculation.glob("*.py")
        if path.name not in {"implementation.py", "equivalence.py"}
    )
    for forbidden in ("class_path", "factor_path", "runtime_id", "cluster_id", "created_at", "uuid4"):
        assert forbidden not in semantic_source


def test_external_calculation_fixture_uses_only_public_calculation_contract() -> None:
    fixture = Path(
        "tests/fixtures/external_plugins/onlyalpha_test_plugin/src/onlyalpha_test_plugin/research_calculation.py"
    )
    onlyalpha_imports = {name for name in _imports(fixture) if name.startswith("onlyalpha")}
    assert onlyalpha_imports == {"onlyalpha.calculation"}
    metadata = Path("tests/fixtures/external_plugins/onlyalpha_test_plugin/pyproject.toml").read_text(encoding="utf-8")
    assert '[project.entry-points."onlyalpha.calculations"]' in metadata
    assert "onlyalpha_test_plugin.research_calculation:registrations" in metadata
