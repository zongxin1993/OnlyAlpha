from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.research.novelty import OnlyNoveltyPolicyStore
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]


def test_novelty_policy_has_only_exact_revision_store_operations() -> None:
    methods = {name for name in vars(OnlyNoveltyPolicyStore) if not name.startswith("_")}
    assert methods == {"put", "load_exact"}


def test_novelty_policy_cannot_reach_fact_decision_or_action_authorities() -> None:
    forbidden = (
        "onlyalpha.application",
        "onlyalpha.research.agent",
        "onlyalpha.research.memory",
        "onlyalpha.research.run",
        "onlyalpha.research.search",
        "onlyalpha.strategy.qualification",
    )
    root = ROOT / "src/onlyalpha/research/novelty"
    for path in root.glob("*.py"):
        imports = imported_modules_for_path(path, ROOT)
        assert not any(name.startswith(forbidden) for name in imports), (path, imports)
