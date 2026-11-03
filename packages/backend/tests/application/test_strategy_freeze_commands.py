"""Actual durable Freeze-command recovery; artificial scientific preconditions only.

The cfg(test) seal factory cannot be used by Product. This proves persistence,
Command identity and atomic projection/receipt behavior, not Research or Web closure.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(300)]
NAMESPACE = "11111111-1111-4111-8111-111111111111"
RUN = "00000000-0000-4000-8000-000000000701"
COMMAND = "00000000-0000-4000-8000-000000000702"


@pytest.fixture
def freeze_database(postgres_dsn: str, tmp_path: Path) -> tuple[str, Path, dict[str, Any]]:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    repo = Path(__file__).resolve().parents[4]
    fixture = json.loads((repo / "packages/backend/tests/application/fixtures/frozen_strategy.json").read_text())
    relation = fixture["relation"]
    # Isolated historical records are preconditions of this persistence test.
    # No claim that these artificial rows are current scientific evidence.
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute(
            "INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,%s)",
            (NAMESPACE,),
        )
        conn.execute(
            "INSERT INTO private_strategy_asset(strategy_id,schema_version) VALUES('private.strategy.use_test_freeze',1)"
        )
        conn.execute(
            "INSERT INTO private_strategy_revision(revision_fingerprint,strategy_id,definition_fingerprint,payload,schema_version) VALUES(%s,'private.strategy.use_test_freeze',%s,'{}',1)",
            ("1" * 64, "2" * 64),
        )
        conn.execute(
            "INSERT INTO private_strategy_research_composition VALUES(%s,1,'private.strategy.use_test_freeze',%s,%s,%s,'[]',%s,%s,'{}')",
            ("3" * 64, "1" * 64, "2" * 64, "4" * 64, "5" * 64, "6" * 64),
        )
        conn.execute(
            "INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,started_at,finished_at,research_result_fingerprint,artifact_content_fingerprint,calculation_execution_evidence_fingerprints,origin_kind,strategy_research_composition_fingerprint) "
            "VALUES(%s,2,'COMPLETED',1,%s,'{}',%s,'2026-11-01T00:00:00Z','2026-11-01T00:00:00Z','2026-11-01T00:00:01Z',%s,%s,%s,'PRIVATE_STRATEGY',%s)",
            (
                RUN,
                "7" * 64,
                "8" * 64,
                relation["research_result_fingerprint"],
                "9" * 64,
                relation["research_execution_evidence_fingerprints"],
                "3" * 64,
            ),
        )
    root = tmp_path / "use_test_freeze_research"
    root.mkdir(mode=0o700)
    (root / ".onlyalpha-semantic-store.json").write_text(
        only_canonical_json({"schema_version": 1, "store_id": NAMESPACE})
    )
    (root / ".source-cut.lock").write_bytes(b"")
    (root / ".source-cut.lock").chmod(0o600)
    return postgres_dsn, root, fixture


@pytest.fixture
def run_freeze_owner(freeze_database: tuple[str, Path, dict[str, Any]]) -> Callable[..., None]:
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    dsn, root, _ = freeze_database
    repo = Path(__file__).resolve().parents[4]
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    environment = compiler_environment(os.environ, repo / "test-results/rust-kernel/target")
    environment["RUSTUP_TOOLCHAIN"] = tomllib.loads((repo / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    environment["ONLYALPHA_POSTGRES_DSN"] = dsn
    environment["ONLYALPHA_FREEZE_TEST_ROOT"] = str(root)

    built = subprocess.run(
        [
            "cargo",
            "test",
            "--frozen",
            "--offline",
            "--config",
            "profile.dev.package.onlyalpha-backend.debug=0",
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backend",
            "--test",
            "strategy_freeze_postgres",
            "--no-run",
            "--message-format=json",
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    binaries = [
        record["executable"]
        for line in built.stdout.splitlines()
        if line.startswith("{")
        for record in [json.loads(line)]
        if record.get("reason") == "compiler-artifact"
        and record["target"]["name"] == "strategy_freeze_postgres"
        and record.get("executable")
    ]
    assert len(binaries) == 1

    def run(phase: str, boundary: str = "", *, expect_crash: bool = False) -> None:
        result = subprocess.run(
            [binaries[0], "--exact", "actual_command_boundary", "--nocapture"],
            cwd=repo,
            env={**environment, "ONLYALPHA_FREEZE_TEST_PHASE": phase, "ONLYALPHA_FREEZE_TEST_BOUNDARY": boundary},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == (86 if expect_crash else 0), result.stdout + result.stderr
        if expect_crash:
            from tests.support.postgres_link import wait_no_advisory_locks

            pid = re.search(r"FREEZE_TEST_BACKEND_PID ([0-9]+)", result.stdout)
            assert pid is not None, result.stdout
            wait_no_advisory_locks(dsn, int(pid.group(1)))

    return run


def snapshot(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        return {
            "commands": conn.execute(
                "SELECT command_id::text,state,strategy_fingerprint,freeze_relation_fingerprint,actor,comment FROM strategy_freeze_command_admission ORDER BY 1"
            ).fetchall(),
            "admissions": conn.execute(
                "SELECT command_id::text,command_kind,command_fingerprint FROM product_command_admission ORDER BY 1"
            ).fetchall(),
            "receipts": conn.execute(
                "SELECT command_id::text,outcome_kind,outcome_id,accepted_at FROM product_command_receipt ORDER BY 1"
            ).fetchall(),
            "catalog": conn.execute(
                "SELECT strategy_fingerprint,semantic_namespace_id FROM strategy_catalog ORDER BY 1"
            ).fetchall(),
            "audit": conn.execute(
                "SELECT freeze_record_fingerprint,actor,comment FROM strategy_freeze_record ORDER BY 1"
            ).fetchall(),
        }


@pytest.mark.parametrize("boundary", ["prepared", "relation", "revision", "before_commit", "after_commit"])
def test_original_unknown_resumes_after_each_durable_process_boundary(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], boundary: str
) -> None:
    dsn, root, fixture = freeze_database
    run_freeze_owner("stop", boundary)
    stopped = snapshot(dsn)
    assert len(stopped["commands"]) == len(stopped["admissions"]) == 1
    assert stopped["commands"][0][0] == COMMAND
    assert stopped["commands"][0][1] == ("COMPLETED" if boundary == "after_commit" else "PREPARED")
    assert (
        len(stopped["receipts"]) == len(stopped["catalog"]) == len(stopped["audit"]) == int(boundary == "after_commit")
    )
    files = list(root.rglob("manifest.json"))
    assert len(files) == {"prepared": 0, "relation": 1, "revision": 2, "before_commit": 2, "after_commit": 2}[boundary]
    if boundary == "relation":
        assert "freeze-relations" in str(files[0])
    before = {str(p.relative_to(root)): p.read_bytes() for p in files}
    run_freeze_owner("resume")
    completed = snapshot(dsn)
    assert (
        len(completed["commands"])
        == len(completed["admissions"])
        == len(completed["receipts"])
        == len(completed["catalog"])
        == len(completed["audit"])
        == 1
    )
    assert completed["commands"][0][1:4] == (
        "COMPLETED",
        fixture["source"]["strategy_fingerprint"],
        fixture["relation"]["relation_fingerprint"],
    )
    assert completed["commands"][0][4:] == ("local-developer", "use_test original Freeze")
    for path, raw in before.items():
        assert (root / path).read_bytes() == raw
    run_freeze_owner("conflict")
    assert snapshot(dsn) == completed
    # A completed replay must reject corruption without restoring overwritten bytes.
    path = next(p for p in root.rglob("manifest.json") if "frozen-revisions" in str(p))
    path.write_bytes(b"{}\n")
    run_freeze_owner("corrupt")
    assert path.read_bytes() == b"{}\n"
    assert snapshot(dsn) == completed


@pytest.mark.parametrize("boundary", ["prepared", "revision", "after_commit"])
def test_reading_original_freeze_outcome_never_resumes_publication(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], boundary: str
) -> None:
    dsn, root, _ = freeze_database
    initial = snapshot(dsn)
    run_freeze_owner("observe-freeze:NOT_SUBMITTED")
    assert snapshot(dsn) == initial
    run_freeze_owner("stop", boundary)
    before = snapshot(dsn)
    files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    run_freeze_owner("observe-freeze:" + ("COMPLETED" if boundary == "after_commit" else "PENDING"))
    assert snapshot(dsn) == before
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} == files


@pytest.mark.parametrize("phase", ["deferred-prepared-guard", "deferred-final-guard"])
def test_freeze_reproves_original_physical_authority_after_deferred_effects(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], phase: str
) -> None:
    # Persistence/guard proof only: reuse the existing artificial scientific
    # preconditions, actual Freezes owner, and original AuthoritySession.
    dsn, root, _ = freeze_database
    run_freeze_owner(phase)
    rejected = snapshot(dsn)
    assert rejected["receipts"] == rejected["catalog"] == rejected["audit"] == []
    if phase == "deferred-prepared-guard":
        assert rejected["commands"] == rejected["admissions"] == []
        assert list(root.rglob("manifest.json")) == []
    else:
        assert len(rejected["commands"]) == len(rejected["admissions"]) == 1
        assert rejected["commands"][0][0:2] == (COMMAND, "PREPARED")
        assert len(list(root.rglob("manifest.json"))) == 2
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TRIGGER use_test_freeze_guard_fault ON strategy_freeze_command_admission")
        conn.execute("DROP FUNCTION use_test_freeze_guard_fault()")
    run_freeze_owner("submit" if phase == "deferred-prepared-guard" else "resume")
    recovered = snapshot(dsn)
    assert recovered["commands"][0][0:2] == (COMMAND, "COMPLETED")
    assert len(recovered["commands"]) == len(recovered["admissions"]) == 1
    assert len(recovered["receipts"]) == len(recovered["catalog"]) == len(recovered["audit"]) == 1


def test_deferred_projection_mutation_rolls_back_completion_and_receipt_together(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, root, _ = freeze_database
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "CREATE FUNCTION use_test_mutate_freeze_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE strategy_freeze_record SET actor='unexpected deferred mutation'; RETURN NEW; END $$"
        )
        conn.execute(
            "CREATE CONSTRAINT TRIGGER use_test_freeze_receipt_mutation AFTER INSERT ON product_command_receipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION use_test_mutate_freeze_audit()"
        )
    run_freeze_owner("trigger")
    state = snapshot(dsn)
    assert state["commands"][0][1] == "PREPARED"
    assert len(state["admissions"]) == 1
    assert state["receipts"] == state["catalog"] == state["audit"] == []
    assert len(list(root.rglob("manifest.json"))) == 2
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TRIGGER use_test_freeze_receipt_mutation ON product_command_receipt")
    run_freeze_owner("resume")
    assert snapshot(dsn)["commands"][0][1] == "COMPLETED"


@pytest.mark.parametrize(
    "point", ["stage_created", "partial_write", "leaf_written", "file_synced", "stage_synced", "renamed"]
)
def test_original_prepared_command_recovers_after_process_exit_inside_immutable_publication(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], point: str
) -> None:
    dsn, root, fixture = freeze_database
    run_freeze_owner("crash", point, expect_crash=True)
    crashed = snapshot(dsn)
    assert crashed["commands"][0][0:2] == (COMMAND, "PREPARED")
    assert len(crashed["commands"]) == len(crashed["admissions"]) == 1
    assert crashed["receipts"] == crashed["catalog"] == crashed["audit"] == []
    # Interrupted staging is auxiliary data, outside both semantic SHA trees.
    # Unknown old stages remain intact; recovery must not delete guessed owners.
    semantic = root / "strategy"
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    leftovers = [p for p in root.rglob(".stage-*") if p.is_dir()]
    if point != "renamed":
        assert len(leftovers) == 1
        assert not leftovers[0].is_relative_to(semantic)
    run_freeze_owner("resume")
    completed = snapshot(dsn)
    assert (
        len(completed["commands"])
        == len(completed["admissions"])
        == len(completed["receipts"])
        == len(completed["catalog"])
        == len(completed["audit"])
        == 1
    )
    assert completed["commands"][0][1:4] == (
        "COMPLETED",
        fixture["source"]["strategy_fingerprint"],
        fixture["relation"]["relation_fingerprint"],
    )
    assert len(list(semantic.rglob("manifest.json"))) == 2
    for stage in leftovers:
        assert stage.is_dir()
    for name, raw in before.items():
        assert (root / name).read_bytes() == raw


# Existing harness and guarded DB, explicit cfg(test) semantic preconditions only.
# These are operational owner tests; real Product admission has its own readers.
def backtest_snapshot(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        return {
            "runs": conn.execute(
                "SELECT run_id::text,state,revision,specification_schema_version,specification_payload,admission_resolution_schema_version,admission_resolution_payload,evidence_fingerprint,result_fingerprint,determinism_fingerprint FROM backtest_run ORDER BY run_id"
            ).fetchall(),
            "attempts": conn.execute(
                "SELECT attempt_number,fencing_token,state FROM backtest_run_attempt ORDER BY attempt_number"
            ).fetchall(),
            "commands": conn.execute(
                "SELECT command_kind,outcome_kind,outcome_id,accepted_at FROM product_command_receipt WHERE command_kind IN ('CREATE_BACKTEST_RUN','CANCEL_BACKTEST_RUN') ORDER BY command_id"
            ).fetchall(),
            "admissions": conn.execute(
                "SELECT command_kind,command_fingerprint FROM product_command_admission WHERE command_kind IN ('CREATE_BACKTEST_RUN','CANCEL_BACKTEST_RUN') ORDER BY command_id"
            ).fetchall(),
        }


def test_backtest_original_command_replays_after_source_revocation_without_a_second_run(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("backtest:create")
    original = backtest_snapshot(dsn)
    assert len(original["runs"]) == len(original["commands"]) == len(original["admissions"]) == 1
    row = original["runs"][0]
    assert row[1:4] == ("QUEUED", 0, 3)
    assert row[5] == 2
    assert row[4]["preparation_fingerprint"] == row[6]["preparation_fingerprint"]
    assert (
        hashlib.sha256(only_canonical_json(row[6]["preparation"]).encode()).hexdigest()
        == row[4]["preparation_fingerprint"]
    )
    assert row[6]["preparation"]["settings"]["policy"]["buy_multiplier"] == "1.0002"
    assert row[6]["preparation"]["settings"]["policy"]["sell_multiplier"] == "0.9998"
    assert row[6]["preparation"]["policy_binding"]["kind"] == "BINANCE_SPOT_EXPERIMENTAL_NEXT_OPEN"
    run_freeze_owner("backtest:replay")
    assert backtest_snapshot(dsn) == original


def test_backtest_queued_cancel_has_no_attempt_and_replays_the_original_cancel_receipt(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("backtest:queued-cancel")
    state = backtest_snapshot(dsn)
    assert state["runs"][0][1:3] == ("CANCELLED", 1)
    assert state["attempts"] == []
    assert [row[0] for row in state["commands"]] == ["CREATE_BACKTEST_RUN", "CANCEL_BACKTEST_RUN"]
    assert len(state["admissions"]) == 2
    assert state["runs"][0][7:] == (None, None, None)


def test_backtest_attempt_fence_expiry_and_running_cancel_preserve_the_same_run(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("backtest:fence-cancel")
    state = backtest_snapshot(dsn)
    assert len(state["runs"]) == 1
    assert state["runs"][0][1] == "CANCELLED"
    assert state["attempts"] == [(1, 1, "EXPIRED"), (2, 2, "CANCELLED")]
    assert len(state["commands"]) == len(state["admissions"]) == 2
    # This running cancellation supplies an explicit sealed prefix proof.
    # Queued cancellation above still has no producer and retains three NULLs.
    assert state["runs"][0][7:] == ("1" * 64, "2" * 64, "3" * 64)


def test_backtest_sealed_completion_sets_all_final_pins_in_one_transaction(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("backtest:complete")
    state = backtest_snapshot(dsn)
    assert len(state["runs"]) == len(state["commands"]) == len(state["admissions"]) == 1
    assert state["runs"][0][1] == "COMPLETED"
    assert state["runs"][0][7:] == ("1" * 64, "2" * 64, "3" * 64)
    assert state["attempts"] == [(1, 1, "SUCCEEDED")]


def test_backtest_guard_socket_loss_cannot_commit_attempt_and_completion_on_another_socket(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("backtest:trigger")
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TRIGGER backtest_test_finalization_guard ON backtest_run")
        conn.execute("DROP FUNCTION backtest_test_terminate_guard()")
    state = backtest_snapshot(dsn)
    assert state["runs"][0][1:3] == ("RUNNING", 1)
    assert state["runs"][0][7:] == (None, None, None)
    assert state["attempts"] == [(1, 1, "ACTIVE")]


@pytest.mark.parametrize(
    "phase",
    [
        "deferred-create-guard",
        "deferred-create-receipt",
        "deferred-claim-guard",
        "deferred-finalize-guard",
        "deferred-finalize-result",
    ],
)
def test_backtest_deferred_effects_are_drained_before_the_final_business_and_physical_proof(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], phase: str
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner(f"backtest:{phase}")
    state = backtest_snapshot(dsn)
    if phase.startswith("deferred-create"):
        assert state == {"runs": [], "attempts": [], "commands": [], "admissions": []}
    elif phase == "deferred-claim-guard":
        assert state["runs"][0][1:3] == ("QUEUED", 0)
        assert state["attempts"] == []
        assert len(state["commands"]) == len(state["admissions"]) == 1
    else:
        assert state["runs"][0][1:3] == ("RUNNING", 1)
        assert state["runs"][0][7:] == (None, None, None)
        assert state["attempts"] == [(1, 1, "ACTIVE")]
        assert len(state["commands"]) == len(state["admissions"]) == 1


def preparation_snapshot(dsn: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "SELECT p.command_id::text,p.preparation_kind,p.accepted_fingerprint,p.accepted_payload,p.revision,p.state,a.command_kind,r.outcome_kind,r.outcome_id "
            "FROM research_preparation p JOIN product_command_admission a USING(command_id) JOIN product_command_receipt r USING(command_id) ORDER BY p.command_id"
        ).fetchall()


def test_strategy_preparation_recovers_original_committed_command_without_a_factor_study(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("strategy-preparation:commit-no-reply", expect_crash=True)
    before = preparation_snapshot(dsn)
    assert len(before) == 1
    assert before[0][1] == "STRATEGY_RESEARCH"
    assert before[0][6:] == ("PREPARE_STRATEGY_RESEARCH", "RESEARCH_PREPARATION_OPERATION", before[0][2])
    accepted = json.loads(before[0][3])
    assert accepted["contract"] == "ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1"
    assert "study" not in accepted
    run_freeze_owner("strategy-preparation:replay")
    assert preparation_snapshot(dsn) == before
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM factor_study_snapshot").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM research_run WHERE specification_schema_version=5").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM private_strategy_authoring_outcome").fetchone() == (2,)


def test_strategy_preparation_rejects_unpublished_rebound_or_unconfirmed_inputs_before_admission(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("strategy-preparation:reject-pins")
    assert preparation_snapshot(dsn) == []


def test_strategy_preparation_cancel_replays_original_receipt_and_denies_late_submission(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("strategy-preparation:cancel")
    rows = preparation_snapshot(dsn)
    assert len(rows) == 1 and rows[0][1] == "STRATEGY_RESEARCH" and rows[0][5] == "CANCELLED"
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM research_run WHERE specification_schema_version=5").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_kind='CANCEL_STRATEGY_RESEARCH_PREPARATION'"
        ).fetchone() == (1,)


def test_preparation_kind_is_immutable_and_cannot_reinterpret_a_legacy_contract(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]]
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("strategy-preparation:commit-no-reply", expect_crash=True)
    before = preparation_snapshot(dsn)
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute(
                "UPDATE research_preparation SET preparation_kind='FACTOR_RESEARCH',revision=revision+1,state='RUNNING',phase='VALIDATING'"
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation) as rejected:
            conn.execute(
                "INSERT INTO research_preparation(command_id,owner,accepted_fingerprint,accepted_payload,revision,state,phase,outputs_payload,detail_payload,preparation_kind) "
                "VALUES('00000000-0000-4000-8000-000000006199','use-test',%s,%s,0,'ACCEPTED','ACCEPTED','{}','null','STRATEGY_RESEARCH')",
                ("9" * 64, only_canonical_json({"contract": "ONLYALPHA_ACCEPTED_RESEARCH_PREPARATION_V1"})),
            )
        assert rejected.value.diag.constraint_name == "research_preparation_kind_contract_check"
        conn.rollback()
    assert preparation_snapshot(dsn) == before


def qualification_snapshot(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        return {
            "qualifications": conn.execute(
                "SELECT command_id::text,command_fingerprint,subject_strategy_fingerprint,policy_id,policy_version,evidence_payload,state,decision_fingerprint,prepared_at,completed_at,schema_version FROM qualification_command_admission ORDER BY command_id"
            ).fetchall(),
            "promotions": conn.execute(
                "SELECT promotion_record_fingerprint,strategy_fingerprint,from_stage,to_stage,evidence_fingerprints,previous_record_fingerprint,decision,reason,actor,recorded_at,schema_version,qualification_decision_fingerprint FROM strategy_promotion_record ORDER BY promotion_record_fingerprint"
            ).fetchall(),
            "receipts": conn.execute(
                "SELECT command_id::text,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at FROM product_command_receipt WHERE command_kind IN ('EVALUATE_QUALIFICATION','PROMOTE_STRATEGY') ORDER BY command_id"
            ).fetchall(),
        }


@pytest.mark.parametrize("boundary", ["prepared", "decision", "before_commit", "after_commit"])
def test_qualification_original_command_resumes_each_durable_boundary(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]], boundary: str
) -> None:
    dsn, root, _ = freeze_database
    run_freeze_owner("qualification:qualification-stop:" + boundary, expect_crash=True)
    partial = qualification_snapshot(dsn)
    assert len(partial["qualifications"]) == 1
    assert partial["qualifications"][0][6] == ("COMPLETED" if boundary == "after_commit" else "PREPARED")
    assert len(partial["receipts"]) == (1 if boundary == "after_commit" else 0)
    decisions = list((root / "strategy/qualification-decisions/sha256").glob("*/*/manifest.json"))
    assert len(decisions) == (0 if boundary == "prepared" else 1)
    prepared_at = partial["qualifications"][0][8]
    run_freeze_owner("qualification:qualification-recover")
    complete = qualification_snapshot(dsn)
    assert complete["qualifications"][0][6] == "COMPLETED"
    assert complete["qualifications"][0][8] == prepared_at
    assert len(complete["receipts"]) == 1
    run_freeze_owner("qualification:qualification-recover")
    assert qualification_snapshot(dsn) == complete


@pytest.mark.parametrize("boundary", ["before_commit", "after_commit"])
def test_qualified_promotion_commits_one_original_public_record_and_receipt(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]], boundary: str
) -> None:
    dsn, root, _ = freeze_database
    run_freeze_owner("qualification:promotion-stop:" + boundary, expect_crash=True)
    partial = qualification_snapshot(dsn)
    assert len(partial["promotions"]) == (1 if boundary == "after_commit" else 0)
    run_freeze_owner("qualification:promotion-recover")
    complete = qualification_snapshot(dsn)
    assert len(complete["promotions"]) == 1
    assert complete["promotions"][0][2:4] == ("RESEARCH", "BACKTEST")
    assert complete["promotions"][0][10] == 2
    assert len(complete["receipts"]) == 2
    run_freeze_owner("qualification:promotion-recover")
    assert qualification_snapshot(dsn) == complete
    assert not (root / "strategy/promotions").exists(), "PostgreSQL remains the sole Promotion ledger"


@pytest.mark.parametrize(
    "phase",
    [
        "deferred-prepared-guard",
        "deferred-final-guard",
        "deferred-final-receipt",
        "deferred-promotion-guard",
        "deferred-promotion-audit",
        "deferred-promotion-freeze",
    ],
)
def test_qualification_and_promotion_reprove_the_original_cut_after_deferred_effects(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]], phase: str
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("qualification:" + phase)
    state = qualification_snapshot(dsn)
    if phase == "deferred-prepared-guard":
        assert state["qualifications"] == [] and state["receipts"] == []
    elif phase.startswith("deferred-final-"):
        assert len(state["qualifications"]) == 1 and state["qualifications"][0][6] == "PREPARED"
        assert state["receipts"] == []
    else:
        assert len(state["receipts"]) == 1 and state["receipts"][0][1] == "EVALUATE_QUALIFICATION"
    assert state["promotions"] == []


@pytest.mark.parametrize("phase", ["policy-mismatch", "historical-promotion", "completed-missing-decision"])
def test_qualification_replay_refuses_repair_and_legacy_or_mismatched_promotion_grants(
    run_freeze_owner: Callable[..., None], freeze_database: tuple[str, Path, dict[str, Any]], phase: str
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner("qualification:" + phase)
    state = qualification_snapshot(dsn)
    assert len(state["receipts"]) == 1
    assert state["receipts"][0][1] == "EVALUATE_QUALIFICATION"
    assert all(row[10] == 1 for row in state["promotions"])


@pytest.mark.parametrize("mutation", ["rehash", "namespace", "receipt", "freeze", "chain", "chain-orphan"])
def test_readonly_qualified_admission_rechecks_the_exact_postgres_closure(
    run_freeze_owner: Callable[..., None], mutation: str
) -> None:
    run_freeze_owner("qualification:admission-pg:" + mutation)


@pytest.mark.parametrize("phase", ["admission-source-cut", "admission-decision-bytes", "admission-frozen-bytes"])
def test_qualified_admission_keeps_actual_decision_counts_and_frozen_files_alive(
    run_freeze_owner: Callable[..., None], phase: str
) -> None:
    run_freeze_owner("qualification:" + phase)


@pytest.mark.parametrize("phase", ["scheduler-inventory", "scheduler-queued-cancel", "scheduler-expiry"])
def test_backtest_scheduler_uses_original_pending_rows_queued_cancel_and_server_expiry(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None], phase: str
) -> None:
    dsn, _, _ = freeze_database
    run_freeze_owner(f"backtest:{phase}")
    state = backtest_snapshot(dsn)
    assert len(state["runs"]) == 1
    if phase == "scheduler-queued-cancel":
        assert state["runs"][0][1] == "CANCELLED"
        assert state["attempts"] == []
        assert state["runs"][0][7:] == (None, None, None)
    else:
        assert state["runs"][0][1] == "COMPLETED"
        expected = [(1, 1, "EXPIRED"), (2, 2, "SUCCEEDED")] if phase == "scheduler-expiry" else [(1, 1, "SUCCEEDED")]
        assert state["attempts"] == expected


def test_another_candidate_with_only_graph_alias_changes_reuses_the_first_frozen_revision(
    freeze_database: tuple[str, Path, dict[str, Any]], run_freeze_owner: Callable[..., None]
) -> None:
    # Technical identity/Freeze proof: completed scientific fixtures are explicit
    # test preconditions, never evidence of an actual Research or Web workflow.
    dsn, root, fixture = freeze_database
    run_freeze_owner("submit")
    revision = next(p for p in root.rglob("manifest.json") if "frozen-revisions" in p.parts)
    original = (revision.stat().st_ino, revision.read_bytes())
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,started_at,finished_at,research_result_fingerprint,artifact_content_fingerprint,calculation_execution_evidence_fingerprints,origin_kind,strategy_research_composition_fingerprint) "
            "SELECT '00000000-0000-4000-8000-000000000703',revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,started_at,finished_at,research_result_fingerprint,artifact_content_fingerprint,calculation_execution_evidence_fingerprints,origin_kind,strategy_research_composition_fingerprint FROM research_run WHERE run_id=%s",
            (RUN,),
        )
    run_freeze_owner("alias-equivalent-freeze")
    complete = snapshot(dsn)
    assert len(complete["commands"]) == len(complete["admissions"]) == len(complete["receipts"]) == 2
    assert all(row[1] == "COMPLETED" for row in complete["commands"])
    assert all(row[2] == fixture["source"]["strategy_fingerprint"] for row in complete["commands"])
    assert len(complete["catalog"]) == 1 and len(complete["audit"]) == 2
    assert (revision.stat().st_ino, revision.read_bytes()) == original
    assert len(list((root / "strategy/frozen-revisions").rglob("manifest.json"))) == 1
    assert len(list((root / "strategy/freeze-relations").rglob("manifest.json"))) == 2
    run_freeze_owner("resume")
    assert snapshot(dsn) == complete
