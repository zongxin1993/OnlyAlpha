"""A4 browser identity is Agent-audience only, separately issued from backend Human access."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent.app import create_app
from onlyalpha_agent.security import AUDIENCE, Denied, authenticate, issue_token


def test_browser_issuer_is_separate_and_cookies_are_never_agent_credentials(settings):
    key = b"b" * 32
    configured = replace(settings, browser_issuer_key=key)
    token = issue_token(
        key,
        subject="local-developer",
        audience=AUDIENCE,
        kind="human",
        scopes=["chat:read"],
        token_id=str(uuid4()),
        expires_at=4000000000,
        issuer="onlyalpha-backend-browser-v1",
    )
    with TestClient(create_app(configured)) as client:
        headers = {"Authorization": "Bearer " + token, "Origin": configured.origin}
        assert client.get("/api/v1/agent/sessions", headers=headers).status_code == 200
        assert (
            client.get(
                "/api/v1/agent/sessions", headers={**headers, "Cookie": "onlyalpha_dev_session=foreign"}
            ).status_code
            == 401
        )
        assert (
            client.get("/api/v1/agent/sessions", headers={**headers, "Origin": "https://foreign.invalid"}).status_code
            == 401
        )
        assert (
            client.get(
                "/api/v1/agent/sessions",
                headers={
                    **headers,
                    "Authorization": "Bearer "
                    + issue_token(
                        settings.signing_key,
                        subject="local-developer",
                        audience=AUDIENCE,
                        kind="human",
                        scopes=["chat:read"],
                        token_id=str(uuid4()),
                        expires_at=4000000000,
                        issuer="onlyalpha-backend-browser-v1",
                    ),
                },
            ).status_code
            == 401
        )
    with pytest.raises(Denied):
        authenticate(settings.signing_key, "Bearer " + token)


def test_unknown_command_can_be_abandoned_without_cancelling_an_accepted_effect(settings, model_server):
    from packages.agent.tests.test_agent import headers, model, session

    with TestClient(create_app(settings)) as client:
        command = str(uuid4())
        h = headers(settings)
        assert client.get("/api/v1/agent/commands/" + command, headers=h).json()["status"] == "UNKNOWN"
        assert client.post("/api/v1/agent/commands/" + command + "/abandon", headers=h).json()["status"] == "ABANDONED"
        body = {"model_revision": model(client, settings, model_server.url), "model_call_limit": 2}
        assert (
            client.put(
                "/api/v1/agent/sessions/" + str(uuid4()), headers={**h, "Idempotency-Key": command}, json=body
            ).status_code
            == 409
        )
        existing = session(client, settings, body["model_revision"])
        cid = str(uuid4())
        response = client.post(
            "/api/v1/agent/sessions/" + existing["id"] + "/messages",
            headers={**h, "Idempotency-Key": cid},
            json={"expected": None, "text": "idea"},
        )
        assert response.status_code == 200
        assert client.post("/api/v1/agent/commands/" + cid + "/abandon", headers=h).json()["status"] == "ACCEPTED"
        assert model_server.calls == 1
        assert client.get("/api/v1/agent/commands/" + cid, headers=headers(settings, "other")).status_code == 404


def test_cors_is_one_explicit_origin_without_cookie_authority(settings):
    with TestClient(create_app(settings)) as client:
        headers = {
            "Origin": settings.origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,idempotency-key,content-type",
        }
        response = client.options("/api/v1/agent/models/" + str(uuid4()), headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == settings.origin
        assert "access-control-allow-credentials" not in response.headers
        assert (
            client.options(
                "/api/v1/agent/sessions", headers={**headers, "Origin": "https://foreign.invalid"}
            ).status_code
            == 400
        )


@pytest.mark.parametrize("mutation", ["owner", "whole_context", "wrong_family", "leaf"])
def test_command_observation_requires_its_own_effect_not_a_valid_copied_receipt(settings, model_server, mutation):
    from onlyalpha_agent.store import Store
    from psycopg.types.json import Jsonb

    from packages.agent.tests.test_agent import headers, model, session

    with TestClient(create_app(settings)) as client:
        revision = model(client, settings, model_server.url)
        s = session(client, settings, revision)
        cid = str(uuid4())
        assert (
            client.post(
                "/api/v1/agent/sessions/" + s["id"] + "/messages",
                headers={**headers(settings), "Idempotency-Key": cid},
                json={"expected": None, "text": "idea"},
            ).status_code
            == 200
        )
        with Store(settings) as store:
            # Removing optional model output must not erase accepted occurrence.
            store.conn.execute("ALTER TABLE agent_result DISABLE TRIGGER USER")
            store.conn.execute("DELETE FROM agent_result WHERE command=%s", (cid,))
            store.conn.execute("ALTER TABLE agent_result ENABLE TRIGGER USER")
            assert store.observe_command(cid, "owner")["status"] == "ACCEPTED"
            store.conn.execute("ALTER TABLE agent_command DISABLE TRIGGER USER")
            if mutation == "owner":
                store.conn.execute("UPDATE agent_command SET owner='other' WHERE id=%s", (cid,))
            elif mutation == "whole_context":
                other = session(client, settings, revision)
                store.conn.execute(
                    "UPDATE agent_command SET outcome=%s WHERE id=%s",
                    (Jsonb({"id": other["id"], "workflow": other["workflow"]}), cid),
                )
            else:
                store.conn.execute(
                    "UPDATE agent_command SET outcome=%s WHERE id=%s",
                    (Jsonb({"backend_plan" if mutation == "wrong_family" else "event": "a" * 64}), cid),
                )
            store.conn.execute("ALTER TABLE agent_command ENABLE TRIGGER USER")
        response = client.get("/api/v1/agent/commands/" + cid, headers=headers(settings))
        assert response.status_code == (404 if mutation == "owner" else 409)


def test_contained_transport_checks_exact_peer_and_host_before_protected_data(settings):
    from packages.agent.tests.test_agent import headers

    configured = replace(settings, contained_peer="172.20.0.1")
    with TestClient(create_app(configured), base_url="http://127.0.0.1:5174", client=("172.20.0.1", 40000)) as client:
        assert client.get("/api/v1/agent/sessions", headers=headers(settings)).status_code == 200
        assert (
            client.get("/api/v1/agent/sessions", headers={**headers(settings), "Host": "foreign.invalid"}).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/agent/sessions", headers={**headers(settings), "X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 401
        )
    with TestClient(create_app(configured), base_url="http://127.0.0.1:5174", client=("172.20.0.9", 40000)) as client:
        assert client.get("/api/v1/agent/sessions", headers=headers(settings)).status_code == 403


def test_frozen_model_request_and_unknown_predecessor_are_not_reinterpreted(settings, model_server):
    from onlyalpha_agent.store import Conflict, Store

    from packages.agent.tests.test_agent import headers, model, session

    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        first = str(uuid4())
        second = str(uuid4())
        with Store(settings) as store, store.session_lock(s["id"]):
            assert store.accept_message(s["id"], "owner", first, {"expected": None, "text": "first"})
            plan = store.plan(first)
            head = store.view(s["id"], "owner", s["workflow"])["head"]
            with pytest.raises(Conflict, match="AGENT_ORIGINAL_CALL_UNKNOWN"):
                store.accept_message(s["id"], "owner", second, {"expected": head, "text": "second"})
            store.finish(first, {"response": {"message": "clarify", "candidate": None}})
            assert store.accept_message(s["id"], "owner", second, {"expected": head, "text": "second"})
            frozen = store.plan(second)
            assert [m["content"] for m in frozen["request"]["messages"] if m["role"] == "user"] == ["first", "second"]
            with pytest.raises(Conflict, match="AGENT_RESULT_CONFLICT"):
                store.finish(first, {"response": {"message": "late changed result", "candidate": None}})
            assert store.plan(first) == plan
            assert store.plan(second) == frozen
        assert client.get("/api/v1/agent/commands/" + second, headers=headers(settings)).json()["status"] == "ACCEPTED"
        assert model_server.calls == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "nested_origin",
        "source_ref",
        "candidate_leaf",
        "physical_session",
        "complete_context",
        "backend_child",
        "missing_plan",
    ],
)
def test_stage_recovery_requires_the_exact_model_source_relation(settings, monkeypatch, mutation):
    from copy import deepcopy

    from onlyalpha_agent import backend
    from onlyalpha_agent import model as provider
    from onlyalpha_agent.store import Store
    from onlyalpha_agent.workflow import digest
    from psycopg.types.json import Jsonb

    from packages.agent.tests.test_agent import headers, model, session

    configured = replace(
        settings,
        backend_url="http://127.0.0.1:5173",
        backend_credential="oa-proposal-v1." + str(uuid4()) + "." + "a" * 64,
    )
    candidate = {"name": "price", "purpose": "observe", "hypothesis": "persistence", "expression": {"input": "close"}}
    monkeypatch.setattr(provider, "invoke", lambda *args: {"response": {"message": "preview", "candidate": candidate}})

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
        return {
            "schema_version": 1,
            "command_id": command,
            "operation_fingerprint": "a" * 64,
            "effect": {"proposal_fingerprint": "b" * 64},
        }

    monkeypatch.setattr(backend, "request", transport)
    with TestClient(create_app(configured)) as client:
        revision = model(client, configured, "https://model.invalid/v1")
        s = session(client, configured, revision)
        other = session(client, configured, revision)
        response = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers=headers(configured),
            json={"expected": None, "text": "idea"},
        )
        assert response.status_code == 200
        other_turn = client.post(
            "/api/v1/agent/sessions/" + other["id"] + "/messages",
            headers=headers(configured),
            json={"expected": None, "text": "other"},
        )
        assert other_turn.status_code == 200
        cid = str(uuid4())
        stage = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/proposals",
            headers={**headers(configured), "Idempotency-Key": cid},
            json={"expected": response.json()["head"]},
        )
        assert stage.json()["status"] == "REGISTERED", stage.text
        with Store(configured) as store:
            # Backend receipt is optional for the existence of a staged occurrence.
            store.conn.execute("ALTER TABLE agent_backend_result DISABLE TRIGGER USER")
            store.conn.execute("DELETE FROM agent_backend_result WHERE command=%s", (cid,))
            store.conn.execute("ALTER TABLE agent_backend_result ENABLE TRIGGER USER")
            assert store.observe_command(cid, "owner")["status"] == "ACCEPTED"
            plan = deepcopy(store.backend_plan(cid))
            for table in ["agent_backend_plan", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " DISABLE TRIGGER USER")
            if mutation == "missing_plan":
                store.conn.execute("DELETE FROM agent_backend_plan WHERE command=%s", (cid,))
            elif mutation == "physical_session":
                store.conn.execute("UPDATE agent_backend_plan SET session=%s WHERE command=%s", (other["id"], cid))
            else:
                if mutation == "complete_context":
                    plan["session"] = other["id"]
                    plan["body"]["origin"]["session_id"] = other["id"]
                    plan["body"]["origin"]["event_fingerprint"] = other_turn.json()["head"]
                    _, events = store.history(other["id"], "owner")
                    source = store.conn.execute(
                        "SELECT fingerprint FROM agent_result WHERE command=%s", (events[-1]["command"],)
                    ).fetchone()
                    plan["body"]["origin"]["result_fingerprint"] = source["fingerprint"]
                    store.conn.execute("UPDATE agent_backend_plan SET session=%s WHERE command=%s", (other["id"], cid))
                elif mutation == "backend_child":
                    plan["backend_command"] = str(uuid4())
                    store.conn.execute(
                        "UPDATE agent_backend_plan SET backend_command=%s WHERE command=%s",
                        (plan["backend_command"], cid),
                    )
                elif mutation == "nested_origin":
                    plan["body"]["origin"]["session_id"] = other["id"]
                elif mutation == "source_ref":
                    plan["body"]["origin"]["result_fingerprint"] = "f" * 64
                else:
                    plan["body"]["candidate"]["name"] = "different"
                fp = digest(plan)
                store.conn.execute(
                    "UPDATE agent_backend_plan SET payload=%s,fingerprint=%s WHERE command=%s", (Jsonb(plan), fp, cid)
                )
                store.conn.execute(
                    "UPDATE agent_command SET outcome=%s WHERE id=%s", (Jsonb({"backend_plan": fp}), cid)
                )
            for table in ["agent_backend_plan", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " ENABLE TRIGGER USER")
        observed = client.get("/api/v1/agent/commands/" + cid, headers=headers(configured))
        assert observed.status_code == 409
        assert "CORRUPT" in observed.text


def test_rehashed_message_cannot_replace_the_original_human_intent(settings, model_server):
    from onlyalpha_agent.store import Store
    from onlyalpha_agent.workflow import digest
    from psycopg.types.json import Jsonb

    from packages.agent.tests.test_agent import headers, model, session

    with TestClient(create_app(settings)) as client:
        s = session(client, settings, model(client, settings, model_server.url))
        cid = str(uuid4())
        assert (
            client.post(
                "/api/v1/agent/sessions/" + s["id"] + "/messages",
                headers={**headers(settings), "Idempotency-Key": cid},
                json={"expected": None, "text": "original"},
            ).status_code
            == 200
        )
        with Store(settings) as store:
            plan = store.plan(cid)
            plan["text"] = "unapproved different idea"
            plan["request"]["messages"][-1]["content"] = plan["text"]
            fp = digest(plan)
            for table in ["agent_event", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " DISABLE TRIGGER USER")
            store.conn.execute("UPDATE agent_event SET plan=%s,fingerprint=%s WHERE command=%s", (Jsonb(plan), fp, cid))
            store.conn.execute("UPDATE agent_command SET outcome=%s WHERE id=%s", (Jsonb({"event": fp}), cid))
            for table in ["agent_event", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " ENABLE TRIGGER USER")
        assert client.get("/api/v1/agent/commands/" + cid, headers=headers(settings)).status_code == 409
        assert client.get("/api/v1/agent/sessions/" + s["id"], headers=headers(settings)).status_code == 409
        assert model_server.calls == 1
