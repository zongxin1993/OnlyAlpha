"""Real PG Study-registration Authority proofs; these are not Shipping UI acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest

from packages.backend.tests.application.test_factor_proposals_postgres import (
    AT,
)
from packages.backend.tests.application.test_factor_proposals_postgres import (
    call as factor_call,
)
from packages.backend.tests.application.test_factor_proposals_postgres import (
    grant as factor_grant,
)
from packages.backend.tests.application.test_factor_proposals_postgres import (
    proposal as factor_proposal,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
EXPIRED = "2028-01-01T00:00:00Z"


def call(
    probe: Path,
    action: str,
    *,
    command: str | None = None,
    actor: str = "owner",
    token: str | None = None,
    body: dict[str, Any] | None = None,
    at: str = AT,
    **values: Any,
) -> dict[str, Any]:
    request = {
        "op": "factor-study",
        "action": action,
        "command_id": command or str(uuid4()),
        "actor": actor,
        "token": token,
        "body": body or {},
        "at": at,
        **values,
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(request), text=True, capture_output=True, check=True, timeout=20
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def confirmed(probe: Path, dsn: str) -> tuple[str, str, str, dict[str, Any]]:
    gid, token = factor_grant(probe, dsn)
    body = factor_proposal(probe, token)
    staged = factor_call(probe, "stage", token=token, body=body)
    assert "error" not in staged, staged
    pin = staged["effect"]["proposal_fingerprint"]
    confirmation = factor_call(probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": pin})
    assert "error" not in confirmation, confirmation
    return gid, token, pin, body


def grant(factor_pin: str, limit: int = 2) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "factor_proposal_fingerprint": factor_pin,
        "grant_id": str(uuid4()),
        "proposal_limit": limit,
    }
    return body


def proposal(factor_pin: str, original: dict[str, Any], expected: str | None = None) -> dict[str, Any]:
    origin = copy.deepcopy(original["origin"])
    origin["event_fingerprint"] = hashlib.sha256(str(uuid4()).encode()).hexdigest()
    return {
        "schema_version": 1,
        "factor_proposal_fingerprint": factor_pin,
        "origin": origin,
        "expected_study_fingerprint": expected,
        "advice": {
            "source": {
                "integration_id": "00000000-0000-4000-8000-000000000002",
                "integration_revision_fingerprint": "f" * 64,
                "expected_type_id": "binance.spot.source",
                "source_id": "spot",
                "environment": "public",
                "instrument_id": "BTCUSDT.BINANCE",
            },
            "timeframe_minutes": 1,
            "start_at": "1970-01-01T00:02:00Z",
            "development_end_at": "1970-01-01T01:06:00Z",
            "end_at": "1970-01-01T02:10:00Z",
            "protected_start_at": "1970-01-01T02:10:00Z",
            "protected_end_at": "1970-01-01T03:14:00Z",
            "horizon_bars": 1,
            "expected_block_length": 4,
            "replicates": 4096,
            "confidence_bps": 9500,
            "seed": "0" * 64,
            "rationale": "固定开发和样本外区间，保留样本不读取。",
        },
    }


def staged(probe: Path, token: str, factor_pin: str, original: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    granted = call(probe, "grant", body=grant(factor_pin))
    assert "error" not in granted, granted
    body = proposal(factor_pin, original)
    command = str(uuid4())
    result = call(probe, "stage", command=command, token=token, body=body)
    assert "error" not in result, result
    return result["effect"]["proposal_fingerprint"], command, body


def test_explicit_scope_quota_and_same_command_restart_replay(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    body = proposal(factor_pin, original)
    assert call(native_probe, "stage", token=token, body=body)["error"] == "FACTOR_STUDY_GRANT_REQUIRED"
    assert "error" in call(native_probe, "grant", actor="other", body=grant(factor_pin))
    assert "error" in call(native_probe, "grant", token=token, body=grant(factor_pin))
    grant_body = grant(factor_pin)
    grant_command = str(uuid4())
    permission = call(native_probe, "grant", command=grant_command, body=grant_body)
    assert "error" not in permission, permission
    assert call(native_probe, "grant", command=grant_command, body=grant_body) == permission
    assert call(native_probe, "grant", body=grant(factor_pin))["error"] == "FACTOR_STUDY_GRANT_CONFLICT"
    command = str(uuid4())
    first = call(native_probe, "stage", command=command, token=token, body=body)
    assert "error" not in first, first
    assert call(native_probe, "stage", command=command, token=token, body=body) == first
    assert call(native_probe, "observe", token=token, observed_command=command) == first
    pin = first["effect"]["proposal_fingerprint"]
    second_body = proposal(factor_pin, original, pin)
    second = call(native_probe, "stage", token=token, body=second_body)
    assert "error" not in second, second
    assert (
        call(
            native_probe,
            "stage",
            token=token,
            body=proposal(factor_pin, original, second["effect"]["proposal_fingerprint"]),
        )["error"]
        == "FACTOR_STUDY_PROPOSAL_BUDGET_EXHAUSTED"
    )
    assert (
        call(native_probe, "context", token=token, factor_proposal_fingerprint=factor_pin)["error"]
        == "FACTOR_STUDY_PROPOSAL_BUDGET_EXHAUSTED"
    )
    context = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin)
    assert context["remaining_proposals"] == 0
    assert context["factor"]["name"] == "放量动量"
    assert call(native_probe, "read", fingerprint=pin)["is_current"] is False
    changed = copy.deepcopy(body)
    changed["advice"]["rationale"] = "different"
    assert (
        call(native_probe, "stage", command=command, token=token, body=changed)["error"]
        == "FACTOR_STUDY_COMMAND_CONFLICT"
    )
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM factor_study_grant").fetchone()[0] == 1
        for table in ["research_run", "research_factor_study_authorization", "private_factor_revision"]:
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("boundary", ["expiry", "revocation"])
def test_inherited_parent_revocation_blocks_new_writes_but_not_original_outcomes(native_probe, postgres_dsn, boundary):
    gid, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    grant_body = grant(factor_pin)
    grant_command = str(uuid4())
    granted = call(native_probe, "grant", command=grant_command, body=grant_body)
    assert "error" not in granted, granted
    body = proposal(factor_pin, original)
    command = str(uuid4())
    registered = call(native_probe, "stage", command=command, token=token, body=body)
    assert "error" not in registered, registered
    at = AT
    if boundary == "revocation":
        assert "error" not in factor_call(native_probe, "revoke", body={"grant_id": gid})
    else:
        at = EXPIRED
    assert call(native_probe, "grant", command=grant_command, body=grant_body, at=at) == granted
    assert call(native_probe, "stage", command=command, token=token, body=body, at=at) == registered
    assert call(native_probe, "observe", token=token, observed_command=command, at=at) == registered
    pin = registered["effect"]["proposal_fingerprint"]
    assert "error" not in call(native_probe, "read", token=token, fingerprint=pin, at=at)
    assert "error" in call(native_probe, "stage", token=token, body=proposal(factor_pin, original, pin), at=at)
    assert "error" in call(native_probe, "grant", body=grant(factor_pin), at=at)
    wrong = token[:-64] + "b" * 64
    assert "error" in call(native_probe, "observe", token=wrong, observed_command=command, at=at)


@pytest.mark.parametrize("mutation", ["session", "workflow", "uncertainty", "service_token", "owner"])
def test_stage_never_inherits_cross_session_or_cross_credential_authority(native_probe, postgres_dsn, mutation):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    assert "error" not in call(native_probe, "grant", body=grant(factor_pin))
    body = proposal(factor_pin, original)
    if mutation == "session":
        body["origin"]["session_id"] = str(uuid4())
    elif mutation == "workflow":
        body["origin"]["workflow_fingerprint"] = "9" * 64
    elif mutation == "uncertainty":
        body["advice"]["replicates"] = 10
    elif mutation == "service_token":
        _, token = factor_grant(native_probe, postgres_dsn)
    else:
        _, token = factor_grant(native_probe, postgres_dsn, owner="other")
    assert "error" in call(native_probe, "stage", token=token, body=body)
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone()[0] == 0


def test_stale_study_and_new_factor_head_are_not_silently_reinterpreted(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, command, body = staged(native_probe, token, factor_pin, original)
    assert (
        call(native_probe, "stage", token=token, body=proposal(factor_pin, original))["error"]
        == "FACTOR_STUDY_PROPOSAL_STALE"
    )
    repeated_event = copy.deepcopy(body)
    repeated_event["expected_study_fingerprint"] = pin
    assert call(native_probe, "stage", token=token, body=repeated_event)["error"] == "FACTOR_STUDY_ORIGIN_CONFLICT"
    newer = factor_proposal(native_probe, token, original["origin"]["session_id"])
    newer["origin"]["event_fingerprint"] = "7" * 64
    assert "error" not in factor_call(native_probe, "stage", token=token, body=newer)
    assert (
        call(native_probe, "stage", token=token, body=proposal(factor_pin, original, pin))["error"]
        == "FACTOR_PROPOSAL_STALE"
    )
    assert call(native_probe, "stage", command=command, token=token, body=body)["effect"]["proposal_fingerprint"] == pin
    assert "error" not in call(native_probe, "read", fingerprint=pin)


def test_explicit_withdrawal_retains_confirmation_and_original_receipt(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, stage_command, stage_body = staged(native_probe, token, factor_pin, original)
    factor_before = factor_call(native_probe, "read", fingerprint=factor_pin)
    body = {"schema_version": 1, "study_proposal_fingerprint": pin}
    assert "error" in call(native_probe, "withdraw", actor="other", body=body)
    assert "error" in call(native_probe, "withdraw", token=token, body=body)
    command = str(uuid4())
    withdrawn = call(native_probe, "withdraw", command=command, body=body)
    assert "error" not in withdrawn, withdrawn
    assert call(native_probe, "withdraw", command=command, body=body) == withdrawn
    assert call(native_probe, "read", fingerprint=pin)["withdrawn"] is True
    assert (
        call(native_probe, "stage", command=stage_command, token=token, body=stage_body)["effect"][
            "proposal_fingerprint"
        ]
        == pin
    )
    assert factor_call(native_probe, "read", fingerprint=factor_pin) == factor_before
    next_study = call(native_probe, "stage", token=token, body=proposal(factor_pin, original, pin))
    assert "error" not in next_study, next_study
    assert call(native_probe, "withdraw", body=body)["error"] == "FACTOR_STUDY_PROPOSAL_STALE"
    assert call(native_probe, "withdraw", command=command, body=body) == withdrawn


def test_same_service_other_parent_token_cannot_read_or_observe_original_scope(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, command, _ = staged(native_probe, token, factor_pin, original)
    _, other = factor_grant(native_probe, postgres_dsn)
    assert "error" in call(native_probe, "read", token=other, fingerprint=pin)
    assert "error" in call(native_probe, "observe", token=other, observed_command=command)
    assert "error" in call(native_probe, "read", actor="other", fingerprint=pin)
    assert "error" in call(native_probe, "observe", actor="other", observed_command=command)


@pytest.mark.parametrize("missing", ["head", "operation", "withdrawal", "snapshot"])
def test_missing_fact_or_projection_is_never_interpreted_as_available_or_absent(native_probe, postgres_dsn, missing):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, command, _ = staged(native_probe, token, factor_pin, original)
    if missing == "withdrawal":
        assert "error" not in call(
            native_probe, "withdraw", body={"schema_version": 1, "study_proposal_fingerprint": pin}
        )
    with psycopg.connect(postgres_dsn) as db:
        if missing in {"head", "snapshot"}:
            db.execute("DELETE FROM factor_study_head WHERE factor_proposal_fingerprint=%s", (factor_pin,))
        if missing != "head":
            table = {
                "operation": "factor_study_operation",
                "withdrawal": "factor_study_withdrawal",
                "snapshot": "factor_study_snapshot",
            }[missing]
            db.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
            if missing == "operation":
                db.execute("DELETE FROM factor_study_operation WHERE command_id=%s", (command,))
            elif missing == "withdrawal":
                db.execute("DELETE FROM factor_study_withdrawal WHERE study_proposal_fingerprint=%s", (pin,))
            else:
                db.execute("DELETE FROM factor_study_snapshot WHERE fingerprint=%s", (pin,))
            db.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")
    action = "context" if missing in {"head", "snapshot"} else "read"
    assert (
        call(native_probe, action, token=token, fingerprint=pin, factor_proposal_fingerprint=factor_pin)["error"]
        == "FACTOR_STUDY_PROPOSAL_CORRUPT"
    )


@pytest.mark.parametrize(
    "table", ["factor_study_grant", "factor_study_snapshot", "factor_study_operation", "factor_study_withdrawal"]
)
def test_study_source_facts_reject_mutation_and_truncation(native_probe, postgres_dsn, table):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, _, _ = staged(native_probe, token, factor_pin, original)
    assert "error" not in call(native_probe, "withdraw", body={"schema_version": 1, "study_proposal_fingerprint": pin})
    assignment = "command_id=command_id" if table == "factor_study_withdrawal" else "payload=payload"
    for statement in [f"UPDATE {table} SET {assignment}", f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"]:
        with (
            psycopg.connect(postgres_dsn) as db,
            pytest.raises(psycopg.Error, match="Private Asset Revisions are immutable"),
        ):
            db.execute(statement)
    assert call(native_probe, "read", fingerprint=pin)["withdrawn"] is True


def test_operation_failure_rolls_back_snapshot_head_and_global_receipt(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    assert "error" not in call(native_probe, "grant", body=grant(factor_pin))
    command = str(uuid4())
    body = proposal(factor_pin, original)
    with psycopg.connect(postgres_dsn) as db:
        db.execute(
            "CREATE FUNCTION study_operation_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled study operation fault'; END $$"
        )
        db.execute(
            "CREATE TRIGGER study_operation_fault BEFORE INSERT ON factor_study_operation FOR EACH STATEMENT EXECUTE FUNCTION study_operation_fault()"
        )
    assert (
        call(native_probe, "stage", command=command, token=token, body=body)["error"]
        == "FACTOR_STUDY_PROPOSAL_UNAVAILABLE"
    )
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM factor_study_head").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM product_command_admission WHERE command_id=%s", (command,)).fetchone()[0]
            == 0
        )
        assert (
            db.execute("SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)).fetchone()[0]
            == 0
        )
        db.execute("DROP TRIGGER study_operation_fault ON factor_study_operation")
        db.execute("DROP FUNCTION study_operation_fault()")
    # Positive absence was proved at the original transaction boundary; reuse the same identity.
    result = call(native_probe, "stage", command=command, token=token, body=body)
    assert "error" not in result, result
    assert call(native_probe, "observe", token=token, observed_command=command) == result


def test_admitted_unknown_cannot_become_a_second_registration(native_probe, postgres_dsn):
    gid, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    assert "error" not in call(native_probe, "grant", body=grant(factor_pin))
    command = str(uuid4())
    body = proposal(factor_pin, original)
    with psycopg.connect(postgres_dsn) as db:
        parent = db.execute("SELECT fingerprint FROM factor_proposal_grant WHERE grant_id=%s", (gid,)).fetchone()[0]
        intent = {
            "contract": "ONLYALPHA_FACTOR_STUDY_COMMAND_V1",
            "owner": "owner",
            "actor": "discovery",
            "kind": "STAGE_FACTOR_STUDY",
            "body": {"parent_grant_fingerprint": parent, "stage": body},
        }
        pin = hashlib.sha256(
            json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        db.execute(
            "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,'STAGE_FACTOR_STUDY',%s,1)",
            (command, pin),
        )
    assert (
        call(native_probe, "stage", command=command, token=token, body=body)["error"] == "FACTOR_STUDY_COMMAND_UNKNOWN"
    )
    assert (
        call(native_probe, "observe", token=token, observed_command=command)["error"] == "FACTOR_STUDY_COMMAND_UNKNOWN"
    )
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone()[0] == 0
        assert (
            db.execute("SELECT count(*) FROM product_command_admission WHERE command_id=%s", (command,)).fetchone()[0]
            == 1
        )
        assert (
            db.execute("SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)).fetchone()[0]
            == 0
        )


def test_copied_global_receipt_family_is_not_study_authority(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, command, _ = staged(native_probe, token, factor_pin, original)
    with psycopg.connect(postgres_dsn) as db:
        db.execute("ALTER TABLE product_command_receipt DISABLE TRIGGER USER")
        db.execute(
            "UPDATE product_command_receipt SET outcome_kind='FACTOR_PROPOSAL_OPERATION' WHERE command_id=%s",
            (command,),
        )
        db.execute("ALTER TABLE product_command_receipt ENABLE TRIGGER USER")
    assert call(native_probe, "read", fingerprint=pin)["error"] == "FACTOR_STUDY_PROPOSAL_CORRUPT"
    assert call(native_probe, "observe", observed_command=command)["error"] == "FACTOR_STUDY_PROPOSAL_CORRUPT"


def test_factor_staging_does_not_replace_first_human_confirmation(native_probe, postgres_dsn):
    _, token = factor_grant(native_probe, postgres_dsn)
    original = factor_proposal(native_probe, token)
    first = factor_call(native_probe, "stage", token=token, body=original)
    assert "error" not in first, first
    pin = first["effect"]["proposal_fingerprint"]
    body = grant(pin)
    assert call(native_probe, "grant", body=body)["error"] == "FACTOR_PROPOSAL_NOT_CONFIRMED"
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_grant").fetchone()[0] == 0
    assert "error" not in factor_call(native_probe, "confirm", body={"schema_version": 1, "proposal_fingerprint": pin})
    assert "error" not in call(native_probe, "grant", body=body)


def test_human_context_recovers_existing_registration_without_token_or_new_grant(native_probe, postgres_dsn):
    _, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    missing = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin)
    assert missing["study_grant_id"] is None and missing["remaining_proposals"] == 0
    assert missing["study_grant_state"] == "ABSENT"
    assert (
        call(native_probe, "context", token=token, factor_proposal_fingerprint=factor_pin)["error"]
        == "FACTOR_STUDY_GRANT_REQUIRED"
    )
    assert "error" in call(native_probe, "human-context", actor="other", factor_proposal_fingerprint=factor_pin)
    assert "error" in call(native_probe, "human-context", token=token, factor_proposal_fingerprint=factor_pin)
    pin, _, _ = staged(native_probe, token, factor_pin, original)
    service = call(native_probe, "context", token=token, factor_proposal_fingerprint=factor_pin)
    human = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin)
    assert human == service
    assert human["study_grant_state"] == "ACTIVE"
    assert human["remaining_proposals"] == 1 and human["study_proposal_fingerprint"] == pin
    assert call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin) == human
    assert "credential" not in json.dumps(human).lower()
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_grant").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM factor_study_snapshot").fetchone()[0] == 1


@pytest.mark.parametrize("boundary", ["expiry", "revocation"])
def test_human_registration_context_retains_original_grant_when_parent_becomes_inactive(
    native_probe, postgres_dsn, boundary
):
    gid, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    pin, _, _ = staged(native_probe, token, factor_pin, original)
    original_context = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin)
    at = EXPIRED if boundary == "expiry" else AT
    if boundary == "revocation":
        assert "error" not in factor_call(native_probe, "revoke", body={"grant_id": gid})
    context = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin, at=at)
    assert context["study_grant_state"] == ("EXPIRED" if boundary == "expiry" else "REVOKED")
    assert context["study_grant_id"] == original_context["study_grant_id"]
    assert context["remaining_proposals"] == 1 and context["study_proposal_fingerprint"] == pin
    assert (
        call(native_probe, "context", token=token, factor_proposal_fingerprint=factor_pin, at=at)["error"]
        == "FACTOR_STUDY_GRANT_INACTIVE"
    )
    with psycopg.connect(postgres_dsn) as db:
        assert db.execute("SELECT count(*) FROM factor_study_grant").fetchone()[0] == 1


def test_human_context_does_not_offer_new_permission_after_parent_expiry(native_probe, postgres_dsn):
    _, _, factor_pin, _ = confirmed(native_probe, postgres_dsn)
    context = call(native_probe, "human-context", factor_proposal_fingerprint=factor_pin, at=EXPIRED)
    assert context["study_grant_id"] is None
    assert context["study_grant_state"] == "EXPIRED"
    assert context["remaining_proposals"] == 0


@pytest.mark.parametrize("revoked", [False, True])
def test_historical_factor_study_and_permission_facts_are_verified_on_an_actual_read_only_session(
    native_probe: Path, postgres_dsn: str, revoked: bool
) -> None:
    gid, token, factor_pin, original = confirmed(native_probe, postgres_dsn)
    grant_command = str(uuid4())
    permission = call(native_probe, "grant", command=grant_command, body=grant(factor_pin))
    assert "error" not in permission, permission
    stage_command = str(uuid4())
    staged_result = call(native_probe, "stage", command=stage_command, token=token, body=proposal(factor_pin, original))
    assert "error" not in staged_result, staged_result
    pin = staged_result["effect"]["proposal_fingerprint"]
    if revoked:
        assert "error" not in factor_call(native_probe, "revoke", body={"grant_id": gid})
    factor = factor_call(native_probe, "read", fingerprint=factor_pin)
    study = call(native_probe, "read", fingerprint=pin)
    with psycopg.connect(postgres_dsn) as db:
        before = db.execute(
            "SELECT (SELECT count(*) FROM product_command_admission), (SELECT count(*) FROM product_command_receipt)"
        ).fetchone()
    result = call(
        native_probe,
        "historical-read-only",
        fingerprint=pin,
        factor_proposal_fingerprint=factor_pin,
        grant_command=grant_command,
        observed_command=stage_command,
    )
    assert result == {
        "read_only": "on",
        "factor": factor,
        "study": study,
        "permission": permission,
        "stage": staged_result,
    }
    with psycopg.connect(postgres_dsn) as db:
        assert (
            db.execute(
                "SELECT (SELECT count(*) FROM product_command_admission), (SELECT count(*) FROM product_command_receipt)"
            ).fetchone()
            == before
        )
    if revoked:
        assert (
            call(native_probe, "stage", token=token, body=proposal(factor_pin, original, pin))["error"]
            == "FACTOR_PROPOSAL_UNAUTHORIZED"
        )
