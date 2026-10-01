from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.parametrize("test_status,log_status", [(0, 0), (23, 0), (23, 31)])
def test_web_e2e_captures_logs_before_cleanup_without_hiding_exit_status(
    tmp_path: Path, test_status: int, log_status: int
) -> None:
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$CALLS"\n'
        'case " $* " in\n'
        '  *" logs "*) printf "fixture service diagnostics\\n"; exit "$LOG_STATUS";;\n'
        '  *" run "*) exit "$TEST_STATUS";;\n'
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    artifacts = tmp_path / "artifacts"
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "deploy/run-web-e2e.sh"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "CALLS": str(calls),
            "TEST_STATUS": str(test_status),
            "LOG_STATUS": str(log_status),
            "ONLYALPHA_WEB_E2E_ARTIFACTS_DIR": str(artifacts),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == test_status
    commands = calls.read_text(encoding="utf-8").splitlines()
    assert " logs --no-color " in commands[-2]
    assert " down -v --remove-orphans" in commands[-1]
    assert (artifacts / "service-logs.txt").read_text(encoding="utf-8") == "fixture service diagnostics\n"
