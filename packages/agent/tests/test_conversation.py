"""Read-only conversation projection retains each verified occurrence's own content."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent.app import create_app
from onlyalpha_agent.store import Store
from psycopg.types.json import Jsonb

from packages.agent.tests.test_agent import headers, model, session
from packages.agent.tests.test_study_proposals import advice


def test_projection_preserves_turns_and_attaches_only_their_own_references(monkeypatch):
    store = object.__new__(Store)
    candidate = {"name": "动量", "purpose": "观察", "hypothesis": "持续性", "expression": {"input": "close"}}
    study = advice()
    rows = [
        {"command": "first", "fingerprint": "a" * 64, "plan": {"text": "想法一"}},
        {"command": "second", "fingerprint": "b" * 64, "plan": {"text": "研究条件", "topic": "STUDY"}},
        {"command": "third", "fingerprint": "c" * 64, "plan": {"text": "想法二"}},
    ]
    results = {
        "first": {"response": {"message": "建议一", "candidate": candidate}},
        "second": {"response": {"message": "条件建议", "study": study}},
        "third": {"response": {"message": "需要补充", "candidate": None}},
    }
    factor = {"command": "register-factor", "head": "a" * 64, "fingerprint": "d" * 64}
    research = {"command": "register-study", "head": "b" * 64, "fingerprint": "e" * 64}
    monkeypatch.setattr(store, "history", lambda sid, owner: ({"model": "f" * 64}, rows))
    monkeypatch.setattr(
        store, "model", lambda revision, owner: ({"name": "旧模型", "model_id": "m", "model_version": "v1"}, "secret")
    )
    monkeypatch.setattr(store, "result", results.get)
    monkeypatch.setattr(store, "backend_references", lambda sid, owner: [({}, factor), ({"topic": "STUDY"}, research)])
    value = store.conversation("sid", "owner")
    assert value == {
        "id": "sid",
        "head": "c" * 64,
        "model_revision": "f" * 64,
        "model": {"name": "旧模型", "model_id": "m", "model_version": "v1"},
        "turns": [
            {
                "head": "a" * 64,
                "topic": "FACTOR",
                "user": "想法一",
                "assistant": "建议一",
                "status": "READY",
                "candidate": candidate,
                "study": None,
                "factor_reference": factor,
                "study_reference": None,
            },
            {
                "head": "b" * 64,
                "topic": "STUDY",
                "user": "研究条件",
                "assistant": "条件建议",
                "status": "READY",
                "candidate": None,
                "study": study,
                "factor_reference": None,
                "study_reference": research,
            },
            {
                "head": "c" * 64,
                "topic": "FACTOR",
                "user": "想法二",
                "assistant": "需要补充",
                "status": "READY",
                "candidate": None,
                "study": None,
                "factor_reference": None,
                "study_reference": None,
            },
        ],
    }


@pytest.mark.parametrize(
    "result,status",
    [
        (None, "OUTCOME_UNKNOWN"),
        ({"error": "MODEL_OUTCOME_UNKNOWN"}, "OUTCOME_UNKNOWN"),
        ({"error": "MODEL_RESPONSE_INVALID"}, "FAILED"),
    ],
)
def test_projection_never_invents_content_for_missing_unknown_or_failed_results(monkeypatch, result, status):
    store = object.__new__(Store)
    monkeypatch.setattr(
        store,
        "history",
        lambda sid, owner: (
            {"model": "a" * 64},
            [{"command": "cmd", "fingerprint": "b" * 64, "plan": {"text": "idea"}}],
        ),
    )
    monkeypatch.setattr(
        store, "model", lambda revision, owner: ({"name": "model", "model_id": "m", "model_version": "v1"}, "secret")
    )
    monkeypatch.setattr(store, "result", lambda command: result)
    monkeypatch.setattr(store, "backend_references", lambda sid, owner: [])
    turn = store.conversation("sid", "owner")["turns"][0]
    assert turn["status"] == status
    assert turn["assistant"] is None
    assert turn["candidate"] is None and turn["study"] is None


@pytest.mark.integration
@pytest.mark.postgres
def test_conversation_auth_exact_model_and_read_only_projection(settings, model_server, monkeypatch):
    with TestClient(create_app(settings)) as client:
        revision = model(client, settings, model_server.url)
        s = session(client, settings, revision)
        path = "/api/v1/agent/sessions/" + s["id"] + "/conversation"
        with Store(settings) as store:
            profile, _secret = store.model(revision, "owner")
            store.configure(
                profile["id"],
                "owner",
                str(uuid4()),
                {
                    "expected": revision,
                    "name": "Renamed model",
                    "base_url": model_server.url,
                    "model_id": "new-model",
                    "model_version": "v2",
                    "secret": "different-secret",
                },
            )
            cid = str(uuid4())
            store.accept_message(s["id"], "owner", cid, {"expected": None, "text": "original idea"})
            store.finish(cid, {"response": {"message": "original answer", "candidate": None}})
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers(settings, "other")).status_code == 404
        assert client.get(path, headers=headers(settings, scopes=["chat:write"])).status_code == 403
        # A read-only database transaction rejects any hidden write, including checkpoints.
        original_enter = Store.__enter__

        def read_only_enter(self):
            value = original_enter(self)
            self.conn.execute("SET default_transaction_read_only=on")
            return value

        monkeypatch.setattr(Store, "__enter__", read_only_enter)
        response = client.get(path, headers=headers(settings, scopes=["chat:read"]))
        assert response.status_code == 200, response.text
        assert response.json()["model"] == {
            "name": "Controlled model",
            "model_id": "controlled",
            "model_version": "recorded-v1",
        }
        assert response.json()["model_revision"] == revision
        assert response.json()["turns"][0]["assistant"] == "original answer"
        assert model_server.calls == 0
        assert "secret" not in response.text and "base_url" not in response.text


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize("mutation", ["history", "result", "reference"])
def test_conversation_refuses_corrupt_durable_relations(settings, model_server, mutation):
    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        with Store(settings) as store:
            cid = str(uuid4())
            store.accept_message(s["id"], "owner", cid, {"expected": None, "text": "idea"})
            store.finish(
                cid,
                {
                    "response": {
                        "message": "answer",
                        "candidate": {"name": "n", "purpose": "p", "hypothesis": "h", "expression": {"input": "close"}},
                    }
                },
            )
            head = store.view(s["id"], "owner", client.app.state.workflow)["head"]
            if mutation == "history":
                store.conn.execute("ALTER TABLE agent_event DISABLE TRIGGER USER")
                store.conn.execute("UPDATE agent_event SET plan=%s WHERE command=%s", (Jsonb({}), cid))
                store.conn.execute("ALTER TABLE agent_event ENABLE TRIGGER USER")
            elif mutation == "result":
                store.conn.execute("ALTER TABLE agent_result DISABLE TRIGGER USER")
                store.conn.execute("UPDATE agent_result SET payload=%s WHERE command=%s", (Jsonb({}), cid))
                store.conn.execute("ALTER TABLE agent_result ENABLE TRIGGER USER")
            else:
                command = str(uuid4())
                store.prepare_backend(
                    s["id"],
                    "owner",
                    command,
                    head,
                    "f" * 64,
                    {"draft_fingerprint": None, "display_fingerprint": None, "proposal_fingerprint": None},
                )
                store.conn.execute("ALTER TABLE agent_backend_plan DISABLE TRIGGER USER")
                store.conn.execute("DELETE FROM agent_backend_plan WHERE command=%s", (command,))
                store.conn.execute("ALTER TABLE agent_backend_plan ENABLE TRIGGER USER")
        response = client.get("/api/v1/agent/sessions/" + s["id"] + "/conversation", headers=headers(settings))
        assert response.status_code == 409, response.text
