from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from onlyalpha_http_server.dev_web import (
    DEV_COOKIE,
    OnlyDevWebIngress,
    only_dev_web_configuration,
    only_mount_dev_web,
)
from onlyalpha_http_server.local_read_access import only_request_read_session
from onlyalpha_http_server.main import main as product_main
from onlyalpha_http_server.market_data import create_market_data_stream_router
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductError,
    OnlyMarketDataSourceProjectionV1,
    OnlyMarketDataTimeBarCapabilityV1,
)
from onlyalpha.application.source_read_access import OnlySourceReadAccessError, OnlySourceReadPermission

from .test_integration_api import COMMAND_ID, INTEGRATION_ID, _client, _Queries
from .test_local_read_access import _Session, _StreamService, _subscribe

ORIGIN = "http://127.0.0.1:5173"
NAVIGATION = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document", "Sec-Fetch-Site": "none"}


def _integration_app(tmp_path: Path, queries: _Queries | None = None):
    commands, client = _client(queries)
    configuration, credential = only_dev_web_configuration(ORIGIN, ())
    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text("Shipping entry fixture")
    only_mount_dev_web(client.app, directory, credential)
    client.app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    return commands, client.app


@pytest.mark.parametrize(
    "endpoint,body",
    [
        (
            "draft",
            {"schema_version": 1, "expected_draft_version": 1, "public_configuration": {}, "probe_configuration": None},
        ),
        (
            "draft/secrets/api_key",
            {"schema_version": 1, "expected_draft_version": 1, "secret": "CONTROLLED_TEST_SECRET"},
        ),
        ("lifecycle", {"schema_version": 1, "expected_lifecycle_state": "ACTIVE", "lifecycle_state": "DISABLED"}),
    ],
)
def test_shipping_integration_put_routes_use_separate_dev_human_policy(tmp_path: Path, endpoint: str, body) -> None:
    commands, app = _integration_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        path = f"/api/v2/integrations/{INTEGRATION_ID}/{endpoint}"
        assert client.put(path, headers={"Idempotency-Key": COMMAND_ID}, json=body).status_code == 403
        response = client.put(path, headers={"Origin": ORIGIN, "Idempotency-Key": COMMAND_ID}, json=body)
        assert response.status_code == 200
        assert "CONTROLLED_TEST_SECRET" not in response.text
    assert len(commands.received) == 1


@pytest.mark.parametrize("command", [False, True])
def test_real_integration_response_is_fenced_after_withdrawal_without_rolling_back_command(
    tmp_path: Path, command: bool
) -> None:
    entered, release = Event(), Event()
    queries = _Queries()
    commands, app = _integration_app(tmp_path, queries)
    original = commands.update_integration_draft if command else queries.get_integration

    def blocked(value):
        entered.set()
        assert release.wait(timeout=5)
        return original(value)

    if command:
        commands.update_integration_draft = blocked
    else:
        queries.get_integration = blocked
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as executor:
        client.get("/", headers=NAVIGATION)
        path = f"/api/v2/integrations/{INTEGRATION_ID}"
        if command:
            future = executor.submit(
                client.put,
                path + "/draft",
                headers={"Origin": ORIGIN, "Idempotency-Key": COMMAND_ID},
                json={
                    "schema_version": 1,
                    "expected_draft_version": 1,
                    "public_configuration": {},
                    "probe_configuration": None,
                },
            )
        else:
            future = executor.submit(client.get, path)
        try:
            assert entered.wait(timeout=5)
            client.portal.call(app.state.local_read_ingress.withdraw)
        finally:
            release.set()
        response = future.result(timeout=5)
        assert response.status_code == 401 and "Binance Main" not in response.text
        assert len(commands.received) == (1 if command else 0)
        assert (
            client.put(path + "/draft", headers={"Origin": ORIGIN, "Idempotency-Key": COMMAND_ID}, json={}).status_code
            == 401
        )
        assert len(commands.received) == (1 if command else 0)


def test_standalone_dev_web_refuses_all_interface_binding_before_application_startup(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DEV_WEB_ACCESS_MODES_CONFLICT"):
        product_main(
            [
                "--user-data-root",
                str(tmp_path),
                "--dev-web-root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
                "--port",
                "5173",
            ]
        )


def _app(tmp_path: Path, stream: _StreamService | None = None, *, source_reader=None):
    configuration, credential = only_dev_web_configuration(
        ORIGIN,
        (
            OnlyMarketDataSourceProjectionV1(
                "integration",
                "a" * 64,
                "Source",
                "test.market_data",
                "test.source",
                "LIVE",
                OnlyMarketDataTimeBarCapabilityV1(),
            ),
        ),
    )
    app = FastAPI()
    calls: list[str] = []

    @app.get("/api/v2/market-data/sources")
    @app.get("/api/v2/chart/studies/capabilities")
    @app.post("/api/v2/chart/studies/evaluate")
    def query(request: Request):
        session = only_request_read_session(request.scope)
        assert session is not None
        session.check_active()
        calls.append("query")
        return {"authenticated": True}

    @app.post("/api/v2/integrations")
    def configuration_command():
        calls.append("configuration")
        return {"submitted": True}

    @app.post("/api/v2/market-data/acquisitions")
    @app.get("/api/v2/agent/status")
    @app.post("/api/v2/strategies/promotions")
    def forbidden():
        calls.append("forbidden")
        raise AssertionError("No acquisition/Agent/LIVE dispatch in ordinary dev")

    if stream is not None:
        app.include_router(create_market_data_stream_router(stream))
    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text("<h1>Shipping entry fixture</h1>")
    (tmp_path / "web-private.txt").write_text("NOT_AN_ASSET")
    only_mount_dev_web(app, directory, credential)
    app.add_middleware(
        OnlyDevWebIngress, configuration=configuration, chart_study_enabled=True, source_reader=source_reader
    )
    return app, configuration, calls


def _source():
    return OnlyMarketDataSourceProjectionV1(
        "integration",
        "a" * 64,
        "Source",
        "test.market_data",
        "test.source",
        "LIVE",
        OnlyMarketDataTimeBarCapabilityV1(),
    )


def test_dev_human_acquisition_is_separate_from_read_permission_and_source_bound(tmp_path: Path) -> None:
    from .test_market_data_api import (
        BASE_BAR_SEMANTIC,
        END_NS_TEXT,
        INSTRUMENT_ID,
        START_NS_TEXT,
        _client,
        _selection,
        _Service,
    )

    class Service(_Service):
        def acquire_bars(self, reference, *, source_session=None, **kwargs):
            assert source_session is not None
            source_session.require_selection(_selection(), OnlySourceReadPermission.CLOSED_HISTORY)
            return super().acquire_bars(reference, **kwargs)

    service = Service()
    app = _client(service).app
    app.add_exception_handler(
        OnlySourceReadAccessError, lambda request, error: JSONResponse({"error": error.code}, status_code=403)
    )
    source = service.list_sources()[0]
    configuration, credential = only_dev_web_configuration(ORIGIN, (source,))
    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text("Shipping entry fixture")
    only_mount_dev_web(app, directory, credential)
    app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    payload = {
        "source_reference": {
            "integration_id": source.integration_id,
            "integration_revision_fingerprint": source.integration_revision_fingerprint,
            "expected_type_id": source.type_id,
        },
        "instrument_id": INSTRUMENT_ID,
        "start_ns": START_NS_TEXT,
        "end_ns": END_NS_TEXT,
        "bar_semantic": BASE_BAR_SEMANTIC.to_dict(),
        "provenance": "REST_BACKFILL",
    }
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        assert client.post("/api/v2/market-data/acquisitions", json=payload).status_code == 403
        wrong = {
            **payload,
            "source_reference": {**payload["source_reference"], "integration_revision_fingerprint": "b" * 64},
        }
        assert (
            client.post("/api/v2/market-data/acquisitions", headers={"Origin": ORIGIN}, json=wrong).status_code == 403
        )
        assert service.acquisitions == []
        response = client.post("/api/v2/market-data/acquisitions", headers={"Origin": ORIGIN}, json=payload)
        assert response.status_code == 201
        assert len(service.acquisitions) == 1


def test_dev_acquisition_withdrawal_retains_work_capacity_and_suppresses_its_response(tmp_path: Path) -> None:
    entered, release = Event(), Event()
    configuration, credential = only_dev_web_configuration(ORIGIN, (_source(),))
    app = FastAPI()
    completed: list[str] = []

    @app.post("/api/v2/market-data/acquisitions")
    def acquire(request: Request):
        session = only_request_read_session(request.scope)
        assert session is not None and request.scope["onlyalpha.dev_acquisition_session"] is session
        session.check_active()
        entered.set()
        assert release.wait(timeout=5)
        completed.append("owning command completed")
        return {"private_response": "must not be released"}

    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text("Shipping entry fixture")
    only_mount_dev_web(app, directory, credential)
    app.add_middleware(OnlyDevWebIngress, configuration=configuration)
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as executor:
        client.get("/", headers=NAVIGATION)
        future = executor.submit(client.post, "/api/v2/market-data/acquisitions", headers={"Origin": ORIGIN}, json={})
        try:
            assert entered.wait(timeout=5)
            ingress = app.state.local_read_ingress
            client.portal.call(ingress.withdraw)
            assert ingress._reads == 1
            assert completed == []
        finally:
            release.set()
        response = future.result(timeout=5)
        assert response.status_code == 401 and "private_response" not in response.text
        assert completed == ["owning command completed"]
        assert ingress._reads == 0


@pytest.mark.parametrize("change", ["added", "revision", "source", "environment", "type", "removed", "unchanged"])
def test_explicit_dev_source_refresh_replaces_exact_grants_without_restart(tmp_path: Path, change: str) -> None:
    source = _source()
    changes = {
        "added": (source, replace(source, integration_id="second-integration", source_id="second-source")),
        "revision": (replace(source, integration_revision_fingerprint="b" * 64),),
        "source": (replace(source, source_id="different-source"),),
        "environment": (replace(source, environment="TEST"),),
        "type": (replace(source, type_id="other.market_data"),),
        "removed": (),
        "unchanged": (source,),
    }
    app, original, calls = _app(tmp_path, source_reader=lambda: changes[change])
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        token = client.cookies.get(DEV_COOKIE)
        assert token is not None
        session = original.authority.authenticate("Bearer " + token)
        assert client.get("/api/v2/market-data/sources").status_code == 200
        current = app.state.local_read_ingress.configuration.authority
        assert len(current.grants) == len(changes[change])
        for grant, item in zip(current.grants, changes[change], strict=True):
            assert (
                grant.integration_id,
                grant.integration_revision_fingerprint,
                grant.expected_type_id,
                grant.source_id,
                grant.environment,
            ) == (
                item.integration_id,
                item.integration_revision_fingerprint,
                item.type_id,
                item.source_id,
                item.environment,
            )
        assert original.authority.grants[0].integration_revision_fingerprint == "a" * 64
        if change == "unchanged":
            assert current is original.authority
            session.check_active()
        else:
            assert current is not original.authority
            with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_UNAUTHORIZED"):
                session.check_active()
        assert client.cookies.get(DEV_COOKIE) == token
        assert client.get("/api/v2/chart/studies/capabilities").status_code == 200
    assert calls == ["query", "query"]


@pytest.mark.parametrize("failure", ["unavailable", "canonical-corrupt", "duplicate", "malformed", "too-many"])
def test_dev_source_refresh_refuses_missing_or_malformed_proof_without_dispatch(tmp_path: Path, failure: str) -> None:
    def read_sources():
        if failure == "unavailable":
            raise RuntimeError("PRIVATE_BACKEND_DETAIL")
        if failure == "canonical-corrupt":
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_CATALOG_CORRUPT", "PRIVATE_BACKEND_DETAIL")
        if failure == "duplicate":
            return (_source(), _source())
        if failure == "malformed":
            return (object(),)
        return tuple(replace(_source(), integration_id=str(index)) for index in range(33))

    app, original, calls = _app(tmp_path, source_reader=read_sources)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        response = client.get("/api/v2/market-data/sources")
        assert response.status_code == 503 and response.json()["error"]["code"] == "LOCAL_READ_PROOF_UNAVAILABLE"
        assert "PRIVATE_BACKEND_DETAIL" not in response.text
        assert app.state.local_read_ingress.configuration.authority is original.authority
    assert calls == []


def test_dev_source_refresh_authenticates_before_owning_discovery_and_never_revives_withdrawn_session(
    tmp_path: Path,
) -> None:
    reads = []

    def read_sources():
        reads.append(True)
        return (_source(),)

    app, _, calls = _app(tmp_path, source_reader=read_sources)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v2/market-data/sources").status_code == 401
        client.get("/", headers=NAVIGATION)
        assert client.get("/api/v2/market-data/sources", headers={"Origin": "http://evil.example"}).status_code == 403
        assert reads == []
        assert client.get("/api/v2/market-data/sources").status_code == 200
        client.portal.call(app.state.local_read_ingress.withdraw)
        assert client.get("/api/v2/market-data/sources").status_code == 401
    assert reads == [True] and calls == ["query"]


def test_withdrawal_during_dev_source_discovery_cannot_install_or_release_new_generation(tmp_path: Path) -> None:
    entered, release = Event(), Event()

    def read_sources():
        entered.set()
        assert release.wait(timeout=5)
        return (replace(_source(), integration_revision_fingerprint="b" * 64),)

    app, original, calls = _app(tmp_path, source_reader=read_sources)
    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as executor:
        client.get("/", headers=NAVIGATION)
        future = executor.submit(client.get, "/api/v2/market-data/sources")
        try:
            assert entered.wait(timeout=5)
            client.portal.call(app.state.local_read_ingress.withdraw)
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 401
        assert app.state.local_read_ingress.configuration.authority is original.authority
    assert calls == []


def test_changed_source_refresh_suppresses_inflight_old_http_release(tmp_path: Path) -> None:
    entered, release = Event(), Event()
    app, _, _ = _app(tmp_path, source_reader=lambda: (replace(_source(), integration_revision_fingerprint="b" * 64),))

    @app.get("/api/v2/market/instruments")
    def blocked_query(request: Request):
        session = only_request_read_session(request.scope)
        assert session is not None
        session.check_active()
        entered.set()
        assert release.wait(timeout=5)
        return {"private_old_source_data": True}

    # _app mounts Shipping assets last; the additional technical route belongs
    # before that catch-all, just like the real Product router composition.
    app.router.routes.insert(0, app.router.routes.pop())

    with TestClient(app, base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as executor:
        client.get("/", headers=NAVIGATION)
        future = executor.submit(client.get, "/api/v2/market/instruments")
        try:
            assert entered.wait(timeout=5)
            assert client.get("/api/v2/market-data/sources").status_code == 200
        finally:
            release.set()
        response = future.result(timeout=5)
        assert response.status_code == 401 and "private_old_source_data" not in response.text


def test_guarded_navigation_establishes_stable_host_only_session_without_manual_credentials(tmp_path: Path) -> None:
    app, _, calls = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v2/market-data/sources").status_code == 401
        response = client.get("/", headers=NAVIGATION)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/" in cookie
        assert "Domain=" not in cookie and "Expires=" not in cookie and "Max-Age=" not in cookie
        token = client.cookies.get(DEV_COOKIE)
        assert token and token not in response.text
        assert client.get("/", headers=NAVIGATION).headers["set-cookie"] == cookie
        for path in ("/api/v2/market-data/sources", "/api/v2/chart/studies/capabilities"):
            assert client.get(path).json() == {"authenticated": True}
        assert client.post("/api/v2/chart/studies/evaluate", json={}, headers={"Origin": ORIGIN}).status_code == 200
        assert client.post("/api/v2/chart/studies/evaluate", json={}).status_code == 403
        assert client.post("/api/v2/integrations", json={}, headers={"Origin": ORIGIN}).status_code == 200
    assert calls == ["query", "query", "query", "configuration"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example:5173"},
        {"Host": "127.0.0.1:8000"},
        {"Origin": "http://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-User": "local-developer"},
    ],
)
def test_foreign_host_origin_and_forwarded_identity_cannot_issue_or_use_session(tmp_path: Path, headers) -> None:
    app, _, calls = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/", headers={**NAVIGATION, **headers})
        assert response.status_code == 403 and "set-cookie" not in response.headers
        client.get("/", headers=NAVIGATION)
        assert client.get("/api/v2/market-data/sources", headers=headers).status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "cookie",
    ["", "other=value", f"{DEV_COOKIE}=bad", f"{DEV_COOKIE}=" + "00" * 32, f"{DEV_COOKIE}=bad; {DEV_COOKIE}=other"],
)
def test_missing_malformed_wrong_and_duplicate_cookie_are_unauthorized(tmp_path: Path, cookie: str) -> None:
    app, _, calls = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v2/market-data/sources", headers={"Cookie": cookie}).status_code == 401
    assert calls == []


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v2/market-data/acquisitions", "POST"),
        ("/api/v2/research/runs", "POST"),
        ("/api/v2/agent/status", "GET"),
        ("/api/v2/agents/status", "GET"),
        ("/internal/v1/agent-provider-runtime/admit-new", "POST"),
        ("/api/v2/strategies/promotions", "POST"),
        ("/api/v2/trading/orders", "POST"),
        ("/api/v2/live/activate", "POST"),
    ],
)
def test_source_session_never_becomes_acquisition_agent_or_live_command_permission(
    tmp_path: Path, path: str, method: str
) -> None:
    app, _, calls = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        assert client.request(method, path, headers={"Origin": ORIGIN}).status_code == 403
    assert calls == []


def test_conflicting_cookie_bearer_and_old_process_session_are_denied(tmp_path: Path) -> None:
    app, configuration, calls = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        token = client.cookies.get(DEV_COOKIE)
        assert token is not None
        assert (
            client.get("/api/v2/market-data/sources", headers={"Authorization": "Bearer " + token}).status_code == 401
        )
        configuration.authority.withdraw()
        assert client.get("/api/v2/market-data/sources").status_code == 401
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    other, _, _ = _app(replacement)
    with TestClient(other, base_url=ORIGIN) as client:
        assert client.get("/api/v2/market-data/sources", headers={"Cookie": f"{DEV_COOKIE}={token}"}).status_code == 401
    assert calls == []


def test_source_and_private_paths_are_not_served_as_shipping_assets(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        for path in ("/.git/config", "/.env", "/test-results/secret", "/..%2Fweb-private.txt"):
            response = client.get(path)
            assert response.status_code == 404 and "NOT_AN_ASSET" not in response.text


def test_cookie_websocket_uses_existing_single_subscribe_and_source_permission(tmp_path: Path) -> None:
    service = _StreamService()
    closed = Event()
    original_close = service.session.close

    def close() -> None:
        original_close()
        closed.set()

    service.session.close = close
    app, _, _ = _app(tmp_path, service)
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        with client.websocket_connect(
            "ws://127.0.0.1:5173/api/v2/market-data/stream", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json(_subscribe())
            assert socket.receive_json()["event"] == "SUBSCRIBED"
            assert service.session.waiting.wait(timeout=5)
        assert closed.wait(timeout=5)
        assert service.session.closed == 1
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1:5173/api/v2/market-data/stream", headers={"Origin": "http://evil.example"}
            ):
                pass
    assert service.opened == 1


@pytest.mark.parametrize("withdraw_process", [False, True])
def test_changed_dev_grants_close_blocked_old_stream_then_allow_fresh_same_cookie_connection(
    tmp_path: Path, withdraw_process: bool
) -> None:
    service = _StreamService()
    closing, allow_close, blocked = Event(), Event(), Event()
    original_close = service.session.close
    original_next = service.session.next_event

    def next_event():
        if service.session.events.empty():
            blocked.set()
        return original_next()

    def close():
        closing.set()
        try:
            assert allow_close.wait(timeout=5)
        finally:
            original_close()

    service.session.close = close
    service.session.next_event = next_event
    app, _, _ = _app(
        tmp_path,
        service,
        source_reader=lambda: (
            _source(),
            replace(_source(), integration_id="second-integration", source_id="second-source"),
        ),
    )
    with TestClient(app, base_url=ORIGIN) as client:
        client.get("/", headers=NAVIGATION)
        with client.websocket_connect(
            "ws://127.0.0.1:5173/api/v2/market-data/stream", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json(_subscribe())
            assert socket.receive_json()["event"] == "SUBSCRIBED"
            assert blocked.wait(timeout=5)
            assert client.get("/api/v2/market-data/sources").status_code == 200
            try:
                assert closing.wait(timeout=5)
                ingress = app.state.local_read_ingress
                assert ingress._streams == 1
                assert not ingress.withdrawn.is_set()
                if withdraw_process:
                    client.portal.call(ingress.withdraw)
                    assert ingress._streams == 1
            finally:
                allow_close.set()
            message = socket.receive()
            assert message["type"] == "websocket.close" and message["code"] == (1008 if withdraw_process else 1012)
        assert service.session.closed == 1
        if withdraw_process:
            assert client.get("/api/v2/market-data/sources").status_code == 401
            return
        service.session = _Session()
        with client.websocket_connect(
            "ws://127.0.0.1:5173/api/v2/market-data/stream", headers={"Origin": ORIGIN}
        ) as socket:
            socket.send_json(_subscribe())
            assert socket.receive_json()["event"] == "SUBSCRIBED"
        assert service.opened == 2


def test_duplicate_transport_headers_never_dispatch() -> None:
    async def scenario() -> None:
        configuration, _ = only_dev_web_configuration(ORIGIN, ())
        calls = []
        messages = []

        async def owning(scope, receive, send):
            calls.append(scope)

        async def receive():
            raise AssertionError("Must refuse before body or Source IO")

        async def send(message):
            messages.append(message)

        ingress = OnlyDevWebIngress(owning, configuration)
        for headers in (
            [(b"host", b"127.0.0.1:5173")] * 2,
            [(b"host", b"127.0.0.1:5173"), (b"origin", ORIGIN.encode()), (b"origin", ORIGIN.encode())],
            [(b"host", b"127.0.0.1:5173"), (b"cookie", b"other=x"), (b"cookie", b"other=y")],
        ):
            await ingress(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v2/market-data/sources",
                    "headers": headers,
                    "query_string": b"",
                },
                receive,
                send,
            )
        assert calls == []
        assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [403, 403, 401]

    asyncio.run(scenario())


def test_cookie_query_withdrawal_suppresses_release_and_retains_capacity_until_cleanup() -> None:
    async def scenario() -> None:
        configuration, credential = only_dev_web_configuration(ORIGIN, ())
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        incoming = asyncio.Queue()
        await incoming.put({"type": "http.request", "body": b"{}", "more_body": False})

        async def owning(scope, receive, send):
            assert only_request_read_session(scope) is not None
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"PROTECTED_VALUE"})

        async def send(message):
            messages.append(message)

        ingress = OnlyDevWebIngress(owning, configuration, chart_study_enabled=True)
        task = asyncio.create_task(
            ingress(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/api/v2/chart/studies/evaluate",
                    "query_string": b"",
                    "headers": [
                        (b"host", b"127.0.0.1:5173"),
                        (b"origin", ORIGIN.encode()),
                        (b"cookie", f"{DEV_COOKIE}={credential}".encode()),
                        (b"content-type", b"application/json"),
                        (b"content-length", b"2"),
                    ],
                },
                incoming.get,
                send,
            )
        )
        await entered.wait()
        assert ingress._reads == 1
        await ingress.withdraw()
        assert ingress._reads == 1 and not task.done()
        release.set()
        await task
        assert ingress._reads == 0
        assert [m["status"] for m in messages if m["type"] == "http.response.start"] == [401]
        assert b"PROTECTED_VALUE" not in b"".join(m.get("body", b"") for m in messages)

    asyncio.run(scenario())
