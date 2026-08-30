import ast
import importlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "onlyalpha"


def test_core_does_not_import_binance_provider_adapter() -> None:
    violations: list[str] = []
    for path in CORE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = () if node.module is None else (node.module,)
            else:
                continue
            if any(name.startswith("onlyalpha_plugin_binance") for name in names):
                violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_core_business_code_does_not_hard_code_p9_2_symbols() -> None:
    violations = [
        str(path.relative_to(ROOT))
        for path in CORE.rglob("*.py")
        if "BTCUSDT" in path.read_text(encoding="utf-8") or "ETHUSDT" in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_binance_data_source_is_discoverable_through_existing_spi() -> None:
    pyproject = ROOT / "packages" / "provider" / "onlyalpha-plugin-binance" / "pyproject.toml"
    raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    target = raw["project"]["entry-points"]["onlyalpha.data_sources"]["binance"]
    module_name, attribute = target.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute)
    assert factory.descriptor.plugin_id == "binance"
