"""Scoped backend proposal client. No Human credential, confirmation or execution methods."""

from __future__ import annotations

import hashlib
import json
import ssl
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from .model import NoRedirect, strict_json
from .workflow import digest


class Unknown(Exception):
    """An original backend Command may have committed. Query it; never resubmit automatically."""


class Rejected(Exception):
    pass


@dataclass(frozen=True)
class Connection:
    url: str
    credential: str = field(repr=False)

    def __post_init__(self) -> None:
        u = urlsplit(self.url)
        p = self.credential.split(".")
        if (
            u.username is not None
            or u.password is not None
            or u.query
            or u.fragment
            or not u.hostname
            or not (u.scheme == "https" or u.scheme == "http" and u.hostname in {"127.0.0.1", "localhost", "::1"})
            or len(p) != 3
            or p[0] != "oa-proposal-v1"
            or str(UUID(p[1])) != p[1]
            or UUID(p[1]).version != 4
            or len(p[2]) != 64
            or any(c not in "0123456789abcdef" for c in p[2])
        ):
            raise ValueError("AGENT_BACKEND_CONFIGURATION_INVALID")

    def fingerprint(self) -> str:
        return digest({"url": self.url, "credential_sha256": hashlib.sha256(self.credential.encode()).hexdigest()})


def request(
    connection: Connection, method: str, path: str, body: dict[str, Any] | None = None, command: str | None = None
) -> dict[str, Any]:
    # Prevent this adapter becoming an authenticated arbitrary-URL or Human-operation proxy.
    valid = method == "POST" and path == "/api/v2/factor-proposals"
    if method == "GET":
        for prefix in ("/api/v2/factor-proposal-context/", "/api/v2/factor-proposals/commands/"):
            if path.startswith(prefix):
                try:
                    raw = path[len(prefix) :]
                    valid = str(UUID(raw)) == raw and UUID(raw).version == 4
                except ValueError:
                    valid = False
    if method == "GET" and path.startswith("/api/v2/factor-proposals/"):
        value = path.removeprefix("/api/v2/factor-proposals/")
        if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            valid = True
    if not valid:
        raise Rejected("AGENT_BACKEND_OPERATION_DENIED")
    headers = {
        "Authorization": "Bearer " + connection.credential,
        "Content-Type": "application/json",
        "Host": "127.0.0.1:5173",
    }
    if command is not None:
        headers["Idempotency-Key"] = command
    r = Request(
        connection.url.rstrip("/") + path,
        method=method,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(r, timeout=10) as response:
            raw = response.read(131073)
        if len(raw) > 131072 or connection.credential.encode() in raw:
            raise Unknown()
        result = strict_json(raw)
        if not isinstance(result, dict) or result.get("schema_version") != 1:
            raise Unknown()
        return result
    except HTTPError as error:
        if 400 <= error.code < 500 and error.code not in {408, 429}:
            raise Rejected("AGENT_BACKEND_REJECTED") from error
        raise Unknown() from error
    except (OSError, ValueError, RecursionError) as error:
        raise Unknown() from error
