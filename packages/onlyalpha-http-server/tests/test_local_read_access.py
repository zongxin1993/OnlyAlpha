from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from queue import Queue
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.local_read_access import (
    OnlyLocalReadConfiguration,
    OnlyLocalReadIngress,
    only_load_local_read_configuration,
)
from onlyalpha_http_server.market_data import create_market_data_stream_router
from starlette.websockets import WebSocketDisconnect

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1, OnlyMarketDataSourceSelectionV1
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamEventV1
from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadAuthority,
    OnlySourceReadGrant,
    OnlySourceReadPermission,
)
from onlyalpha.domain.market import OnlyBarSemantic

TOKEN = "ee" * 32
ORIGIN = "http://localhost"
# Starlette resolves relative WS URLs against ws://testserver, not base_url.
STREAM_URL = "ws://localhost/api/v2/market-data/stream"
REFERENCE = OnlyMarketDataSourceReferenceV1("integration", "a" * 64, "test.market_data")


def _configuration(*, realtime: bool = True) -> OnlyLocalReadConfiguration:
    permissions = (OnlySourceReadPermission.CLOSED_HISTORY,)
    if realtime:
        permissions += (OnlySourceReadPermission.REALTIME_PREVIEW,)
    return OnlyLocalReadConfiguration(
        OnlySourceReadAuthority(
            "operator",
            hashlib.sha256(TOKEN.encode()).hexdigest(),
            (OnlySourceReadGrant("integration", "a" * 64, "test.market_data", "test.source", "LIVE", permissions),),
        ),
        ORIGIN,
    )


def _document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "subject_id": "operator",
        "bearer_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(),
        "origin": ORIGIN,
        "grants": [
            {
                "integration_id": "integration",
                "integration_revision_fingerprint": "a" * 64,
                "expected_type_id": "test.market_data",
                "source_id": "test.source",
                "environment": "LIVE",
                "permissions": ["CLOSED_HISTORY", "REALTIME_PREVIEW"],
            }
        ],
    }


def _write(tmp_path: Path, document: object) -> Path:
    path = tmp_path.resolve() / "read-access.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    return path


def test_private_startup_configuration_is_frozen_and_rejects_agent_credential(tmp_path: Path) -> None:
    path = _write(tmp_path, _document())
    config = only_load_local_read_configuration(path)
    path.write_text("{}")
    path.chmod(0o644)
    config.authority.authenticate("Bearer " + TOKEN).require_reference(
        REFERENCE, OnlySourceReadPermission.CLOSED_HISTORY
    )
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID"):
        only_load_local_read_configuration(path)
    path = _write(tmp_path, _document())
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID") as error:
        only_load_local_read_configuration(path, excluded_credentials=(TOKEN,))
    assert TOKEN not in str(error.value) and str(path) not in str(error.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "bool-version",
        "digest",
        "empty-grants",
        "duplicate-grant",
        "wildcard",
        "scope",
        "origin",
        "oversized",
    ],
)
def test_invalid_configuration_never_falls_back_to_anonymous(tmp_path: Path, mutation: str) -> None:
    document = _document()
    if mutation == "extra":
        document["extra"] = True
    elif mutation == "missing":
        del document["subject_id"]
    elif mutation == "bool-version":
        document["schema_version"] = True
    elif mutation == "digest":
        document["bearer_sha256"] = "bad"
    elif mutation == "empty-grants":
        document["grants"] = []
    elif mutation == "duplicate-grant":
        document["grants"] *= 2
    elif mutation == "wildcard":
        document["grants"][0]["source_id"] = "*"
    elif mutation == "scope":
        document["grants"][0]["permissions"] = ["ACQUIRE"]
    elif mutation == "origin":
        document["origin"] = "http://192.168.1.1"
    elif mutation == "oversized":
        document["subject_id"] = "x" * 33000
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID"):
        only_load_local_read_configuration(_write(tmp_path, document))


def test_symlink_duplicate_keys_and_world_readable_config_are_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _document())
    link = tmp_path.resolve() / "link"
    link.symlink_to(path)
    with pytest.raises(OnlySourceReadAccessError):
        only_load_local_read_configuration(link)
    parent_link = tmp_path.resolve() / "parent-link"
    parent_link.symlink_to(tmp_path.resolve(), target_is_directory=True)
    with pytest.raises(OnlySourceReadAccessError):
        only_load_local_read_configuration(parent_link / path.name)
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(OnlySourceReadAccessError):
        only_load_local_read_configuration(path)
    path = _write(tmp_path, _document())
    path.chmod(0o644)
    with pytest.raises(OnlySourceReadAccessError):
        only_load_local_read_configuration(path)


class _Session:
    source_id = "test.source"

    def __init__(self) -> None:
        self.events: Queue[OnlyMarketDataStreamEventV1] = Queue()
        self.events.put(
            OnlyMarketDataStreamEventV1(
                "SUBSCRIBED",
                {
                    "stream_id": "s",
                    "source_id": self.source_id,
                    "instrument_id": "BTCUSDT.TEST",
                    "resolution_mode": "PROVIDER_NATIVE",
                    "resolution_plan_fingerprint": "a" * 64,
                    "cursor_bar_stride_minutes": 15,
                },
            )
        )
        self.closed = 0
        self.waiting = Event()

    def next_event(self) -> OnlyMarketDataStreamEventV1:
        self.waiting.set()
        return self.events.get()

    def close(self) -> None:
        self.closed += 1
        self.events.put(OnlyMarketDataStreamEventV1("STATE", {"state": "CLOSED"}))


class _StreamService:
    def __init__(self) -> None:
        self.opened = 0
        self.session = _Session()
        self.entered = Event()
        self.release: Event | None = None

    def open(self, reference, *, read_session, **kwargs):
        read_session.require_reference(reference, OnlySourceReadPermission.REALTIME_PREVIEW)
        read_session.require_selection(
            OnlyMarketDataSourceSelectionV1("integration", "a" * 64, "test.market_data", "test.source", "LIVE"),
            OnlySourceReadPermission.REALTIME_PREVIEW,
        )
        self.opened += 1
        self.entered.set()
        if self.release is not None:
            self.release.wait()
        return self.session


def _app(config: OnlyLocalReadConfiguration, stream: _StreamService | None = None) -> tuple[FastAPI, list[str]]:
    app = FastAPI()
    calls: list[str] = []

    @app.get("/api/v2/market-data/sources")
    def sources():
        calls.append("sources")
        return {"protected": "value"}

    @app.post("/api/v2/market-data/acquisitions")
    @app.post("/api/v2/research/runs")
    @app.get("/api/v2/artifact-alias")
    def alias():
        calls.append("alias")
        return {"protected": "alias"}

    if stream is not None:
        app.include_router(create_market_data_stream_router(stream))
    app.add_middleware(OnlyLocalReadIngress, configuration=config)
    return app, calls


@pytest.mark.parametrize("header", [None, "Bearer bad", "Bearer " + "00" * 32, "Bearer " + "a" * 5000])
def test_http_rejects_before_dispatch_without_disclosing_private_facts(header: str | None) -> None:
    app, calls = _app(_configuration())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get(
            "/api/v2/market-data/sources", headers={} if header is None else {"Authorization": header}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "LOCAL_READ_UNAUTHORIZED"
        assert "protected" not in response.text and TOKEN not in response.text
    assert calls == []


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v2/market-data/acquisitions", "POST"),
        ("/api/v2/research/runs", "POST"),
        ("/api/v2/artifact-alias", "GET"),
        ("/api/v2/integrations", "GET"),
        ("/internal/v1/agent-provider-runtime/admit-new", "POST"),
        ("/docs", "GET"),
        ("/api/v2/market-data/sources/", "GET"),
        ("/health/other", "GET"),
    ],
)
@pytest.mark.parametrize("bearer", [False, True])
def test_read_ingress_denies_all_aliases_commands_and_redirects_with_or_without_bearer(
    path: str, method: str, bearer: bool
) -> None:
    app, calls = _app(_configuration())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.request(method, path, headers={"Authorization": "Bearer " + TOKEN} if bearer else {})
        assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "null"},
        {"Origin": "https://evil.example"},
        {"X-User": "operator"},
        {"Forwarded": "for=127.0.0.1"},
        {"X-Forwarded-Proto": "https"},
    ],
)
def test_origin_and_identity_headers_are_not_authority(headers: dict[str, str]) -> None:
    app, calls = _app(_configuration())
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/api/v2/market-data/sources", headers={"Authorization": "Bearer " + TOKEN, **headers})
        assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "path,scope_type",
    [
        ("/api/v2/market-data/sources", "http"),
        ("/api/v2/market/instruments", "http"),
        ("/api/v2/market-data/bars", "http"),
        ("/api/v2/market-data/acquisitions/owned", "http"),
        ("/api/v2/market-data/stream", "websocket"),
    ],
)
@pytest.mark.parametrize(
    "hosts", [[], [b"evil.example"], [b"127.0.0.1"], [b"localhost:8000"], [b"localhost", b"localhost"]]
)
def test_every_owning_read_rejects_missing_wrong_or_duplicate_host_before_dispatch(
    path: str, scope_type: str, hosts: list[bytes]
) -> None:
    async def scenario() -> None:
        calls = []
        messages = []

        async def owning(scope, receive, send):
            calls.append(scope)

        async def receive():
            raise AssertionError("Rejected Host must not consume credentials or body")

        async def send(message):
            messages.append(message)

        scope = {
            "type": scope_type,
            "method": "GET",
            "path": path,
            "headers": [(b"host", host) for host in hosts]
            + [(b"origin", ORIGIN.encode()), (b"authorization", ("Bearer " + TOKEN).encode())],
            "query_string": b"",
        }
        ingress = OnlyLocalReadIngress(owning, _configuration())
        await ingress(scope, receive, send)
        assert calls == [] and ingress._reads == 0 and ingress._streams == 0
        if scope_type == "websocket":
            assert messages == [{"type": "websocket.close", "code": 1008}]
        else:
            assert messages[0]["status"] == 403
            assert (b"cache-control", b"no-store") in messages[0]["headers"]

    asyncio.run(scenario())


def _subscribe() -> dict[str, object]:
    return {
        "schema_version": 2,
        "operation": "SUBSCRIBE_BAR",
        "source_reference": {
            "integration_id": "integration",
            "integration_revision_fingerprint": "a" * 64,
            "expected_type_id": "test.market_data",
        },
        "instrument_id": "BTCUSDT.TEST",
        "bar_semantic": OnlyBarSemantic.fixed_duration(15).to_dict(),
        "resume_after_sequence": "0",
    }


@pytest.mark.parametrize("origin", [None, "null", "http://evil.example"])
def test_ws_origin_is_checked_before_upgrade_and_source_open(origin: str | None) -> None:
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(STREAM_URL, headers={} if origin is None else {"Origin": origin}):
                pass
    assert service.opened == 0


@pytest.mark.parametrize(
    "first", ["subscribe", "wrong-token", "extra-subject", "bool-version", "oversized", "duplicate", "binary"]
)
def test_ws_auth_failure_never_opens_source(first: str) -> None:
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    auth = {"schema_version": 1, "operation": "AUTH", "bearer": TOKEN}
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            if first == "subscribe":
                socket.send_json(_subscribe())
            elif first == "oversized":
                socket.send_text("x" * 4097)
            elif first == "duplicate":
                socket.send_text(json.dumps(auth)[:-1] + ',"schema_version":1}')
            elif first == "binary":
                socket.send_bytes(b"auth")
            else:
                if first == "wrong-token":
                    auth["bearer"] = "00" * 32
                elif first == "extra-subject":
                    auth["subject"] = "operator"
                elif first == "bool-version":
                    auth["schema_version"] = True
                socket.send_json(auth)
            message = socket.receive()
            assert message["type"] == "websocket.close"
    assert service.opened == 0


def test_ws_exact_grant_and_withdrawal_close_blocked_event_without_late_data() -> None:
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            socket.send_json({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN})
            assert socket.receive_json() == {"schema_version": 1, "event": "AUTHENTICATED"}
            assert service.opened == 0
            socket.send_json(_subscribe())
            assert socket.receive_json()["event"] == "SUBSCRIBED"
            client.portal.call(app.state.local_read_ingress.withdraw)
            assert socket.receive()["type"] == "websocket.close"
    assert service.opened == 1 and service.session.closed == 1


def test_historical_only_grant_never_opens_realtime_source() -> None:
    service = _StreamService()
    app, _ = _app(_configuration(realtime=False), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            socket.send_json({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN})
            socket.receive_json()
            socket.send_json(_subscribe())
            assert socket.receive()["type"] == "websocket.close"
    assert service.opened == 0


def test_withdrawal_during_blocked_open_retains_slot_until_actual_cleanup() -> None:
    service = _StreamService()
    service.release = Event()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            socket.send_json({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN})
            socket.receive_json()
            socket.send_json(_subscribe())
            assert service.entered.wait(5), "controlled open barrier was not reached"
            ingress = app.state.local_read_ingress
            client.portal.call(ingress.withdraw)
            assert ingress._streams == 1
            service.release.set()
            assert socket.receive()["type"] == "websocket.close"
    assert service.session.closed == 1


def test_http_release_cutoff_and_capacity_use_deterministic_barriers() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def owning(scope, receive, send):
            nonlocal calls
            calls += 1
            if calls == 4:
                entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"protected"})

        ingress = OnlyLocalReadIngress(owning, _configuration())
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {"type": "http.request", "body": b""}

        def scope():
            return {
                "type": "http",
                "method": "GET",
                "path": "/api/v2/market-data/sources",
                "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + TOKEN).encode())],
                "query_string": b"",
            }

        tasks = [asyncio.create_task(ingress(scope(), receive, send)) for _ in range(4)]
        await entered.wait()
        await ingress(scope(), receive, send)
        assert calls == 4 and ingress._reads == 4
        assert any(m.get("status") == 429 for m in messages)
        await ingress.withdraw()
        release.set()
        await asyncio.gather(*tasks)
        assert not any(m.get("body") == b"protected" for m in messages)
        assert ingress._reads == 0

    asyncio.run(scenario())


def test_cancelled_http_callers_do_not_release_actual_worker_capacity() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = Event()
        messages = []
        calls = 0

        async def owning(scope, receive, send):
            nonlocal calls
            calls += 1
            if calls == 4:
                entered.set()
            await asyncio.to_thread(release.wait)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"protected"})

        ingress = OnlyLocalReadIngress(owning, _configuration())

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        def scope():
            return {
                "type": "http",
                "method": "GET",
                "path": "/api/v2/market-data/sources",
                "query_string": b"",
                "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + TOKEN).encode())],
            }

        callers = [asyncio.create_task(ingress(scope(), receive, send)) for _ in range(4)]
        await entered.wait()
        for caller in callers:
            caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
        assert ingress._reads == 4 and len(ingress._work) == 4
        await ingress(scope(), receive, send)
        assert messages[0]["status"] == 429 and calls == 4
        owners = tuple(ingress._work)
        release.set()
        await asyncio.gather(*owners)
        assert ingress._reads == 0
        assert not any(message.get("body") == b"protected" for message in messages)

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_phase", ["open", "close"])
def test_cancelled_ws_caller_retains_late_open_cleanup_and_close_owner(blocked_phase: str) -> None:
    async def scenario() -> None:
        service = _StreamService()
        entered = Event()
        release = Event()
        if blocked_phase == "open":
            service.release = release
            entered = service.entered
        else:
            original_close = service.session.close

            def close():
                entered.set()
                release.wait()
                original_close()

            service.session.close = close
        app, _ = _app(_configuration(), service)
        incoming: asyncio.Queue = asyncio.Queue()
        outgoing: asyncio.Queue = asyncio.Queue()

        async def receive():
            return await incoming.get()

        async def send(message):
            await outgoing.put(message)

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": "/api/v2/market-data/stream",
            "raw_path": b"/api/v2/market-data/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost"), (b"origin", ORIGIN.encode())],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8000),
            "subprotocols": [],
        }
        incoming.put_nowait({"type": "websocket.connect"})
        caller = asyncio.create_task(app(scope, receive, send))
        assert (await outgoing.get())["type"] == "websocket.accept"
        incoming.put_nowait(
            {
                "type": "websocket.receive",
                "text": json.dumps({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN}),
            }
        )
        assert json.loads((await outgoing.get())["text"])["event"] == "AUTHENTICATED"
        incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(_subscribe())})
        if blocked_phase == "close":
            assert json.loads((await outgoing.get())["text"])["event"] == "SUBSCRIBED"
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        assert await asyncio.to_thread(entered.wait, 5)
        ingress = app.state.local_read_ingress
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        assert ingress._streams == 1 and len(ingress._work) == 1
        owners = tuple(ingress._work)
        release.set()
        await asyncio.gather(*owners)
        assert service.session.closed == 1 and ingress._streams == 0
        assert not any(message.get("text") and "BAR_" in message["text"] for message in list(outgoing._queue))

    asyncio.run(scenario())


def test_get_body_frames_are_denied_even_without_framing_headers() -> None:
    async def scenario() -> None:
        calls = []
        messages = []

        async def owning(scope, receive, send):
            calls.append(scope)

        async def receive():
            return {"type": "http.request", "body": b"untrusted"}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/market-data/sources",
            "query_string": b"",
            "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + TOKEN).encode())],
        }
        await OnlyLocalReadIngress(owning, _configuration())(scope, receive, send)
        assert calls == [] and messages[0]["status"] == 403

    asyncio.run(scenario())


def test_writable_ancestor_cannot_substitute_private_configuration(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    path = _write(unsafe, _document())
    unsafe.chmod(0o777)
    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_CONFIG_INVALID"):
        only_load_local_read_configuration(path)


def test_detachment_while_response_headers_block_never_releases_protected_body() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        messages = []

        async def owning(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"protected"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            if message["type"] == "http.response.start":
                started.set()
                await release.wait()
            messages.append(message)

        ingress = OnlyLocalReadIngress(owning, _configuration())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/market-data/sources",
            "query_string": b"",
            "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + TOKEN).encode())],
        }
        caller = asyncio.create_task(ingress(scope, receive, send))
        await started.wait()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        assert ingress._reads == 1
        owners = tuple(ingress._work)
        release.set()
        await asyncio.gather(*owners)
        assert ingress._reads == 0
        assert not any(message.get("body") == b"protected" for message in messages)

    asyncio.run(scenario())


def test_cancelled_inventory_observer_cannot_cancel_actual_work_owner() -> None:
    from tests.runtime_support.local_read_browser import wait_for_read_cleanup

    async def scenario() -> None:
        entered = asyncio.Event()
        release = Event()
        messages = []

        async def owning(scope, receive, send):
            entered.set()
            await asyncio.to_thread(release.wait)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"protected"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        ingress = OnlyLocalReadIngress(owning, _configuration())
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v2/market-data/sources",
            "query_string": b"",
            "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + TOKEN).encode())],
        }
        caller = asyncio.create_task(ingress(scope, receive, send))
        await entered.wait()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        observer_entered = asyncio.Event()

        async def observe():
            observer_entered.set()
            await wait_for_read_cleanup(ingress)

        observer = asyncio.create_task(observe())
        await observer_entered.wait()
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
        assert ingress._reads == 1 and len(ingress._work) == 1
        assert not next(iter(ingress._work)).cancelled()
        owners = tuple(ingress._work)
        release.set()
        await asyncio.gather(*owners)
        assert ingress._reads == 0 and messages == []

    asyncio.run(scenario())


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "192.168.1.1"])
def test_configured_cli_rejects_unproved_binding_before_product_composition(tmp_path: Path, host: str) -> None:
    from onlyalpha_http_server.main import main

    with pytest.raises(OnlySourceReadAccessError, match="LOCAL_READ_TRANSPORT_NOT_ADMITTED"):
        main(
            [
                "--user-data-root",
                str(tmp_path),
                "--host",
                host,
                "--local-read-auth-config",
                str(tmp_path / "missing.json"),
            ]
        )
    assert tuple(tmp_path.iterdir()) == ()


def test_four_unauthenticated_ws_slots_are_bounded_and_disconnect_releases_them() -> None:
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with ExitStack() as stack:
            for _ in range(4):
                stack.enter_context(client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}))
            assert app.state.local_read_ingress._streams == 4
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}):
                    pass
    assert service.opened == 0


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("integration_id", "different"),
        ("integration_revision_fingerprint", "b" * 64),
        ("expected_type_id", "different.type"),
    ],
)
def test_ws_authenticated_subject_does_not_authorize_wrong_nested_reference(dimension: str, value: str) -> None:
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            socket.send_json({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN})
            assert socket.receive_json()["event"] == "AUTHENTICATED"
            subscribe = _subscribe()
            subscribe["source_reference"][dimension] = value
            socket.send_json(subscribe)
            assert socket.receive()["type"] == "websocket.close"
    assert service.opened == 0


@pytest.mark.parametrize("phase", ["auth", "subscribe"])
def test_handshake_deadline_fault_rejects_each_phase_before_source_open(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    from onlyalpha_http_server.market_data import stream_routes

    original = stream_routes._control_text
    calls = 0

    async def controlled_deadline(websocket):
        nonlocal calls
        calls += 1
        if calls == (1 if phase == "auth" else 2):
            monkeypatch.setattr(stream_routes, "HANDSHAKE_SECONDS", 0)
        return await original(websocket)

    monkeypatch.setattr(stream_routes, "_control_text", controlled_deadline)
    service = _StreamService()
    app, _ = _app(_configuration(), service)
    with TestClient(app, base_url=ORIGIN) as client:
        with client.websocket_connect(STREAM_URL, headers={"Origin": ORIGIN}) as socket:
            if phase == "subscribe":
                socket.send_json({"schema_version": 1, "operation": "AUTH", "bearer": TOKEN})
                assert socket.receive_json()["event"] == "AUTHENTICATED"
            assert socket.receive()["type"] == "websocket.close"
    assert service.opened == 0 and app.state.local_read_ingress._streams == 0
