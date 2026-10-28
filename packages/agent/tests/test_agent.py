"""A2 technical service proofs; Shipping C2 remains on the backend until A4."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent.app import create_app
from onlyalpha_agent.security import issue_token

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def headers(settings, subject="owner", *, audience="onlyalpha-agent", kind="human", scopes=None):
    return {
        "Authorization": "Bearer "
        + issue_token(
            settings.signing_key,
            subject=subject,
            audience=audience,
            kind=kind,
            scopes=scopes or ["chat:read", "chat:write", "model:write", "access:revoke"],
            token_id=str(uuid4()),
            expires_at=4_000_000_000,
        ),
        "Idempotency-Key": str(uuid4()),
    }


def model(client, settings, url):
    response = client.put(
        "/api/v1/agent/models/" + str(uuid4()),
        headers=headers(settings),
        json={
            "expected": None,
            "name": "Controlled model",
            "base_url": url,
            "model_id": "controlled",
            "model_version": "recorded-v1",
            "secret": "model-only-secret",
        },
    )
    assert response.status_code == 200, response.text
    assert "model-only-secret" not in response.text
    return response.json()["revision"]


def session(client, settings, revision, budget=3):
    response = client.put(
        "/api/v1/agent/sessions/" + str(uuid4()),
        headers=headers(settings),
        json={"model_revision": revision, "model_call_limit": budget},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_identity_audience_owner_revocation_and_no_formal_authority(settings, model_server):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/agent/sessions").status_code == 401
        assert (
            client.get("/api/v1/agent/sessions", headers=headers(settings, audience="onlyalpha-backend")).status_code
            == 401
        )
        rev = model(client, settings, model_server.url)
        s = session(client, settings, rev)
        assert client.get("/api/v1/agent/sessions/" + s["id"], headers=headers(settings, "other")).status_code == 404
        assert (
            client.post(
                "/api/v1/agent/sessions/" + s["id"] + "/messages",
                headers=headers(settings, kind="service"),
                json={"expected": None, "text": "idea"},
            ).status_code
            == 403
        )
        assert client.post("/api/v1/agent/research", headers=headers(settings), json={}).status_code == 404
        token_headers = headers(settings)
        import jwt

        claims = jwt.decode(token_headers["Authorization"][7:], options={"verify_signature": False})
        assert client.put("/api/v1/agent/access/revocations/" + claims["jti"], headers=token_headers).status_code == 200
        assert client.get("/api/v1/agent/sessions", headers=token_headers).status_code == 401


def test_message_replay_restart_budget_and_checkpoint_repair(settings, model_server):
    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url), budget=1)
        h = headers(settings)
        data = {"expected": None, "text": "请解释放量动量"}
        r = client.post("/api/v1/agent/sessions/" + s["id"] + "/messages", headers=h, json=data)
        assert r.status_code == 200, r.text
        assert r.json()["messages"][-1]["content"] == "需要明确观察周期"
        assert model_server.calls == 1
        assert client.post("/api/v1/agent/sessions/" + s["id"] + "/messages", headers=h, json=data).json() == r.json()
        assert model_server.calls == 1
    with TestClient(create_app(settings)) as client:
        restored = client.get("/api/v1/agent/sessions/" + s["id"], headers=headers(settings))
        assert restored.json() == r.json()
        denied = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers=headers(settings),
            json={"expected": r.json()["head"], "text": "20根"},
        )
        assert denied.status_code == 409 and model_server.calls == 1


def test_acceptance_without_response_is_unknown_and_never_redispatched(settings, model_server):
    from onlyalpha_agent.store import Store

    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        request_id = str(uuid4())
        with Store(settings) as store:
            store.accept_message(s["id"], "owner", request_id, {"expected": None, "text": "interrupted"})
        result = client.post("/api/v1/agent/sessions/" + s["id"] + "/resume", headers=headers(settings))
        assert result.status_code == 200 and result.json()["status"] == "OUTCOME_UNKNOWN"
        assert model_server.calls == 0


def test_exact_workflow_unavailable_pauses_without_budget_reset(settings, model_server):
    with TestClient(create_app(settings)) as old:
        s = session(old, settings, model(old, settings, model_server.url))
        with TestClient(create_app(settings)) as new:
            new.app.state.workflow = "different-installed-artifact"
            r = new.post("/api/v1/agent/sessions/" + s["id"] + "/resume", headers=headers(settings))
            assert r.status_code == 200 and r.json()["status"] == "WORKFLOW_UNAVAILABLE"
            assert r.json()["workflow"] == s["workflow"] and r.json()["consumed"] == 0
        assert (
            old.post("/api/v1/agent/sessions/" + s["id"] + "/resume", headers=headers(settings)).json()["status"]
            == "READY"
        )


def test_concurrent_instances_have_one_external_occurrence(settings, model_server):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    model_server.release = threading.Event()
    with TestClient(create_app(settings)) as first, TestClient(create_app(settings)) as second:
        s = session(first, settings, model(first, settings, model_server.url))
        path = "/api/v1/agent/sessions/" + s["id"] + "/messages"
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                first.post, path, headers=headers(settings), json={"expected": None, "text": "idea"}
            )
            try:
                assert model_server.entered.wait(10)
                rejected = second.post(path, headers=headers(settings), json={"expected": None, "text": "other"})
                assert rejected.status_code == 409 and rejected.json()["error"] == "AGENT_SESSION_BUSY"
            finally:
                model_server.release.set()
            assert pending.result(timeout=10).status_code == 200
        assert model_server.calls == 1


def test_recorded_result_repairs_checkpoint_without_new_call(settings, model_server, monkeypatch):
    from langgraph.checkpoint.postgres import PostgresSaver
    from onlyalpha_agent.store import Store

    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        cid = str(uuid4())
        with Store(settings) as store, store.session_lock(s["id"]):
            store.accept_message(s["id"], "owner", cid, {"expected": None, "text": "before checkpoint"})
            store.finish(
                cid,
                {"response": {"message": "durable result", "candidate": None}, "provider_response": {"id": "recorded"}},
            )
        path = "/api/v1/agent/sessions/" + s["id"] + "/resume"
        r = client.post(path, headers=headers(settings))
        assert r.status_code == 200 and r.json()["messages"][-1]["content"] == "durable result"
        with Store(settings) as store:
            assert PostgresSaver(store.conn).get_tuple({"configurable": {"thread_id": s["id"]}}) is not None
        assert model_server.calls == 0


def test_command_binding_origin_secrets_and_immutable_records(settings, model_server):
    import psycopg
    from onlyalpha_agent.store import Store

    with TestClient(create_app(settings)) as client:
        h = headers(settings)
        assert (
            client.get("/api/v1/agent/sessions", headers={**h, "Origin": "https://foreign.invalid"}).status_code == 401
        )
        assert client.get("/api/v1/agent/sessions", headers={**h, "Cookie": "owner=true"}).status_code == 401
        invalid = client.put(
            "/api/v1/agent/models/" + str(uuid4()), headers=h, json={"secret": "do-not-echo", "unexpected": True}
        )
        assert invalid.status_code == 422 and "do-not-echo" not in invalid.text
        s = session(client, settings, model(client, settings, model_server.url))
        path = "/api/v1/agent/sessions/" + s["id"] + "/messages"
        assert client.post(path, headers=h, json={"expected": None, "text": "first"}).status_code == 200
        assert client.post(path, headers=h, json={"expected": None, "text": "changed"}).status_code == 409
        with Store(settings) as store:
            for table in ("agent_command", "agent_event", "agent_result", "checkpoints", "checkpoint_blobs"):
                rows = store.conn.execute("SELECT row_to_json(t)::text FROM " + table + " t").fetchall()
                assert "model-only-secret" not in str(rows)
            with pytest.raises(psycopg.Error, match="AGENT_IMMUTABLE_FACT"):
                store.conn.execute("DELETE FROM agent_event")
        assert model_server.calls == 1


def test_storage_role_has_no_backend_permissions(settings):
    import os

    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(settings.dsn)
    backend = conninfo_to_dict(os.environ["ONLYALPHA_POSTGRES_DSN"])
    # A real backend-owned table in the isolated canonical test database, not dev state.
    from psycopg import sql

    name = "agent_isolation_" + uuid4().hex
    with psycopg.connect(os.environ["ONLYALPHA_POSTGRES_DSN"], autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE TABLE public.{} (secret text)").format(sql.Identifier(name)))
        try:
            with psycopg.connect(make_conninfo(settings.dsn, dbname=backend["dbname"]), autocommit=True) as agent:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    agent.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(name)))
            assert info["user"] != backend.get("user")
        finally:
            admin.execute(sql.SQL("DROP TABLE public.{}").format(sql.Identifier(name)))


def test_model_successor_does_not_replace_original_session_binding(settings, model_server):
    with TestClient(create_app(settings)) as client:
        revision = model(client, settings, model_server.url)
        s = session(client, settings, revision)
        profile = client.get("/api/v1/agent/models", headers=headers(settings)).json()["items"][0]
        changed = client.put(
            "/api/v1/agent/models/" + profile["id"],
            headers=headers(settings),
            json={
                "expected": revision,
                "name": "successor",
                "base_url": model_server.url,
                "model_id": "different",
                "model_version": "v2",
                "secret": "different-secret",
            },
        )
        assert changed.status_code == 200
        r = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers=headers(settings),
            json={"expected": None, "text": "original"},
        )
        assert r.status_code == 200 and r.json()["model_revision"] == revision
        assert model_server.requests[0]["model"] == "controlled"


def test_separate_process_restores_exact_history_without_external_io(settings, model_server):
    import json
    import subprocess
    import sys

    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        response = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers=headers(settings),
            json={"expected": None, "text": "persist"},
        )
        assert response.status_code == 200
    script = """
import json,sys
from onlyalpha_agent.config import Settings
from onlyalpha_agent.store import Store
from onlyalpha_agent.workflow import current_identity
v=json.load(sys.stdin)
with Store(Settings(v['dsn'],bytes.fromhex(v['key']),bytes.fromhex(v['sign']))) as store:
    store.initialize()
    print(json.dumps(store.view(v['session'],'owner',current_identity()),ensure_ascii=False))
"""
    restored = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            {
                "dsn": settings.dsn,
                "key": settings.encryption_key.hex(),
                "sign": settings.signing_key.hex(),
                "session": s["id"],
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert json.loads(restored.stdout) == response.json()
    assert model_server.calls == 1


def test_independent_http_process_restart_restores_owned_session(settings, model_server, tmp_path):
    import contextlib
    import json
    import select
    import socket
    import subprocess
    import sys
    from urllib.request import Request, urlopen

    script = """
import json,sys
from contextlib import asynccontextmanager
import uvicorn
from onlyalpha_agent.app import create_app
from onlyalpha_agent.config import Settings
v=json.load(sys.stdin)
app=create_app(Settings(v['dsn'],bytes.fromhex(v['key']),bytes.fromhex(v['sign'])))
original=app.router.lifespan_context
@asynccontextmanager
async def ready(app):
    async with original(app):
        print('READY',flush=True)
        yield
app.router.lifespan_context=ready
uvicorn.run(app,fd=int(sys.argv[1]),access_log=False,log_level='critical',proxy_headers=False)
"""

    @contextlib.contextmanager
    def process():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with (tmp_path / "process.log").open("a") as errors:
                child = subprocess.Popen(
                    [sys.executable, "-c", script, str(listener.fileno())],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    text=True,
                    pass_fds=(listener.fileno(),),
                )
                try:
                    child.stdin.write(
                        json.dumps(
                            {
                                "dsn": settings.dsn,
                                "key": settings.encryption_key.hex(),
                                "sign": settings.signing_key.hex(),
                            }
                        )
                    )
                    child.stdin.close()
                    assert select.select([child.stdout], [], [], 15)[0], "Agent startup barrier not reached"
                    assert child.stdout.readline().strip() == "READY", (tmp_path / "process.log").read_text()
                    yield f"http://127.0.0.1:{port}"
                finally:
                    child.terminate()
                    child.wait(timeout=10)

    def call(base, path, method="GET", body=None):
        request = Request(
            base + path,
            method=method,
            headers={**headers(settings), "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    with process() as base:
        revision = call(
            base,
            "/api/v1/agent/models/" + str(uuid4()),
            "PUT",
            {
                "expected": None,
                "name": "model",
                "base_url": model_server.url,
                "model_id": "controlled",
                "model_version": "recorded",
                "secret": "model-only-secret",
            },
        )["revision"]
        sid = str(uuid4())
        path = "/api/v1/agent/sessions/" + sid
        call(base, path, "PUT", {"model_revision": revision, "model_call_limit": 1})
        accepted = call(base, path + "/messages", "POST", {"expected": None, "text": "fresh process"})
        assert accepted["consumed"] == 1
    with process() as base:
        assert call(base, path) == accepted
        assert call(base, path + "/resume", "POST") == accepted
    assert model_server.calls == 1
