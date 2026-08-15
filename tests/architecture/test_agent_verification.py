from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.verify as verify
from scripts.test_suite import LANES, RELEASE_LANES, OnlyReleaseCheck, OnlyTestLane
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
BASE = "0" * 40


def _plan(*paths: str):  # type: ignore[no-untyped-def]
    changes = tuple(VerificationChangedPath(path) for path in paths)
    return plan_for_change_set(VerificationChangeSet(BASE, HEAD, changes, bool(changes)))


def test_input_order_is_deterministic_and_rules_union_monotonically() -> None:
    first = _plan("src/onlyalpha/research/job/orchestration.py", "src/onlyalpha/research/calculation/execution.py")
    second = _plan("src/onlyalpha/research/calculation/execution.py", "src/onlyalpha/research/job/orchestration.py")

    assert first.as_json() == second.as_json()
    assert set(first.impact.lanes) == {
        OnlyTestLane.RESEARCH_CALCULATION,
        OnlyTestLane.RESEARCH_FACTOR,
        OnlyTestLane.RESEARCH_EVALUATION,
        OnlyTestLane.RESEARCH_JOB,
        OnlyTestLane.RESEARCH_SWEEP,
    }


def test_unknown_production_path_fails_closed_to_full_local() -> None:
    plan = _plan("src/onlyalpha/new_unknown_core/authority.py")

    assert plan.impact.escalation is VerificationEscalation.FULL_LOCAL
    assert plan.impact.lanes == RELEASE_LANES
    assert plan.impact.checks == (OnlyReleaseCheck.STATIC, OnlyReleaseCheck.BUILD)
    assert {reason.rule for reason in plan.impact.reasons} == {"unknown-impact-fallback"}


def test_research_result_change_is_scoped_to_its_lane_and_static_targets() -> None:
    plan = _plan("src/onlyalpha/research/result/result_store.py", "tests/research/result/test_result_store.py")

    assert plan.impact.lanes == (OnlyTestLane.RESEARCH_RESULT,)
    assert plan.impact.escalation is VerificationEscalation.COMPONENT
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == ("src/onlyalpha/research/result",)
    assert OnlyTestLane.CORE_FULL not in plan.impact.lanes
    assert OnlyTestLane.RESEARCH_EVALUATION not in plan.impact.lanes


def test_statistics_authority_change_propagates_to_research_result_consumer() -> None:
    plan = _plan("src/onlyalpha/research/evaluation/result_store.py")

    assert plan.impact.lanes == (OnlyTestLane.RESEARCH_RESULT, OnlyTestLane.RESEARCH_EVALUATION)
    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.mypy_targets == (
        "src/onlyalpha/research/evaluation",
        "src/onlyalpha/research/result",
    )


def test_research_result_architecture_boundary_requests_import_linter_without_full_local() -> None:
    plan = _plan("tests/architecture/test_research_result_boundaries.py")

    assert plan.impact.lanes == (OnlyTestLane.RESEARCH_RESULT,)
    assert plan.impact.static_plan is not None and plan.impact.static_plan.import_linter_required
    assert plan.impact.escalation is VerificationEscalation.COMPONENT


def test_package_metadata_requests_version_sync_and_targeted_build() -> None:
    plan = _plan("pyproject.toml")

    assert plan.impact.static_plan is not None
    assert plan.impact.static_plan.version_sync_required
    assert plan.impact.static_plan.build_targets == ("onlyalpha",)


def test_verification_infrastructure_cannot_self_narrow() -> None:
    plan = _plan("scripts/test_suite.py")

    assert plan.impact.escalation is VerificationEscalation.VERIFICATION_INFRASTRUCTURE
    assert plan.impact.lanes == RELEASE_LANES
    assert plan.impact.checks == (OnlyReleaseCheck.STATIC, OnlyReleaseCheck.BUILD)


def test_docs_only_selects_no_runtime_lane_and_mixed_change_cannot_downgrade() -> None:
    docs = _plan("docs/engineering/quality-system.md", "prompts/P7.5.2.md")
    mixed = _plan("docs/roadmap.md", "src/onlyalpha/runtime/streaming/recovery.py")

    assert docs.impact.escalation is VerificationEscalation.DOCS_ONLY
    assert docs.impact.lanes == ()
    assert docs.impact.checks == ()
    assert mixed.impact.escalation is VerificationEscalation.BROAD
    assert set(mixed.impact.lanes) == set(verify.CORE_RECOVERY)


def test_shared_core_and_shared_test_fixture_are_conservative() -> None:
    core = _plan("src/onlyalpha/execution/processor.py")
    fixture = _plan("tests/fixtures/shared_state.py")

    assert set(core.impact.lanes) == set(verify.CORE_RECOVERY)
    assert core.impact.escalation is VerificationEscalation.BROAD
    assert fixture.impact.lanes == RELEASE_LANES
    assert fixture.impact.escalation is VerificationEscalation.FULL_LOCAL


def test_specific_test_change_uses_component_lane() -> None:
    plan = _plan("tests/research/job/test_orchestration.py")

    assert plan.impact.lanes == (OnlyTestLane.RESEARCH_SWEEP, OnlyTestLane.RESEARCH_JOB)
    assert plan.impact.escalation is VerificationEscalation.COMPONENT


def test_rename_and_delete_have_deterministic_impact_semantics() -> None:
    change_set = VerificationChangeSet(
        BASE,
        HEAD,
        (
            VerificationChangedPath(
                "docs/old_runtime.md",
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
    assert [item.path for item in plan.change_set.changed_paths] == ["docs/new_name.md", "docs/old_runtime.md"]


def test_name_status_parser_preserves_rename_and_delete() -> None:
    parsed = verify._parse_name_status(b"R100\0old.py\0new.py\0D\0gone.py\0")

    assert parsed == (
        VerificationChangedPath("new.py", ChangeKind.RENAMED, "old.py"),
        VerificationChangedPath("gone.py", ChangeKind.DELETED),
    )


def test_dirty_worktree_and_untracked_files_are_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_git(*args: str) -> str:
        if args[:2] == ("rev-parse", "--verify"):
            return BASE + "\n"
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

    change_set = verify.resolve_change_set("explicit-base")

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


def test_full_local_command_order_preserves_release_static_lanes_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "release_check_commands", lambda check: ((check.value,),))
    plan = _plan("scripts/verify.py")

    commands = verify.verification_commands(plan)

    assert commands[0][0] == "check:release-static"
    assert [gate for gate, _ in commands[1:-1]] == [f"lane:{lane.value}" for lane in RELEASE_LANES]
    assert commands[-1][0] == "check:build"


def test_plan_is_stable_across_fresh_hash_seed_processes() -> None:
    code = (
        "import json; from scripts.verify import *; "
        "c=VerificationChangeSet('0'*40,'1'*40,(VerificationChangedPath('src/onlyalpha/research/job/x.py'),"
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


def test_compact_success_output_and_manifest_retains_full_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = (sys.executable, "-c", "print('full successful output retained')")
    monkeypatch.setattr(verify, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "release_check_commands", lambda check: (command,))
    change_set = VerificationChangeSet(BASE, HEAD, (VerificationChangedPath("tool.py"),), True)
    plan = VerificationPlan(
        change_set,
        VerificationImpact((), (OnlyReleaseCheck.STATIC,), (), VerificationEscalation.COMPONENT),
    )

    assert verify.run_plan(plan) == 0

    output = capsys.readouterr().out
    assert "PASS check:release-static" in output
    assert "IMPACT VERIFIED" in output
    assert "full successful output retained" not in output
    manifests = list(tmp_path.glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["authority"] == "LOCAL_DEVELOPMENT_VERIFICATION_ONLY"
    assert manifest["result"] == "VERIFICATION_PASSED"
    log = next(tmp_path.glob("*/check-release-static*.log")).read_text(encoding="utf-8")
    assert "full successful output retained" in log


def test_compact_failure_exposes_command_diagnostic_and_full_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    log = tmp_path / "failed.log"
    log.write_text("short failure diagnostic\n", encoding="utf-8")
    result = VerificationStepResult("lane:research-job", ("false",), 1, 0.5, "failed.log")

    verify._print_result(result, tmp_path)

    output = capsys.readouterr().out
    assert "FAIL lane:research-job" in output
    assert "exit_code=1" in output
    assert "command: false" in output
    assert "short failure diagnostic" in output
    assert "full log: failed.log" in output
