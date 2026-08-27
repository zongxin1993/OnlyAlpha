from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import scripts.local_verify as local_verify
from scripts.verify import (
    VerificationChangedPath,
    VerificationChangeSet,
    plan_for_change_set,
)

HEAD = "1" * 40
BASE = "0" * 40


def _plan(*paths: str):  # type: ignore[no-untyped-def]
    changes = tuple(VerificationChangedPath(path) for path in paths)
    return plan_for_change_set(VerificationChangeSet(BASE, HEAD, changes, bool(changes)))


def test_small_component_plan_executes_fully_within_default_budget() -> None:
    verification_plan = _plan("src/onlyalpha/strategy/model.py")

    execution = local_verify.build_execution_plan(verification_plan)

    assert execution.estimated_units <= execution.budget_units
    assert execution.local == execution.required
    assert execution.deferred_to_ci == ()
    assert execution.ci_required is False


def test_broad_core_plan_defers_heavy_lanes_instead_of_running_full_suite_locally() -> None:
    verification_plan = _plan("src/onlyalpha/execution/processor.py")

    execution = local_verify.build_execution_plan(verification_plan)

    deferred = {item.gate for item in execution.deferred_to_ci}
    assert execution.ci_required is True
    assert {
        "lane:core-full",
        "lane:recovery",
        "lane:sim-recovery",
    }.issubset(deferred)
    assert any(item.gate.startswith("check:release-static") for item in execution.local)


def test_verification_infrastructure_self_change_is_fail_closed_but_budgeted() -> None:
    verification_plan = _plan("scripts/local_verify.py")

    execution = local_verify.build_execution_plan(verification_plan)

    assert execution.ci_required is True
    assert len(execution.required) > len(execution.local)
    assert any(item.gate.startswith("check:release-static") for item in execution.local)
    assert "lane:core-full" in {item.gate for item in execution.deferred_to_ci}
    assert "check:web-e2e" in {item.gate for item in execution.deferred_to_ci}


def test_full_local_is_explicit_opt_in_and_preserves_complete_required_plan() -> None:
    verification_plan = _plan("src/onlyalpha/execution/processor.py")

    execution = local_verify.build_execution_plan(
        verification_plan,
        budget_units=0,
        full_local=True,
    )

    assert execution.full_local is True
    assert execution.local == execution.required
    assert execution.deferred_to_ci == ()
    assert execution.ci_required is False


def test_zero_budget_never_silently_drops_required_proof() -> None:
    verification_plan = _plan("src/onlyalpha/strategy/model.py")

    execution = local_verify.build_execution_plan(
        verification_plan,
        budget_units=0,
    )

    assert execution.local == ()
    assert execution.deferred_to_ci == execution.required
    assert execution.ci_required is True


def test_negative_budget_fails_closed() -> None:
    verification_plan = _plan("src/onlyalpha/strategy/model.py")

    with pytest.raises(ValueError, match="budget_units must be >= 0"):
        local_verify.build_execution_plan(
            verification_plan,
            budget_units=-1,
        )


def test_execution_policy_is_stable_across_hash_seeds() -> None:
    code = (
        "import json; "
        "from scripts.verify import VerificationChangedPath,VerificationChangeSet,plan_for_change_set; "
        "from scripts.local_verify import build_execution_plan; "
        "p=plan_for_change_set(VerificationChangeSet('0'*40,'1'*40,"
        "(VerificationChangedPath('src/onlyalpha/research/job/x.py'),"
        "VerificationChangedPath('src/onlyalpha/research/calculation/y.py')),True)); "
        "print(json.dumps(build_execution_plan(p).as_json(),sort_keys=True))"
    )
    outputs = []
    for seed in ("1", "827"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            capture_output=True,
            check=True,
            text=True,
        )
        outputs.append(completed.stdout)

    assert outputs[0] == outputs[1]


def test_local_budget_does_not_copy_canonical_lane_semantics() -> None:
    source = (local_verify.ROOT / "scripts" / "local_verify.py").read_text(encoding="utf-8")

    assert "--import-mode" not in source
    assert "not external" not in source
    assert "--cov=" not in source
    assert "verification_commands(plan)" in source


def test_policy_vocabulary_cannot_claim_certification_authority() -> None:
    verification_plan = _plan("src/onlyalpha/execution/processor.py")
    payload = json.dumps(local_verify.build_execution_plan(verification_plan).as_json())

    assert "LOCAL_EXECUTION_POLICY_ONLY" in payload
    assert "CERTIFIED" not in payload
    assert "ACCEPTED" not in payload


def test_debug_ruff_format_diff() -> None:
    completed = subprocess.run(
        ["ruff", "format", "--diff", "scripts/local_verify.py"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert not completed.stdout, completed.stdout
