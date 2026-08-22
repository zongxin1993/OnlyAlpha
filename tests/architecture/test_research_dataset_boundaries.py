import ast
from pathlib import Path

import pytest

from onlyalpha.research.dataset.ports import OnlyResearchDatasetSnapshotStore

pytestmark = pytest.mark.architecture


def test_research_dataset_has_no_trading_authority_imports() -> None:
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
    for path in Path("src/onlyalpha/research/dataset").rglob("*.py"):
        tree = ast.parse(path.read_text())
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
        assert not any(
            module.startswith("onlyalpha.")
            and not module.startswith("onlyalpha.research.")
            and module.split(".")[1] in forbidden
            for module in imports
        )


def test_snapshot_store_exposes_no_mutation_api() -> None:
    names = set(OnlyResearchDatasetSnapshotStore.__dict__)
    assert not names.intersection({"update", "append", "overwrite", "invalidate", "delete"})
