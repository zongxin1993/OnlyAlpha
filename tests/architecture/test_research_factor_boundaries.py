import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_example_alpha_has_no_trading_authority_or_mutable_factor_lifecycle_imports() -> None:
    forbidden = (
        "onlyalpha.runtime",
        "onlyalpha.cluster",
        "onlyalpha.strategy",
        "onlyalpha.broker",
        "onlyalpha.account",
        "onlyalpha.order",
        "onlyalpha.position",
        "onlyalpha.risk",
        "onlyalpha.reservation",
        "onlyalpha.execution",
        "onlyalpha.transaction",
        "onlyalpha.factor",
    )
    root = Path("examples/onlyalpha-example-alpha/src/onlyalpha_example_alpha")
    for path in root.glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)


def test_factor_backend_cannot_hide_reusable_implementation_or_create_parallel_authority() -> None:
    root = Path("examples/onlyalpha-example-alpha/src/onlyalpha_example_alpha")
    imports = set().union(*(_imports(path) for path in root.glob("*.py")))
    assert not any(
        name.startswith(("onlyalpha.indicator", "onlyalpha_plugin_indicators", "onlyalpha_plugin_operators"))
        for name in imports
    )
    names = {path.name.lower() for path in root.glob("*.py")}
    assert not any(token in name for name in names for token in ("store", "job", "graph", "runtime"))


def test_calculation_core_does_not_depend_on_concrete_factor_plugin() -> None:
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        assert not any(name.startswith("onlyalpha_example_alpha") for name in _imports(path)), path


def test_four_layer_package_placement_and_dependency_direction() -> None:
    assert not Path("plugs/onlyalpha-plugin-factors").exists()
    roots = {
        "operators": Path("plugs/onlyalpha-plugin-operators/src/onlyalpha_plugin_operators"),
        "indicators": Path("plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators"),
        "alpha": Path("examples/onlyalpha-example-alpha/src/onlyalpha_example_alpha"),
        "strategies": Path("examples/onlyalpha-example-strategies/src/onlyalpha_example_strategies"),
    }
    assert all(root.is_dir() for root in roots.values())
    imports = {name: set().union(*(_imports(path) for path in root.glob("*.py"))) for name, root in roots.items()}
    assert not any(
        name.startswith(("onlyalpha_plugin_indicators", "onlyalpha_example")) for name in imports["operators"]
    )
    assert not any(name.startswith("onlyalpha_example") for name in imports["indicators"])
    assert {name for name in imports["strategies"] if name.startswith("onlyalpha")} <= {
        "onlyalpha.quant_assets",
        "onlyalpha_example_strategies",
    }


def test_examples_are_not_default_production_dependencies() -> None:
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")
    project_dependencies = metadata.split("[dependency-groups]", 1)[0]
    assert "onlyalpha-example" not in project_dependencies
    dockerfile = Path("deploy/compose/Dockerfile.acceptance").read_text(encoding="utf-8")
    operator_stage, acceptance_stage = dockerfile.split("FROM operator AS acceptance-operator", 1)
    assert "--no-install-package onlyalpha-example-alpha" in operator_stage
    assert "--no-install-package onlyalpha-example-strategies" in operator_stage
    assert "uv sync --frozen --all-packages --no-dev" in acceptance_stage
    compose_test = Path("deploy/compose/compose.test.yaml").read_text(encoding="utf-8")
    assert compose_test.count("target: acceptance-operator") == 2


def test_example_strategy_is_authoring_data_not_a_python_callback_authority() -> None:
    root = Path("examples/onlyalpha-example-strategies")
    python_source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "def on_bar" not in python_source
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.ClassDef)
            and any(isinstance(base, ast.Name) and base.id == "OnlyStrategy" for base in node.bases)
            for node in ast.walk(tree)
        ), path
    assert not any((root / "simple_momentum").glob("*.py"))


def test_private_asset_path_loading_does_not_enter_core_or_runtime_authority() -> None:
    core_source = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    assert "onlyalpha_example_alpha" not in core_source
    assert "onlyalpha_example_strategies" not in core_source
    strategy_api = Path("examples/onlyalpha-example-strategies/src/onlyalpha_example_strategies/__init__.py").read_text(
        encoding="utf-8"
    )
    assert "onlyalpha." not in strategy_api
    assert "library_root" in strategy_api
    assert "importlib.resources" in strategy_api
