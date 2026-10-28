"""Only the owning backend can return proposal registration receipts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent import backend
from onlyalpha_agent.app import create_app
from onlyalpha_agent.store import Store

from packages.agent.tests.test_agent import headers, model, session

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_backend_client_denies_unprotected_remote_and_confirmation_routes():
    token = "oa-proposal-v1." + str(uuid4()) + "." + "a" * 64
    with pytest.raises(ValueError):
        backend.Connection("http://remote.invalid", token)
    connection = backend.Connection("http://127.0.0.1:5173", token)
    for method, path in [
        ("POST", "/api/v2/factor-proposals/" + "b" * 64 + "/confirmation"),
        ("GET", "/api/v2/agent/sessions"),
    ]:
        with pytest.raises(backend.Rejected, match="OPERATION_DENIED"):
            backend.request(connection, method, path)


def test_staging_lost_ack_queries_original_command_without_second_post(settings, model_server, monkeypatch):
    from dataclasses import replace

    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    posts = []
    reads = []
    received = {}
    owner = "other"
    confirmation = None

    def call(connection, method, path, body=None, command=None):
        if "context" in path:
            return {
                "schema_version": 1,
                "owner": owner,
                "service_subject": "discovery",
                "factor_id": "private.factor.controlled",
                "draft_fingerprint": None,
                "display_fingerprint": None,
                "proposal_fingerprint": None,
            }
        if method == "POST":
            posts.append(command)
            received[command] = {
                "schema_version": 1,
                "command_id": command,
                "operation_fingerprint": "a" * 64,
                "effect": {"proposal_fingerprint": "b" * 64},
            }
            raise backend.Unknown()
        reads.append(path)
        if "/commands/" not in path:
            return {
                "schema_version": 1,
                "fingerprint": "b" * 64,
                "snapshot": {"owner": "owner"},
                "is_current": True,
                "confirmation": confirmation,
            }
        return received[path.rsplit("/", 1)[1]]

    monkeypatch.setattr(backend, "request", call)
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, model_server.url))
        cid = str(uuid4())
        with Store(configured) as store, store.session_lock(s["id"]):
            store.accept_message(s["id"], "owner", cid, {"expected": None, "text": "idea"})
            store.finish(
                cid,
                {
                    "response": {
                        "message": "preview",
                        "candidate": {
                            "name": "动量",
                            "purpose": "价格变化",
                            "hypothesis": "持续性",
                            "expression": {"input": "close"},
                        },
                    }
                },
            )
        s = client.get("/api/v1/agent/sessions/" + s["id"], headers=headers(configured)).json()
        path = "/api/v1/agent/sessions/" + s["id"] + "/proposals"
        h = headers(configured)
        denied = client.post(path, headers=h, json={"expected": s["head"]})
        assert denied.status_code == 403 and not posts
        owner = "owner"
        r = client.post(path, headers=h, json={"expected": s["head"]})
        assert r.status_code == 200 and r.json()["status"] == "OUTCOME_UNKNOWN", r.text
        assert len(posts) == 1
    rotated = replace(configured, backend_credential=configured.backend_credential[:-64] + "f" * 64)
    with TestClient(create_app(rotated)) as client:
        blocked = client.post(path, headers=h, json={"expected": s["head"]})
        assert blocked.json()["status"] == "BINDING_UNAVAILABLE" and len(posts) == 1 and not reads
    with TestClient(create_app(configured)) as client:
        restored = client.post(path, headers=h, json={"expected": s["head"]})
        assert restored.status_code == 200 and restored.json()["status"] == "REGISTERED", restored.text
        assert len(posts) == 1 and reads[-1].endswith(posts[0])
        assert restored.json()["receipt"]["command_id"] == posts[0]
        assert "confirmation" not in "\n".join(reads)
        query = path + "/" + h["Idempotency-Key"]
        assert client.get(query, headers=headers(configured)).json()["backend_snapshot"]["confirmation"] is None
        confirmation = {"command_id": str(uuid4())}
        assert client.get(query, headers=headers(configured)).json()["backend_snapshot"]["confirmation"] == confirmation


def test_backend_effect_before_checkpoint_is_reused(settings, monkeypatch):
    from dataclasses import replace

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver

    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    posts = []

    def transport(connection, method, path, body=None, command=None):
        if "context" in path:
            return {
                "schema_version": 1,
                "owner": "owner",
                "service_subject": "discovery",
                "factor_id": "private.factor.controlled",
                "draft_fingerprint": None,
                "display_fingerprint": None,
                "proposal_fingerprint": None,
            }
        assert method == "POST"
        posts.append(command)
        return {
            "schema_version": 1,
            "command_id": command,
            "operation_fingerprint": "a" * 64,
            "effect": {"proposal_fingerprint": "b" * 64},
        }

    monkeypatch.setattr(backend, "request", transport)
    with TestClient(create_app(configured)) as client:
        # Existing model/occurrence is a technical precondition, not a Shipping UI substitute.
        with Store(configured) as store:
            mid = str(uuid4())
            rev = store.configure(
                mid,
                "owner",
                str(uuid4()),
                {
                    "expected": None,
                    "name": "model",
                    "base_url": "https://model.invalid/v1",
                    "model_id": "controlled",
                    "model_version": "v1",
                    "secret": "controlled",
                },
            )["revision"]
            sid = str(uuid4())
            store.create(
                sid, "owner", str(uuid4()), {"model_revision": rev, "model_call_limit": 1}, client.app.state.workflow
            )
            event = str(uuid4())
            with store.session_lock(sid):
                store.accept_message(sid, "owner", event, {"expected": None, "text": "idea"})
                store.finish(
                    event,
                    {
                        "response": {
                            "message": "proposal",
                            "candidate": {
                                "name": "价格",
                                "purpose": "观察",
                                "hypothesis": "持续性",
                                "expression": {"input": "close"},
                            },
                        }
                    },
                )
            head = store.view(sid, "owner", client.app.state.workflow)["head"]
        path = "/api/v1/agent/sessions/" + sid + "/proposals"
        h = headers(configured)
        original = PostgresSaver.put

        def fail(*args, **kwargs):
            raise psycopg.OperationalError("controlled checkpoint failure")

        monkeypatch.setattr(PostgresSaver, "put", fail)
        failed = client.post(path, headers=h, json={"expected": head})
        assert failed.status_code == 503, failed.text
        monkeypatch.setattr(PostgresSaver, "put", original)
        restored = client.post(path, headers=h, json={"expected": head})
        assert restored.status_code == 200 and restored.json()["status"] == "REGISTERED"
        assert len(posts) == 1
        with Store(configured) as store:
            assert (
                PostgresSaver(store.conn).get_tuple(
                    {"configurable": {"thread_id": sid + "/proposal/" + h["Idempotency-Key"]}}
                )
                is not None
            )
        # A correctly hashed result from another Command is not this occurrence's receipt.
        from onlyalpha_agent.workflow import digest
        from psycopg.types.json import Jsonb

        with Store(configured) as store:
            forged = {**restored.json()["receipt"], "command_id": str(uuid4())}
            store.conn.execute("ALTER TABLE agent_backend_result DISABLE TRIGGER immutable")
            store.conn.execute(
                "UPDATE agent_backend_result SET payload=%s,fingerprint=%s WHERE command=%s",
                (Jsonb(forged), digest(forged), h["Idempotency-Key"]),
            )
            store.conn.execute("ALTER TABLE agent_backend_result ENABLE TRIGGER immutable")
        assert client.post(path, headers=h, json={"expected": head}).status_code == 409
