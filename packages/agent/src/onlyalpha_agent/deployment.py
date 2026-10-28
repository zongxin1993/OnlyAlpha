"""Explicit operator provisioning and contained-dev transport, never business admission."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
import socket
from pathlib import Path
from uuid import uuid4

from .model import endpoint


def provision(root: Path, backend: Path, dsn_file: Path, agent_url: str) -> None:
    endpoint(agent_url)
    from urllib.parse import urlsplit

    if urlsplit(agent_url).path not in {"", "/"}:
        raise ValueError("AGENT_PROVISION_ENDPOINT_INVALID")
    if any(path.resolve() != path for path in (root, backend, dsn_file)):
        raise ValueError("AGENT_PROVISION_SYMLINK_REFUSED")
    if not root.is_absolute() or root.is_symlink() or root.exists() and any(root.iterdir()):
        raise ValueError("AGENT_PROVISION_EMPTY_ROOT_REQUIRED")
    descriptor = backend / "agent-connection.json"
    browser_key = backend / "secrets/agent-browser-key"
    if (
        not backend.is_absolute()
        or backend.is_symlink()
        or not backend.is_dir()
        or descriptor.exists()
        or browser_key.exists()
    ):
        raise ValueError("AGENT_PROVISION_BACKEND_BINDING_EXISTS")
    if dsn_file.is_symlink() or dsn_file.stat().st_mode & 0o077:
        raise ValueError("AGENT_KEY_PERMISSIONS_INVALID")
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn_file.read_text().strip(), row_factory=dict_row) as conn:
        role = conn.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        occupied = conn.execute(
            "SELECT 1 FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') LIMIT 1"
        ).fetchone()
        if role is None or any(role.values()) or occupied is not None:
            raise ValueError("AGENT_PROVISION_EMPTY_DEDICATED_DATABASE_REQUIRED")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def write(path: Path, raw: bytes) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    write(root / "database.dsn", dsn_file.read_bytes())
    for name in ["model-key", "access-key", "browser-key"]:
        write(root / name, secrets.token_bytes(32))
    token = "oa-proposal-v1." + str(uuid4()) + "." + secrets.token_hex(32)
    write(root / "backend-token", token.encode())
    write(browser_key, (root / "browser-key").read_bytes())
    write(
        descriptor,
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "agent_url": agent_url,
                    "grant_id": token.split(".")[1],
                    "service_subject": "factor-chat",
                    "credential_sha256": hashlib.sha256(token.encode()).hexdigest(),
                }
            )
            + "\n"
        ).encode(),
    )
    # No model, grant, Factor or Command is created here. The Web owns those user steps.


def contained_gateway(path: Path) -> str:
    if path.is_symlink() or path.stat().st_size > 32768:
        raise ValueError("AGENT_CONTAINED_DEPLOYMENT_INVALID")
    value = json.loads(path.read_text())
    if (
        value.get("agent_publication") != "127.0.0.1:5174"
        or os.environ.get("HOSTNAME") != value.get("container_id", "")[:12]
    ):
        raise ValueError("AGENT_CONTAINED_DEPLOYMENT_INVALID")
    gateway = ipaddress.ip_address(value["gateway"])
    local = ipaddress.ip_address(value["local_address"])
    if (
        gateway.version != 4
        or not gateway.is_private
        or gateway.is_loopback
        or local.version != 4
        or not local.is_private
        or local == gateway
    ):
        raise ValueError("AGENT_CONTAINED_DEPLOYMENT_INVALID")
    import fcntl
    import struct

    addresses = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as interface:
        for _, name in socket.if_nameindex():
            try:
                raw = fcntl.ioctl(interface.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
                addresses.add(socket.inet_ntoa(raw[20:24]))
            except OSError:
                continue
    if str(local) not in addresses:
        raise ValueError("AGENT_CONTAINED_DEPLOYMENT_INVALID")
    return str(gateway)
