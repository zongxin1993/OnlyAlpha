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


RETIRED_PATHS = (
    "project-state.toml",
    "AGENTS.override.md",
    "scripts/project_state.py",
    "scripts/local_verify.py",
    "docs/engineering/quality-system.md",
    "docs/engineering/quality-toolchain.md",
    "docs/engineering/task-gate-template.md",
    "docs/engineering/project-state-authority.md",
    "docs/engineering/convergent-audit-policy.md",
    "docs/engineering/local-verification-execution-policy.md",
)

SEMANTIC_SUCCESSORS = {
    "tests/architecture/test_a0_product_vertical_boundaries.py": "tests/architecture/test_backtest_product_boundary.py",
    "tests/architecture/test_p9_k0_api_core_crossings.py": "tests/architecture/test_api_core_crossings.py",
    "tests/architecture/test_p9_k0_authority_contract.py": "tests/architecture/test_product_authority_contract.py",
    "tests/architecture/test_p9_k0_authority_ownership.py": "tests/architecture/test_authority_ownership.py",
    "tests/architecture/test_p9_k0_capability_reachability.py": "tests/architecture/test_capability_reachability.py",
    "tests/architecture/test_p9_k0_composition_ownership.py": "tests/architecture/test_composition_ownership.py",
    "tests/architecture/test_p9_k0_product_surfaces.py": "tests/architecture/test_product_surface_boundaries.py",
    "tests/architecture/test_p9_k0_transport_boundary.py": "tests/architecture/test_transport_boundary.py",
    "tests/architecture/_p9_k0_capability_reachability.py": "tests/architecture/_capability_reachability.py",
    "tests/architecture/test_p9_k3_product_http_control_plane.py": "tests/architecture/test_product_http_control_plane.py",
    "tests/architecture/test_p9_k5_recovery_closure.py": "tests/architecture/test_kernel_recovery_authority.py",
    "tests/architecture/test_p9_k6_external_client_boundary.py": "tests/architecture/test_product_surface_retirement.py",
    "tests/architecture/test_p9_k7_remote_protocol_boundary.py": "tests/architecture/test_gateway_protocol_boundary.py",
    "tests/architecture/test_p9_k8_kernel_seal.py": "tests/architecture/test_product_authority_seal.py",
    "docs/architecture/p9_k0_authority_contract.toml": "docs/architecture/product_authority_contract.toml",
    "docs/p9_k7_remote_gateway_protocol.md": "docs/gateway_protocol.md",
}

PROCESS_SNAPSHOT_SUCCESSORS = {
    "docs/account_broker_component_analysis.md": (
        "docs/account.md",
        "docs/broker_gateway.md",
        "docs/virtual_broker.md",
    ),
    "docs/clock_analysis.md": ("docs/clock.md",),
    "docs/domain_analysis.md": ("docs/domain_model.md",),
    "docs/event_component_analysis.md": ("docs/event.md", "docs/market_data_pipeline.md"),
    "docs/execution_processor_component_analysis.md": ("docs/execution_processor.md",),
    "docs/market_data_source_component_analysis.md": ("docs/market_data_source.md",),
    "docs/order_component_analysis.md": ("docs/order.md",),
    "docs/position_component_analysis.md": ("docs/position.md",),
    "docs/risk_component_analysis.md": ("docs/risk.md",),
    "docs/runtime_context_analysis.md": ("docs/runtime_context.md",),
    "docs/strategy_ledger_component_analysis.md": ("docs/strategy_ledger.md",),
    "docs/time_model_analysis.md": ("docs/time_model.md",),
    "docs/integration_vertical_slice.md": ("docs/testing.md",),
    "docs/nautilus_research.md": (
        "docs/engineering/reference_registry.md",
        "docs/engineering/open_source_engineering_evidence.md",
        "docs/domain_model.md",
    ),
}

PROCESS_TEST_SUCCESSORS = {
    "tests/contracts/test_p9_k7_task_delta.py": (
        "scripts/gateway_protocol.py",
        "tests/contracts/test_gateway_protocol_contract.py",
    ),
}


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

    for retired in RETIRED_PATHS:
        assert not (ROOT / retired).exists(), retired


def test_repository_does_not_version_quality_reports_or_progress_state() -> None:
    assert not (ROOT / "docs/reports").exists()
    assert not (ROOT / "project-state.toml").exists()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "当前状态" not in readme
    assert "project-state.toml" not in readme
    assert "Final-SHA Certification" not in readme


def test_retired_phase_coupled_assets_have_semantic_successors() -> None:
    for retired, successor in SEMANTIC_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        assert (ROOT / successor).is_file(), successor


def test_process_snapshots_are_replaced_by_current_domain_documents() -> None:
    for retired, successors in PROCESS_SNAPSHOT_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        for successor in successors:
            assert (ROOT / successor).is_file(), successor


def test_process_tests_are_replaced_by_durable_contract_verification() -> None:
    for retired, successors in PROCESS_TEST_SUCCESSORS.items():
        assert not (ROOT / retired).exists(), retired
        for successor in successors:
            assert (ROOT / successor).is_file(), successor


def test_one_time_replay_audit_is_not_versioned_as_current_documentation() -> None:
    assert not (ROOT / "docs/replay_contract_correctness_audit.md").exists()


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
