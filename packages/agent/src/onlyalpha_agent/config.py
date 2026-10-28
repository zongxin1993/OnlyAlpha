"""Explicit installation inputs; no backend Store, key or bootstrap-token reuse."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    dsn: str
    encryption_key: bytes
    signing_key: bytes
    origin: str = "http://127.0.0.1:5173"
    backend_url: str | None = None
    backend_credential: str | None = field(default=None, repr=False)
    browser_issuer_key: bytes | None = field(default=None, repr=False)
    contained_peer: str | None = None
    expected_workflow: str | None = None

    def __post_init__(self) -> None:
        if len(self.encryption_key) != 32 or len(self.signing_key) != 32 or self.encryption_key == self.signing_key:
            raise ValueError("AGENT_SEPARATE_KEYS_REQUIRED")
        if self.browser_issuer_key is not None and (
            len(self.browser_issuer_key) != 32 or self.browser_issuer_key in {self.encryption_key, self.signing_key}
        ):
            raise ValueError("AGENT_SEPARATE_KEYS_REQUIRED")
        if (self.backend_url is None) != (self.backend_credential is None):
            raise ValueError("AGENT_BACKEND_CONFIGURATION_INVALID")
        if self.backend_url is not None and self.backend_credential is not None:
            from .backend import Connection

            Connection(self.backend_url, self.backend_credential)
        if not self.dsn or not self.origin.startswith(("https://", "http://127.0.0.1:")):
            raise ValueError("AGENT_CONFIGURATION_INVALID")

    @classmethod
    def from_environment(cls) -> Settings:
        def key(name: str) -> bytes:
            p = Path(os.environ[name])
            if p.is_symlink() or p.stat().st_mode & 0o077:
                raise ValueError("AGENT_KEY_PERMISSIONS_INVALID")
            return p.read_bytes()

        return cls(
            os.environ["ONLYALPHA_POSTGRES_DSN"],
            key("ONLYALPHA_AGENT_KEY_FILE"),
            key("ONLYALPHA_AGENT_ACCESS_KEY_FILE"),
            os.environ["ONLYALPHA_AGENT_ORIGIN"],
            os.environ.get("ONLYALPHA_AGENT_BACKEND_URL"),
            key("ONLYALPHA_AGENT_BACKEND_CREDENTIAL_FILE").decode().strip()
            if "ONLYALPHA_AGENT_BACKEND_CREDENTIAL_FILE" in os.environ
            else None,
            key("ONLYALPHA_AGENT_BROWSER_KEY_FILE") if "ONLYALPHA_AGENT_BROWSER_KEY_FILE" in os.environ else None,
            None,
            os.environ.get("ONLYALPHA_AGENT_EXPECTED_WORKFLOW"),
        )
