from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_suite import OnlyTestLane
from scripts.verify import (
    VerificationChangedPath,
    VerificationChangeSet,
    VerificationEscalation,
    plan_for_change_set,
)

pytestmark = pytest.mark.architecture
ROOT = Path(".")

FORBIDDEN_PARALLEL_AUTHORITIES = (
    "project-state.toml",
    "AGENTS.override.md",
    "scripts/project_state.py",
    "scripts/local_verify.py",
)


def _plan(*paths: str):  # type: ignore[no-untyped-def]
    changes = tuple(VerificationChangedPath(path) for path in paths)
    return plan_for_change_set(VerificationChangeSet("1" * 40, changes, bool(changes)))


def test_task_acceptance_has_one_normative_repository_authority() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "不得创建第二份任务验收 Authority" in agents
    assert (
        "Goal\nModification Scope\nExpected Impact Scope\nRequired Behavior\nAcceptance Tests\nOut of Scope\nStop Condition\nConstitution Impact"
        in agents
    )
    assert "Risk-Tiered + Impact-Aware" in agents
    assert "Scope、Severity 与 Hard Stop" in agents
    assert "bounded Independent Review" in agents
    assert "GitHub CI 是持续质量探针" in agents
    assert "Major Milestone Phase Gate" in agents

    for path in FORBIDDEN_PARALLEL_AUTHORITIES:
        assert not (ROOT / path).exists(), path


def test_simplicity_review_is_bounded_and_subordinate_to_task_acceptance() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    third_party = (ROOT / "docs/third_party_quality_gates.md").read_text(encoding="utf-8")
    quality_policy = (ROOT / "quality-policy.toml").read_text(encoding="utf-8")

    assert "Simplicity / Accidental Complexity Control" in agents
    assert "@ponytail-review" in agents
    assert "Ponytail 不拥有任务验收 Authority" in agents
    assert "bounded Simplicity Review 已完成（涉及非平凡 executable code 时）" in agents
    assert "Modification Scope + 真实 Impact Scope" in agents
    assert "REJECT_AS_ESSENTIAL" in agents

    assert "Ponytail is an Agent-side simplicity discipline" in third_party
    assert "not added to `quality-policy.toml`" in third_party
    assert "@ponytail-audit` must not be used to turn an ordinary task into a repository-wide cleanup" in third_party
    assert "ponytail" not in quality_policy.lower()


def test_repository_does_not_version_quality_reports_or_progress_state() -> None:
    assert not (ROOT / "docs/reports").exists()
    assert not (ROOT / "project-state.toml").exists()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "当前状态" not in readme
    assert "project-state.toml" not in readme
    assert "Final-SHA Certification" not in readme


def test_verifier_is_stateless_worktree_selector() -> None:
    source = (ROOT / "scripts/verify.py").read_text(encoding="utf-8")

    assert 'add_argument("--base"' not in source
    assert "base_revision" not in source
    assert "LOG_ROOT" not in source
    assert "manifest.json" not in source
    assert "IMPACT_SELECTION_ONLY" in source
    assert "resolve_change_set()" in source

    plan = _plan("src/onlyalpha/strategy/model.py")
    payload = plan.as_json()
    assert payload["authority"] == "IMPACT_SELECTION_ONLY"
    assert "base_revision" not in payload["change_set"]  # type: ignore[operator]


def test_quality_infrastructure_is_high_risk_but_bounded() -> None:
    plan = _plan("AGENTS.md", "scripts/verify.py")

    assert plan.impact.escalation is VerificationEscalation.QUALITY_INFRASTRUCTURE
    assert OnlyTestLane.ARCHITECTURE in plan.impact.lanes
    assert OnlyTestLane.EXHAUSTIVE not in plan.impact.lanes
    assert OnlyTestLane.RELEASE not in plan.impact.lanes


def test_runtime_history_retention_is_separate_from_dev_data_reset() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "均为可丢弃开发数据，不属于兼容性、迁移或升级保留目标" in agents
    assert "必须成套清理并重新初始化，禁止只删 user-data 后重绑未清理的数据库" in agents
    assert "普通启动不隐式清库，不因每轮验证自动重建" in agents
    assert "数据已重置，不能称为历史迁移成功" in agents
    assert "当前版本新产生的数据仍须满足 exact identity、引用完整性、持久化和正常停机重启" in agents
    assert "可丢弃旧开发数据不授权绕过当前运行的 Authority 或 UNKNOWN" in agents
    assert "正式部署默认保护历史数据" in agents
    assert "开发期的清空许可不能扩展到正式部署" in agents
    assert "缺失或不匹配的历史、密钥、namespace 必须 fail closed，不能静默采用新存储" in agents
    assert "fresh reader/process restart、真实服务停机重启、格式迁移和真实部署升级" in agents


def test_docs_only_change_does_not_expand_to_executable_lanes() -> None:
    plan = _plan("README.md")

    assert plan.impact.escalation is VerificationEscalation.DOCS_ONLY
    assert plan.impact.lanes == ()
    assert plan.impact.checks == ()


def test_unclassified_path_does_not_trigger_automatic_full_repo_gate() -> None:
    plan = _plan("tools/new_component/config.yaml")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == ()
    assert any(reason.rule == "manual-impact-review-required" for reason in plan.impact.reasons)
