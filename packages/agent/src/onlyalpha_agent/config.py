"""Explicit installation inputs; no backend Store, key or bootstrap-token reuse."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    dsn: str
    encryption_key: bytes
    signing_key: bytes
    origin: str = "http://127.0.0.1:5173"

    def __post_init__(self) -> None:
        if len(self.encryption_key) != 32 or len(self.signing_key) != 32 or self.encryption_key == self.signing_key:
            raise ValueError("AGENT_SEPARATE_KEYS_REQUIRED")
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
        )
