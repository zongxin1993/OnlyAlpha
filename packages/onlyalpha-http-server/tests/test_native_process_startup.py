"""Actual native process startup rejects unadmitted invocation before store IO."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.native_http_contract import native_executable

# Native release cold build belongs to the existing canonical native toolchain lane.
# The two pre-owner child invocations each retain their separate ten-second budget.
pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]


@pytest.mark.parametrize("arguments", [[], ["--host", "0.0.0.0"], ["--port", "8000"], ["--workers", "2"]])
def test_native_server_requires_one_explicit_user_root_and_rejects_old_activation_flags(
    tmp_path: Path, arguments: list[str]
) -> None:
    completed = subprocess.run(
        [str(native_executable()), *arguments],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert completed.stderr.strip() == "NATIVE_ARGUMENT_INVALID"
    assert completed.stdout == ""
    assert tuple(tmp_path.iterdir()) == ()


def test_native_server_missing_deployment_attestation_cannot_open_or_initialize_the_root(tmp_path: Path) -> None:
    user_root = tmp_path / "missing-user-data"
    completed = subprocess.run(
        [str(native_executable()), "--user-data-root", str(user_root)],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 1
    assert completed.stderr.strip() == "NATIVE_CONFIGURATION_REQUIRED"
    assert completed.stdout == ""
    assert not user_root.exists()
    assert tuple(tmp_path.iterdir()) == ()
