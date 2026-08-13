import ast
from pathlib import Path

import pytest

from onlyalpha.runtime.research.factory import OnlyResearchRuntimeFactory

pytestmark = pytest.mark.architecture


def test_research_calculation_has_no_trading_or_product_authority_imports() -> None:
    forbidden = {
        "account",
        "broker",
        "cluster",
        "engine",
        "execution",
        "fee",
        "margin",
        "order",
        "position",
        "risk",
        "runtime",
        "settlement",
    }
    for path in Path("src/onlyalpha/research/calculation").rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
        assert not any(module.split(".")[1:2] and module.split(".")[1] in forbidden for module in imports)


def test_calculation_core_does_not_import_research_or_arrow() -> None:
    for path in Path("src/onlyalpha/calculation").rglob("*.py"):
        source = path.read_text()
        assert "onlyalpha.research" not in source
        assert "pyarrow" not in source


def test_research_runtime_remains_unsupported() -> None:
    result = OnlyResearchRuntimeFactory().create(None)
    assert not result.supported
    assert result.failure_code == "UNSUPPORTED_RUNTIME_TYPE"


def test_plugin_research_backend_does_not_reuse_trading_indicator_classes() -> None:
    source = Path(
        "packages/indicator/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators/research.py"
    ).read_text()
    assert "update_bar" not in source
    assert "OnlyStandardBarIndicator" not in source
    assert "OnlyMacdIndicator" not in source
