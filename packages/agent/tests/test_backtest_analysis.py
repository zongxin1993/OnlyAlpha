"""Signed read-only analysis data; fixtures are controlled financial examples.

These tests prove Agent provenance and one-call recovery, not Backtest Evidence or
Shipping UI acceptance. Backend's actual signer separately requires opaque owners.
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from onlyalpha_agent import backend
from onlyalpha_agent import model as provider
from onlyalpha_agent.app import create_app
from onlyalpha_agent.security import Denied, authenticate, verify_backtest_analysis
from onlyalpha_agent.store import Conflict, Store
from onlyalpha_agent.workflow import digest
from psycopg.types.json import Jsonb

from packages.agent.tests.test_agent import headers, model, session

KEY = b"b" * 32
RUN = "00000000-0000-4000-8000-000000009301"
ISSUER = "onlyalpha-backend-backtest-analysis-v1"
AUDIENCE = "onlyalpha-agent-backtest-analysis"


def data():
    # Explicit controlled input. No parser value is being passed as an owning
    # VerifiedEvidence, admission, exchange fact or profitability certification.
    return {
        "schema_version": 1,
        "profile": "ONLYALPHA_BACKTEST_ANALYSIS_DATA_V1",
        "run_id": RUN,
        "specification_fingerprint": "a" * 64,
        "strategy_fingerprint": "b" * 64,
        "evidence_fingerprint": "c" * 64,
        "result_fingerprint": "d" * 64,
        "determinism_fingerprint": "e" * 64,
        "state": "COMPLETED",
        "sample": {
            "instrument": "BTCUSDT.BINANCE",
            "start_at": "2025-01-03T00:00:00Z",
            "end_at": "2025-01-03T12:00:00Z",
            "quantity": "0.01",
            "rule_observed_at": "2026-11-02T00:00:00Z",
        },
        "metrics": {
            "initial_equity": "10000.00",
            "final_equity": "10000.02",
            "return_since_start": "0.000002",
            "net_pnl": "0.02",
            "realized_pnl": "0.02",
            "unrealized_pnl": "0.00",
            "fees": "0.001",
            "maximum_drawdown": "-0.000001",
            "fill_count": 2,
            "roundtrip_count": 1,
        },
        "baseline": None,
        "trades": [
            {
                "ordinal": 1,
                "time_ns": "1735862460000000000",
                "side": "BUY",
                "quantity": "0.01",
                "price": "100.00",
                "fee": "0.0005",
                "signal_time_ns": "1735862400000000000",
                "signal": "ENTRY",
                "order_id": "controlled-order-1",
                "trade_id": "controlled-trade-1",
            },
            {
                "ordinal": 2,
                "time_ns": "1735862520000000000",
                "side": "SELL",
                "quantity": "0.01",
                "price": "102.10",
                "fee": "0.0005",
                "signal_time_ns": "1735862460000000000",
                "signal": "EXIT",
                "order_id": "controlled-order-2",
                "trade_id": "controlled-trade-2",
            },
        ],
        "trade_count": 2,
        "trades_truncated": False,
        "limitations": [
            "十二小时样本仅供实验性系统验证，不代表收益合格或未来表现。",
            "规则为当前快照，名义金额按模拟成交价检查，不还原历史交易所审核。",
        ],
    }


def claims():
    now = int(time.time())
    return {
        "v": 1,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "owner",
        "kind": "BACKTEST_ANALYSIS_DATA",
        "jti": str(uuid4()),
        "iat": now - 1,
        "exp": now + 299,
        "data": data(),
    }


def token(value=None, *, key=KEY):
    return jwt.encode(claims() if value is None else value, key, algorithm="HS256")


def message(assertion, *, expected=None, run=RUN):
    return {
        "expected": expected,
        "text": "请解释回测收益、费用、交易和短样本局限。",
        "topic": "BACKTEST_ANALYSIS",
        "backtest_run_id": run,
        "analysis_assertion": assertion,
    }


def test_analysis_signature_is_data_not_a_browser_or_backend_credential():
    assertion = token()
    verified = verify_backtest_analysis(KEY, assertion, owner="owner", run_id=RUN)
    assert verified == jwt.decode(assertion, KEY, algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE)["data"]
    with pytest.raises(Denied):
        authenticate(b"s" * 32, "Bearer " + assertion, browser_issuer_key=KEY)
    browser = jwt.encode(
        {
            **claims(),
            "iss": "onlyalpha-backend-browser-v1",
            "aud": "onlyalpha-agent",
            "kind": "human",
            "scopes": ["chat:read", "chat:write"],
        },
        KEY,
        algorithm="HS256",
    )
    with pytest.raises(Denied):
        verify_backtest_analysis(KEY, browser, owner="owner", run_id=RUN)
    with pytest.raises(Denied):
        verify_backtest_analysis(None, assertion, owner="owner", run_id=RUN)


@pytest.mark.parametrize(
    "mutation",
    [
        "forged",
        "issuer",
        "audience",
        "owner",
        "run",
        "expired",
        "future",
        "long_lifetime",
        "float_time",
        "extra_scope",
        "extra_data",
        "bad_pin",
        "too_many_trades",
        "false_truncation",
        "nonfinite",
        "oversized",
    ],
)
def test_bad_analysis_assertion_is_rejected_before_any_occurrence_or_model(mutation):
    value = claims()
    key = KEY
    if mutation == "forged":
        key = b"x" * 32
    elif mutation == "issuer":
        value["iss"] = "onlyalpha-backend-browser-v1"
    elif mutation == "audience":
        value["aud"] = "onlyalpha-agent"
    elif mutation == "owner":
        value["sub"] = "other"
    elif mutation == "run":
        value["data"]["run_id"] = str(uuid4())
    elif mutation == "expired":
        value.update(iat=1, exp=301)
    elif mutation == "future":
        value.update(iat=int(time.time()) + 10, exp=int(time.time()) + 300)
    elif mutation == "long_lifetime":
        value["exp"] = value["iat"] + 301
    elif mutation == "float_time":
        value["iat"] = float(value["iat"])
    elif mutation == "extra_scope":
        value["scopes"] = ["backtest:execute"]
    elif mutation == "extra_data":
        value["data"]["raw_trace"] = {"actions": ["execute"]}
    elif mutation == "bad_pin":
        value["data"]["evidence_fingerprint"] = "C" * 64
    elif mutation == "too_many_trades":
        value["data"]["trades"] *= 5
    elif mutation == "false_truncation":
        value["data"]["trade_count"] = 20
    elif mutation == "nonfinite":
        value["data"]["metrics"]["net_pnl"] = "NaN"
    else:
        value["data"]["limitations"] = ["x" * 13000]
    with pytest.raises(Denied):
        verify_backtest_analysis(KEY, token(value, key=key), owner="owner", run_id=RUN)


def test_analysis_model_contract_never_returns_an_actionable_candidate():
    assert (
        provider.validate_response({"message": "仅为结果解读。", "candidate": None}, "BACKTEST_ANALYSIS")["candidate"]
        is None
    )
    for bad in [
        {"message": "新策略", "candidate": {"expression": {"input": "close"}}},
        {"message": "交易", "candidate": None, "tools": [{"name": "place_order"}]},
        {"message": "研究", "study": None},
    ]:
        with pytest.raises(ValueError):
            provider.validate_response(bad, "BACKTEST_ANALYSIS")
    assert provider.validate_response({"message": "原因子澄清", "candidate": None}, "FACTOR")["candidate"] is None
    assert provider.validate_response({"message": "原研究澄清", "study": None}, "STUDY")["study"] is None


def test_exact_analysis_input_model_revision_history_and_expired_original_replay(settings, model_server, monkeypatch):
    configured = replace(settings, browser_issuer_key=KEY)
    monkeypatch.setattr(
        backend,
        "request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("analysis attempted a backend operation")),
    )
    assertion = token()
    body = message(assertion)
    cid = str(uuid4())
    with TestClient(create_app(configured)) as client:
        revision = model(client, configured, model_server.url)
        s = session(client, configured, revision)
        path = "/api/v1/agent/sessions/" + s["id"]
        h = {**headers(configured), "Idempotency-Key": cid}
        response = client.post(path + "/messages", headers=h, json=body)
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["topic"] == "BACKTEST_ANALYSIS"
        assert current["candidate"] is None and current["study"] is None and current["execution_admitted"] is False
        assert current["factor_reference"] is None and current["study_reference"] is None
        reference = {
            key: data()[key]
            for key in [
                "run_id",
                "specification_fingerprint",
                "strategy_fingerprint",
                "evidence_fingerprint",
                "result_fingerprint",
                "determinism_fingerprint",
            ]
        }
        assert current["backtest_reference"] == reference
        assert model_server.calls == 1
        with Store(configured) as store:
            plan = store.plan(cid)
            assert plan["analysis_assertion"] == assertion and plan["backtest_context"] == data()
            assert plan["backtest_run_id"] == RUN and plan["model_revision"] == revision
            assert plan["request"] == model_server.requests[0]
            assert store.conn.execute("SELECT count(*) AS n FROM agent_backend_plan").fetchone()["n"] == 0
        request = json.dumps(model_server.requests[0], ensure_ascii=False)
        contexts = [
            json.loads(row["content"]) for row in model_server.requests[0]["messages"] if row["content"].startswith("{")
        ]
        assert contexts == [data()]
        assert assertion not in request and "model-only-secret" not in request and "raw_trace" not in request
        staged = client.post(path + "/proposals", headers=headers(configured), json={"expected": current["head"]})
        assert staged.status_code == 409 and staged.json()["error"] == "AGENT_ANALYSIS_READ_ONLY", staged.text
        old_conversation = client.get(path + "/conversation", headers=headers(configured)).json()
        assert old_conversation["turns"][0]["topic"] == "BACKTEST_ANALYSIS"
        assert old_conversation["turns"][0]["backtest_reference"] == reference
        assert old_conversation["turns"][0]["candidate"] is None and old_conversation["turns"][0]["study"] is None

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return (datetime.now(UTC) + timedelta(seconds=600)).astimezone(tz)

    monkeypatch.setattr(jwt.api_jwt, "datetime", Later)
    with TestClient(create_app(configured)) as client:
        assert client.get(path + "/conversation", headers=headers(configured)).json() == old_conversation
        assert client.post(path + "/messages", headers=h, json=body).json() == current
        assert client.post(path + "/resume", headers=headers(configured)).json() == current
        fresh = str(uuid4())
        denied = client.post(
            path + "/messages",
            headers={**headers(configured), "Idempotency-Key": fresh},
            json=message(assertion, expected=current["head"]),
        )
        assert denied.status_code == 403, denied.text
        assert client.get("/api/v1/agent/commands/" + fresh, headers=headers(configured)).json()["status"] == "UNKNOWN"
        assert model_server.calls == 1


@pytest.mark.parametrize("mutation", ["owner", "run", "forged"])
def test_api_invalid_assertion_has_no_durable_model_plan(settings, model_server, mutation):
    configured = replace(settings, browser_issuer_key=KEY)
    value = claims()
    key = KEY
    if mutation == "owner":
        value["sub"] = "other"
    elif mutation == "run":
        value["data"]["run_id"] = str(uuid4())
    else:
        key = b"x" * 32
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, model_server.url))
        cid = str(uuid4())
        response = client.post(
            "/api/v1/agent/sessions/" + s["id"] + "/messages",
            headers={**headers(configured), "Idempotency-Key": cid},
            json=message(token(value, key=key)),
        )
        assert response.status_code == 403, response.text
        assert client.get("/api/v1/agent/commands/" + cid, headers=headers(configured)).json()["status"] == "UNKNOWN"
        assert model_server.calls == 0


def test_model_response_recording_loss_never_repeats_the_accepted_analysis_call(settings, model_server, monkeypatch):
    configured = replace(settings, browser_issuer_key=KEY)
    body = message(token())
    cid = str(uuid4())
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, model_server.url))
        path = "/api/v1/agent/sessions/" + s["id"]
        h = {**headers(configured), "Idempotency-Key": cid}
        original = Store.finish

        def lost(self, command, value):
            if command == cid:
                raise Conflict("CONTROLLED_REPLY_RECORDING_LOSS")
            return original(self, command, value)

        with monkeypatch.context() as fault:
            fault.setattr(Store, "finish", lost)
            response = client.post(path + "/messages", headers=h, json=body)
            assert response.status_code == 409, response.text
        assert model_server.calls == 1
        assert client.get("/api/v1/agent/commands/" + cid, headers=headers(configured)).json()["status"] == "ACCEPTED"
        observed = client.get(path, headers=headers(configured)).json()
        assert observed["status"] == "OUTCOME_UNKNOWN"
        assert client.post(path + "/messages", headers=h, json=body).json() == observed
        assert client.post(path + "/resume", headers=headers(configured)).json() == observed
        blocked = client.post(
            path + "/messages", headers=headers(configured), json=message(token(), expected=observed["head"])
        )
        assert blocked.status_code == 409 and blocked.json()["error"] == "AGENT_ORIGINAL_CALL_UNKNOWN"
        assert model_server.calls == 1
    with TestClient(create_app(configured)) as restarted:
        assert restarted.get(path, headers=headers(configured)).json() == observed
        assert restarted.post(path + "/resume", headers=headers(configured)).json() == observed
        assert model_server.calls == 1


@pytest.mark.parametrize("mutation", ["context", "request"])
def test_rehashed_analysis_input_cannot_replace_signed_or_frozen_model_context(settings, model_server, mutation):
    configured = replace(settings, browser_issuer_key=KEY)
    cid = str(uuid4())
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, model_server.url))
        path = "/api/v1/agent/sessions/" + s["id"]
        response = client.post(
            path + "/messages", headers={**headers(configured), "Idempotency-Key": cid}, json=message(token())
        )
        assert response.status_code == 200, response.text
        with Store(configured) as store:
            plan = deepcopy(store.plan(cid))
            if mutation == "context":
                plan["backtest_context"]["metrics"]["final_equity"] = "999999.00"
            else:
                contexts = [row for row in plan["request"]["messages"] if RUN in row["content"]]
                assert len(contexts) == 1
                contexts[0]["content"] = contexts[0]["content"].replace("10000.02", "999999.00")
            fp = digest(plan)
            for table in ["agent_event", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " DISABLE TRIGGER USER")
            store.conn.execute("UPDATE agent_event SET plan=%s,fingerprint=%s WHERE command=%s", (Jsonb(plan), fp, cid))
            store.conn.execute("UPDATE agent_command SET outcome=%s WHERE id=%s", (Jsonb({"event": fp}), cid))
            for table in ["agent_event", "agent_command"]:
                store.conn.execute("ALTER TABLE " + table + " ENABLE TRIGGER USER")
        assert client.get(path + "/conversation", headers=headers(configured)).status_code == 409
        assert model_server.calls == 1


def test_recorded_analysis_response_cannot_smuggle_a_factor_candidate(settings, model_server, monkeypatch):
    configured = replace(settings, browser_issuer_key=KEY)
    monkeypatch.setattr(
        provider,
        "invoke",
        lambda *a, **k: {
            "response": {"message": "新增因子", "candidate": {"name": "unsafe", "expression": {"input": "close"}}}
        },
    )
    with TestClient(create_app(configured)) as client:
        s = session(client, configured, model(client, configured, model_server.url))
        path = "/api/v1/agent/sessions/" + s["id"]
        response = client.post(path + "/messages", headers=headers(configured), json=message(token()))
        assert response.status_code == 200 and response.json()["status"] == "FAILED", response.text
        assert response.json()["candidate"] is None and response.json()["study"] is None
        turn = client.get(path + "/conversation", headers=headers(configured)).json()["turns"][0]
        assert turn["status"] == "FAILED" and turn["candidate"] is None and turn["study"] is None
        assert model_server.calls == 0


def test_third_topic_has_exact_context_fields_and_keeps_the_existing_body_budget(settings):
    from onlyalpha_agent.app import MessageInput
    from pydantic import ValidationError

    MessageInput.model_validate({"expected": None, "text": "原因子"})
    MessageInput.model_validate(
        {"expected": None, "text": "原研究", "topic": "STUDY", "factor_proposal_fingerprint": "a" * 64}
    )
    MessageInput.model_validate(message(token()))
    for patch in [{"analysis_assertion": None}, {"backtest_run_id": None}, {"factor_proposal_fingerprint": "a" * 64}]:
        with pytest.raises(ValidationError):
            MessageInput.model_validate({**message(token()), **patch})
    with TestClient(create_app(replace(settings, browser_issuer_key=KEY))) as client:
        response = client.post(
            "/api/v1/agent/sessions/" + str(uuid4()) + "/messages", headers=headers(settings), content=b"x" * 16385
        )
        assert response.status_code == 413


def test_malformed_bounded_jwt_header_is_denied_without_parser_recursion_escape():
    from base64 import urlsafe_b64encode

    # Untrusted header decoding happens before signature verification. The entire
    # token is within the existing bound; malformed depth must remain a denial.
    raw = '{"alg":"HS256","typ":"JWT","extra":' + "[" * 4000 + "0" + "]" * 4000 + "}"
    assertion = urlsafe_b64encode(raw.encode()).decode().rstrip("=") + ".e30.invalid"
    assert len(assertion) < 12288
    with pytest.raises(Denied):
        verify_backtest_analysis(KEY, assertion, owner="owner", run_id=RUN)
