"""Technical transaction/recovery proof; business acceptance uses the real Shipping UI."""

from __future__ import annotations

import json
import subprocess
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def invoke(probe, conversation, action, command=None, **values):
    value = {
        "op": "factor-chat",
        "conversation_id": conversation,
        "action": action,
        "command_id": command or str(uuid4()),
        **values,
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(value), text=True, capture_output=True, check=True, timeout=20
    )
    return json.loads(result.stdout)


def setup(probe, dsn):
    OnlyPostgresMigrationAuthority(dsn).migrate()
    conversation = str(uuid4())
    result = invoke(
        probe,
        conversation,
        "begin",
        input={
            "operation": "CREATE",
            "expected": None,
            "provider": {"integration_id": str(uuid4()), "revision_fingerprint": "a" * 64},
        },
    )
    assert result["view"]["event_count"] == 1
    return conversation, result["view"]


def response(name="收盘价关系"):
    return {
        "response": {
            "message": "请确认当前因子",
            "candidate": {
                "name": name,
                "purpose": "观察价格变化",
                "hypothesis": "价格变化具有持续性",
                "expression": {"op": "sub", "left": {"input": "close"}, "right": {"input": "close", "lag": 20}},
            },
        }
    }


def candidate(probe, conversation, current):
    command = str(uuid4())
    intent = {
        "operation": "MESSAGE",
        "expected": current["head"],
        "text": "请生成价格变化因子",
        "_model_id": "controlled",
    }
    started = invoke(probe, conversation, "begin", command, input=intent)
    assert started["dispatch"] is True
    replay = invoke(probe, conversation, "begin", command, input=intent)
    assert replay["dispatch"] is False
    assert replay["view"]["status"] == "OUTCOME_UNKNOWN"
    return command, invoke(probe, conversation, "finish", command, response=response())


def test_original_model_occurrence_and_confirmation_survive_fresh_processes(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    command, preview = candidate(native_probe, conversation, current)
    assert invoke(native_probe, conversation, "read") == preview
    assert preview["confirmed"] is False
    confirm = str(uuid4())
    intent = {
        "operation": "CONFIRM",
        "expected": preview["head"],
        "preview_fingerprint": preview["preview_fingerprint"],
    }
    accepted = invoke(native_probe, conversation, "begin", confirm, input=intent)
    assert accepted["view"]["confirmed"] is True
    assert invoke(native_probe, conversation, "begin", confirm, input=intent)["view"] == accepted["view"]
    restored = invoke(native_probe, conversation, "read")
    assert restored == accepted["view"]
    with psycopg.connect(postgres_dsn) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM private_factor_revision WHERE factor_id=%s", (restored["factor_id"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT count(*) FROM factor_chat_model_result WHERE event_fingerprint=%s", (preview["head"],)
            ).fetchone()[0]
            == 1
        )
    assert invoke(native_probe, conversation, "finish", command, response=response("changed")) == {
        "error": "FACTOR_CHAT_RESULT_CONFLICT"
    }


def test_stale_confirmation_and_actor_mismatch_have_no_effect(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    _, preview = candidate(native_probe, conversation, current)
    result = invoke(
        native_probe,
        conversation,
        "begin",
        input={
            "operation": "CONFIRM",
            "expected": current["head"],
            "preview_fingerprint": preview["preview_fingerprint"],
        },
    )
    assert result == {"error": "FACTOR_CHAT_CONFLICT"}
    result = invoke(
        native_probe,
        conversation,
        "begin",
        input={"operation": "CONFIRM", "expected": preview["head"], "preview_fingerprint": "b" * 64},
    )
    assert result == {"error": "FACTOR_CHAT_PREVIEW_CONFLICT"}
    assert invoke(native_probe, conversation, "read", actor="other") == {"error": "FACTOR_CHAT_NOT_FOUND"}
    assert invoke(native_probe, conversation, "read")["confirmed"] is False


def test_failed_receipt_rolls_back_the_authoring_save_and_confirmation(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    _, preview = candidate(native_probe, conversation, current)
    command = str(uuid4())
    with psycopg.connect(postgres_dsn) as db:
        db.execute(
            "CREATE FUNCTION c2_receipt_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_id=%s::uuid THEN RAISE EXCEPTION 'controlled receipt failure'; END IF; RETURN NEW; END $$".replace(
                "%s", "'" + command + "'"
            )
        )
        db.execute(
            "CREATE TRIGGER c2_receipt_fault BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION c2_receipt_fault()"
        )
    try:
        assert "error" in invoke(
            native_probe,
            conversation,
            "begin",
            command,
            input={
                "operation": "CONFIRM",
                "expected": preview["head"],
                "preview_fingerprint": preview["preview_fingerprint"],
            },
        )
        with psycopg.connect(postgres_dsn) as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM private_factor_asset WHERE factor_id=%s", (preview["factor_id"],)
                ).fetchone()[0]
                == 0
            )
        assert invoke(native_probe, conversation, "read") == preview
    finally:
        with psycopg.connect(postgres_dsn) as db:
            db.execute("DROP TRIGGER c2_receipt_fault ON product_command_receipt")
            db.execute("DROP FUNCTION c2_receipt_fault()")


def test_replay_uses_human_intent_not_current_derived_context(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    command = str(uuid4())
    request = {
        "operation": "MESSAGE",
        "expected": current["head"],
        "text": "生成价量关系",
        "candidate_context": None,
        "_model_id": "controlled",
    }
    assert invoke(native_probe, conversation, "begin", command, input=request)["dispatch"]
    invoke(native_probe, conversation, "finish", command, response=response())
    replay = invoke(
        native_probe, conversation, "begin", command, input={**request, "candidate_context": {"new": "preview"}}
    )
    assert replay.get("dispatch") is False


def test_each_model_request_freezes_the_exact_history_before_a_late_response(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    first = str(uuid4())
    pending = invoke(
        native_probe,
        conversation,
        "begin",
        first,
        input={"operation": "MESSAGE", "expected": current["head"], "text": "first", "_model_id": "controlled"},
    )["view"]
    second = str(uuid4())
    invoke(
        native_probe,
        conversation,
        "begin",
        second,
        input={"operation": "MESSAGE", "expected": pending["head"], "text": "second", "_model_id": "controlled"},
    )
    with psycopg.connect(postgres_dsn) as db:
        before = db.execute(
            "SELECT payload->'input'->'model_request' FROM factor_chat_event WHERE command_id=%s", (second,)
        ).fetchone()[0]
    assert before is not None
    invoke(native_probe, conversation, "finish", first, response=response())
    with psycopg.connect(postgres_dsn) as db:
        after = db.execute(
            "SELECT payload->'input'->'model_request' FROM factor_chat_event WHERE command_id=%s", (second,)
        ).fetchone()[0]
    assert after == before
    assert [m["content"] for m in before["messages"] if m["role"] == "user"] == ["first", "second"]
    assert not any("请确认当前因子" in m["content"] for m in before["messages"])


def test_manual_display_edit_is_not_overwritten_by_chat_confirmation(native_probe, postgres_dsn):
    conversation, current = setup(native_probe, postgres_dsn)
    _, preview = candidate(native_probe, conversation, current)
    accepted = invoke(
        native_probe,
        conversation,
        "begin",
        input={
            "operation": "CONFIRM",
            "expected": preview["head"],
            "preview_fingerprint": preview["preview_fingerprint"],
        },
    )["view"]
    factor_id = accepted["factor_id"]

    def author(action, **fields):
        request = {
            "op": "factor-authoring",
            "factor_id": factor_id,
            "action": action,
            "command_id": str(uuid4()),
            "accepted_at": "2026-10-28T00:00:00Z",
            **fields,
        }
        result = subprocess.run(
            [str(native_probe)], input=json.dumps(request), text=True, capture_output=True, check=True, timeout=20
        )
        return json.loads(result.stdout)

    state = author("read")
    changed = author(
        "display", expected=state["display_fingerprint"], display_name="手工保留名称", usage_summary="手工用途"
    )
    assert "error" not in changed
    second = str(uuid4())
    invoke(
        native_probe,
        conversation,
        "begin",
        second,
        input={"operation": "MESSAGE", "expected": accepted["head"], "text": "改名", "_model_id": "controlled"},
    )
    next_preview = invoke(native_probe, conversation, "finish", second, response=response("聊天新名"))
    result = invoke(
        native_probe,
        conversation,
        "begin",
        input={
            "operation": "CONFIRM",
            "expected": next_preview["head"],
            "preview_fingerprint": next_preview["preview_fingerprint"],
        },
    )
    assert result == {"error": "FACTOR_CHAT_AUTHORING_CONFLICT"}
    assert author("read")["display"]["display_name"] == "手工保留名称"


def test_explicit_abandonment_fences_late_acceptance_without_a_conversation(native_probe, postgres_dsn):
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    conversation, command = str(uuid4()), str(uuid4())
    intent = {
        "operation": "CREATE",
        "expected": None,
        "provider": {"integration_id": str(uuid4()), "revision_fingerprint": "a" * 64},
    }
    rejected = invoke(native_probe, conversation, "abandon", command, input=intent)
    assert rejected == {"accepted": False, "abandoned": True}
    assert invoke(native_probe, conversation, "begin", command, input=intent) == {
        "error": "FACTOR_CHAT_COMMAND_ABANDONED"
    }
    assert invoke(native_probe, conversation, "abandon", command, input=intent) == rejected
    with psycopg.connect(postgres_dsn) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM factor_chat_conversation WHERE conversation_id=%s", (conversation,)
            ).fetchone()[0]
            == 0
        )
