from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import onlyalpha.research.novelty as novelty
from onlyalpha.research.novelty import OnlyNoveltyDecisionAuthority, OnlyNoveltyDecisionRequestV2
from tests.architecture._architecture_imports import imported_modules_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).resolve().parents[2]


def test_novelty_decision_authority_is_the_only_public_write_capability() -> None:
    assert not hasattr(novelty, "OnlyNoveltyDecisionBundleStore")
    assert not hasattr(novelty, "only_build_novelty_decision_bundle")
    assert not hasattr(novelty, "only_seal_novelty_decision")
    methods = {name for name in vars(OnlyNoveltyDecisionAuthority) if not name.startswith("_")}
    assert methods == {"seal_from_request", "load_exact", "seal_group_from_requests", "load_group_exact"}


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


def test_prospective_decision_contract_accepts_only_the_canonical_intent_subject() -> None:
    parameters = inspect.signature(OnlyNoveltyDecisionRequestV2).parameters
    assert "evaluation_subject" in parameters
    assert "research_result_fingerprint" not in parameters
    assert "statistics_result_fingerprint" not in parameters
    assert "evaluation_selector" not in parameters
