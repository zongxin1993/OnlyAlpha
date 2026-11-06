"""在受控 PostgreSQL 验证中调用实际 Rust Probe。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast


def call(probe: Path, request: dict[str, Any], *, dsn: str | None = None) -> dict[str, Any]:
    environment = None if dsn is None else {**os.environ, "ONLYALPHA_POSTGRES_DSN": dsn}
    result = subprocess.run(
        [str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20, env=environment
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict), "native PostgreSQL probe must return one JSON object"
    return cast(dict[str, Any], value)
