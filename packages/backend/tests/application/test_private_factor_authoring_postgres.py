"""Native authoring Authority checks; business acceptance is the Shipping UI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


def draft(factor_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "factor_id": factor_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return {'value': inputs['close']}\n",
        "factor_api_version": 1,
        "factor_api_contract_fingerprint": "3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9",
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend",
        "category": "price",
        "tags": [],
    }


@pytest.fixture
def database(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def call(probe: Path, factor_id: str, action: str, **values):
    request = {
        "op": "factor-authoring",
        "action": action,
        "factor_id": factor_id,
        "command_id": str(uuid4()),
        "accepted_at": "2026-10-27T00:00:00Z",
        **values,
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(request, separators=(",", ":")), text=True, capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_saved_draft_and_two_revisions_survive_fresh_processes_with_exact_command_replay(native_probe, database):
    factor_id = "private.factor.f" + uuid4().hex
    original = draft(factor_id)
    command = str(uuid4())
    saved = call(native_probe, factor_id, "save", draft=original, expected=None, command_id=command)
    assert saved["result"]["draft"] == original
    assert call(native_probe, factor_id, "read")["draft"] == original
    pin = saved["result"]["draft_fingerprint"]
    published = call(native_probe, factor_id, "publish", expected=pin)
    first = published["result"]["revision"]
    assert first["parent_revision_fingerprint"] is None
    changed = {
        **original,
        "base_revision_fingerprint": first["revision_fingerprint"],
        "semantic_version": "2",
        "description": "Changed",
    }
    second = call(native_probe, factor_id, "save", draft=changed, expected=pin)
    call(native_probe, factor_id, "publish", expected=second["result"]["draft_fingerprint"])
    state = call(native_probe, factor_id, "read")
    assert len(state["revisions"]) == 2
    assert state["revisions"][0] == first
    assert state["current_revision_fingerprint"] == state["revisions"][1]["revision_fingerprint"]
    assert call(native_probe, factor_id, "command", command_id=command) == saved
    assert call(native_probe, factor_id, "save", draft=original, expected=None, command_id=command) == saved
    assert call(native_probe, factor_id, "save", draft=changed, expected=None, command_id=command) == {
        "error": "PRIVATE_FACTOR_COMMAND_CONFLICT"
    }
    assert call(native_probe, "private.factor.other", "command", command_id=command) == {
        "error": "PRIVATE_FACTOR_COMMAND_CONFLICT"
    }


def test_stale_draft_and_unknown_command_never_mutate_or_reissue(native_probe, database):
    factor_id = "private.factor.f" + uuid4().hex
    value = draft(factor_id)
    saved = call(native_probe, factor_id, "save", draft=value, expected=None)
    stale = str(uuid4())
    assert call(native_probe, factor_id, "save", draft=value, expected=None, command_id=stale) == {
        "error": "PRIVATE_FACTOR_DRAFT_CONFLICT"
    }
    assert call(native_probe, factor_id, "publish", expected="a" * 64) == {"error": "PRIVATE_FACTOR_DRAFT_CONFLICT"}
    unknown = str(uuid4())
    with psycopg.connect(database) as db:
        assert db.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (stale,)
        ).fetchone() == (0,)
        db.execute(
            "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,'SAVE_PRIVATE_FACTOR_DRAFT',%s,1)",
            (unknown, "a" * 64),
        )
    assert call(native_probe, factor_id, "command", command_id=unknown) == {"error": "PRIVATE_FACTOR_COMMAND_UNKNOWN"}
    assert call(
        native_probe, factor_id, "save", draft=value, expected=saved["result"]["draft_fingerprint"], command_id=unknown
    ) == {"error": "PRIVATE_FACTOR_COMMAND_CONFLICT"}
    assert call(native_probe, factor_id, "read")["draft_fingerprint"] == saved["result"]["draft_fingerprint"]


def test_receipt_failure_rolls_back_authoring_and_outcomes_are_immutable(native_probe, database):
    factor_id = "private.factor.f" + uuid4().hex
    command = str(uuid4())
    with psycopg.connect(database) as db:
        db.execute(
            "CREATE FUNCTION reject_factor_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_kind='SAVE_PRIVATE_FACTOR_DRAFT' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END $$"
        )
        db.execute(
            "CREATE TRIGGER reject_factor_receipt BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION reject_factor_receipt()"
        )
    try:
        assert call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None, command_id=command) == {
            "error": "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"
        }
    finally:
        with psycopg.connect(database) as db:
            db.execute("DROP TRIGGER reject_factor_receipt ON product_command_receipt")
            db.execute("DROP FUNCTION reject_factor_receipt()")
    with psycopg.connect(database) as db:
        assert db.execute("SELECT count(*) FROM private_factor_asset WHERE factor_id=%s", (factor_id,)).fetchone() == (
            0,
        )
        assert db.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (command,)
        ).fetchone() == (0,)
    call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None, command_id=command)
    with psycopg.connect(database) as db:
        with pytest.raises(psycopg.Error, match="immutable"):
            db.execute("UPDATE private_factor_authoring_outcome SET payload='{}' WHERE command_id=%s", (command,))


def test_concurrent_publish_has_one_revision_and_same_command_replay_is_exact(
    native_probe: Path, database: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    factor_id = "private.factor.f" + uuid4().hex
    saved = call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None)
    pin = saved["result"]["draft_fingerprint"]
    barrier = Barrier(2)

    def publish():
        barrier.wait(timeout=10)
        return call(native_probe, factor_id, "publish", expected=pin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = [future.result() for future in (pool.submit(publish), pool.submit(publish))]
    assert sum("result" in reply for reply in replies) == 1
    assert {reply["error"] for reply in replies if "error" in reply} == {"PRIVATE_FACTOR_DRAFT_CONFLICT"}
    assert len(call(native_probe, factor_id, "read")["revisions"]) == 1

    factor_id = "private.factor.f" + uuid4().hex
    saved = call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None)
    pin = saved["result"]["draft_fingerprint"]
    command = str(uuid4())
    barrier = Barrier(2)

    def replay():
        barrier.wait(timeout=10)
        return call(native_probe, factor_id, "publish", expected=pin, command_id=command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = [future.result() for future in (pool.submit(replay), pool.submit(replay))]
    assert replies[0] == replies[1]
    assert "result" in replies[0]
    assert len(call(native_probe, factor_id, "read")["revisions"]) == 1


def test_corrupt_saved_outcome_never_becomes_an_accepted_command(native_probe: Path, database: str) -> None:
    factor_id = "private.factor.f" + uuid4().hex
    command = str(uuid4())
    value = call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None, command_id=command)
    with psycopg.connect(database) as db:
        original = db.execute(
            "SELECT payload FROM private_factor_authoring_outcome WHERE command_id=%s", (command,)
        ).fetchone()[0]
        db.execute(
            "ALTER TABLE private_factor_authoring_outcome DISABLE TRIGGER private_factor_authoring_outcome_immutable"
        )
        db.execute(
            "UPDATE private_factor_authoring_outcome SET payload=jsonb_set(payload,'{result,draft,description}','\"corrupt\"') WHERE command_id=%s",
            (command,),
        )
        db.execute(
            "ALTER TABLE private_factor_authoring_outcome ENABLE TRIGGER private_factor_authoring_outcome_immutable"
        )
    try:
        assert call(native_probe, factor_id, "command", command_id=command) == {"error": "PRIVATE_ASSET_CORRUPT"}
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                "ALTER TABLE private_factor_authoring_outcome DISABLE TRIGGER private_factor_authoring_outcome_immutable"
            )
            db.execute(
                "UPDATE private_factor_authoring_outcome SET payload=%s::jsonb WHERE command_id=%s",
                (json.dumps(original), command),
            )
            db.execute(
                "ALTER TABLE private_factor_authoring_outcome ENABLE TRIGGER private_factor_authoring_outcome_immutable"
            )
    assert call(native_probe, factor_id, "command", command_id=command) == value


def test_publish_replay_rechecks_the_owning_revision_not_only_its_outcome_copy(
    native_probe: Path, database: str
) -> None:
    factor_id = "private.factor.f" + uuid4().hex
    saved = call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None)
    command = str(uuid4())
    accepted = call(
        native_probe, factor_id, "publish", expected=saved["result"]["draft_fingerprint"], command_id=command
    )
    pin = accepted["result"]["revision"]["revision_fingerprint"]
    with psycopg.connect(database) as db:
        trigger = db.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid='private_factor_revision'::regclass AND NOT tgisinternal"
        ).fetchone()[0]
        original = db.execute(
            "SELECT payload FROM private_factor_revision WHERE revision_fingerprint=%s", (pin,)
        ).fetchone()[0]
        from psycopg import sql

        db.execute(sql.SQL("ALTER TABLE private_factor_revision DISABLE TRIGGER {}").format(sql.Identifier(trigger)))
        db.execute(
            "UPDATE private_factor_revision SET payload=jsonb_set(payload,'{description}','\"corrupt owning fact\"') WHERE revision_fingerprint=%s",
            (pin,),
        )
        db.execute(sql.SQL("ALTER TABLE private_factor_revision ENABLE TRIGGER {}").format(sql.Identifier(trigger)))
    try:
        assert call(native_probe, factor_id, "command", command_id=command) == {"error": "PRIVATE_ASSET_CORRUPT"}
    finally:
        with psycopg.connect(database) as db:
            db.execute(
                sql.SQL("ALTER TABLE private_factor_revision DISABLE TRIGGER {}").format(sql.Identifier(trigger))
            )
            db.execute(
                "UPDATE private_factor_revision SET payload=%s::jsonb WHERE revision_fingerprint=%s",
                (json.dumps(original), pin),
            )
            db.execute(sql.SQL("ALTER TABLE private_factor_revision ENABLE TRIGGER {}").format(sql.Identifier(trigger)))
    assert call(native_probe, factor_id, "command", command_id=command) == accepted


def test_authoring_default_binds_the_frozen_algorithm_api(native_probe: Path, database: str) -> None:
    from onlyalpha.algorithm.private_factor import ONLY_PRIVATE_FACTOR_API_V1

    value = call(native_probe, "private.factor.contract", "list")
    assert value["factor_api_version"] == ONLY_PRIVATE_FACTOR_API_V1.api_version
    assert value["factor_api_contract_fingerprint"] == ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint


def test_expanded_jsonb_cannot_commit_an_unreadable_draft(native_probe: Path, database: str) -> None:
    factor_id = "private.factor.f" + uuid4().hex
    value = {**draft(factor_id), "input_contract": {"values": [0] * 100000}}
    command = str(uuid4())
    assert call(native_probe, factor_id, "save", draft=value, expected=None, command_id=command) == {
        "error": "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"
    }
    assert call(native_probe, factor_id, "command", command_id=command) is None
    assert call(native_probe, factor_id, "read") == {"error": "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE"}


@pytest.mark.parametrize("count,padding", [(200, 0), (33, 250000)])
def test_history_capacity_rejection_preserves_last_readable_state(
    native_probe: Path, database: str, count: int, padding: int
) -> None:
    import hashlib

    factor_id = "private.factor.f" + uuid4().hex
    value = {**draft(factor_id), "economic_rationale": "x" * padding}
    parent = None
    with psycopg.connect(database) as db:
        db.execute("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES(%s,1)", (factor_id,))
        for index in range(count):
            revision = {**value, "semantic_version": str(index + 1)}
            del revision["base_revision_fingerprint"]
            source_sha = hashlib.sha256(str(value["source_text"]).encode()).hexdigest()
            revision.update(parent_revision_fingerprint=parent, source_sha256=source_sha)
            canonical = json.dumps(
                {"contract": "ONLYALPHA_PRIVATE_FACTOR_REVISION_V1", **revision},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            pin = hashlib.sha256(canonical.encode()).hexdigest()
            revision["revision_fingerprint"] = pin
            db.execute(
                "INSERT INTO private_factor_revision(revision_fingerprint,factor_id,parent_revision_fingerprint,source_text,source_sha256,payload,schema_version) VALUES(%s,%s,%s,%s,%s,%s::jsonb,1)",
                (pin, factor_id, parent, value["source_text"], source_sha, json.dumps(revision)),
            )
            parent = pin
        db.execute(
            "UPDATE private_factor_asset SET current_revision_fingerprint=%s WHERE factor_id=%s", (parent, factor_id)
        )
    value.update(base_revision_fingerprint=parent, semantic_version=str(count + 1))
    saved = call(native_probe, factor_id, "save", draft=value, expected=None)
    command = str(uuid4())
    assert call(
        native_probe, factor_id, "publish", expected=saved["result"]["draft_fingerprint"], command_id=command
    ) == {"error": "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"}
    state = call(native_probe, factor_id, "read")
    assert len(state["revisions"]) == count
    assert state["current_revision_fingerprint"] == parent
    assert call(native_probe, factor_id, "command", command_id=command) is None


def test_concurrent_creation_cannot_overflow_inventory_capacity(native_probe: Path, database: str) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    prefix = "private.factor.capacity_" + uuid4().hex
    with psycopg.connect(database) as db:
        count = db.execute("SELECT count(*) FROM private_factor_asset").fetchone()[0]
        placeholders = [prefix + "_" + str(index) for index in range(199 - count)]
        for factor_id in placeholders:
            db.execute("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES(%s,1)", (factor_id,))
    barrier = Barrier(2)
    ids = ["private.factor.f" + uuid4().hex for _ in range(2)]

    def create(factor_id: str):
        barrier.wait(timeout=10)
        return call(native_probe, factor_id, "save", draft=draft(factor_id), expected=None)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(create, ids))
        assert sum("result" in reply for reply in replies) == 1
        assert {reply["error"] for reply in replies if "error" in reply} == {"PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"}
        inventory = call(native_probe, ids[0], "list")
        assert len(inventory["entries"]) == 200
    finally:
        with psycopg.connect(database) as db:
            db.execute("DELETE FROM private_factor_asset WHERE factor_id=ANY(%s)", (placeholders,))
