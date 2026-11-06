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


@pytest.mark.parametrize(
    "scenario",
    [
        "missing",
        "uninitialized",
        "pending",
        "observed",
        "busy",
        "bad-digest",
        "foreign-strategy",
        "foreign-run",
        "symlink",
        "wrong-schema",
        "corrupt",
        "boolean-meta-schema",
        "boolean-binding-schema",
    ],
)
def test_web_runtime_interruption_barrier_observes_read_only_and_rejects_bad_inputs(
    tmp_path: Path, scenario: str
) -> None:
    """Exercise the actual TS-embedded observer, never a Runtime Source proof.

    These temporary SQLite rows establish technical barrier validation only.
    Formal PAUSE/RESUME and results remain owned by the Rust snapshot and API.
    """
    import hashlib
    import json
    import re
    import sqlite3
    import sys
    import uuid

    source = (Path(__file__).resolve().parents[4] / "packages/frontend/e2e/support/backtest-runtime.ts").read_text()
    embedded = re.search(r"const observe = String.raw`(.*?)`;", source, re.DOTALL)
    assert embedded is not None
    observer = embedded.group(1)
    run = str(uuid.uuid4())
    strategy = "a" * 64
    path = tmp_path / "backtest/runtime" / run / "runtime.sqlite3"

    def image(value):
        raw = json.dumps(value)
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    connection = None
    if scenario != "missing":
        path.parent.mkdir(parents=True)
        if scenario == "symlink":
            path.symlink_to(path.parent / "missing")
        elif scenario == "corrupt":
            path.write_bytes(b"invalid SQLite bytes")
        else:
            connection = sqlite3.connect(path)
            if scenario != "uninitialized":
                connection.executescript(
                    "PRAGMA application_id=1329680976; PRAGMA user_version=4;"
                    "CREATE TABLE meta(singleton INTEGER,payload TEXT,digest TEXT);"
                    "CREATE TABLE replay_binding(singleton INTEGER,payload TEXT,digest TEXT);"
                    "CREATE TABLE records(sequence INTEGER,payload TEXT,digest TEXT,ready INTEGER,delivered INTEGER);"
                    "CREATE TABLE replay_steps(sequence INTEGER,payload TEXT,digest TEXT,ready INTEGER);"
                )
                metadata = {
                    "schema_version": True if scenario == "boolean-meta-schema" else 1,
                    "family": "RUST_EXECUTION_RUNTIME",
                    "configuration": {
                        "runtime_kind": "BACKTEST",
                        "engine": "onlyalpha-backtest",
                        "profiles": {
                            "strategy": {"revision": "d" * 64 if scenario == "foreign-strategy" else strategy}
                        },
                    },
                    "kernel_artifact": "b" * 64,
                }
                connection.execute("INSERT INTO meta VALUES(1,?,?)", image(metadata))
                if scenario != "pending":
                    binding = {
                        "schema_version": True if scenario == "boolean-binding-schema" else 2,
                        "work_id": str(uuid.uuid4()) if scenario == "foreign-run" else run,
                        "kernel_artifact": "b" * 64,
                    }
                    connection.execute("INSERT INTO replay_binding VALUES(1,?,?)", image(binding))
                    connection.execute("INSERT INTO records VALUES(1,?,?,1,0)", image({"opaque_frame": "execution"}))
                    connection.execute("INSERT INTO replay_steps VALUES(1,?,?,1)", image({"opaque_frame": "replay"}))
                if scenario == "bad-digest":
                    connection.execute("UPDATE records SET digest=?", ("c" * 64,))
                if scenario == "wrong-schema":
                    connection.execute("PRAGMA user_version=99")
                connection.commit()

    def actual_files():
        return {
            candidate.relative_to(tmp_path).as_posix(): (
                ("symlink", str(candidate.readlink()))
                if candidate.is_symlink()
                else (candidate.stat().st_dev, candidate.stat().st_ino, candidate.read_bytes())
            )
            for candidate in tmp_path.rglob("*")
            if candidate.is_symlink() or candidate.is_file()
        }

    before = actual_files()
    if scenario == "busy":
        # Capture bytes before taking the lock: closing another descriptor of
        # this inode can release process-owned POSIX locks on the host platform.
        assert connection is not None
        connection.execute("BEGIN EXCLUSIVE")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", observer, str(tmp_path), run, strategy],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        assert actual_files() == before, "observer mutated actual bytes, inode, or directory contents"
        expected = {
            "missing": "MISSING",
            "uninitialized": "UNINITIALIZED",
            "pending": "PENDING",
            "observed": "OBSERVED",
            "busy": "BUSY",
        }
        if scenario in expected:
            assert completed.returncode == 0, completed.stderr
            actual = json.loads(completed.stdout)
            assert actual["state"] == expected[scenario], (actual, completed.stderr)
            if scenario == "observed":
                assert actual["inode"] == str(path.stat().st_ino)
                assert actual["execution"] == [
                    {"sequence": 1, "digest": image({"opaque_frame": "execution"})[1], "delivered": 0}
                ]
                assert actual["replay"] == [{"sequence": 1, "digest": image({"opaque_frame": "replay"})[1]}]
        else:
            assert completed.returncode != 0
            assert completed.stdout == ""
    finally:
        if connection is not None:
            connection.close()
