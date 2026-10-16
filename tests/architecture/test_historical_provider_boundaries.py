import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture


def test_historical_provider_spi_has_no_runtime_dependencies() -> None:
    source = Path("src/onlyalpha/data/historical/ports.py").read_text()
    tree = ast.parse(source)
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name.startswith(("onlyalpha.runtime", "onlyalpha.event", "onlyalpha.core.clock")) for name in imports
    )
    assert all(name not in source for name in ("runtime_id", "engine_id", "cluster_id", "market_data_sink"))
