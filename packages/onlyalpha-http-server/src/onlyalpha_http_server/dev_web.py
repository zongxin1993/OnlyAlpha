"""Explicit local-developer session; not production or Agent authentication."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onlyalpha.application.market_data_product import OnlyMarketDataSourceProjectionV1
from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadAuthority,
    OnlySourceReadGrant,
    OnlySourceReadPermission,
    OnlySourceReadSession,
)

from .local_read_access import OnlyLocalReadConfiguration, OnlyLocalReadIngress

DEV_COOKIE = "onlyalpha_dev_session"


def only_dev_web_configuration(
    origin: str, sources: tuple[OnlyMarketDataSourceProjectionV1, ...], *, credential: str | None = None
) -> tuple[OnlyLocalReadConfiguration, str]:
    """Explicit dev-role policy; discovery supplies identity, never permission."""
    if origin != "http://127.0.0.1:5173":
        raise ValueError("DEV_WEB_ORIGIN_NOT_ADMITTED")
    credential = secrets.token_hex(32) if credential is None else credential
    grants = tuple(
        OnlySourceReadGrant(
            source.integration_id,
            source.integration_revision_fingerprint,
            source.type_id,
            source.source_id,
            source.environment,
            (OnlySourceReadPermission.CLOSED_HISTORY, OnlySourceReadPermission.REALTIME_PREVIEW),
        )
        for source in sources
    )
    return (
        OnlyLocalReadConfiguration(
            OnlySourceReadAuthority("local-developer", hashlib.sha256(credential.encode("ascii")).hexdigest(), grants),
            origin,
        ),
        credential,
    )


class OnlyDevWebIngress(OnlyLocalReadIngress):
    """Cookie transport over the same authority, bounded work and release fences."""

    def __init__(
        self,
        app: ASGIApp,
        configuration: OnlyLocalReadConfiguration,
        *,
        chart_study_enabled: bool = False,
        source_reader: Callable[[], tuple[OnlyMarketDataSourceProjectionV1, ...]] | None = None,
    ) -> None:
        super().__init__(app, configuration, chart_study_enabled=chart_study_enabled)
        self._source_reader = source_reader
        self._source_refresh_lock = asyncio.Lock()
        self._source_withdrawn = asyncio.Event()

    @staticmethod
    def _cookie_credential(scope: Scope) -> str:
        cookies: list[bytes] = [value for key, value in scope["headers"] if key.lower() == b"cookie"]
        if len(cookies) != 1:
            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
        pairs = [item.strip().partition(b"=") for item in cookies[0].split(b";")]
        values = [value for name, separator, value in pairs if name == DEV_COOKIE.encode() and separator]
        if len(values) != 1:
            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
        return values[0].decode("ascii")

    def _authenticate(self, scope: Scope) -> OnlySourceReadSession:
        headers = scope["headers"]
        if self.withdrawn.is_set() or any(key.lower() == b"authorization" for key, _ in headers):
            raise OnlySourceReadAccessError("LOCAL_READ_UNAUTHORIZED")
        return self.configuration.authority.authenticate("Bearer " + self._cookie_credential(scope))

    async def _prepare_read_session(self, scope: Scope, session: OnlySourceReadSession) -> OnlySourceReadSession:
        if scope["path"] != "/api/v2/market-data/sources" or self._source_reader is None:
            return session
        # An explicit Source-list refresh admits a new exact dev-policy snapshot.
        # Existing requests keep their immutable session; changed grants withdraw
        # that generation behind the same response fence, never mutate it in place.
        async with self._source_refresh_lock:
            session = self._authenticate(scope)
            try:
                sources = await run_in_threadpool(self._source_reader)
                configuration, _ = only_dev_web_configuration(
                    self.configuration.origin, sources, credential=self._cookie_credential(scope)
                )
            except Exception:
                raise OnlySourceReadAccessError("LOCAL_READ_PROOF_UNAVAILABLE") from None
            async with self._send_lock:
                session.check_active()
                if frozenset(configuration.authority.grants) != frozenset(self.configuration.authority.grants):
                    self.configuration.authority.withdraw()
                    self._source_withdrawn.set()
                    self._source_withdrawn = asyncio.Event()
                    self.configuration = configuration
                return self._authenticate(scope)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await super().__call__(scope, receive, send)
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value)
        origin = self.configuration.origin.encode("ascii")
        is_http = scope["type"] == "http"
        mutation = not is_http or scope["method"] not in {"GET", "HEAD"}
        if (
            headers.get(b"host") != [urlsplit(self.configuration.origin).netloc.encode("ascii")]
            or headers.get(b"origin", []) not in ([], [origin])
            or (mutation and headers.get(b"origin") != [origin])
            or headers.get(b"sec-fetch-site", []) not in ([], [b"none"], [b"same-origin"])
            or any(key in headers for key in (b"forwarded", b"x-forwarded-for", b"x-forwarded-proto", b"x-user"))
        ):
            await self._deny(scope, receive, send, "LOCAL_READ_FORBIDDEN")
            return
        cookie_headers = headers.get(b"cookie", [])
        if (
            b"authorization" in headers
            or len(cookie_headers) > 1
            or (
                cookie_headers
                and sum(
                    part.strip().partition(b"=")[0] == DEV_COOKIE.encode() for part in cookie_headers[0].split(b";")
                )
                > 1
            )
        ):
            await self._deny(scope, receive, send, "LOCAL_READ_UNAUTHORIZED")
            return

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *(
                            (key, value)
                            for key, value in message.get("headers", [])
                            if key.lower() not in {b"cache-control", b"x-frame-options", b"content-security-policy"}
                        ),
                        (b"x-frame-options", b"DENY"),
                        (b"content-security-policy", b"frame-ancestors 'none'"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            await send(message)

        path = scope["path"]
        navigation = (
            is_http
            and scope["method"] == "GET"
            and path == "/"
            and not scope.get("query_string")
            and headers.get(b"sec-fetch-mode") == [b"navigate"]
            and headers.get(b"sec-fetch-dest") == [b"document"]
        )
        if navigation or (is_http and scope["method"] == "GET" and path in {"/health/live", "/health/ready"}):
            if self.withdrawn.is_set():
                await self._deny(scope, receive, guarded_send, "LOCAL_READ_UNAUTHORIZED")
            else:
                await self.app(scope, receive, guarded_send)
            return
        try:
            session = self._authenticate(scope)
            scope["onlyalpha.local_read_session"] = session
        except (OnlySourceReadAccessError, UnicodeError):
            await self._deny(scope, receive, guarded_send, "LOCAL_READ_UNAUTHORIZED")
            return
        if path.startswith(("/internal/", "/api/v2/agent", "/api/v2/trading", "/api/v2/live")):
            await self._deny(scope, receive, guarded_send, "LOCAL_READ_FORBIDDEN")
            return
        if path.startswith(("/api/v2/market-data/", "/api/v2/market/", "/api/v2/chart/")):
            if not is_http:
                scope["onlyalpha.local_read_generation_withdrawn"] = self._source_withdrawn
            await super().__call__(scope, receive, guarded_send)
            return
        # Explicit dev-human command policy, separate from read-only Source grants.
        integration = path == "/api/v2/integrations" or path.startswith("/api/v2/integrations/")
        if is_http and (
            scope["method"] == "GET" or (integration and scope["method"] in {"POST", "PUT", "PATCH", "DELETE"})
        ):
            started = False
            suppressed = False

            async def general_send(message: Message) -> None:
                nonlocal started, suppressed
                async with self._send_lock:
                    try:
                        session.check_active()
                    except OnlySourceReadAccessError:
                        suppressed = True
                        return
                    if message["type"] == "http.response.start":
                        started = True
                    await guarded_send(message)

            # Admission is not rollback: already accepted Commands finish through
            # their owning Authority, but withdrawal suppresses subsequent release.
            session.check_active()
            await self.app(scope, receive, general_send)
            if suppressed and not started:
                await self._deny(scope, receive, guarded_send, "LOCAL_READ_UNAUTHORIZED")
            return
        await self._deny(scope, receive, guarded_send, "LOCAL_READ_FORBIDDEN")


def only_mount_dev_web(app: FastAPI, directory: Path, credential: str) -> None:
    """Serve only the built Shipping assets; no source, credential or fixture mount."""
    index = directory / "index.html"
    if not index.is_file():
        raise ValueError("DEV_WEB_BUILD_MISSING")

    @app.get("/", include_in_schema=False)
    def workspace() -> FileResponse:
        response = FileResponse(index, headers={"Cache-Control": "no-store"})
        response.set_cookie(DEV_COOKIE, credential, httponly=True, samesite="strict", path="/")
        return response

    app.mount("/", StaticFiles(directory=directory, html=True), name="dev-web")
