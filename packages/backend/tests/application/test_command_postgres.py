"""Real Rust/Python readers over the one existing Product Command authority.

These are persistence/interop proofs, not Shipping Web business acceptance.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from tests.support.postgres_link import CommitAckCut

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
ID = "00000000-0000-4000-8000-000000000501"
RUN = "00000000-0000-4000-8000-000000000510"
NOW = datetime(2026, 8, 27, tzinfo=UTC)
INTENT = {"command_id": ID, "kind": "CREATE_RESEARCH_RUN", "fingerprint": "a" * 64}
RECEIPT = {**INTENT, "outcome_kind": "RESEARCH_RUN", "outcome_id": RUN, "accepted_at": NOW.isoformat()}


def run(probe: Path, op: str, *, no_reply: bool = False, **fields: object) -> dict[str, Any]:
    request = {**RECEIPT, "op": op, **fields}
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    if no_reply:
        assert result.stdout == ""
        return {}
    return cast(dict[str, Any], json.loads(result.stdout))


def models() -> tuple[OnlyProductCommandAdmissionV1, OnlyProductCommandReceipt]:
    admission = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId(ID), OnlyProductCommandKind.CREATE_RESEARCH_RUN, "a" * 64
    )
    return admission, OnlyProductCommandReceipt(
        admission.command_id,
        admission.command_kind,
        admission.command_fingerprint,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, RUN),
        NOW,
    )


def test_existing_python_history_is_read_exactly_by_fresh_rust_process(native_probe: Path, postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    owner = OnlyPostgresProductCommandAuthority(postgres_dsn)
    admission, receipt = models()
    assert run(native_probe, "binding") == {"state": "NONE"}
    owner.admit_exact(admission)
    unknown = run(native_probe, "binding")
    assert unknown["state"] == "ADMITTED_NO_OUTCOME"
    assert unknown["admission"] == {
        "schema_version": 1,
        "command_id": ID,
        "command_kind": INTENT["kind"],
        "command_fingerprint": "a" * 64,
    }
    owner.put_verified_receipt(receipt)
    accepted = run(native_probe, "binding")
    assert accepted == {
        "state": "VERIFIED_ACCEPTED",
        "admission": unknown["admission"],
        "receipt": {"outcome_kind": "RESEARCH_RUN", "outcome_id": RUN, "accepted_at": "2026-08-27T00:00:00Z"},
    }
    assert run(native_probe, "admit") == {"result": "REUSED"}
    assert run(native_probe, "receipt") == {"result": "REUSED"}


def test_rust_writes_are_exactly_read_by_existing_python_and_conflicts_cannot_rebind(
    native_probe: Path, postgres_dsn: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    owner = OnlyPostgresProductCommandAuthority(postgres_dsn)
    admission, receipt = models()
    assert run(native_probe, "receipt") == {"error": "PRODUCT_COMMAND_RECEIPT_CORRUPT"}
    assert run(native_probe, "admit") == {"result": "CREATED"}
    assert owner.load_admission(admission.command_id) == admission
    assert run(native_probe, "admit", fingerprint="b" * 64) == {"error": "PRODUCT_COMMAND_CONFLICT"}
    assert run(native_probe, "admit", kind="CREATE_BACKTEST_RUN") == {"error": "PRODUCT_COMMAND_CONFLICT"}
    assert run(native_probe, "receipt") == {"result": "CREATED"}
    assert owner.load_verified_receipt(admission.command_id) == receipt
    assert run(native_probe, "receipt", outcome_id="00000000-0000-4000-8000-000000000511") == {
        "error": "PRODUCT_COMMAND_CONFLICT"
    }
    assert owner.load_verified_receipt(admission.command_id) == receipt
    assert run(native_probe, "lost-connection") == {"error": "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"}
    assert run(native_probe, "binding")["state"] == "VERIFIED_ACCEPTED"


def test_caller_transaction_rolls_back_all_effects_and_lost_response_preserves_same_identity(
    native_probe: Path, postgres_dsn: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("CREATE TABLE command_atomic_effect(command_id UUID PRIMARY KEY)")
    assert run(native_probe, "rollback") == {"result": "ROLLED_BACK"}
    assert run(native_probe, "binding") == {"state": "NONE"}
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM command_atomic_effect").fetchone() == (0,)
    run(native_probe, "commit-no-reply", no_reply=True)
    assert run(native_probe, "binding")["state"] == "VERIFIED_ACCEPTED"
    assert run(native_probe, "admit") == {"result": "REUSED"}
    assert run(native_probe, "receipt") == {"result": "REUSED"}
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM command_atomic_effect").fetchone() == (1,)


def test_existing_stricter_transaction_timeouts_are_never_relaxed(native_probe: Path, postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assert run(native_probe, "bounds") == {"statement_timeout": "1s", "lock_timeout": "500ms"}


@pytest.mark.parametrize("other_fingerprint", ["a" * 64, "b" * 64])
def test_two_ready_native_processes_serialize_one_command_identity(
    native_probe: Path, postgres_dsn: str, other_fingerprint: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    children = [
        subprocess.Popen(
            [str(native_probe), "--barrier"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            assert child.stdout is not None
            assert json.loads(child.stdout.readline()) == {"ready": True}
        for child, fingerprint in zip(children, ["a" * 64, other_fingerprint], strict=True):
            assert child.stdin is not None
            child.stdin.write(json.dumps({**RECEIPT, "op": "admit", "fingerprint": fingerprint}))
            child.stdin.close()
            child.stdin = None
        outputs = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            outputs.append(json.loads(stdout))
        assert outputs.count({"result": "CREATED"}) == 1
        expected = {"result": "REUSED"} if other_fingerprint == "a" * 64 else {"error": "PRODUCT_COMMAND_CONFLICT"}
        assert outputs.count(expected) == 1
        binding = run(native_probe, "binding")
        assert binding["state"] == "ADMITTED_NO_OUTCOME"
        assert binding["admission"]["command_fingerprint"] in {"a" * 64, other_fingerprint}
        with psycopg.connect(postgres_dsn) as connection:
            assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


@pytest.mark.parametrize(
    "damage",
    [
        "orphan",
        "copied-kind",
        "copied-fingerprint",
        "receipt-schema",
        "outcome-family",
        "timestamp-infinity",
        "admission-schema",
    ],
)
def test_corrupt_rows_never_become_absence_or_accepted_and_optional_receipt_cannot_hide_admission(
    native_probe: Path, postgres_dsn: str, damage: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    owner = OnlyPostgresProductCommandAuthority(postgres_dsn)
    admission, receipt = models()
    if damage != "orphan":
        owner.admit_exact(admission)
        owner.put_verified_receipt(receipt)
    with psycopg.connect(postgres_dsn) as connection:
        if damage == "orphan":
            # Controlled corrupt source row in the guarded disposable test DB;
            # preserve source append-only/delete protections even in this fixture.
            connection.execute(
                "INSERT INTO product_command_receipt(command_id,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at,schema_version) VALUES(%s,%s,%s,'RESEARCH_RUN',%s,%s,1)",
                (ID, INTENT["kind"], "a" * 64, RUN, NOW),
            )
        elif damage == "copied-kind":
            connection.execute(
                "UPDATE product_command_receipt SET command_kind='CREATE_BACKTEST_RUN' WHERE command_id=%s", (ID,)
            )
        elif damage == "copied-fingerprint":
            connection.execute(
                "UPDATE product_command_receipt SET command_fingerprint=%s WHERE command_id=%s", ("b" * 64, ID)
            )
        elif damage == "receipt-schema":
            connection.execute(
                "ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_schema_version_check"
            )
            connection.execute("UPDATE product_command_receipt SET schema_version=2 WHERE command_id=%s", (ID,))
        elif damage == "outcome-family":
            connection.execute(
                "ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_kind_check"
            )
            connection.execute(
                "ALTER TABLE product_command_receipt DROP CONSTRAINT product_command_receipt_outcome_id_check"
            )
            connection.execute(
                "UPDATE product_command_receipt SET outcome_kind='NOT_A_PRODUCT_RESOURCE' WHERE command_id=%s", (ID,)
            )
        elif damage == "timestamp-infinity":
            connection.execute("UPDATE product_command_receipt SET accepted_at='infinity' WHERE command_id=%s", (ID,))
        else:
            connection.execute(
                "ALTER TABLE product_command_admission DROP CONSTRAINT product_command_admission_schema_version_check"
            )
            connection.execute("UPDATE product_command_admission SET schema_version=2 WHERE command_id=%s", (ID,))
    expected = (
        "PRODUCT_COMMAND_ADMISSION_CORRUPT" if damage == "admission-schema" else "PRODUCT_COMMAND_RECEIPT_CORRUPT"
    )
    assert run(native_probe, "binding") == {"error": expected}
    if damage == "orphan":
        assert run(native_probe, "load-admission") == {"admission": None}
    elif damage == "admission-schema":
        assert run(native_probe, "load-admission") == {"error": expected}
    else:
        assert run(native_probe, "load-admission")["admission"]["command_id"] == ID


@pytest.mark.parametrize(
    "accepted_at", ["0001-01-01T00:00:00Z", "1969-12-31T23:59:59.999999Z", "9999-12-31T23:59:59.999999Z"]
)
def test_exact_utc_microseconds_roundtrip_at_domain_boundaries(
    native_probe: Path, postgres_dsn: str, accepted_at: str
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assert run(native_probe, "admit") == {"result": "CREATED"}
    assert run(native_probe, "receipt", accepted_at=accepted_at) == {"result": "CREATED"}
    assert run(native_probe, "binding")["receipt"]["accepted_at"] == accepted_at
    expected = datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    receipt = OnlyPostgresProductCommandAuthority(postgres_dsn).load_verified_receipt(OnlyProductCommandId(ID))
    assert receipt is not None
    assert receipt.accepted_at == expected


def test_actual_pg_commit_ack_loss_is_uncertain_then_fresh_reader_recovers_same_identity(
    native_probe: Path, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("CREATE TABLE command_atomic_effect(command_id UUID PRIMARY KEY)")
    with CommitAckCut(postgres_dsn) as fault:
        with monkeypatch.context() as child_configuration:
            child_configuration.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert run(native_probe, "atomic-commit") == {"error": "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"}
        assert fault.done.is_set(), "must observe server's actual COMMIT, not a precommit disconnect"
    assert run(native_probe, "binding")["state"] == "VERIFIED_ACCEPTED"
    assert run(native_probe, "admit") == {"result": "REUSED"}
    assert run(native_probe, "receipt") == {"result": "REUSED"}
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM command_atomic_effect").fetchone() == (1,)
