"""A3 technical authority proofs. Shipping C2 stays unchanged until A4."""

from __future__ import annotations

import hashlib
import json
import subprocess
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
AT = "2026-10-28T00:00:00Z"


def call(probe, action, *, command=None, actor="owner", token=None, body=None, **values):
    request = {
        "op": "factor-proposal",
        "action": action,
        "command_id": command or str(uuid4()),
        "actor": actor,
        "token": token,
        "body": body or {},
        "at": AT,
        **values,
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(request), text=True, capture_output=True, check=True, timeout=20
    )
    return json.loads(result.stdout)


def grant(probe, dsn):
    OnlyPostgresMigrationAuthority(dsn).migrate()
    gid = str(uuid4())
    token = "oa-proposal-v1." + gid + "." + "a" * 64
    body = {
        "schema_version": 1,
        "grant_id": gid,
        "service_subject": "discovery",
        "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "proposal_limit": 3,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    result = call(probe, "grant", body=body)
    assert "error" not in result, result
    return gid, token


def proposal(probe, token, sid=None):
    sid = sid or str(uuid4())
    context = call(probe, "context", token=token, session_id=sid)
    assert "error" not in context, context
    return {
        "schema_version": 1,
        "origin": {
            "session_id": sid,
            "event_fingerprint": "b" * 64,
            "result_fingerprint": "c" * 64,
            "workflow_fingerprint": "d" * 64,
            "model_revision": "e" * 64,
        },
        "candidate": {
            "name": "放量动量",
            "purpose": "观察量价变化",
            "hypothesis": "价格变化具有持续性",
            "expression": {"op": "sub", "left": {"input": "close"}, "right": {"input": "close", "lag": 20}},
        },
        "expected_draft_fingerprint": context["draft_fingerprint"],
        "expected_display_fingerprint": context["display_fingerprint"],
        "expected_proposal_fingerprint": context["proposal_fingerprint"],
    }


def test_stage_confirm_receipt_and_restart_use_one_authoring_effect(native_probe, postgres_dsn):
    _, token = grant(native_probe, postgres_dsn)
    body = proposal(native_probe, token)
    command = str(uuid4())
    staged = call(native_probe, "stage", token=token, command=command, body=body)
    assert "error" not in staged, staged
    assert call(native_probe, "stage", token=token, command=command, body=body) == staged
    fp = staged["effect"]["proposal_fingerprint"]
    view = call(native_probe, "read", fingerprint=fp)
    assert view["snapshot"]["preview"]["formula"] == "(close − lag(close, 20))"
    assert view["snapshot"]["preview"]["execution_admitted"] is False
    assert call(native_probe, "observe", token=token, observed_command=command) == staged
    confirm_id = str(uuid4())
    confirmed = call(
        native_probe, "confirm", command=confirm_id, body={"schema_version": 1, "proposal_fingerprint": fp}
    )
    assert "error" not in confirmed, confirmed
    assert (
        call(native_probe, "confirm", command=confirm_id, body={"schema_version": 1, "proposal_fingerprint": fp})
        == confirmed
    )
    with psycopg.connect(postgres_dsn) as db:
        fid = view["snapshot"]["factor_id"]
        assert db.execute("SELECT count(*) FROM private_factor_revision WHERE factor_id=%s", (fid,)).fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM private_factor_authoring_outcome WHERE factor_id=%s", (fid,)).fetchone()[0]
            == 1
        )


def test_service_scope_revocation_and_stale_proposals(native_probe, postgres_dsn):
    gid, token = grant(native_probe, postgres_dsn)
    first = proposal(native_probe, token)
    staged = call(native_probe, "stage", token=token, body=first)
    fp = staged["effect"]["proposal_fingerprint"]
    assert "error" in call(native_probe, "confirm", token=token, body={"schema_version": 1, "proposal_fingerprint": fp})
    assert "error" in call(native_probe, "read", actor="other", fingerprint=fp)
    newer = proposal(native_probe, token, first["origin"]["session_id"])
    newer["origin"]["event_fingerprint"] = "f" * 64
    newer["candidate"]["name"] = "新的名称"
    second = call(native_probe, "stage", token=token, body=newer)
    assert "error" not in second, second
    assert "error" in call(native_probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": fp})
    assert "error" in call(native_probe, "stage", token=token, body=first)
    assert "error" not in call(native_probe, "revoke", body={"schema_version": 1, "grant_id": gid})
    assert "error" in call(native_probe, "context", token=token, session_id=str(uuid4()))
    # Already registered input remains readable by its Human owner without the Agent.
    assert "error" not in call(native_probe, "read", fingerprint=second["effect"]["proposal_fingerprint"])


def test_grant_expiry_tampering_and_budget_have_no_authoring_effect(native_probe, postgres_dsn):
    gid, token = grant(native_probe, postgres_dsn)
    bad = proposal(native_probe, token)
    bad["candidate"]["source_text"] = "def calculate(): pass"
    assert "error" in call(native_probe, "stage", token=token, body=bad)
    assert "error" in call(native_probe, "context", token=token[:-1] + "b", session_id=str(uuid4()))
    assert "error" in call(native_probe, "context", token=token, session_id=str(uuid4()), at="2028-01-01T00:00:00Z")
    for _ in range(3):
        assert "error" not in call(native_probe, "stage", token=token, body=proposal(native_probe, token))
    assert (
        call(native_probe, "stage", token=token, body=proposal(native_probe, token))["error"]
        == "FACTOR_PROPOSAL_BUDGET_EXHAUSTED"
    )
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_proposal_snapshot WHERE grant_id=%s", (gid,)).fetchone()[0] == 3


def test_confirmation_failure_rolls_back_authoring_and_global_receipts(native_probe, postgres_dsn):
    _, token = grant(native_probe, postgres_dsn)
    staged = call(native_probe, "stage", token=token, body=proposal(native_probe, token))
    fp = staged["effect"]["proposal_fingerprint"]
    fid = call(native_probe, "read", fingerprint=fp)["snapshot"]["factor_id"]
    command = str(uuid4())
    with psycopg.connect(postgres_dsn, autocommit=True) as db:
        db.execute(
            "CREATE FUNCTION a3_reject_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_kind='CONFIRM_FACTOR_PROPOSAL' THEN RAISE EXCEPTION 'controlled receipt fault'; END IF; RETURN NEW; END $$"
        )
        db.execute(
            "CREATE TRIGGER a3_reject_receipt BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION a3_reject_receipt()"
        )
        try:
            assert "error" in call(
                native_probe, "confirm", command=command, body={"schema_version": 1, "proposal_fingerprint": fp}
            )
            assert db.execute("SELECT count(*) FROM private_factor_asset WHERE factor_id=%s", (fid,)).fetchone()[0] == 0
            assert (
                db.execute("SELECT count(*) FROM product_command_admission WHERE command_id=%s", (command,)).fetchone()[
                    0
                ]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM factor_proposal_confirmation WHERE proposal_fingerprint=%s", (fp,)
                ).fetchone()[0]
                == 0
            )
        finally:
            db.execute("DROP TRIGGER a3_reject_receipt ON product_command_receipt")
            db.execute("DROP FUNCTION a3_reject_receipt()")
    assert "error" not in call(
        native_probe, "confirm", command=command, body={"schema_version": 1, "proposal_fingerprint": fp}
    )


def test_manual_authoring_change_and_command_collision_are_rejected(native_probe, postgres_dsn):
    from packages.backend.tests.application.test_private_factor_authoring_postgres import call as author
    from packages.backend.tests.application.test_private_factor_authoring_postgres import draft

    _, token = grant(native_probe, postgres_dsn)
    request = proposal(native_probe, token)
    command = str(uuid4())
    registered = call(native_probe, "stage", command=command, token=token, body=request)
    fp = registered["effect"]["proposal_fingerprint"]
    fid = call(native_probe, "read", fingerprint=fp)["snapshot"]["factor_id"]
    assert "error" in call(
        native_probe, "confirm", command=command, body={"schema_version": 1, "proposal_fingerprint": fp}
    )
    assert "error" not in author(native_probe, fid, "save", draft=draft(fid), expected=None)
    assert (
        call(native_probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": fp})["error"]
        == "FACTOR_PROPOSAL_AUTHORING_CONFLICT"
    )


@pytest.mark.parametrize("mutation", ["wrong_family", "different_proposal"])
def test_confirmation_structural_relation_must_prove_exact_human_effect(native_probe, postgres_dsn, mutation):
    _, token = grant(native_probe, postgres_dsn)
    staged = call(native_probe, "stage", token=token, body=proposal(native_probe, token))
    fp = staged["effect"]["proposal_fingerprint"]
    other = call(native_probe, "stage", token=token, body=proposal(native_probe, token))
    command = staged["command_id"]
    if mutation == "different_proposal":
        confirmed = call(
            native_probe,
            "confirm",
            body={"schema_version": 1, "proposal_fingerprint": other["effect"]["proposal_fingerprint"]},
        )
        command = confirmed["command_id"]
    with psycopg.connect(postgres_dsn) as db:
        # Deliberate malformed relation in the isolated _test Authority, not a user workflow.
        if mutation == "different_proposal":
            db.execute("ALTER TABLE factor_proposal_confirmation DISABLE TRIGGER USER")
            db.execute(
                "UPDATE factor_proposal_confirmation SET proposal_fingerprint=%s WHERE command_id=%s", (fp, command)
            )
            db.execute("ALTER TABLE factor_proposal_confirmation ENABLE TRIGGER USER")
        else:
            db.execute("INSERT INTO factor_proposal_confirmation VALUES(%s,%s)", (fp, command))
    assert call(native_probe, "read", fingerprint=fp) == {"error": "FACTOR_PROPOSAL_CORRUPT"}


@pytest.mark.parametrize("mutation", ["foreign", "missing", "superseded"])
def test_head_structural_mutation_cannot_be_certified_as_nonmatch(native_probe, postgres_dsn, mutation):
    _, token = grant(native_probe, postgres_dsn)
    request = proposal(native_probe, token)
    first = call(native_probe, "stage", token=token, body=request)["effect"]["proposal_fingerprint"]
    fid = call(native_probe, "read", fingerprint=first)["snapshot"]["factor_id"]
    newer = proposal(native_probe, token, request["origin"]["session_id"])
    newer["origin"]["event_fingerprint"] = "f" * 64
    current = call(native_probe, "stage", token=token, body=newer)["effect"]["proposal_fingerprint"]
    foreign = call(native_probe, "stage", token=token, body=proposal(native_probe, token))["effect"][
        "proposal_fingerprint"
    ]
    with psycopg.connect(postgres_dsn) as db:
        if mutation == "missing":
            db.execute("DELETE FROM factor_proposal_head WHERE factor_id=%s", (fid,))
        else:
            db.execute(
                "UPDATE factor_proposal_head SET fingerprint=%s WHERE factor_id=%s",
                (foreign if mutation == "foreign" else first, fid),
            )
    assert call(native_probe, "read", fingerprint=current) == {"error": "FACTOR_PROPOSAL_CORRUPT"}
    assert call(native_probe, "context", token=token, session_id=request["origin"]["session_id"]) == {
        "error": "FACTOR_PROPOSAL_CORRUPT"
    }


@pytest.mark.parametrize("mutation", ["missing_save", "unrelated_save", "wrong_display"])
def test_confirmation_requires_owning_authoring_children_even_with_valid_hashes(native_probe, postgres_dsn, mutation):
    _, token = grant(native_probe, postgres_dsn)
    first = call(native_probe, "stage", token=token, body=proposal(native_probe, token))["effect"][
        "proposal_fingerprint"
    ]
    other = call(native_probe, "stage", token=token, body=proposal(native_probe, token))["effect"][
        "proposal_fingerprint"
    ]
    accepted = call(native_probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": first})
    unrelated = call(native_probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": other})
    with psycopg.connect(postgres_dsn) as db:
        record = db.execute(
            "SELECT payload FROM factor_proposal_operation WHERE command_id=%s", (accepted["command_id"],)
        ).fetchone()[0]
        if mutation == "missing_save":
            record["effect"]["authoring"] = None
        elif mutation == "unrelated_save":
            record["effect"]["authoring"] = unrelated["effect"]["authoring"]
        else:
            record["effect"]["display_authoring"] = unrelated["effect"]["authoring"]
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        pin = hashlib.sha256(raw.encode()).hexdigest()
        # Controlled corruption of isolated test facts, including valid copied digest/receipt pointers.
        for table in ["factor_proposal_operation", "product_command_receipt"]:
            db.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
        db.execute(
            "UPDATE factor_proposal_operation SET payload=%s::jsonb,fingerprint=%s WHERE command_id=%s",
            (raw, pin, accepted["command_id"]),
        )
        db.execute(
            "UPDATE product_command_receipt SET outcome_id=%s WHERE command_id=%s", (pin, accepted["command_id"])
        )
        for table in ["factor_proposal_operation", "product_command_receipt"]:
            db.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    assert call(native_probe, "read", fingerprint=first) == {"error": "FACTOR_PROPOSAL_CORRUPT"}
