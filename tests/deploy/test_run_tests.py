from __future__ import annotations

import os
import shutil
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


def test_runner_makes_only_artifact_root_writable_with_sticky_protection(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    deploy = root / "deploy"
    deploy.mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[2] / "deploy/run-tests.sh", deploy / "run-tests.sh")
    artifacts = root / "test-results"
    artifacts.mkdir(mode=0o755)
    previous = artifacts / "previous"
    previous.mkdir(mode=0o700)
    private = previous / "private.log"
    private.write_text("preserved")
    private.chmod(0o600)
    docker = tmp_path / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n")
    docker.chmod(0o755)
    environment = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run([deploy / "run-tests.sh", "true"], env=environment, check=True)
    assert artifacts.stat().st_mode & 0o7777 == 0o1777
    assert previous.stat().st_mode & 0o777 == 0o700
    assert private.stat().st_mode & 0o777 == 0o600
    assert private.read_text() == "preserved"


def test_runner_rejects_artifact_symlink_without_changing_target_permissions(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    deploy = root / "deploy"
    deploy.mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[2] / "deploy/run-tests.sh", deploy / "run-tests.sh")
    target = tmp_path / "external"
    target.mkdir(mode=0o700)
    (root / "test-results").symlink_to(target, target_is_directory=True)
    completed = subprocess.run([deploy / "run-tests.sh", "true"], capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert "must not be a symlink" in completed.stderr
    assert target.stat().st_mode & 0o777 == 0o700
