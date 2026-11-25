"""原节点、真实 Research 来源回测上的正式 Product API SIM 启动完整正向、幂等重放与拒绝场景。"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg

from packages.backend.tests.application.backtest_human_owners import login, private_json
from packages.backend.tests.application.backtest_native_host import prepare_comparison, request, run_comparison
from packages.backend.tests.application.test_strategy_research_evidence import http_json
from scripts.database_guard import assert_test_database

RUNS = "/api/v2/sim/runs"
COMMANDS = "/api/v2/sim/commands"
ACCOUNTS = "/api/v2/sim/accounts"


def refused(
    http: Any,
    method: str,
    path: str,
    status: int,
    code: str,
    *,
    body: dict[str, Any] | None = None,
    command: str | None = None,
) -> None:
    headers = {} if body is None else {"Content-Type": "application/json"}
    if command is not None:
        headers["Idempotency-Key"] = command
    actual, response = http_json(http, method, path, body, headers)
    observed = (actual, response.get("schema_version"), response.get("error", {}).get("code"))
    assert observed == (status, 1, code), (method, path, actual, response)
    assert "run_id" not in response and "command_id" not in response, response


def completed_backtest(http: Any, payload: dict[str, Any]) -> str:
    preparation, run = prepare_comparison(http, payload)
    run_comparison(http, preparation, run)
    path = f"/api/v2/backtest/runs/{run}"
    details, evidence = request(http, path), request(http, path + "/evidence")
    assert details["state"] == "COMPLETED" and details["report_status"]["state"] == "VERIFIED", details
    assert details["run_id"] == evidence["run_id"] == run and evidence["preparation_command_id"] == preparation
    origin = payload["origin"]
    assert origin["kind"] == "FROZEN_STRATEGY" and details["strategy_fingerprint"] == origin["strategy_fingerprint"]
    for key in ("freeze_relation_fingerprint", "qualification_decision_fingerprint", "promotion_fingerprint"):
        assert evidence[key] == origin[key], evidence
    assert evidence["manifest"]["contract"] == "PG_JOB_RESULT_V1"
    return run


def operator_inputs(http: Any, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    assert request(http, "/api/v2/human/session") == {"subject_id": "local-developer", "can_logout": False}
    run = completed_backtest(http, payload)
    broker = str(uuid4())
    path = f"/api/v2/integrations/{broker}"
    request(
        http,
        "/api/v2/integrations",
        {
            "schema_version": 1,
            "type_id": "onlyalpha.virtual_broker",
            "integration_id": broker,
            "display_name": "SIM 启动回归券商",
        },
        str(uuid4()),
    )
    draft = request(http, path + "/draft")
    receipt = request(
        http,
        path + "/revisions",
        {"schema_version": 1, "expected_draft_version": draft["draft_version"]},
        str(uuid4()),
    )
    revision = request(http, path + "/revisions/" + receipt["outcome_id"])
    assert revision["type_id"] == "onlyalpha.virtual_broker" and revision["integration_id"] == broker
    assert revision["revision_fingerprint"] == receipt["outcome_id"]

    origin = payload["origin"]
    strategy = origin["strategy_fingerprint"]
    strategy_view = request(http, f"/api/v2/strategies/{strategy}")
    universe_instruments = strategy_view["source_revision"]["universe"]["instruments"]
    assert universe_instruments, strategy_view

    account_id = "sim-" + uuid4().hex
    account_body = {
        "schema_version": 1,
        "opening_cash": {
            "amount": "10000.00",
            "currency": {"code": "USD", "precision": 2, "currency_type": "FIAT"},
        },
        "broker_integration_id": broker,
        "instruments": [
            {
                "id": instrument_id,
                "price_precision": 2,
                "quantity_precision": 5,
                "multiplier": "1",
            }
            for instrument_id in universe_instruments
        ],
        "risk_rules": [
            {
                "schema_version": 1,
                "id": "limit-notional",
                "scope": "ACCOUNT",
                "order": 10,
                "mode": "ENFORCING",
                "kind": "MAX_ORDER_NOTIONAL",
                "limit": "5000.00",
            }
        ],
    }
    # 账户修订负向校验：缺少 ENFORCING 风控、未知券商、非虚拟券商集成、错账户读取。
    refused(
        http,
        "POST",
        f"{ACCOUNTS}/{account_id}/revisions",
        400,
        "SIM_ACCOUNT_REVISION_INVALID",
        body={
            **account_body,
            "risk_rules": [{**account_body["risk_rules"][0], "mode": "OBSERVING"}],
        },
    )
    refused(
        http,
        "POST",
        f"{ACCOUNTS}/{account_id}/revisions",
        404,
        "SIM_ACCOUNT_REVISION_NOT_FOUND",
        body={**account_body, "broker_integration_id": str(uuid4())},
    )
    refused(
        http,
        "POST",
        f"{ACCOUNTS}/{account_id}/revisions",
        409,
        "SIM_ACCOUNT_REVISION_MISMATCH",
        body={**account_body, "broker_integration_id": payload["source"]["integration_id"]},
    )

    published_status, account_revision = http_json(
        http,
        "POST",
        f"{ACCOUNTS}/{account_id}/revisions",
        account_body,
        {"Content-Type": "application/json"},
    )
    assert published_status == 200, account_revision
    assert account_revision["schema_version"] == 1
    assert account_revision["account_id"] == account_id
    assert account_revision["broker_integration_id"] == broker
    assert account_revision["opening_cash"]["amount"] == "10000.00"
    # 内容寻址规范幂等重放与精确回读。
    replay_status, account_replay = http_json(
        http,
        "POST",
        f"{ACCOUNTS}/{account_id}/revisions",
        account_body,
        {"Content-Type": "application/json"},
    )
    assert replay_status == 200 and account_replay == account_revision, account_replay
    account_fp = account_revision["revision_fingerprint"]
    fetched = request(http, f"{ACCOUNTS}/{account_id}/revisions/{account_fp}")
    assert fetched == account_revision, fetched
    refused(http, "GET", f"{ACCOUNTS}/other-account/revisions/{account_fp}", 409, "SIM_ACCOUNT_REVISION_MISMATCH")

    policy = request(http, "/api/v2/qualification-policies/experimental-backtest/revisions/1")
    assert policy["gate"] == "RESEARCH_TO_BACKTEST"
    sim_policy = request(http, "/api/v2/qualification-policies/experimental-sim/revisions/1")
    assert sim_policy["gate"] == "BACKTEST_TO_SIM"

    # local-developer 无显式 sim_start 授权，不能直接启动 SIM。
    selection = {
        "strategy_fingerprint": strategy,
        "backtest_run_id": run,
        "policy_fingerprint": policy["policy_fingerprint"],
        "decision_fingerprint": origin["qualification_decision_fingerprint"],
        "promotion_fingerprint": origin["promotion_fingerprint"],
        "account_id": account_id,
        "account_revision_fingerprint": account_fp,
        "broker_revision_fingerprint": revision["revision_fingerprint"],
    }
    command = str(uuid4())
    refused(http, "POST", RUNS, 403, "LOCAL_READ_FORBIDDEN", body=selection, command=command)
    refused(http, "GET", f"{COMMANDS}/{command}", 404, "SIM_START_REFERENCE_NOT_FOUND")
    return revision, {
        **selection,
        "freeze_relation_fingerprint": origin["freeze_relation_fingerprint"],
        "sim_policy_fingerprint": sim_policy["policy_fingerprint"],
    }


def assert_no_admission(dsn: str, commands: list[str]) -> None:
    assert_test_database(dsn)
    ids = [UUID(value) for value in commands]
    with psycopg.connect(dsn) as db:
        row = db.execute(
            """SELECT
            EXISTS (SELECT 1 FROM public.product_command_admission WHERE command_id=ANY(%(ids)s)),
            EXISTS (SELECT 1 FROM public.product_command_receipt WHERE command_id=ANY(%(ids)s)),
            EXISTS (SELECT 1 FROM public.sim_run_reservation WHERE command_id=ANY(%(ids)s)),
            EXISTS (SELECT 1 FROM public.sim_run_admission WHERE command_id=ANY(%(ids)s))""",
            {"ids": ids},
        ).fetchone()
        assert row == (False, False, False, False)


def assert_sim_admitted(
    dsn: str,
    command_id: str,
    run_id: str,
    account_id: str,
    broker_runtime_fingerprint: str,
) -> None:
    assert_test_database(dsn)
    with psycopg.connect(dsn) as db:
        reservation = db.execute(
            """SELECT run_id::text, account_id, generation, kernel_artifact
               FROM public.sim_run_reservation
               WHERE command_id=%s""",
            (UUID(command_id),),
        ).fetchone()
        assert reservation is not None
        assert reservation[0] == run_id and reservation[1] == account_id
        admission = db.execute(
            """SELECT run_id::text, account_id, scope_key, binding_fingerprint, broker_runtime_fingerprint
               FROM public.sim_run_admission
               WHERE command_id=%s""",
            (UUID(command_id),),
        ).fetchone()
        assert admission is not None
        assert admission[0] == run_id
        assert admission[1] == account_id
        assert admission[4] == broker_runtime_fingerprint
        scope_key = admission[2]
        stream = db.execute(
            """SELECT binding_fingerprint, head
               FROM public.trading_fact_stream
               WHERE scope_key=%s""",
            (scope_key,),
        ).fetchone()
        assert stream == (admission[3], 0), stream
        receipt = db.execute(
            """SELECT outcome_kind, outcome_id
               FROM public.product_command_receipt
               WHERE command_id=%s""",
            (UUID(command_id),),
        ).fetchone()
        assert receipt == ("SIM_RUN", run_id), receipt
        facts = db.execute(
            """SELECT count(*),
                      (SELECT count(*) FROM public.trading_fact_ready WHERE scope_key=%s),
                      (SELECT count(*) FROM public.sim_venue_log WHERE scope_key=%s AND sequence=0 AND document::jsonb->>'kind'='OPEN')
               FROM public.trading_fact WHERE scope_key=%s""",
            (scope_key, scope_key, scope_key),
        ).fetchone()
        assert facts == (0, 0, 1), facts


def exercise_sim_subjects(
    host: Callable[..., AbstractContextManager[Any]],
    directory: Path,
    payload: dict[str, Any],
    broker: dict[str, Any],
    operator_selection: dict[str, str],
    dsn: str,
) -> None:
    source = payload["source"]
    history = {field: source[field] for field in ("integration_id", "expected_type_id", "source_id", "environment")}
    history["revision_fingerprint"] = source["integration_revision_fingerprint"]
    owner, observer = "sim-owner", "backtest-only"
    credentials = {name: secrets.token_hex(32) for name in (owner, observer)}
    strategy = operator_selection["strategy_fingerprint"]
    account_id = operator_selection["account_id"]
    account_fp = operator_selection["account_revision_fingerprint"]
    subjects = [
        {
            "subject_id": name,
            "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "closed_history": [history],
            "frozen_strategy_fingerprints": [strategy],
        }
        for name, token in credentials.items()
    ]
    subjects[0]["sim_start"] = [
        {
            "strategy_fingerprint": strategy,
            "account_id": account_id,
            "broker_configuration_fingerprint": broker["runtime_configuration_fingerprint"],
        }
    ]
    policy = private_json(directory, subjects)
    with host(human_credentials_file=policy) as anonymous:
        a, b = (login(name, credentials[name], CookieJar()) for name in (owner, observer))
        run = completed_backtest(a, payload)
        assert run != operator_selection["backtest_run_id"]
        for session, foreign in ((a, operator_selection["backtest_run_id"]), (b, run)):
            refused(session, "GET", f"/api/v2/backtest/runs/{foreign}/evidence", 404, "BACKTEST_RUN_NOT_FOUND")

        base_selection = {
            field: operator_selection[field]
            for field in (
                "strategy_fingerprint",
                "policy_fingerprint",
                "decision_fingerprint",
                "promotion_fingerprint",
                "account_id",
                "account_revision_fingerprint",
                "broker_revision_fingerprint",
            )
        }
        base_selection["backtest_run_id"] = run

        refused_commands: list[str] = []

        def fresh_refused() -> str:
            refused_commands.append(str(uuid4()))
            return refused_commands[-1]

        # 1. 受限主体不得访问运营方账户修订路由。
        for session in (a, b):
            refused(session, "GET", f"{ACCOUNTS}/{account_id}/revisions/{account_fp}", 403, "OWNER_OPERATION_DENIED")
            refused(
                session,
                "POST",
                f"{ACCOUNTS}/{account_id}/revisions",
                403,
                "OWNER_OPERATION_DENIED",
                body={"schema_version": 1},
            )

        # 2. 无 sim_start 授权的主体（backtest-only）不得访问资格政策、评估或晋级。
        base = f"/api/v2/strategies/{strategy}"
        refused(b, "GET", "/api/v2/qualification-policies", 403, "OWNER_OPERATION_DENIED")
        refused(b, "GET", "/api/v2/qualification-policies/experimental-sim/revisions/1", 403, "OWNER_OPERATION_DENIED")
        refused(
            b,
            "POST",
            base + "/qualifications",
            403,
            "OWNER_OPERATION_DENIED",
            body={
                "schema_version": 1,
                "backtest_run_id": run,
                "policy_id": "experimental-sim",
                "policy_version": "1",
            },
            command=str(uuid4()),
        )

        # 3. 持有 sim_start 授权的主体仅限 BACKTEST_TO_SIM 与自身授权策略/自身回测。
        policies_view = request(a, "/api/v2/qualification-policies")
        assert policies_view["policies"] and all(p["gate"] == "BACKTEST_TO_SIM" for p in policies_view["policies"]), (
            policies_view
        )
        refused(a, "GET", "/api/v2/qualification-policies/experimental-backtest/revisions/1", 403, "OWNER_OPERATION_DENIED")
        refused(a, "GET", base, 403, "OWNER_OPERATION_DENIED")
        refused(a, "GET", base + "/qualification-decisions", 403, "OWNER_OPERATION_DENIED")
        refused(
            a,
            "GET",
            f"/api/v2/qualification-decisions/{operator_selection['decision_fingerprint']}",
            403,
            "OWNER_OPERATION_DENIED",
        )
        refused(
            a,
            "POST",
            base + "/qualifications",
            403,
            "OWNER_OPERATION_DENIED",
            body={
                "schema_version": 1,
                "research_run_id": str(uuid4()),
                "freeze_relation_fingerprint": operator_selection["freeze_relation_fingerprint"],
                "policy_id": "experimental-backtest",
                "policy_version": "1",
            },
            command=str(uuid4()),
        )
        # 不能用他人的回测 Run 做 BACKTEST_TO_SIM 评估。
        refused(
            a,
            "POST",
            base + "/qualifications",
            403,
            "BACKTEST_ACCESS_DENIED",
            body={
                "schema_version": 1,
                "backtest_run_id": operator_selection["backtest_run_id"],
                "policy_id": "experimental-sim",
                "policy_version": "1",
            },
            command=str(uuid4()),
        )

        # 4. SIM 启动基础负向用例（均不得写入任何准入记录）。
        key = fresh_refused()
        refused(anonymous, "POST", RUNS, 401, "LOCAL_READ_UNAUTHORIZED", body=base_selection, command=key)
        refused(anonymous, "GET", f"{COMMANDS}/{key}", 401, "LOCAL_READ_UNAUTHORIZED")
        refused(b, "POST", RUNS, 403, "LOCAL_READ_FORBIDDEN", body=base_selection, command=key)
        refused(
            a,
            "POST",
            RUNS,
            403,
            "LOCAL_READ_FORBIDDEN",
            body={**base_selection, "account_id": "not-granted"},
            command=key,
        )
        refused(a, "POST", RUNS, 400, "PRODUCT_REQUEST_INVALID", body=base_selection)  # 缺幂等键
        for field in ("decision_fingerprint", "promotion_fingerprint", "policy_fingerprint"):
            incomplete = {name: value for name, value in base_selection.items() if name != field}
            refused(a, "POST", RUNS, 400, "PRODUCT_REQUEST_INVALID", body=incomplete, command=fresh_refused())
        refused(
            a,
            "POST",
            RUNS,
            400,
            "SIM_START_INTENT_INVALID",
            body={**base_selection, "decision_fingerprint": "not-a-fingerprint"},
            command=fresh_refused(),
        )
        missing_account = {**base_selection, "account_revision_fingerprint": secrets.token_hex(32)}
        for _ in range(2):
            refused(a, "POST", RUNS, 404, "SIM_START_REFERENCE_NOT_FOUND", body=missing_account, command=key)
            refused(a, "GET", f"{COMMANDS}/{key}", 404, "SIM_START_REFERENCE_NOT_FOUND")
        # 使用旧 RESEARCH_TO_BACKTEST 决策/晋级直接启动 SIM 必须被拒绝。
        refused(
            a,
            "POST",
            RUNS,
            409,
            "QUALIFICATION_EVIDENCE_GATE_MISMATCH",
            body=base_selection,
            command=fresh_refused(),
        )
        assert_no_admission(dsn, refused_commands)

        # 5. 正向完整链路：BACKTEST_TO_SIM 政策读取 → 资格评估 → 晋级 → SIM 启动 → 重放与冲突。
        sim_policy = request(a, "/api/v2/qualification-policies/experimental-sim/revisions/1")
        assert sim_policy["policy_fingerprint"] == operator_selection["sim_policy_fingerprint"]

        qual_cmd = str(uuid4())
        qual_body = {
            "schema_version": 1,
            "backtest_run_id": run,
            "policy_id": "experimental-sim",
            "policy_version": "1",
        }
        qual_result = request(a, base + "/qualifications", qual_body, qual_cmd)
        assert qual_result["state"] == "COMPLETED", qual_result
        decision_fp = qual_result["decision_fingerprint"]
        assert decision_fp and len(decision_fp) == 64, qual_result
        assert request(a, f"{base}/qualifications/commands/{qual_cmd}") == qual_result
        decision_view = request(a, f"/api/v2/qualification-decisions/{decision_fp}")
        assert decision_view["state"] == "VERIFIED"
        assert decision_view["backtest_run_id"] == run
        assert decision_view["decision"]["gate"] == "BACKTEST_TO_SIM"
        assert decision_view["decision"]["outcome"] == "APPROVED"
        refused(b, "GET", f"/api/v2/qualification-decisions/{decision_fp}", 403, "OWNER_OPERATION_DENIED")

        promo_cmd = str(uuid4())
        promo_body = {
            "schema_version": 1,
            "backtest_run_id": run,
            "policy_id": "experimental-sim",
            "policy_version": "1",
            "qualification_decision_fingerprint": decision_fp,
            "reason": "正式回测通过 experimental-sim 门禁，申请 SIM 运行",
        }
        promo_result = request(a, base + "/qualification-promotions", promo_body, promo_cmd)
        assert promo_result["state"] == "COMPLETED", promo_result
        promo_record = promo_result["record"]
        assert promo_record["from_stage"] == "BACKTEST" and promo_record["to_stage"] == "SIM", promo_record
        assert promo_record["decision"] == "APPROVED", promo_record
        assert promo_record["qualification_decision_fingerprint"] == decision_fp, promo_record
        assert request(a, f"{base}/qualification-promotions/commands/{promo_cmd}") == promo_result

        valid_selection = {
            "strategy_fingerprint": strategy,
            "backtest_run_id": run,
            "policy_fingerprint": sim_policy["policy_fingerprint"],
            "decision_fingerprint": decision_fp,
            "promotion_fingerprint": promo_record["record_fingerprint"],
            "account_id": account_id,
            "account_revision_fingerprint": account_fp,
            "broker_revision_fingerprint": broker["revision_fingerprint"],
        }
        start_cmd = str(uuid4())
        started = request(a, RUNS, valid_selection, start_cmd)
        assert started["schema_version"] == 1
        assert started["command_id"] == start_cmd
        assert started["state"] == "ACCEPTED"
        run_id = started["run_id"]
        assert UUID(run_id).version == 4

        # 同键同意图重放与 GET 查询返回完全一致的 Run 引用。
        replayed = request(a, RUNS, valid_selection, start_cmd)
        assert replayed == started, replayed
        observed = request(a, f"{COMMANDS}/{start_cmd}")
        assert observed == started, observed

        # 同键异意图必须报冲突，他人不得读取该命令。
        refused(
            a,
            "POST",
            RUNS,
            409,
            "SIM_START_CONFLICT",
            body={**valid_selection, "decision_fingerprint": operator_selection["decision_fingerprint"]},
            command=start_cmd,
        )
        refused(b, "GET", f"{COMMANDS}/{start_cmd}", 404, "SIM_START_REFERENCE_NOT_FOUND")

        # 核对 PostgreSQL 中的正式预留、准入、经济事实与场所 OPEN 日志。
        assert_sim_admitted(
            dsn,
            start_cmd,
            run_id,
            account_id,
            broker["runtime_configuration_fingerprint"],
        )
