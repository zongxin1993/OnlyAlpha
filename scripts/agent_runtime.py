"""Infrastructure lifecycle for one independently installed local Agent process."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def environment(root: Path, installation: Path) -> dict[str, str]:
    # No backend DSN, broker credential or root Python import path crosses this boundary.
    result = {k: v for k, v in os.environ.items() if not k.startswith(("ONLYALPHA_", "PYTHON", "UV_"))}

    def key(name: str) -> str:
        return str(root / name)

    result.update(
        ONLYALPHA_POSTGRES_DSN=(root / "database.dsn").read_text().strip(),
        ONLYALPHA_AGENT_KEY_FILE=key("model-key"),
        ONLYALPHA_AGENT_ACCESS_KEY_FILE=key("access-key"),
        ONLYALPHA_AGENT_BROWSER_KEY_FILE=key("browser-key"),
        ONLYALPHA_AGENT_BACKEND_CREDENTIAL_FILE=key("backend-token"),
        ONLYALPHA_AGENT_ORIGIN="http://127.0.0.1:5173",
        ONLYALPHA_AGENT_BACKEND_URL="http://127.0.0.1:5173",
        ONLYALPHA_AGENT_EXPECTED_WORKFLOW=json.loads((installation / "installation.json").read_text())["workflow"],
    )
    return result


def launch(
    root: Path, installation: Path, *, contained: Path | None = None, stdout: Any = None, stderr: Any = None
) -> subprocess.Popen[bytes]:
    if not root.is_absolute() or root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError("AGENT_STATE_ROOT_INVALID")
    args = [
        str(installation / "env/bin/python"),
        "-B",
        "-I",
        "-m",
        "onlyalpha_agent",
        "serve",
        "--host",
        "0.0.0.0" if contained else "127.0.0.1",
        "--port",
        "5174",
    ]
    if contained:
        args += ["--contained-record", str(contained)]
    return subprocess.Popen(
        args,
        env=environment(root, installation),
        cwd=installation,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
