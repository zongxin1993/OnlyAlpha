"""Installed arithmetic and native next-open in-memory backtest shipping check."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def replay_environment(root: Path, artifacts: Path) -> dict[str, str]:
    from packages.backend.tests.workers.test_installed_trading_nodes import installed_trading_environment

    artifacts.mkdir(parents=True, exist_ok=True)
    # A fresh owned installation for every invocation: never adopt an old worker
    # or replace the artifact selected by an existing work identity.
    output = Path(tempfile.mkdtemp(prefix="installed-", dir=artifacts))
    return installed_trading_environment(root, output)


def check_replay(root: Path, env: dict[str, str], target: str, artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    build = subprocess.run(
        [
            "cargo",
            "test",
            "-p",
            "onlyalpha-backend",
            "--test",
            "workers_trading",
            "--no-run",
            "--release",
            "--message-format=json",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
        ],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    executable = next(
        Path(row["executable"])
        for line in build.stdout.splitlines()
        if (row := json.loads(line)).get("reason") == "compiler-artifact"
        and row.get("executable")
        and row["target"]["name"] == "workers_trading"
    )
    # Run the installed next-open memory composition against one exact stripped
    # Shipping-size test image.
    with tempfile.NamedTemporaryFile(prefix="workers-trading-", suffix=".elf", dir=artifacts, delete=False) as image:
        selected = Path(image.name)
    shutil.copyfile(executable, selected)
    subprocess.run(["strip", "--strip-all", str(selected)], check=True, timeout=30)
    selected.chmod(0o500)
    if selected.stat().st_size > 128 * 1024 * 1024:
        raise RuntimeError("REPLAY_NATIVE_IMAGE_BUDGET_EXCEEDED")
    command = [
        str(selected),
        "installed_trading_algorithms::next_open_trading::",
        "--nocapture",
        "--test-threads=1",
    ]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=150)
    (artifacts / "next-open-memory.log").write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"BACKTEST_MEMORY_CHECK_FAILED: {(result.stdout + result.stderr).decode()}")
    (artifacts / "receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "IN_MEMORY_NEXT_OPEN",
                "target": target,
                "selector": "installed_trading_algorithms::next_open_trading::",
                "log": "next-open-memory.log",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    print("BACKTEST_MEMORY_CHECK: PASS", flush=True)
