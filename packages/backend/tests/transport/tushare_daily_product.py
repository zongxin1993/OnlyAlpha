"""受控交易日原始输入与原生工作站日线 Product API 场景。"""

from __future__ import annotations

import copy
import hashlib
import http.cookiejar
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from queue import Queue
from threading import Event
from typing import Any

import psycopg
from psycopg import sql

from scripts.database_guard import assert_test_database

ORIGIN = "http://127.0.0.1:5173"
TEST_TOKEN = "onlyalpha-controlled-daily-input"
FIELDS = {
    "stock_basic": "ts_code,symbol,name,market,exchange,list_date,delist_date",
    "trade_cal": "exchange,cal_date,is_open,pretrade_date",
    "daily": "ts_code,trade_date,open,high,low,close,vol,amount",
    "adj_factor": "ts_code,trade_date,adj_factor",
}
# Explicit civil calendar observations; holidays and sessions are provider inputs.
OPEN = {"20250103": True, "20250104": False, "20250105": False, "20250106": True, "20250107": True}
PRICES = {"20250103": (10, 11, 9, 10), "20250106": (12, 13, 11, 12), "20250107": (14, 15, 13, 14)}
FACTORS = {"20250103": 2, "20250106": 4, "20250107": 8}


@dataclass
class _PendingCalendar:
    requests: Queue[str] = field(default_factory=Queue)
    release: Event = field(default_factory=Event)


_pending_calendar: _PendingCalendar | None = None


def external_response(request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if set(request) != {"api_name", "params", "fields", "token"} or request["token"] != TEST_TOKEN:
        raise ValueError("CONTROLLED_TUSHARE_REQUEST_INVALID")
    api, params, fields = request["api_name"], request["params"], request["fields"]
    if api not in FIELDS or fields != FIELDS[api] or not isinstance(params, dict):
        raise ValueError("CONTROLLED_TUSHARE_QUERY_INVALID")
    rows: list[list[Any]]
    if api == "stock_basic":
        if (
            set(params) != {"exchange", "list_status"}
            or params["list_status"] != "L"
            or params["exchange"] not in {"SSE", "SZSE"}
        ):
            raise ValueError("CONTROLLED_TUSHARE_SECURITY_SCOPE_INVALID")
        symbol, code = ("600000", "600000.SH") if params["exchange"] == "SSE" else ("000001", "000001.SZ")
        rows = [[code, symbol, "受控股票", "主板", params["exchange"], "19990101", None]]
    else:
        calendar = api == "trade_cal"
        key = "exchange" if calendar else "ts_code"
        if set(params) != {key, "start_date", "end_date"} or params[key] not in (
            {"SSE", "SZSE"} if calendar else {"600000.SH", "000001.SZ"}
        ):
            raise ValueError("CONTROLLED_TUSHARE_DAY_SCOPE_INVALID")
        start, end = params["start_date"], params["end_date"]
        if start in OPEN and end in OPEN and start <= end:
            days = [d for d in OPEN if start <= d <= end]
            if calendar:
                rows = [[params[key], d, int(OPEN[d]), None] for d in days]
            elif api == "daily":
                rows = [[params[key], d, *PRICES[d], "123.45", "10.25"] for d in days if OPEN[d]]
            else:
                rows = [[params[key], d, FACTORS[d]] for d in days if OPEN[d]]
        else:
            # Probe asks for the prior fourteen-day span in Shanghai civil dates.
            today = (datetime.now(UTC) + timedelta(hours=8)).date()
            last = today - timedelta(days=1)
            if (
                api != "daily"
                or end != last.strftime("%Y%m%d")
                or start != (last - timedelta(days=14)).strftime("%Y%m%d")
            ):
                raise ValueError("CONTROLLED_TUSHARE_UNDECLARED_WINDOW")
            rows = [[params[key], end, 10, 11, 9, 10, "123.45", "10.25"]]
    gate = _pending_calendar
    if gate is not None:
        gate.requests.put(api)
        if api == "trade_cal" and not gate.release.wait(timeout=30):
            raise ValueError("CONTROLLED_TUSHARE_CALENDAR_RELEASE_TIMEOUT")
    return api, {"code": 0, "msg": "", "data": {"fields": fields.split(","), "items": list(reversed(rows))}}


class _OriginalStatus(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


@contextmanager
def _owner() -> Iterator[urllib.request.OpenerDirector]:
    cookies = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(
        _OriginalStatus(), urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies)
    )
    navigation = urllib.request.Request(
        ORIGIN + "/",
        headers={
            "Origin": ORIGIN,
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Site": "none",
            "Accept": "text/html",
        },
    )
    with client.open(navigation, timeout=30) as response:
        assert response.status == 200
    assert len([c for c in cookies if c.name == "onlyalpha_dev_session"]) == 1
    yield client


def _request(
    client: urllib.request.OpenerDirector,
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict[str, Any]]:
    url = ORIGIN + path + ("?" + urllib.parse.urlencode(params) if params else "")
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Origin": ORIGIN,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
            **(headers or {}),
        },
        data=None if body is None else json.dumps(body).encode(),
    )
    try:
        response = client.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def _body(client: urllib.request.OpenerDirector, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    status, data = _request(client, method, path, **kwargs)
    assert 200 <= status < 300, (method, path, status, data.get("error", {}).get("code"))
    return data


def _command(client: urllib.request.OpenerDirector, method: str, path: str, **body: Any) -> dict[str, Any]:
    return _body(
        client, method, path, headers={"Idempotency-Key": str(uuid.uuid4())}, body={"schema_version": 1, **body}
    )


def _source(
    client: urllib.request.OpenerDirector, venue: str, *, adjustment: str = "none"
) -> tuple[dict[str, Any], dict[str, Any]]:
    ident = str(uuid.uuid4())
    root = f"/api/v2/integrations/{ident}"
    _command(
        client,
        "POST",
        "/api/v2/integrations",
        integration_id=ident,
        type_id="tushare.daily.market_data",
        display_name=f"接口测试 {venue}",
    )

    def version() -> int:
        return _body(client, "GET", root + "/draft")["draft_version"]

    _command(
        client,
        "PUT",
        root + "/draft",
        expected_draft_version=version(),
        public_configuration={"venue": venue, "adjustment": adjustment, "cache_policy": "force_refresh"},
        probe_configuration=None,
    )
    _command(client, "PUT", root + "/draft/secrets/token", expected_draft_version=version(), secret=TEST_TOKEN)
    _command(client, "POST", root + "/revisions", expected_draft_version=version())
    source = next(
        s for s in _body(client, "GET", "/api/v2/market-data/sources")["sources"] if s["integration_id"] == ident
    )
    descriptor = _body(client, "GET", root + "/draft")["type_descriptor"]
    assert descriptor["probe_contract"]["configured_instruments"] == {
        "field_id": "venue",
        "instruments": {"XSHG": "600000.XSHG", "XSHE": "000001.XSHE"},
    }
    pin = source["integration_revision_fingerprint"]
    revision_doc = _body(client, "GET", root + "/revisions/" + pin)
    assert revision_doc["type_descriptor"] == descriptor
    ref = dict(integration_id=ident, integration_revision_fingerprint=pin, expected_type_id=source["type_id"])
    receipt = _body(client, "POST", root + "/probe", body={"schema_version": 1, "expected_revision_fingerprint": pin})
    expected = "600000.XSHG" if venue == "XSHG" else "000001.XSHE"
    assert receipt["probe_instrument"] == expected and receipt["overall_status"] == "READY"
    assert {r["check"] for r in receipt["checks"]} == {"AUTHENTICATION", "CONNECTIVITY", "HISTORICAL_DATA"}
    operational = _body(client, "GET", root + "/operational-status")
    assert operational["probe_attempt_id"] == receipt["probe_attempt_id"] and operational["status"] == "READY"
    assert _body(client, "GET", root + "/probe-attempts/" + receipt["probe_attempt_id"]) == receipt
    return source["historical_day_semantic"], ref


def _nanos(day: str) -> str:
    return str((date.fromisoformat(day) - date(1970, 1, 1)).days * 86400 * 10**9)


def _requests(log: Path) -> int:
    return sum(json.loads(line).get("kind") == "tushare" for line in log.read_text().splitlines())


def _projection(client: urllib.request.OpenerDirector, body: dict, receipt: dict) -> dict:
    params = {
        **body["source_reference"],
        "instrument_id": body["instrument_id"],
        "bar_semantic": json.dumps(body["bar_semantic"]),
        "anchor_kind": "LATEST_CLOSED",
        "target_bar_count": "2",
        "revision_id": receipt["revision_id"],
    }
    data = _body(client, "GET", "/api/v2/market-data/bars", params=params)
    assert (
        data["coverage"]["status"] == "COMPLETE"
        and data["resume_after_sequence"] is None
        and data["resume_plan_fingerprint"] is None
    )
    assert [Decimal(b["close"]) for b in data["bars"]] == [Decimal(5), Decimal(12)]
    assert [Decimal(b["volume"]) for b in data["bars"]] == [Decimal(12345)] * 2
    assert data["revision_evidence"][0]["seal_id"] == receipt["seal_id"]
    return data


def run_product(phase: str, output: Path, dsn: str) -> None:
    assert_test_database(dsn)
    state = output / "tushare-day-api-proof.json"
    log = output / "controlled-source-https.jsonl"
    path = "/api/v2/market-data/acquisitions"
    with _owner() as client:
        if phase == "restored":
            saved = json.loads(state.read_text())
            body, receipt = saved["request"], saved["receipt"]
            n = _requests(log)
            assert (
                _body(client, "GET", path + "/" + body["original_request_id"], params=body["source_reference"])
                == receipt
            )
            assert _projection(client, body, receipt) == saved["projection"]
            assert _requests(log) == n
            ref = body["source_reference"]
            _command(
                client,
                "PUT",
                "/api/v2/integrations/" + ref["integration_id"] + "/lifecycle",
                expected_lifecycle_state="ACTIVE",
                lifecycle_state="DISABLED",
            )
            assert _request(client, "GET", path + "/" + body["original_request_id"], params=ref)[0] == 403
            assert _requests(log) == n
            return
        _, foreign = _source(client, "XSHE")
        semantic, ref = _source(client, "XSHG", adjustment="qfq")
        body = dict(
            source_reference=ref,
            bar_semantic=semantic,
            instrument_id="600000.XSHG",
            start_ns=_nanos("2025-01-03"),
            end_ns=_nanos("2025-01-07"),
            original_request_id=str(uuid.uuid4()),
            adjustment_anchor="2025-01-06",
            provenance="REST_BACKFILL",
        )
        anonymous = urllib.request.build_opener(_OriginalStatus(), urllib.request.ProxyHandler({}))
        n = _requests(log)
        assert _request(anonymous, "POST", path, body=body)[0] in {401, 403}
        assert _request(
            anonymous,
            "POST",
            "/api/v2/integrations/" + ref["integration_id"] + "/probe",
            body={"schema_version": 1, "expected_revision_fingerprint": ref["integration_revision_fingerprint"]},
        )[0] in {401, 403}
        assert _requests(log) == n
        missing = {k: v for k, v in body.items() if k != "original_request_id"}
        assert _request(client, "POST", path, body=missing)[0] == 400
        receipt = _concurrent_collection(client, path, body, dsn, log)
        assert receipt["status"] == "COMPLETE" and receipt["original_request_id"] == body["original_request_id"]
        get = path + "/" + body["original_request_id"]
        n = _requests(log)
        assert _body(client, "GET", get, params=ref) == receipt
        assert _body(client, "POST", path, body=body) == receipt
        assert _request(client, "GET", get, params=foreign)[0] == 409
        assert _request(client, "POST", path, body={**body, "adjustment_anchor": "2025-01-03"})[0] == 409
        assert _request(client, "GET", get, params={**ref, "integration_revision_fingerprint": "0" * 64})[0] in {
            403,
            404,
        }
        assert _requests(log) == n
        projection = _projection(client, body, receipt)
        fresh = _body(client, "POST", path, body={**body, "original_request_id": str(uuid.uuid4())})
        assert fresh["status"] == "COMPLETE" and fresh["acquisition_id"] != receipt["acquisition_id"]
        _original_evidence(client, dsn, body, receipt, fresh, log)
        _cached_inputs(client, dsn, body, (receipt, fresh), log)
        root = "/api/v2/integrations/" + ref["integration_id"]
        version = _body(client, "GET", root + "/draft")["draft_version"]
        _command(
            client, "PUT", root + "/draft/secrets/token", expected_draft_version=version, secret=TEST_TOKEN + "-rotated"
        )
        n = _requests(log)
        assert _body(client, "GET", get, params=ref) == receipt
        assert _projection(client, body, receipt) == projection
        instruments = _body(
            client, "GET", "/api/v2/market/instruments", params={**ref, "sealed_only": "true", "query": "600000"}
        )
        assert [i["instrument_id"] for i in instruments["instruments"]] == ["600000.XSHG"]
        assert _requests(log) == n
        state.write_text(json.dumps({"request": body, "receipt": receipt, "projection": projection}))


def _concurrent_collection(
    owner: urllib.request.OpenerDirector,
    path: str,
    body: dict,
    dsn: str,
    log: Path,
) -> dict:
    """两个真实 HTTP 连接共享原应用。仅暂停源端答复以观察已提交的 attempt。"""
    global _pending_calendar
    assert _pending_calendar is None
    gate = _PendingCalendar()
    ref = body["source_reference"]
    before = _requests(log)
    with _owner() as observer, ThreadPoolExecutor(max_workers=1) as executor:
        _pending_calendar = gate
        pending = executor.submit(_body, owner, "POST", path, body=body)
        try:
            assert gate.requests.get(timeout=30) == "trade_cal"
            challenger = {**body, "original_request_id": str(uuid.uuid4())}
            observed = _body(observer, "POST", path, body=challenger)
            assert observed["status"] == "UNKNOWN" and observed["original_request_id"] == body["original_request_id"]
            assert _body(observer, "GET", path + "/" + observed["original_request_id"], params=ref) == observed
            with psycopg.connect(dsn) as db:
                rows = db.execute(
                    "SELECT i.acquisition_id, i.requested_scope->>'original_request_id', a.attempt_id, o.outcome "
                    "FROM market_acquisition_intent i LEFT JOIN market_data_acquisition_attempt a USING(acquisition_id) "
                    "LEFT JOIN market_data_acquisition_attempt_outcome o USING(attempt_id) "
                    "WHERE i.identity_version=3 AND i.requested_scope->>'integration_id'=%s",
                    (ref["integration_id"],),
                ).fetchall()
                assert len(rows) == 1
                acquisition, original, attempt, outcome = rows[0]
                assert (acquisition, original, outcome) == (
                    observed["acquisition_id"],
                    body["original_request_id"],
                    None,
                )
                assert attempt and gate.requests.empty() and _requests(log) == before
            gate.release.set()
            receipt = pending.result(timeout=30)
            assert receipt["acquisition_id"] == observed["acquisition_id"] and receipt["status"] == "COMPLETE"
            assert [gate.requests.get_nowait() for _ in range(3)] == ["stock_basic", "daily", "adj_factor"]
            assert gate.requests.empty() and _requests(log) == before + 4
            return receipt
        finally:
            gate.release.set()
            _pending_calendar = None


def _original_evidence(
    client: urllib.request.OpenerDirector, dsn: str, body: dict, original: dict, other: dict, log: Path
) -> None:
    """在已隔离的测试库模拟存储故障；每次恢复原记录后复核原 operation。"""
    path = "/api/v2/market-data/acquisitions"
    get = path + "/" + body["original_request_id"]
    ref = body["source_reference"]
    n = _requests(log)
    with psycopg.connect(dsn, autocommit=True) as db:

        def first(sql: str, *args: Any) -> Any:
            row = db.execute(sql, args).fetchone()
            assert row is not None
            return row[0]

        attempt = first(
            "SELECT attempt_id FROM market_data_acquisition_attempt WHERE acquisition_id=%s", original["acquisition_id"]
        )
        other_attempt = first(
            "SELECT attempt_id FROM market_data_acquisition_attempt WHERE acquisition_id=%s", other["acquisition_id"]
        )
        prepared = first("SELECT to_jsonb(p) FROM market_history_prepared_scope p WHERE attempt_id=%s", attempt)
        foreign = first("SELECT to_jsonb(p) FROM market_history_prepared_scope p WHERE attempt_id=%s", other_attempt)
        _migrate_direct_inputs(db, attempt, other_attempt, prepared)
        assert _body(client, "GET", get, params=ref) == original
        assert prepared["requested_scope"]["data_version"] == foreign["requested_scope"]["data_version"]
        assert prepared["input_manifest"]["candidate_refs"] != foreign["input_manifest"]["candidate_refs"]

        def mutate(table: str, commands: list[tuple[str, tuple]]) -> None:
            # Fixed identifiers; restore the trigger within the same transaction before publishing the fault.
            trigger = table + "_reject_mutation"
            with db.transaction():
                db.execute(
                    sql.SQL("ALTER TABLE {} DISABLE TRIGGER {}").format(sql.Identifier(table), sql.Identifier(trigger))
                )
                for statement, values in commands:
                    db.execute(statement, values)
                db.execute(
                    sql.SQL("ALTER TABLE {} ENABLE TRIGGER {}").format(sql.Identifier(table), sql.Identifier(trigger))
                )

        single = prepared["input_manifest"]["inputs"][0]
        physical = first(
            "SELECT to_jsonb(p) FROM market_segment_physical_proof p WHERE segment_id=%s", single["segment_id"]
        )
        table = "market_segment_physical_proof"
        mutate(table, [("DELETE FROM market_segment_physical_proof WHERE segment_id=%s", (single["segment_id"],))])
        try:
            assert _request(client, "GET", get, params=ref)[0] == 503
        finally:
            db.execute(
                "INSERT INTO market_segment_physical_proof SELECT * FROM jsonb_populate_record(NULL::market_segment_physical_proof,%s::jsonb)",
                (json.dumps(physical),),
            )
        assert _body(client, "GET", get, params=ref) == original

        def set_preparation(row: dict) -> None:
            mutate(
                "market_history_prepared_scope",
                [
                    (
                        "UPDATE market_history_prepared_scope SET input_manifest=%s::jsonb,input_fingerprint=%s,requested_scope=%s::jsonb WHERE attempt_id=%s",
                        (
                            json.dumps(row["input_manifest"]),
                            row["input_fingerprint"],
                            json.dumps(row["requested_scope"]),
                            attempt,
                        ),
                    )
                ],
            )

        # A consistent construction generated with a different executable cannot
        # stand for this operation, even when every raw price and candidate exists.
        def digest(value: dict) -> str:
            return hashlib.sha256(
                json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()

        alternate = copy.deepcopy(prepared)
        scope = alternate["requested_scope"]
        c = scope["bar_construction"]
        intent = first(
            "SELECT requested_scope FROM market_acquisition_intent WHERE acquisition_id=%s", original["acquisition_id"]
        )

        def version(artifact: str) -> str:
            return "history-day:" + digest(
                {
                    "schema_version": 1,
                    "implementation": intent["implementation_fingerprint"],
                    "artifact": artifact,
                    "calendar_fingerprint": c["plan"]["calendar_fingerprint"],
                    "normalized_daily_fingerprint": prepared["input_manifest"]["normalized_daily_fingerprint"],
                    "provider_semantic": c["provider_semantic"],
                    "adjustment_evidence": c["adjustment_evidence"],
                    "adjustment_policy": body["bar_semantic"]["adjustment_policy"],
                }
            )

        assert version(intent["artifact_fingerprint"]) == scope["data_version"]
        c["data_version"] = scope["data_version"] = version("f" * 64)
        c["fingerprint"] = digest({k: v for k, v in c.items() if k != "fingerprint"})
        set_preparation(alternate)
        try:
            assert _request(client, "GET", get, params=ref)[0] in {409, 503}
        finally:
            set_preparation(prepared)
        set_preparation(foreign)
        try:
            assert _request(client, "GET", get, params=ref)[0] in {409, 503}
        finally:
            set_preparation(prepared)
        assert _body(client, "GET", get, params=ref) == original

        # Lost ACK for creation of the final scope and for revision publication,
        # with the original candidate already drained to the physical store.
        outcome = first(
            "SELECT to_jsonb(o) FROM market_data_acquisition_attempt_outcome o WHERE attempt_id=%s", attempt
        )
        mutate(
            "market_data_acquisition_attempt_outcome",
            [("DELETE FROM market_data_acquisition_attempt_outcome WHERE attempt_id=%s", (attempt,))],
        )
        try:
            mutate(
                "market_history_prepared_scope",
                [("DELETE FROM market_history_prepared_scope WHERE attempt_id=%s", (attempt,))],
            )
            try:
                unknown = _body(client, "GET", get, params=ref)
                assert unknown["status"] == "UNKNOWN" and unknown["revision_id"] is None
                assert _body(client, "POST", path, body=body) == unknown
                blocked = _body(client, "POST", path, body={**body, "original_request_id": str(uuid.uuid4())})
                assert blocked == unknown
            finally:
                db.execute(
                    "INSERT INTO market_history_prepared_scope SELECT * FROM jsonb_populate_record(NULL::market_history_prepared_scope,%s::jsonb)",
                    (json.dumps(prepared),),
                )
            assert _body(client, "POST", path, body=body) == original
            assert (
                first(
                    "SELECT count(*) FROM market_data_acquisition_attempt WHERE acquisition_id=%s",
                    original["acquisition_id"],
                )
                == 1
            )
        finally:
            db.execute(
                "INSERT INTO market_data_acquisition_attempt_outcome SELECT * FROM jsonb_populate_record(NULL::market_data_acquisition_attempt_outcome,%s::jsonb) ON CONFLICT DO NOTHING",
                (json.dumps(outcome),),
            )
    assert _requests(log) == n


def _migrate_direct_inputs(db: psycopg.Connection, attempt: str, other: str, prepared: dict) -> None:
    """在本隔离库重建原格式合法行，核验原迁移 SQL 的回滚、重试与不可变关联。"""
    migrations = Path(__file__).resolve().parents[4] / "database/postgres/migrations"
    ddl = (migrations / "0074_market_history_preparation.sql").read_text()
    # 仅提取原输入表与 trigger。既有 attempt、Segment 和拒绝变更函数沿真实原 FK 引用。
    statements = [
        statement[statement.index("CREATE ") :]
        for statement in ddl.split(";")
        if "CREATE TABLE market_history_preparation_input (" in statement
        or "CREATE TRIGGER market_history_preparation_input_reject_mutation" in statement
    ]
    assert len(statements) == 2
    migration = (migrations / "0076_market_history_input_producer.sql").read_text()
    inputs = sorted(prepared["input_manifest"]["inputs"], key=lambda row: row["query_fingerprint"])
    schema = sql.Identifier("history_upgrade_" + uuid.uuid4().hex)
    with db.transaction(force_rollback=True):
        db.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        db.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(schema))
        for statement in statements:
            db.execute(statement)
        for row in inputs:
            db.execute(
                "INSERT INTO market_history_preparation_input SELECT * FROM "
                "jsonb_populate_record(NULL::market_history_preparation_input,%s::jsonb)",
                (json.dumps(row),),
            )

        def records(projection: str) -> list:
            return [
                row[0]
                for row in db.execute(
                    sql.SQL(
                        "SELECT ({})::text FROM market_history_preparation_input i "
                        "WHERE attempt_id=%s ORDER BY query_fingerprint"
                    ).format(sql.SQL(projection)),
                    (attempt,),
                )
            ]

        old = records("to_jsonb(i)")
        assert list(map(json.loads, old)) == inputs
        with db.transaction(force_rollback=True):
            db.execute(migration)
            assert records("to_jsonb(i)-'producer_attempt_id'") == old
        assert records("to_jsonb(i)") == old
        db.execute(migration)
        assert (
            records(
                "CASE WHEN i.producer_attempt_id IS NULL THEN to_jsonb(i)-'producer_attempt_id' ELSE to_jsonb(i) END"
            )
            == old
        )
        assert all(row["producer_attempt_id"] is None for row in map(json.loads, records("to_jsonb(i)")))
        link = {**inputs[0], "attempt_id": other, "producer_attempt_id": attempt}
        insert = (
            "INSERT INTO market_history_preparation_input SELECT * FROM "
            "jsonb_populate_record(NULL::market_history_preparation_input,%s::jsonb)"
        )
        try:
            with db.transaction():
                db.execute(insert, (json.dumps({**link, "query_fingerprint": "f" * 64}),))
        except psycopg.errors.ForeignKeyViolation as exc:
            assert exc.diag.constraint_name == "market_history_input_producer_query"
        else:
            raise AssertionError("错误 producer/Query 被接受")
        db.execute(insert, (json.dumps(link),))
        assert list(map(json.loads, old)) == [
            row[0]
            for row in db.execute(
                "SELECT to_jsonb(i)-'producer_attempt_id' FROM "
                "public.market_history_preparation_input i WHERE attempt_id=%s ORDER BY query_fingerprint",
                (attempt,),
            )
        ]
        record = db.execute(
            "SELECT input_manifest, input_fingerprint FROM public.market_history_prepared_scope WHERE attempt_id=%s",
            (attempt,),
        ).fetchone()
        assert record == (prepared["input_manifest"], prepared["input_fingerprint"])


def _cached_inputs(
    client: urllib.request.OpenerDirector, dsn: str, original: dict, producers: tuple[dict, dict], log: Path
) -> None:
    ref = original["source_reference"]
    root = "/api/v2/integrations/" + ref["integration_id"]
    draft = _body(client, "GET", root + "/draft")
    _command(
        client,
        "PUT",
        root + "/draft",
        expected_draft_version=draft["draft_version"],
        public_configuration={**draft["public_configuration"], "cache_policy": "cache_only"},
        probe_configuration=draft["probe_configuration"],
    )
    _command(
        client,
        "POST",
        root + "/revisions",
        expected_draft_version=_body(client, "GET", root + "/draft")["draft_version"],
    )
    new_pin = _body(client, "GET", root)["current_revision_fingerprint"]
    assert new_pin != ref["integration_revision_fingerprint"]
    target = {**original, "source_reference": {**ref, "integration_revision_fingerprint": new_pin}}
    path = "/api/v2/market-data/acquisitions"
    n = _requests(log)
    with psycopg.connect(dsn, autocommit=True) as db:

        def inputs(id: str) -> list[dict]:
            return [
                r[0]
                for r in db.execute(
                    "SELECT to_jsonb(i) FROM market_history_preparation_input i JOIN market_data_acquisition_attempt a USING(attempt_id) WHERE a.acquisition_id=%s ORDER BY query_fingerprint",
                    (id,),
                )
            ]

        originals = {r[0]["attempt_id"]: r for p in producers if (r := inputs(p["acquisition_id"]))}
        assert len(originals) == 2 and all(
            len(r) == 4 and all(i["producer_attempt_id"] is None for i in r) for r in originals.values()
        )
        physical = None
        for _ in range(2):
            receipt = _body(client, "POST", path, body={**target, "original_request_id": str(uuid.uuid4())})
            assert receipt["status"] == "COMPLETE"
            linked = inputs(receipt["acquisition_id"])
            assert len(linked) == 4
            if physical is None:
                physical = originals[linked[0]["producer_attempt_id"]]
            assert len(linked) == len(physical)
            for link, source in zip(linked, physical, strict=True):
                assert link["producer_attempt_id"] == source["attempt_id"] != link["attempt_id"]
                assert all(
                    link[k] == source[k]
                    for k in (
                        "segment_id",
                        "segment_content_hash",
                        "query_document",
                        "query_fingerprint",
                        "raw_event_id",
                        "raw_sha256",
                    )
                )
        miss = _body(
            client,
            "POST",
            path,
            body={**target, "start_ns": _nanos("2025-01-04"), "original_request_id": str(uuid.uuid4())},
        )
        assert miss["status"] == "FAILED" and miss["failure_detail"] == "MARKET_DATA_HISTORY_CACHE_MISS"
        chosen = linked[0]
        actual_origin = chosen["producer_attempt_id"]
        other_origin = next(p for p in originals if p != actual_origin)

        def replace_origin(producer_id: str) -> None:
            with db.transaction():
                db.execute(
                    "ALTER TABLE market_history_preparation_input DISABLE TRIGGER market_history_preparation_input_reject_mutation"
                )
                db.execute(
                    "UPDATE market_history_preparation_input SET producer_attempt_id=%s WHERE attempt_id=%s AND query_fingerprint=%s",
                    (producer_id, chosen["attempt_id"], chosen["query_fingerprint"]),
                )
                db.execute(
                    "ALTER TABLE market_history_preparation_input ENABLE TRIGGER market_history_preparation_input_reject_mutation"
                )

        replace_origin(other_origin)
        try:
            assert _request(
                client, "GET", path + "/" + receipt["original_request_id"], params=target["source_reference"]
            )[0] in {409, 503}
        finally:
            replace_origin(actual_origin)
        assert (
            _body(client, "GET", path + "/" + receipt["original_request_id"], params=target["source_reference"])
            == receipt
        )
    assert _requests(log) == n


def check_stopped_preparation(output: Path, dsn: str, binary: Path, env: dict[str, str]) -> None:
    """初次 Host 已退出且重启尚未开始，可独占使用原 AuthoritySession probe。"""
    assert_test_database(dsn)
    proof = json.loads((output / "tushare-day-api-proof.json").read_text())
    receipt = proof["receipt"]
    at = datetime.now(UTC).isoformat()

    def probe(operation: str, **params: Any) -> dict:
        request = {
            "op": operation,
            "at": at,
            "database": env["ONLYALPHA_CLICKHOUSE_DATABASE"],
            "url": env["ONLYALPHA_CLICKHOUSE_URL"],
            **params,
        }
        result = subprocess.run(
            [str(binary)],
            input=json.dumps({"op": "market-storage", "request": request}),
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
            env=env,
        )
        return json.loads(result.stdout)

    with psycopg.connect(dsn, autocommit=True) as db:
        record = db.execute(
            "SELECT to_jsonb(o), p.input_fingerprint FROM market_data_acquisition_attempt a "
            "JOIN market_data_acquisition_attempt_outcome o USING(attempt_id) "
            "JOIN market_history_prepared_scope p USING(attempt_id) WHERE a.acquisition_id=%s",
            (receipt["acquisition_id"],),
        ).fetchone()
        assert record is not None
        outcome, preparation = record
        assert outcome["outcome"] == "COMPLETE" and outcome["revision_id"] == receipt["revision_id"]
        attempt = outcome["attempt_id"]

        def delete_outcome() -> None:
            with db.transaction():
                db.execute(
                    "ALTER TABLE market_data_acquisition_attempt_outcome DISABLE TRIGGER market_data_acquisition_attempt_outcome_reject_mutation"
                )
                db.execute("DELETE FROM market_data_acquisition_attempt_outcome WHERE attempt_id=%s", (attempt,))
                db.execute(
                    "ALTER TABLE market_data_acquisition_attempt_outcome ENABLE TRIGGER market_data_acquisition_attempt_outcome_reject_mutation"
                )

        original = probe("read", id=receipt["revision_id"])
        first = min(original["facts"], key=lambda row: int(row["ts_event_ns"]))
        update = first["canonical_payload"]
        candidate = copy.deepcopy(update)
        bar = candidate["payload"]["value"]
        assert tuple(Decimal(bar[k]["value"]) for k in ("low", "close", "high")) == (
            Decimal("4.50"),
            Decimal("5"),
            Decimal("5.50"),
        )
        bar["close"]["value"] = "5.25"
        legal = probe("fixture", action="day-bar-value-proof", update=candidate)
        assert legal["bar"] == bar
        assert (
            legal["payload_hash"]
            == hashlib.sha256(
                json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        assert legal["payload_hash"] != first["canonical_payload_hash"]
        delete_outcome()
        try:
            rejected = probe("failure", id=receipt["acquisition_id"], detail="MARKET_DATA_SOURCE_TIMEOUT")
            assert rejected == {"error": "MARKET_DATA_IDENTITY_CONFLICT"}, rejected
            state = db.execute(
                "SELECT p.input_fingerprint, o.outcome FROM market_history_prepared_scope p "
                "LEFT JOIN market_data_acquisition_attempt_outcome o USING(attempt_id) WHERE p.attempt_id=%s",
                (attempt,),
            ).fetchone()
            assert state == (preparation, None)
        finally:
            with db.transaction():
                delete_outcome()
                db.execute(
                    "INSERT INTO market_data_acquisition_attempt_outcome SELECT * FROM jsonb_populate_record(NULL::market_data_acquisition_attempt_outcome,%s::jsonb)",
                    (json.dumps(outcome),),
                )
        assert db.execute(
            "SELECT to_jsonb(o) FROM market_data_acquisition_attempt_outcome o WHERE attempt_id=%s", (attempt,)
        ).fetchone() == (outcome,)
        assert probe("read", id=receipt["revision_id"]) == original
