import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    }


def test_calculation_core_does_not_depend_on_concrete_provider_or_private_example_package() -> None:
    for path in Path("src/onlyalpha/calculation").glob("*.py"):
        imports = _imports(path)
        assert not any(name.startswith(("onlyalpha_plugin_", "onlyalpha_example_")) for name in imports), path


def test_quant_asset_placement_uses_plugins_for_public_capabilities_and_seeds_for_private_assets() -> None:
    assert Path("plugs/onlyalpha-plugin-operators").is_dir()
    assert Path("plugs/onlyalpha-plugin-indicators").is_dir()
    assert Path("examples/private-assets/factor").is_dir()
    assert Path("examples/private-assets/strategy").is_dir()
    assert not Path("examples/onlyalpha-example-factor").exists()
    assert not Path("examples/onlyalpha-example-strategies").exists()
    assert not tuple(Path("examples/private-assets").rglob("pyproject.toml"))
    assert not tuple(Path("examples/private-assets").rglob("provider.py"))


def test_example_seeds_are_not_installed_or_auto_imported() -> None:
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")
    dockerfile = Path("deploy/Dockerfile.dev").read_text(encoding="utf-8")
    application = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/onlyalpha").rglob("*.py"))
    assert "onlyalpha-example-factor" not in metadata + dockerfile
    assert "onlyalpha-example-strategies" not in metadata + dockerfile
    assert "examples/private-assets" not in application


def test_private_seed_source_has_no_direct_runtime_authority() -> None:
    source = Path("examples/private-assets/factor/simple_momentum/source.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert [node.name for node in tree.body if isinstance(node, ast.FunctionDef)] == ["calculate"]
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
