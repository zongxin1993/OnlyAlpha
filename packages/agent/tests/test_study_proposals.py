"""Study suggestions retain their origin; only backend owns Research permission."""

from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent import backend
from onlyalpha_agent import model as provider
from onlyalpha_agent.app import create_app
from onlyalpha_agent.store import Conflict, Store
from onlyalpha_agent.workflow import digest
from psycopg.types.json import Jsonb

from packages.agent.tests.test_agent import headers, model, session

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def advice():
    return {
        "source": {
            "integration_id": "00000000-0000-4000-8000-000000000001",
            "integration_revision_fingerprint": "a" * 64,
            "expected_type_id": "binance.spot.source",
            "source_id": "spot",
            "environment": "public",
            "instrument_id": "BTCUSDT",
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
        "seed": "b" * 64,
        "rationale": "固定区间和序列依赖修正；未准备或运行研究。",
    }


def test_study_chat_retains_factor_and_reconciles_original_registration(settings, monkeypatch):
    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    factor_fp = "c" * 64
    study_fp = "d" * 64
    candidate = {"name": "动量", "purpose": "观察", "hypothesis": "持续性", "expression": {"input": "close"}}
    context = {
        "schema_version": 1,
        "owner": "owner",
        "service_subject": "discovery",
        "factor_proposal_fingerprint": factor_fp,
        "factor": candidate,
        "study_proposal_fingerprint": None,
        "sources": [{k: v for k, v in advice()["source"].items() if k != "instrument_id"}],
        "supported_profile": {"statistics_family": "TIME_SERIES_ASSOCIATION"},
    }
    posts = []
    queries = []
    receipt = None

    def transport(connection, method, path, body=None, command=None):
        nonlocal receipt
        if path.startswith("/api/v2/factor-study-context/"):
            return context
        if method == "POST":
            assert path == "/api/v2/factor-studies"
            posts.append((command, body))
            receipt = {
                "schema_version": 1,
                "command_id": command,
                "operation_fingerprint": "e" * 64,
                "effect": {"proposal_fingerprint": study_fp},
            }
            raise backend.Unknown()
        queries.append(path)
        if path == "/api/v2/factor-studies/" + study_fp:
            return {"schema_version": 1, "fingerprint": study_fp, "snapshot": {"owner": "owner"}, "is_current": True}
        assert path == "/api/v2/factor-studies/commands/" + receipt["command_id"]
        return receipt

    monkeypatch.setattr(backend, "request", transport)
    monkeypatch.setattr(
        provider, "invoke", lambda *args, **kwargs: {"response": {"message": "建议研究条件", "study": advice()}}
    )
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, "https://model.invalid/v1"), budget=5)
        factor_command = str(uuid4())
        with Store(configured) as store, store.session_lock(s["id"]):
            event = str(uuid4())
            store.accept_message(s["id"], "owner", event, {"expected": None, "text": "idea"})
            store.finish(event, {"response": {"message": "因子预览", "candidate": candidate}})
            factor_head = store.view(s["id"], "owner", client.app.state.workflow)["head"]
            plan, _ = store.prepare_backend(
                s["id"],
                "owner",
                factor_command,
                factor_head,
                "f" * 64,
                {"draft_fingerprint": None, "display_fingerprint": None, "proposal_fingerprint": None},
            )
            store.backend_finish(
                factor_command,
                {
                    "schema_version": 1,
                    "command_id": plan["backend_command"],
                    "operation_fingerprint": "e" * 64,
                    "effect": {"proposal_fingerprint": factor_fp},
                },
            )
        path = "/api/v1/agent/sessions/" + s["id"]
        message_headers = headers(configured)
        body = {
            "expected": factor_head,
            "text": "建议研究条件",
            "topic": "STUDY",
            "factor_proposal_fingerprint": factor_fp,
        }
        response = client.post(path + "/messages", headers=message_headers, json=body)
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["topic"] == "STUDY"
        assert current["candidate"] is None and current["study"] == advice()
        assert current["factor_reference"] == {
            "command": factor_command,
            "head": factor_head,
            "fingerprint": factor_fp,
            "abandoned": False,
        }
        assert current["study_reference"] is None
        with Store(configured) as store:
            call = store.plan(message_headers["Idempotency-Key"])
            assert call["study_context"] == context
            assert (
                call["backend_binding"]
                == backend.Connection(configured.backend_url, configured.backend_credential).fingerprint()
            )
        stage_headers = headers(configured)
        staged = client.post(path + "/proposals", headers=stage_headers, json={"expected": current["head"]})
        assert staged.status_code == 200 and staged.json()["status"] == "OUTCOME_UNKNOWN", staged.text
        assert posts[0][1]["advice"] == advice()
        assert posts[0][1]["factor_proposal_fingerprint"] == factor_fp
    with TestClient(create_app(configured)) as restarted:
        restored = restarted.post(
            path + "/proposals/" + stage_headers["Idempotency-Key"] + "/resume", headers=headers(configured)
        )
        assert restored.status_code == 200 and restored.json()["status"] == "REGISTERED", restored.text
        current = restarted.get(path, headers=headers(configured)).json()
        assert current["topic"] == "STUDY"
        assert current["factor_reference"]["fingerprint"] == factor_fp
        assert current["study_reference"]["fingerprint"] == study_fp
        assert len(posts) == 1 and len(queries) == 1
        observed = restarted.get(path + "/proposals/" + stage_headers["Idempotency-Key"], headers=headers(configured))
        assert observed.status_code == 200 and observed.json()["backend_snapshot"]["fingerprint"] == study_fp
        context["study_proposal_fingerprint"] = study_fp
        context["sources"] = []
        # The same typed suggestion is no longer allowed with an empty owning inventory.
        blocked = restarted.post(
            path + "/messages",
            headers=headers(configured),
            json={
                "expected": current["head"],
                "text": "建议数据条件",
                "topic": "STUDY",
                "factor_proposal_fingerprint": factor_fp,
            },
        )
        assert blocked.status_code == 200 and blocked.json()["status"] == "FAILED", blocked.text
        assert blocked.json()["study"] is None
        monkeypatch.setattr(
            provider, "invoke", lambda *args, **kwargs: {"response": {"message": "请先配置可用数据源", "study": None}}
        )
        clarified = restarted.post(
            path + "/messages",
            headers=headers(configured),
            json={
                "expected": blocked.json()["head"],
                "text": "还缺什么",
                "topic": "STUDY",
                "factor_proposal_fingerprint": factor_fp,
            },
        )
        assert clarified.status_code == 200 and clarified.json()["status"] == "READY", clarified.text
        assert clarified.json()["study"] is None and clarified.json()["factor_reference"]["fingerprint"] == factor_fp
        assert clarified.json()["study_reference"]["fingerprint"] == study_fp
        calls_before = (len(posts), len(queries))
        conversation = restarted.get(path + "/conversation", headers=headers(configured))
        assert conversation.status_code == 200, conversation.text
        turns = conversation.json()["turns"]
        assert [turn["user"] for turn in turns] == ["idea", "建议研究条件", "建议数据条件", "还缺什么"]
        assert turns[0]["candidate"] == candidate and turns[0]["study"] is None
        assert turns[0]["factor_reference"] == {
            "command": factor_command,
            "head": factor_head,
            "fingerprint": factor_fp,
            "abandoned": False,
        }
        assert turns[1]["candidate"] is None and turns[1]["study"] == advice()
        assert turns[1]["study_reference"] == {
            "command": stage_headers["Idempotency-Key"],
            "head": current["head"],
            "fingerprint": study_fp,
            "abandoned": False,
        }
        assert turns[1]["factor_reference"] is None
        assert turns[2]["status"] == "FAILED" and turns[2]["assistant"] is None
        assert turns[3]["status"] == "READY" and turns[3]["study"] is None
        assert all(turn["factor_reference"] is None and turn["study_reference"] is None for turn in turns[2:])
        assert (len(posts), len(queries)) == calls_before


def test_study_context_denied_does_not_consume_model_occurrence(settings, monkeypatch):
    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    calls = []

    def denied(*args, **kwargs):
        raise backend.Rejected()

    monkeypatch.setattr(backend, "request", denied)
    monkeypatch.setattr(provider, "invoke", lambda *args, **kwargs: calls.append(args))
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, "https://model.invalid/v1"))
        response = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers=headers(configured),
            json={
                "expected": None,
                "text": "建议研究条件",
                "topic": "STUDY",
                "factor_proposal_fingerprint": "c" * 64,
            },
        )
        assert response.status_code == 503, response.text
        current = client.get("/api/v1/agent/sessions/" + s["id"], headers=headers(configured)).json()
        assert current["head"] is None and current["consumed"] == 0 and not calls


@pytest.mark.parametrize("patch", [{"start_at": 120_000_000_000.0}, {"replicates": True}, {"execute": True}])
def test_study_model_response_is_closed_and_uses_exact_utc_strings(patch):
    with pytest.raises(ValueError):
        provider.validate_response({"message": "建议", "study": {**advice(), **patch}}, "STUDY")
    assert provider.validate_response({"message": "请先选择可用数据源", "study": None}, "STUDY")["study"] is None


def test_agent_study_adapter_cannot_grant_prepare_activate_or_execute():
    connection = backend.Connection("http://127.0.0.1:5173", "oa-proposal-v1." + str(uuid4()) + "." + "a" * 64)
    for path in (
        "/api/v2/factor-study-grants",
        "/api/v2/factor-studies/preparations",
        "/api/v2/factor-studies/" + "a" * 64 + "/research",
        "/api/v2/runtime/generations/activation",
    ):
        with pytest.raises(backend.Rejected, match="OPERATION_DENIED"):
            backend.request(connection, "POST", path)


def test_rejected_registration_resolves_without_replaying_old_workflow_and_can_continue(settings, monkeypatch):
    from onlyalpha_agent import workflow

    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    factor_fp = "c" * 64
    source = {"name": "动量", "purpose": "研究", "hypothesis": "持续", "expression": {"input": "close"}}
    context = {
        "schema_version": 1,
        "owner": "owner",
        "service_subject": "discovery",
        "factor_proposal_fingerprint": factor_fp,
        "factor": source,
        "study_proposal_fingerprint": None,
        "sources": [{k: v for k, v in advice()["source"].items() if k != "instrument_id"}],
        "supported_profile": {},
    }
    posts, resolutions = [], []
    proof = None

    def transport(connection, method, path, body=None, command=None):
        if path.startswith("/api/v2/factor-study-context/"):
            return context
        if path.startswith("/api/v2/factor-study-continuations/"):
            return proof
        if path.endswith("/resolution"):
            resolutions.append((command, body))
            if len(resolutions) == 1:
                raise backend.Unknown()
            return {
                "schema_version": 1,
                "command_id": command,
                "operation_fingerprint": "f" * 64,
                "effect": {"registration_abandoned": True},
            }
        assert method == "POST" and path == "/api/v2/factor-studies"
        posts.append((command, body))
        if body.get("continuation_command_id") is not None:
            return {
                "schema_version": 1,
                "command_id": command,
                "operation_fingerprint": "e" * 64,
                "effect": {"proposal_fingerprint": "d" * 64},
            }
        raise backend.Rejected()

    calls = []
    monkeypatch.setattr(backend, "request", transport)
    monkeypatch.setattr(
        provider, "invoke", lambda *a, **kw: calls.append(1) or {"response": {"message": "研究条件", "study": advice()}}
    )
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, "https://model.invalid/v1"), budget=5)
        with Store(configured) as store:
            event, registration = str(uuid4()), str(uuid4())
            store.accept_message(s["id"], "owner", event, {"expected": None, "text": "因子"})
            store.finish(event, {"response": {"message": "预览", "candidate": source}})
            factor_head = store.view(s["id"], "owner", s["workflow"])["head"]
            plan, _ = store.prepare_backend(
                s["id"],
                "owner",
                registration,
                factor_head,
                "f" * 64,
                {"draft_fingerprint": None, "display_fingerprint": None, "proposal_fingerprint": None},
            )
            store.backend_finish(
                registration,
                {
                    "schema_version": 1,
                    "command_id": plan["backend_command"],
                    "operation_fingerprint": "e" * 64,
                    "effect": {"proposal_fingerprint": factor_fp},
                },
            )
        path = "/api/v1/agent/sessions/" + s["id"]
        current = client.post(
            path + "/messages",
            headers=headers(configured),
            json={
                "expected": factor_head,
                "text": "建议条件",
                "topic": "STUDY",
                "factor_proposal_fingerprint": factor_fp,
            },
        ).json()
        stage_headers = headers(configured)
        command = stage_headers["Idempotency-Key"]
        assert (
            client.post(path + "/proposals", headers=stage_headers, json={"expected": current["head"]}).json()["status"]
            == "REJECTED"
        )
        client.app.state.workflow = "9" * 64
        unresolved = client.post(path + "/proposals/" + command + "/resolve", headers=headers(configured)).json()
        assert unresolved["status"] == "OUTCOME_UNKNOWN"
        with Store(configured) as store:
            assert store.pending_backend(s["id"], "owner")
        resolved = client.post(path + "/proposals/" + command + "/resolve", headers=headers(configured)).json()
        assert resolved["status"] == "ABANDONED", resolved
        assert resolutions[0] == resolutions[1]
        restored = client.get(path, headers=headers(configured)).json()
        assert restored["status"] == "WORKFLOW_UNAVAILABLE"
        assert restored["study_reference"]["abandoned"] is True
        assert restored["head"] == current["head"] and restored["consumed"] == 2
        assert len(posts) == len(calls) == 1
        assert (
            client.post(path + "/proposals/" + command + "/resume", headers=headers(configured)).json()["status"]
            == "ABANDONED"
        )
        assert client.get(path + "/proposals/" + command, headers=headers(configured)).status_code == 409
        child, backend_command = str(uuid4()), str(uuid4())
        body = {
            "model_revision": s["model_revision"],
            "model_call_limit": 3,
            "continuation": {
                "parent_session": s["id"],
                "parent_head": current["head"],
                "backend_command": backend_command,
            },
        }
        record = {
            "schema_version": 1,
            "command_id": backend_command,
            "owner": "owner",
            "actor": "HUMAN",
            "kind": "CONTINUE_FACTOR_STUDY",
            "effect": {"continuation_command_id": backend_command},
            "request": {
                "schema_version": 1,
                "factor_proposal_fingerprint": factor_fp,
                "session_id": child,
                "workflow_fingerprint": "9" * 64,
                "model_revision": s["model_revision"],
                "source_session_id": s["id"],
                "source_workflow_fingerprint": s["workflow"],
            },
        }
        proof = {
            "schema_version": 1,
            "command_id": backend_command,
            "operation_fingerprint": workflow.digest(record),
            "snapshot": record,
        }
        too_large = client.put(
            "/api/v1/agent/sessions/" + child, headers=headers(configured), json={**body, "model_call_limit": 4}
        )
        assert too_large.status_code == 409
        with Store(configured) as held, held.session_lock(s["id"]):
            locked = client.put("/api/v1/agent/sessions/" + child, headers=headers(configured), json=body)
            assert locked.status_code == 409
        stale_body = {**body, "continuation": {**body["continuation"], "parent_head": factor_head}}
        assert (
            client.put("/api/v1/agent/sessions/" + child, headers=headers(configured), json=stale_body).status_code
            == 409
        )
        create_headers = headers(configured)
        created = client.put("/api/v1/agent/sessions/" + child, headers=create_headers, json=body)
        assert created.status_code == 200, created.text
        continued = created.json()
        assert continued["factor_reference"]["fingerprint"] == factor_fp
        assert continued["workflow"] == "9" * 64 and continued["head"] is None
        assert continued["model_call_limit"] == 3 and continued["topic"] == "STUDY"
        assert client.put("/api/v1/agent/sessions/" + child, headers=create_headers, json=body).json() == continued
        assert client.get(path, headers=headers(configured)).json()["successor"] == child
        client.app.state.workflow = s["workflow"]
        refused = client.post(
            path + "/messages",
            headers=headers(configured),
            json={
                "expected": current["head"],
                "text": "旧会话不能重复使用预算",
                "topic": "STUDY",
                "factor_proposal_fingerprint": factor_fp,
            },
        )
        assert refused.status_code == 409 and "AGENT_SESSION_CONTINUED" in refused.text
        with Store(configured) as store:
            assert len(store.history(s["id"], "owner")[1]) == 2
        client.app.state.workflow = "9" * 64
        result = client.post(
            "/api/v1/agent/sessions/" + child + "/messages",
            headers=headers(configured),
            json={"expected": None, "text": "缩短样本", "topic": "STUDY", "factor_proposal_fingerprint": factor_fp},
        )
        assert result.status_code == 200, result.text
        with Store(configured) as store:
            assert store.history(s["id"], "owner")[0]["workflow"] == s["workflow"]
            assert store.history(child, "owner")[1][0]["plan"]["workflow"] == "9" * 64
        assert (
            client.put("/api/v1/agent/sessions/" + str(uuid4()), headers=headers(configured), json=body).status_code
            == 409
        )

        child_path = "/api/v1/agent/sessions/" + child
        child_stage_headers = headers(configured)
        child_command = child_stage_headers["Idempotency-Key"]
        saved = client.post(
            child_path + "/proposals", headers=child_stage_headers, json={"expected": result.json()["head"]}
        )
        assert saved.status_code == 200 and saved.json()["status"] == "REGISTERED", saved.text
        assert posts[-1][1]["continuation_command_id"] == backend_command
        assert client.get(child_path, headers=headers(configured)).json()["study_reference"]["fingerprint"] == "d" * 64
        assert (
            client.post(child_path + "/proposals/" + child_command + "/resume", headers=headers(configured)).json()[
                "status"
            ]
            == "REGISTERED"
        )
        with Store(configured) as store:
            original = store.backend_plan(child_command)
            assert store.backend_recorded(child_command)["effect"]["proposal_fingerprint"] == "d" * 64
            for table in ("agent_backend_plan", "agent_command"):
                store.conn.execute("ALTER TABLE " + table + " DISABLE TRIGGER USER")
            for value in (None, str(uuid4())):
                altered = deepcopy(original)
                if value is None:
                    del altered["body"]["continuation_command_id"]
                else:
                    altered["body"]["continuation_command_id"] = value
                fp = digest(altered)
                store.conn.execute(
                    "UPDATE agent_backend_plan SET payload=%s,fingerprint=%s WHERE command=%s",
                    (Jsonb(altered), fp, child_command),
                )
                store.conn.execute(
                    "UPDATE agent_command SET outcome=%s WHERE id=%s", (Jsonb({"backend_plan": fp}), child_command)
                )
                with pytest.raises(Conflict, match="AGENT_BACKEND_PLAN_CORRUPT"):
                    store.backend_plan(child_command)
            store.conn.execute(
                "UPDATE agent_backend_plan SET payload=%s,fingerprint=%s WHERE command=%s",
                (Jsonb(original), digest(original), child_command),
            )
            store.conn.execute(
                "UPDATE agent_command SET outcome=%s WHERE id=%s",
                (Jsonb({"backend_plan": digest(original)}), child_command),
            )
            for table in ("agent_backend_plan", "agent_command"):
                store.conn.execute("ALTER TABLE " + table + " ENABLE TRIGGER USER")
            assert store.backend_plan(child_command) == original
