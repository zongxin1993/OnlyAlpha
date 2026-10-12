"""Private startup configuration and deny-by-default local read ingress."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import stat
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadAuthority,
    OnlySourceReadGrant,
    OnlySourceReadPermission,
    OnlySourceReadSession,
)

MAX_CONTROL_BYTES = 4096
HANDSHAKE_SECONDS = 5
MAX_READS = 4
MAX_STREAMS = 4
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_READ_PATHS = frozenset({"/api/v2/market-data/sources", "/api/v2/market/instruments", "/api/v2/market-data/bars"})
_HEALTH_PATHS = frozenset({"/health/live", "/health/ready"})
MAX_CHART_QUERY_BYTES = 64 * 1024
CHART_QUERY_SECONDS = 10
CHART_CAPABILITIES_PATH = "/api/v2/chart/studies/capabilities"
CHART_EVALUATE_PATH = "/api/v2/chart/studies/evaluate"


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError
    return dict(pairs)


def only_decode_local_control(text: str) -> object:
    if len(text.encode("utf-8")) > MAX_CONTROL_BYTES:
        raise ValueError("LOCAL_READ_CONTROL_INVALID")
    return json.loads(text, object_pairs_hook=_strict_object)


@dataclass(frozen=True, slots=True, repr=False)
class OnlyLocalReadConfiguration:
    authority: OnlySourceReadAuthority
    origin: str


def only_load_local_read_configuration(
    path: Path, *, excluded_credentials: tuple[str, ...] = ()
) -> OnlyLocalReadConfiguration:
    """Walk using O_NOFOLLOW descriptors; never fall back to anonymous mode on error."""
    descriptors: list[int] = []
    try:
        if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
            raise ValueError
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(descriptor)
        _require_trusted_directory(os.fstat(descriptor))
        for part in path.parts[1:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
            _require_trusted_directory(os.fstat(descriptor))
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in {0, os.geteuid()}
            or metadata.st_mode & 0o077
            or metadata.st_nlink != 1
            or not 0 < metadata.st_size <= 32768
        ):
            raise ValueError
        data = os.read(descriptor, 32769)
        if len(data) > 32768:
            raise ValueError
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "subject_id", "bearer_sha256", "origin", "grants"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or not isinstance(payload["grants"], list)
            or not 1 <= len(payload["grants"]) <= 32
        ):
            raise ValueError
        origin = payload["origin"]
        if not isinstance(origin, str):
            raise ValueError
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or len(origin) > 256
        ):
            raise ValueError
        _ = parsed.port
        grants = []
        for item in payload["grants"]:
            if (
                not isinstance(item, dict)
                or set(item)
                != {
                    "integration_id",
                    "integration_revision_fingerprint",
                    "expected_type_id",
                    "source_id",
                    "environment",
                    "permissions",
                }
                or not isinstance(item["permissions"], list)
            ):
                raise ValueError
            grants.append(
                OnlySourceReadGrant(
                    item["integration_id"],
                    item["integration_revision_fingerprint"],
                    item["expected_type_id"],
                    item["source_id"],
                    item["environment"],
                    tuple(OnlySourceReadPermission(p) for p in item["permissions"]),
                )
            )
        digest = payload["bearer_sha256"]
        if any(hashlib.sha256(value.encode("utf-8")).hexdigest() == digest for value in excluded_credentials if value):
            raise ValueError
        authority = OnlySourceReadAuthority(payload["subject_id"], digest, tuple(grants))
        return OnlyLocalReadConfiguration(authority, origin)
    except (OSError, ValueError, TypeError, KeyError):
        raise OnlySourceReadAccessError("LOCAL_READ_CONFIG_INVALID") from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def only_request_read_session(scope: Scope) -> OnlySourceReadSession | None:
    value = scope.get("onlyalpha.local_read_session")
    return cast(OnlySourceReadSession | None, value)


def _require_trusted_directory(metadata: os.stat_result) -> None:
    # Root-owned sticky shared roots (e.g. /tmp) protect existing owner-created entries.
    # Every descended entry must independently be root/process-owned and non-writable
    # by other users. A non-root sticky directory is not a trusted root.
    shared_root = metadata.st_uid == 0 and bool(metadata.st_mode & stat.S_ISVTX)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or (metadata.st_mode & 0o022 and not shared_root)
    ):
        raise ValueError("LOCAL_READ_CONFIG_INVALID")


class OnlyLocalReadIngress:
    """Per-process admission and send fence; external ingress withdrawal is still required."""

    def __init__(
        self, app: ASGIApp, configuration: OnlyLocalReadConfiguration, *, chart_study_enabled: bool = False
    ) -> None:
        self.app = app
        self.configuration = configuration
        self.withdrawn = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._reads = 0
        self._streams = 0
        self._work: set[asyncio.Future[None]] = set()
        self._chart_study_enabled = chart_study_enabled

    async def _retain_work(self, work: Awaitable[None], detached: asyncio.Event, *, stream: bool) -> None:
        """The work owner, not the cancellable ASGI caller, owns the capacity slot."""
        task = asyncio.ensure_future(work)
        self._work.add(task)

        def finished(completed: asyncio.Future[None]) -> None:
            self._work.remove(completed)
            if stream:
                self._streams -= 1
            else:
                self._reads -= 1
            if not completed.cancelled():
                completed.exception()  # Retrieve detached failures without logging secret-bearing stacks.

        task.add_done_callback(finished)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            detached.set()
            raise

    async def withdraw(self) -> None:
        async with self._send_lock:
            self.configuration.authority.withdraw()
            self.withdrawn.set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if "app" in scope:
            scope["app"].state.local_read_ingress = self
        if scope["type"] == "lifespan":

            async def lifespan_receive() -> Message:
                message = await receive()
                if message["type"] == "lifespan.shutdown":
                    await self.withdraw()
                return message

            await self.app(scope, lifespan_receive, send)
            return
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if scope["type"] == "http" and scope["method"] == "GET" and path in _HEALTH_PATHS:
            await self.app(scope, receive, send)
            return
        if (
            self._chart_study_enabled
            and scope["type"] == "http"
            and (
                (scope["method"] == "GET" and path == CHART_CAPABILITIES_PATH)
                or (scope["method"] == "POST" and path == CHART_EVALUATE_PATH)
            )
        ):
            await self._chart_query(scope, receive, send)
            return
        is_stream = scope["type"] == "websocket" and path == "/api/v2/market-data/stream"
        is_read = (
            scope["type"] == "http"
            and scope["method"] == "GET"
            and (path in _READ_PATHS or re.fullmatch(r"/api/v2/market-data/acquisitions/[A-Za-z0-9_:-]{1,128}", path))
        )
        if not is_read and not is_stream:
            await self._deny(scope, receive, send, "LOCAL_READ_FORBIDDEN")
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value)
        origins = headers.get(b"origin", [])
        if (
            len(origins) > 1
            or (is_stream and len(origins) != 1)
            or (origins and origins[0] != self.configuration.origin.encode("ascii"))
            or any(key in headers for key in (b"x-user", b"forwarded", b"x-forwarded-for", b"x-forwarded-proto"))
            or len(scope.get("query_string", b"")) > MAX_CONTROL_BYTES
            or (is_stream and (scope.get("query_string") or scope.get("subprotocols")))
            or headers.get(b"content-length", [b"0"]) != [b"0"]
            or b"transfer-encoding" in headers
        ):
            await self._deny(scope, receive, send, "LOCAL_READ_FORBIDDEN")
            return
        if self.withdrawn.is_set():
            await self._deny(scope, receive, send, "LOCAL_READ_UNAUTHORIZED")
            return
        if is_stream:
            if self._streams >= MAX_STREAMS:
                await self._deny(scope, receive, send, "LOCAL_READ_CAPACITY_EXCEEDED")
                return
            self._streams += 1
            scope["onlyalpha.local_read_ingress"] = self
            detached = asyncio.Event()
            scope["onlyalpha.local_read_detached"] = detached

            async def fenced_send(message: Message) -> None:
                if message["type"] == "websocket.send" and only_request_read_session(scope) is not None:
                    async with self._send_lock:
                        if detached.is_set():
                            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
                        session = only_request_read_session(scope)
                        assert session is not None
                        session.check_active()
                        await asyncio.wait_for(send(message), HANDSHAKE_SECONDS)
                else:
                    await send(message)

            await self._retain_work(self.app(scope, receive, fenced_send), detached, stream=True)
            return
        try:
            values = headers.get(b"authorization", [])
            if len(values) != 1:
                raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
            session = self.configuration.authority.authenticate(values[0].decode("ascii"))
        except (OnlySourceReadAccessError, UnicodeError):
            await self._deny(scope, receive, send, "LOCAL_READ_UNAUTHORIZED")
            return
        if self._reads >= MAX_READS:
            await self._deny(scope, receive, send, "LOCAL_READ_CAPACITY_EXCEEDED")
            return
        self._reads += 1
        scope["onlyalpha.local_read_session"] = session
        detached = asyncio.Event()
        start: Message | None = None
        body = bytearray()

        async def capture(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if len(body) > _MAX_RESPONSE_BYTES:
                    raise OnlySourceReadAccessError("LOCAL_READ_RESPONSE_UNAVAILABLE")

        async def work() -> None:
            try:
                first = await asyncio.wait_for(receive(), HANDSHAKE_SECONDS)
                if first["type"] != "http.request" or first.get("body") or first.get("more_body", False):
                    raise OnlySourceReadAccessError("LOCAL_READ_FORBIDDEN")
                await self.app(scope, receive, capture)
                async with self._send_lock:
                    if detached.is_set():
                        return
                    session.check_active()
                    if start is None:
                        raise OnlySourceReadAccessError("LOCAL_READ_RESPONSE_UNAVAILABLE")

                    async def release() -> None:
                        await send(start)
                        if detached.is_set():
                            return
                        session.check_active()
                        await send({"type": "http.response.body", "body": bytes(body)})

                    await asyncio.wait_for(release(), HANDSHAKE_SECONDS)
            except OnlySourceReadAccessError as error:
                if not detached.is_set():
                    await self._deny(scope, receive, send, error.code)
            except TimeoutError:
                if not detached.is_set():
                    await self._deny(scope, receive, send, "LOCAL_READ_RESPONSE_UNAVAILABLE")

        await self._retain_work(work(), detached, stream=False)

    async def _chart_query(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Exact bounded POST Query exception; other protected paths retain their rules.

        A single receiver collects the framed body before watching disconnect. The
        retained ASGI owner is not cancelled on deadline, so its synchronous read/
        computation and capacity accounting survive caller disappearance.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CHART_QUERY_SECONDS
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value)
        post = scope["method"] == "POST"
        lengths = headers.get(b"content-length", [b"0"] if not post else [])
        origins = headers.get(b"origin", [])
        if (
            headers.get(b"host") != [urlsplit(self.configuration.origin).netloc.encode("ascii")]
            or len(origins) > 1
            or (origins and origins != [self.configuration.origin.encode("ascii")])
            or any(key in headers for key in (b"x-user", b"forwarded", b"x-forwarded-for", b"x-forwarded-proto"))
            or scope.get("query_string")
            or b"transfer-encoding" in headers
            or len(lengths) != 1
            or re.fullmatch(rb"(?:0|[1-9][0-9]{0,5})", lengths[0]) is None
            or (post and headers.get(b"content-type") != [b"application/json"])
            or (not post and lengths != [b"0"])
        ):
            await self._deny(scope, receive, send, "LOCAL_READ_FORBIDDEN")
            return
        size = int(lengths[0])
        if size > MAX_CHART_QUERY_BYTES or (post and size == 0):
            await self._chart_error(scope, receive, send, "CHART_STUDY_REQUEST_INVALID", 400)
            return
        try:
            authorization = headers.get(b"authorization", [])
            if self.withdrawn.is_set() or len(authorization) != 1:
                raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
            session = self.configuration.authority.authenticate(authorization[0].decode("ascii"))
        except (OnlySourceReadAccessError, UnicodeError):
            await self._deny(scope, receive, send, "LOCAL_READ_UNAUTHORIZED")
            return
        if self._reads >= MAX_READS:
            await self._chart_error(scope, receive, send, "CHART_STUDY_CAPACITY_UNAVAILABLE", 503)
            return
        self._reads += 1
        scope["onlyalpha.local_read_session"] = session
        detached = asyncio.Event()
        scope["onlyalpha.local_read_detached"] = detached

        async def work() -> None:
            payload = bytearray()
            started = False
            application: asyncio.Future[None] | None = None
            watcher: asyncio.Task[None] | None = None
            try:
                while True:
                    message = await asyncio.wait_for(receive(), max(0, deadline - loop.time()))
                    if message["type"] == "http.disconnect":
                        detached.set()
                        return
                    if message["type"] != "http.request":
                        raise ValueError
                    payload.extend(message.get("body", b""))
                    if len(payload) > size or len(payload) > MAX_CHART_QUERY_BYTES:
                        raise ValueError
                    if not message.get("more_body", False):
                        break
                if len(payload) != size:
                    raise ValueError
                if post:

                    def invalid_constant(_: str) -> None:
                        raise ValueError

                    json.loads(
                        payload.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=invalid_constant
                    )
                session.check_active()
                first = True
                response_start: Message | None = None
                response_body = bytearray()

                async def replay() -> Message:
                    nonlocal first
                    if first:
                        first = False
                        return {"type": "http.request", "body": bytes(payload), "more_body": False}
                    await detached.wait()
                    return {"type": "http.disconnect"}

                async def capture(message: Message) -> None:
                    nonlocal response_start
                    if message["type"] == "http.response.start":
                        response_start = message
                    elif message["type"] == "http.response.body":
                        response_body.extend(message.get("body", b""))
                        if len(response_body) > _MAX_RESPONSE_BYTES:
                            raise OnlySourceReadAccessError("LOCAL_READ_RESPONSE_UNAVAILABLE")

                async def disconnect() -> None:
                    while not detached.is_set():
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            detached.set()
                        else:
                            # Extra body frames after the declared end are invalid.
                            detached.set()

                watcher = asyncio.create_task(disconnect())
                application = asyncio.ensure_future(self.app(scope, replay, capture))
                await asyncio.wait_for(asyncio.shield(application), max(0, deadline - loop.time()))
                async with self._send_lock:
                    if detached.is_set():
                        return
                    session.check_active()
                    if response_start is None:
                        raise OnlySourceReadAccessError("LOCAL_READ_RESPONSE_UNAVAILABLE")

                    async def release() -> None:
                        nonlocal started
                        if loop.time() >= deadline:
                            raise TimeoutError
                        started = True
                        await send(response_start)
                        session.check_active()
                        if not detached.is_set() and loop.time() < deadline:
                            await send({"type": "http.response.body", "body": bytes(response_body)})

                    await asyncio.wait_for(release(), max(0, deadline - loop.time()))
            except (ValueError, UnicodeError, RecursionError):
                if not detached.is_set() and not started:
                    await self._chart_error(scope, receive, send, "CHART_STUDY_REQUEST_INVALID", 400)
            except OnlySourceReadAccessError as error:
                if not detached.is_set() and not started:
                    await self._deny(scope, receive, send, error.code)
            except TimeoutError:
                if not detached.is_set() and not started:
                    await self._chart_error(scope, receive, send, "CHART_STUDY_QUERY_UNAVAILABLE", 503)
                detached.set()
            finally:
                if watcher is not None:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)
                if application is not None and not application.done():
                    # No cancelled ASGI/worker escape and no prematurely free slot.
                    await asyncio.shield(application)

        await self._retain_work(work(), detached, stream=False)

    @staticmethod
    async def _chart_error(scope: Scope, receive: Receive, send: Send, code: str, status: int) -> None:
        await JSONResponse(
            {"schema_version": 1, "error": {"phase": "QUERY", "code": code, "detail": code}},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )(scope, receive, send)

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send, code: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            status = (
                401
                if code == "LOCAL_READ_UNAUTHORIZED"
                else 503
                if code.endswith("UNAVAILABLE")
                else 429
                if code.endswith("EXCEEDED")
                else 403
            )
            await JSONResponse(
                {"schema_version": 1, "error": {"phase": "QUERY", "code": code, "detail": code}},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
