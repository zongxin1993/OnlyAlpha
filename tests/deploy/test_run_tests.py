from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_runner_preserves_failure_and_cleans_only_its_isolated_environment(tmp_path: Path) -> None:
    root = Path(__file__).parents[2]
    docker = tmp_path / "docker"
    log = tmp_path / "docker.log"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\n[[ " $* " == *" run "* ]] && exit 7\nexit 0\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "DOCKER_LOG": str(log)}

    completed = subprocess.run(
        (root / "deploy/run-tests.sh", "python", "-m", "pytest", "tests/example.py"),
        cwd=root,
        env=environment,
        check=False,
    )

    assert completed.returncode == 7
    calls = log.read_text(encoding="utf-8").splitlines()
    assert " config --quiet" in calls[0]
    assert " --profile test run --build --rm " in calls[1]
    assert calls[1].endswith(" test python -m pytest tests/example.py")
    assert " --profile test down -v --remove-orphans" in calls[2]
    assert calls[3].startswith("image rm onlyalpha-test-")
