from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.verify as verify
from scripts.test_suite import LANES, OnlyReleaseCheck, OnlyTestLane
from scripts.verify import (
    ChangeKind,
    VerificationChangedPath,
    VerificationChangeSet,
    VerificationEscalation,
    VerificationImpact,
    VerificationPlan,
    VerificationStepResult,
    plan_for_change_set,
)

HEAD = "1" * 40


def _plan(*paths: str):  # type: ignore[no-untyped-def]
    changes = tuple(VerificationChangedPath(path) for path in paths)
    return plan_for_change_set(VerificationChangeSet(HEAD, changes, bool(changes)))


def test_input_order_is_deterministic_and_rules_union_monotonically() -> None:
    first = _plan("src/onlyalpha/research/job/orchestration.py", "src/onlyalpha/research/calculation/execution.py")
    second = _plan("src/onlyalpha/research/calculation/execution.py", "src/onlyalpha/research/job/orchestration.py")

    assert first.as_json() == second.as_json()
    assert set(first.impact.lanes) == {
        OnlyTestLane.RESEARCH_DEFINITION,
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_RUN,
        OnlyTestLane.RESEARCH_EXECUTION,
        OnlyTestLane.RESEARCH_POSTGRES,
        OnlyTestLane.RESEARCH_CALCULATION,
        OnlyTestLane.RESEARCH_FACTOR,
        OnlyTestLane.RESEARCH_EVALUATION,
        OnlyTestLane.RESEARCH_JOB,
        OnlyTestLane.RESEARCH_SWEEP,
        OnlyTestLane.RESEARCH_RESULT,
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_COMMAND,
        OnlyTestLane.RESEARCH_RUNTIME,
    }


def test_research_definition_change_selects_exact_semantic_consumers() -> None:
    plan = _plan("src/onlyalpha/research/definition/resolver.py")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_DEFINITION,
        OnlyTestLane.RESEARCH_CALCULATION,
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_SWEEP,
    )
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/definition",)
    assert not set(verify.CORE_RECOVERY).intersection(plan.impact.lanes)
    assert not set(verify.WEB_CHECKS).intersection(plan.impact.checks)


def test_unknown_production_path_fails_closed_to_full_local() -> None:
    plan = _plan("src/onlyalpha/new_unknown_core/authority.py")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == ()
    assert plan.impact.checks == (OnlyReleaseCheck.STATIC,)
    assert {reason.rule for reason in plan.impact.reasons} == {"manual-impact-review-required"}


def test_agent_orchestrator_change_selects_canonical_package_and_shared_agent_proof() -> None:
    plan = _plan("packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/runtime.py")

    assert plan.impact.lanes == (
        OnlyTestLane.ARCHITECTURE,
        OnlyTestLane.RESEARCH_AGENT,
        OnlyTestLane.AGENT_ORCHESTRATOR,
    )
    assert {reason.rule for reason in plan.impact.reasons} == {"agent-orchestrator"}
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.ruff_targets == (
        "packages/onlyalpha-agent-orchestrator/src/onlyalpha_agent_orchestrator/runtime.py",
    )


def test_shared_agent_contract_change_selects_orchestrator_consumer() -> None:
    plan = _plan("src/onlyalpha/research/agent/workflow.py")

    assert plan.impact.lanes == (
        OnlyTestLane.ARCHITECTURE,
        OnlyTestLane.RESEARCH_AGENT,
        OnlyTestLane.AGENT_ORCHESTRATOR,
    )
    assert {reason.rule for reason in plan.impact.reasons} == {"research-agent"}
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/agent",)


def test_agent_orchestrator_build_metadata_selects_targeted_package_build() -> None:
    plan = _plan("packages/onlyalpha-agent-orchestrator/pyproject.toml")

    assert OnlyTestLane.AGENT_ORCHESTRATOR in plan.impact.lanes
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.version_sync_required is True
    assert plan.impact.static_plan.build_targets == ("onlyalpha-agent-orchestrator",)


def test_agent_specific_architecture_guards_do_not_expand_to_unrelated_fast_or_integration_lanes() -> None:
    plan = _plan(
        "tests/architecture/test_agent_orchestration_boundaries.py",
        "tests/architecture/test_agent_verification.py",
        "tests/architecture/test_test_lane_contract.py",
    )

    assert set(plan.impact.lanes) == {
        OnlyTestLane.ARCHITECTURE,
        OnlyTestLane.RESEARCH_AGENT,
        OnlyTestLane.AGENT_ORCHESTRATOR,
    }
    assert OnlyTestLane.FAST not in plan.impact.lanes
    assert OnlyTestLane.INTEGRATION not in plan.impact.lanes


def test_research_result_change_is_scoped_to_its_lane_and_static_targets() -> None:
    plan = _plan("src/onlyalpha/research/result/result_store.py", "tests/research/result/test_result_store.py")

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_RESULT,
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_RUNTIME,
    )
    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/result",)
    assert OnlyTestLane.CORE_FULL not in plan.impact.lanes
    assert OnlyTestLane.RESEARCH_EVALUATION not in plan.impact.lanes


def test_research_specification_change_is_component_scoped_without_unrelated_evidence() -> None:
    plan = _plan("src/onlyalpha/research/specification/model.py")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_RUN,
        OnlyTestLane.RESEARCH_EXECUTION,
    )
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/specification",)
    assert not set(verify.CORE_RECOVERY).intersection(plan.impact.lanes)
    assert not set(verify.WEB_CHECKS).intersection(plan.impact.checks)


def test_research_run_and_postgres_changes_select_exact_authority_consumers() -> None:
    run = _plan("src/onlyalpha/research/run/model.py")
    postgres = _plan("database/postgres/migrations/0001_research_run_operational_authority.sql")
    assert run.impact.lanes == (
        OnlyTestLane.RESEARCH_COMMAND,
        OnlyTestLane.RESEARCH_RUN,
        OnlyTestLane.RESEARCH_EXECUTION,
        OnlyTestLane.RESEARCH_POSTGRES,
    )
    assert postgres.impact.lanes == (
        OnlyTestLane.RESEARCH_COMMAND,
        OnlyTestLane.RESEARCH_EXECUTION,
        OnlyTestLane.RESEARCH_POSTGRES,
    )
    assert run.impact.static_plan is not None
    assert "src/onlyalpha/research/run" in run.impact.static_plan.mypy_targets
    assert postgres.impact.static_plan is not None
    assert postgres.impact.static_plan.mypy_targets == ()


def test_research_execution_changes_select_application_and_real_postgres_proofs() -> None:
    plan = _plan("src/onlyalpha/research/execution/worker.py")
    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_EXECUTION,
        OnlyTestLane.RESEARCH_POSTGRES,
    )
    assert plan.impact.static_plan is not None
    assert "src/onlyalpha/research/execution" in plan.impact.static_plan.mypy_targets


def test_research_specification_architecture_gate_is_component_scoped() -> None:
    plan = _plan("tests/architecture/test_research_specification_boundaries.py")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_RUN,
        OnlyTestLane.RESEARCH_EXECUTION,
    )
    assert plan.impact.static_plan is not None and plan.impact.static_plan.import_linter_required


def test_research_workload_change_reaches_compiler_and_runtime_consumers() -> None:
    plan = _plan("src/onlyalpha/research/workload.py")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_EXECUTION,
        OnlyTestLane.RESEARCH_RUNTIME,
    )
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == (
        "src/onlyalpha/research/specification",
        "src/onlyalpha/research/workload.py",
        "src/onlyalpha/runtime/research",
    )


def test_specification_upstream_semantics_propagate_without_downstream_reverse_coupling() -> None:
    sweep = _plan("src/onlyalpha/research/sweep/materialization.py")
    calculation = _plan("src/onlyalpha/calculation/registry.py")
    dataset_identity = _plan("src/onlyalpha/research/dataset/manifest.py")
    dataset_store = _plan("src/onlyalpha/research/dataset/store.py")
    evaluation_contract = _plan("src/onlyalpha/research/evaluation/plan.py")
    evaluation_store = _plan("src/onlyalpha/research/evaluation/result_store.py")
    result_plan = _plan("src/onlyalpha/research/result/plan.py")
    artifact_store = _plan("src/onlyalpha/research/artifact/store.py")

    assert {
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_SWEEP,
        OnlyTestLane.RESEARCH_JOB,
        OnlyTestLane.RESEARCH_RUNTIME,
    }.issubset(sweep.impact.lanes)
    assert OnlyTestLane.RESEARCH_SPECIFICATION in calculation.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION in dataset_identity.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION not in dataset_store.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION in evaluation_contract.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION not in evaluation_store.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION in result_plan.impact.lanes
    assert OnlyTestLane.RESEARCH_SPECIFICATION not in artifact_store.impact.lanes


def test_statistics_authority_change_propagates_to_research_result_consumer() -> None:
    plan = _plan("src/onlyalpha/research/evaluation/result_store.py")

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_EVALUATION,
        OnlyTestLane.RESEARCH_RESULT,
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_RUNTIME,
    )
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == (
        "src/onlyalpha/research/evaluation",
        "src/onlyalpha/research/result",
    )


def test_research_result_architecture_boundary_requests_import_linter_without_full_local() -> None:
    plan = _plan("tests/architecture/test_research_result_boundaries.py")

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_RESULT,
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_RUNTIME,
    )
    assert plan.impact.static_plan is not None and plan.impact.static_plan.import_linter_required
    assert plan.impact.escalation is VerificationEscalation.COMPONENT


def test_research_artifact_change_is_scoped_to_portable_boundary() -> None:
    plan = _plan("src/onlyalpha/research/artifact/store.py", "tests/research/artifact/test_store.py")

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_RUNTIME,
    )
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/artifact",)
    assert plan.impact.escalation is VerificationEscalation.COMPONENT


def test_research_query_and_public_api_changes_use_broad_consumer_proof() -> None:
    plan = _plan(
        "src/onlyalpha/research/query/service.py",
        "packages/backend/src/onlyalpha_http_server/research/routes.py",
        "tests/research/query/test_service.py",
    )

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_ARTIFACT,
        OnlyTestLane.RESEARCH_QUERY,
        OnlyTestLane.RESEARCH_COMMAND,
    )
    assert plan.impact.escalation is VerificationEscalation.BROAD
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ()
    assert plan.impact.static_plan.build_targets == ()
    assert OnlyTestLane.CORE_FULL not in plan.impact.lanes
    assert set(verify.WEB_CHECKS).issubset(plan.impact.checks)


def test_web_only_change_stops_at_api_boundary_and_runs_web_evidence() -> None:
    plan = _plan("packages/frontend/src/charts/researchSeriesProjection.ts")

    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.lanes == ()
    assert plan.impact.checks == verify.WEB_CHECKS
    assert {reason.rule for reason in plan.impact.reasons} == {"research-web"}


def test_research_query_architecture_gate_is_component_scoped() -> None:
    plan = _plan("tests/architecture/test_research_query_boundaries.py")

    assert plan.impact.lanes == (OnlyTestLane.RESEARCH_ARTIFACT, OnlyTestLane.RESEARCH_QUERY)
    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.static_plan is not None and plan.impact.static_plan.import_linter_required


def test_package_metadata_requests_version_sync_and_targeted_build() -> None:
    plan = _plan("pyproject.toml")

    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.version_sync_required
    assert plan.impact.static_plan.build_targets == ("onlyalpha",)


def test_verification_infrastructure_cannot_self_narrow() -> None:
    plan = _plan("scripts/test_suite.py")

    assert plan.impact.escalation is VerificationEscalation.QUALITY_INFRASTRUCTURE
    assert plan.impact.lanes == (OnlyTestLane.ARCHITECTURE,)
    assert plan.impact.checks == (OnlyReleaseCheck.STATIC,)


def test_docs_only_selects_no_runtime_lane_and_mixed_change_cannot_downgrade() -> None:
    docs = _plan("docs/engineering/quality-system.md", "docs/runtime.md")
    mixed = _plan("docs/roadmap.md", "src/onlyalpha/runtime/streaming/recovery.py")

    assert docs.impact.escalation is VerificationEscalation.DOCS_ONLY
    assert docs.impact.lanes == ()
    assert docs.impact.checks == ()
    assert mixed.impact.escalation is VerificationEscalation.BROAD
    assert set(mixed.impact.lanes) == set(verify.CORE_RECOVERY)


def test_shared_core_and_shared_test_fixture_are_conservative() -> None:
    core = _plan("src/onlyalpha/execution/processor.py")
    fixture = _plan("test-data/shared_state.py")

    assert set(core.impact.lanes) == set(verify.CORE_RECOVERY)
    assert core.impact.escalation is VerificationEscalation.BROAD
    assert fixture.impact.lanes == (
        OnlyTestLane.ARCHITECTURE,
        OnlyTestLane.FAST,
        OnlyTestLane.INTEGRATION,
    )
    assert fixture.impact.escalation is VerificationEscalation.BROAD


def test_specific_test_change_uses_component_lane() -> None:
    plan = _plan("tests/research/job/test_orchestration.py")

    assert plan.impact.lanes == (
        OnlyTestLane.RESEARCH_SPECIFICATION,
        OnlyTestLane.RESEARCH_RUNTIME,
        OnlyTestLane.RESEARCH_JOB,
        OnlyTestLane.RESEARCH_SWEEP,
    )
    assert plan.impact.escalation is VerificationEscalation.COMPONENT


def test_rename_and_delete_have_deterministic_impact_semantics() -> None:
    change_set = VerificationChangeSet(
        HEAD,
        (
            VerificationChangedPath(
                "docs/removed_runtime.md",
                ChangeKind.DELETED,
            ),
            VerificationChangedPath(
                "docs/new_name.md",
                ChangeKind.RENAMED,
                "src/onlyalpha/runtime/streaming/old_name.py",
            ),
        ),
        True,
    )
    plan = plan_for_change_set(change_set)

    assert plan.impact.escalation is VerificationEscalation.BROAD
    assert set(plan.impact.lanes) == set(verify.CORE_RECOVERY)
    assert [item.path for item in plan.change_set.changed_paths] == ["docs/new_name.md", "docs/removed_runtime.md"]


def test_name_status_parser_preserves_rename_and_delete() -> None:
    parsed = verify._parse_name_status(b"R100\0old.py\0new.py\0D\0gone.py\0")

    assert parsed == (
        VerificationChangedPath("new.py", ChangeKind.RENAMED, "old.py"),
        VerificationChangedPath("gone.py", ChangeKind.DELETED),
    )


def test_dirty_worktree_and_untracked_files_are_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "--verify"):
            return HEAD + "\n"
        if args == ("rev-parse", "HEAD"):
            return HEAD + "\n"
        if args[0] == "status":
            return "?? new.py\n"
        raise AssertionError(args)

    def fake_git_bytes(*args: str) -> bytes:
        if args[:2] == ("ls-files", "--others"):
            return b"new.py\0"
        if args[0] == "diff":
            return b""
        return fake_git(*args).encode()

    monkeypatch.setattr(verify, "_git", fake_git)
    monkeypatch.setattr(verify, "_git_bytes", fake_git_bytes)

    change_set = verify.resolve_change_set()

    assert change_set.dirty_worktree is True
    assert change_set.changed_paths == (VerificationChangedPath("new.py", ChangeKind.UNTRACKED),)


def test_planner_reuses_canonical_lane_objects_without_copying_lane_semantics() -> None:
    plan = _plan("src/onlyalpha/research/job/orchestration.py")

    assert all(lane in LANES for lane in plan.impact.lanes)
    source = Path("scripts/verify.py").read_text(encoding="utf-8")
    assert "--import-mode" not in source
    assert "not external" not in source
    assert "--durations" not in source
    assert "--cov" not in source


def test_quality_infrastructure_does_not_automatically_run_full_local_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_full_check(check: OnlyReleaseCheck) -> None:
        raise AssertionError(f"unexpected full check: {check}")

    monkeypatch.setattr(verify, "release_check_commands", unexpected_full_check)
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(_plan("scripts/verify.py"))


def test_plan_is_stable_across_fresh_hash_seed_processes() -> None:
    code = (
        "import json; from scripts.verify import *; "
        "c=VerificationChangeSet('1'*40,(VerificationChangedPath('src/onlyalpha/research/job/x.py'),"
        "VerificationChangedPath('src/onlyalpha/research/calculation/y.py')),True); "
        "print(json.dumps(plan_for_change_set(c).as_json(),sort_keys=True))"
    )
    outputs = []
    for seed in ("1", "827"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path.cwd(),
            env=environment,
            capture_output=True,
            check=True,
            text=True,
        )
        outputs.append(completed.stdout)

    assert outputs[0] == outputs[1]


def test_compact_success_output_persists_no_verification_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = (sys.executable, "-c", "print('full successful output retained')")
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "release_check_commands", lambda check: (command,))
    change_set = VerificationChangeSet(HEAD, (VerificationChangedPath("tool.py"),), True)
    plan = VerificationPlan(
        change_set,
        VerificationImpact((), (OnlyReleaseCheck.STATIC,), (), VerificationEscalation.COMPONENT),
    )

    assert verify.run_plan(plan) == 0

    output = capsys.readouterr().out
    assert "PASS check:release-static" in output
    assert "SELECTED CHECKS PASSED" in output
    assert "no verification evidence was persisted" in output
    assert "full successful output retained" not in output
    assert list(tmp_path.rglob("manifest.json")) == []


def test_compact_failure_exposes_command_diagnostic_without_persisted_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    result = VerificationStepResult("lane:research-job", ("false",), 1, 0.5, "short failure diagnostic\n")

    verify._print_result(result)

    output = capsys.readouterr().out
    assert "FAIL lane:research-job" in output
    assert "exit_code=1" in output
    assert "command: false" in output
    assert "short failure diagnostic" in output
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "path",
    [
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "crates/onlyalpha-kernel/predicates/src/lib.rs",
        "test-data/market-data-pipeline/operations-v1.jsonl",
        "test-data/strategy/decisions-v2.jsonl",
        "test-data/order/domain-inputs.json",
        "test-data/position/lifecycle-v1.jsonl",
        "test-data/account/cash-v1.jsonl",
        "test-data/strategy-ledger/valuation-v1.jsonl",
        "test-data/risk/decisions-v1.jsonl",
        "test-data/execution/economics-v1.json",
        "test-data/broker/domain-inputs.json",
        "scripts/broker_reference_check.py",
        "crates/onlyalpha-runtime-persistence/rust/store.rs",
        "crates/onlyalpha-backtest/rust/run.rs",
        "scripts/backtest_replay_check.py",
    ],
)
def test_rust_changes_select_offline_kernel_checks(path: str) -> None:
    plan = _plan(path)
    assert "rust-kernel" in [check.value for check in plan.impact.checks]
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.version_sync_required == (path in {"Cargo.toml", "Cargo.lock"})


@pytest.mark.parametrize(
    "path",
    [
        "crates/onlyalpha-gateway-protocol/Cargo.toml",
        "contracts/gateway/v1/onlyalpha_gateway_protocol/v1/calculation.proto",
        "scripts/gateway_protocol.py",
    ],
)
def test_gateway_wire_and_manifest_changes_select_rust_projection_consumers(path: str) -> None:
    plan = _plan(path)
    assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    assert OnlyTestLane.CALCULATION not in plan.impact.lanes
    if path.startswith("scripts/"):
        with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
            verify.verification_commands(plan)
    else:
        commands = verify.verification_commands(plan)
        native = [command for gate, command in commands if gate == "check:rust-selected"]
        assert "onlyalpha-gateway-protocol" in native[0]
        assert "onlyalpha-calculation-bridge" in native[0]


def test_product_rust_scope_selects_native_checks_and_only_persistence_changes_select_postgres() -> None:
    for path in (
        "packages/backend/src/persistence/postgres.rs",
        "packages/backend/tests/application/test_command_postgres.py",
        "packages/backend/Cargo.toml",
    ):
        plan = _plan(path)
        assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
        assert OnlyTestLane.RESEARCH_POSTGRES in plan.impact.lanes
    session = _plan("packages/backend/src/application/source_access.rs")
    assert OnlyReleaseCheck.RUST_KERNEL in session.impact.checks
    assert OnlyTestLane.RESEARCH_POSTGRES not in session.impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/tests/transport/configuration.rs",
        "packages/backend/tests/transport/deployment.rs",
        "packages/backend/tests/transport/ingress.rs",
        "packages/backend/tests/transport/schema.rs",
        "packages/backend/tests/transport/integration_types.rs",
        "packages/backend/tests/transport/human_access.rs",
        "packages/backend/tests/transport/developer_ingress.rs",
    ],
)
def test_native_http_scope_selects_rust_checks_without_unrelated_postgres_lane(path: str) -> None:
    plan = _plan(path)
    assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    assert OnlyTestLane.RESEARCH_POSTGRES not in plan.impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/application/integration_catalog.rs",
        "packages/backend/src/application/integration_resolver.rs",
        "crates/onlyalpha-integration-contract/rust/authoring.rs",
        "packages/backend/tests/application/test_integration_authoring_postgres.py",
        "packages/backend/tests/application/support/integration.py",
        "tests/support/postgres_link.py",
        "packages/backend/tests/application/support/postgres_probe.rs",
        "tests/support/integration_configuration.py",
    ],
)
def test_authoring_changes_select_postgres_owning_consumer_proof(path: str) -> None:
    plan = _plan(path)
    assert OnlyTestLane.RESEARCH_POSTGRES in plan.impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/bootstrap/deployment.rs",
        "packages/backend/tests/application/test_deployment_postgres.py",
    ],
)
def test_native_deployment_binding_selects_owning_postgres_lane(path: str) -> None:
    assert OnlyTestLane.RESEARCH_POSTGRES in _plan(path).impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/persistence/schema.rs",
        "packages/backend/tests/application/test_schema_postgres.py",
    ],
)
def test_native_schema_reader_selects_owning_postgres_lane(path: str) -> None:
    assert OnlyTestLane.RESEARCH_POSTGRES in _plan(path).impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/transport/integrations.rs",
        "packages/backend/src/bootstrap/node.rs",
        "packages/backend/tests/transport/node.rs",
        "packages/backend/tests/transport/conftest.py",
        "packages/backend/tests/transport/test_native_node_authority.py",
        "packages/backend/src/transport/integration_types.rs",
        "packages/backend/src/security/ingress.rs",
        "packages/backend/tests/transport/test_native_integration_queries.py",
        "packages/backend/tests/transport/support/integration_http_probe.rs",
        "packages/backend/Cargo.toml",
    ],
)
def test_native_integration_http_selects_owning_postgres_and_rust(path: str) -> None:
    plan = _plan(path)
    assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    assert OnlyTestLane.RESEARCH_POSTGRES in plan.impact.lanes


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/tests/transport/web_assets.rs",
        "packages/backend/tests/transport/test_native_web_assets.py",
        "packages/backend/tests/transport/support/http.rs",
    ],
)
def test_native_web_asset_delivery_selects_rust_verification(path: str) -> None:
    assert OnlyReleaseCheck.RUST_KERNEL in _plan(path).impact.checks


@pytest.mark.parametrize(
    "path",
    [
        "packages/backend/src/bootstrap/startup.rs",
        "packages/backend/tests/transport/test_native_frozen_strategy.py",
        "packages/backend/tests/transport/test_native_strategy_projection.py",
        "packages/backend/src/application/strategy_projection.rs",
        "packages/backend/src/application/qualification_policy.rs",
        "packages/backend/tests/transport/test_native_qualification_policy.py",
        "tests/support/frozen_strategy.py",
        "packages/backend/src/application/frozen_strategy.rs",
        "packages/backend/src/persistence/authority_session.rs",
        "packages/backend/src/security/protected_files.rs",
        "packages/backend/src/bootstrap/configuration.rs",
        "packages/backend/tests/transport/startup.rs",
        "packages/backend/tests/transport/test_native_startup_storage.py",
    ],
)
def test_native_startup_storage_selects_owning_rust_and_postgres(path: str) -> None:
    plan = _plan(path)
    assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks
    assert OnlyTestLane.RESEARCH_POSTGRES in plan.impact.lanes


def test_product_calculation_oracle_selects_native_identity_checks() -> None:
    plan = _plan("test-data/calculation/product-readers-v1.jsonl")
    assert OnlyReleaseCheck.RUST_KERNEL in plan.impact.checks


def test_local_fee_verification_is_bounded_and_does_not_run_full_gate() -> None:
    plan = _plan("crates/onlyalpha-kernel/fee/src/lib.rs")
    commands = verify.verification_commands(plan)
    native = [command for gate, command in commands if gate == "check:rust-selected"]
    assert len(native) == 1
    assert native[0][-4:] == ("--package", "onlyalpha-execution", "--package", "onlyalpha-fee")
    assert OnlyTestLane.CALCULATION not in plan.impact.lanes
    assert not any("scripts/test_suite.py" in command for _, command in commands)


def test_rust_tool_edits_run_guards_and_tool_tests_without_native_compilation() -> None:
    commands = verify.verification_commands(_plan("scripts/rust_kernel_check.py"))
    native = [command for gate, command in commands if gate == "check:rust-selected"]
    assert len(native) == 1 and native[0][-1] == "--source-check"
    assert any("tests/tools/test_rust_kernel_check.py" in command for _, command in commands)
    assert not any("scripts/test_suite.py" in command for _, command in commands)


@pytest.mark.parametrize("path", ("scripts/verify.py", "pyproject.toml", "tests/support/strategy.py"))
def test_unbounded_local_scope_requires_impact_review_without_running_global_checks(path: str) -> None:
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(_plan(path))


def test_known_rust_fixture_and_plugin_paths_do_not_select_generic_full_lanes() -> None:
    for path in ("test-data/fee/common-v1.json", "plugs/onlyalpha-plugin-binance/rust/spot_source.rs"):
        plan = _plan(path)
        commands = verify.verification_commands(plan)
        assert plan.impact.escalation is VerificationEscalation.COMPONENT
        assert not {OnlyTestLane.CORE_FULL, OnlyTestLane.FAST, OnlyTestLane.INTEGRATION}.intersection(plan.impact.lanes)
        assert any(gate == "check:rust-selected" for gate, _ in commands)


def test_coarse_legacy_full_core_lane_requires_bounded_manual_selection() -> None:
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(_plan("plugs/onlyalpha-plugin-binance/src/onlyalpha_plugin_binance/factory.py"))


def test_complete_local_web_workflow_requires_bounded_manual_selection() -> None:
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(_plan("packages/frontend/src/App.tsx"))


@pytest.mark.parametrize(
    "path",
    (
        "packages/onlyalpha-calculation-worker/src/onlyalpha_calculation_worker/artifact.py",
        "scripts/gateway_protocol.py",
    ),
)
def test_rust_scope_cannot_claim_unmapped_python_or_protocol_tool_proof(path: str) -> None:
    with pytest.raises(ValueError, match="LOCAL_IMPACT_REVIEW_REQUIRED"):
        verify.verification_commands(_plan(path))
