from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.research.novelty import OnlyNoveltyDecisionBundleStore
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]


def test_novelty_decision_store_has_only_put_once_exact_operations() -> None:
    methods = {name for name in vars(OnlyNoveltyDecisionBundleStore) if not name.startswith("_")}
    assert methods == {"seal", "load_exact"}


def test_novelty_decision_has_no_research_action_or_agent_path() -> None:
    forbidden = (
        "onlyalpha.research.agent",
        "onlyalpha.research.command",
        "onlyalpha.research.run",
        "onlyalpha.research.search",
        "onlyalpha.runtime",
    )
    root = ROOT / "src/onlyalpha/research/novelty"
    for path in root.glob("*.py"):
        imports = imported_modules_for_path(path, ROOT)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)
