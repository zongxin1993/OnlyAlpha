"""Installed arithmetic and native next-open replay process fault lane."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def replay_environment(root: Path, artifacts: Path) -> dict[str, str]:
    from packages.backend.tests.workers.test_installed_trading_nodes import installed_trading_environment

    artifacts.mkdir(parents=True, exist_ok=True)
    # A fresh owned installation for every invocation: never adopt an old worker
    # or replace the artifact selected by an existing work identity.
    output = Path(tempfile.mkdtemp(prefix="installed-", dir=artifacts))
    return installed_trading_environment(root, output)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
    receipts = []
    counter = 0

    def invoke(state: Path, mode: str, cut: str = "", *, mutation: int | None = None) -> None:
        nonlocal counter
        counter += 1
        name = f"{counter:03d}-{mode}-{cut.replace(':', '-')}"
        command = [
            str(executable),
            "--exact",
            "installed_trading_algorithms::next_open_trading::replay_process::process_writer",
            "--nocapture",
            "--test-threads=1",
        ]
        process_env = dict(env, OA_REPLAY_PROCESS_ROOT=str(state), OA_REPLAY_PROCESS_MODE=mode, OA_REPLAY_CUT=cut)
        if mutation is not None:
            process_env["OA_REPLAY_MUTATION"] = str(mutation)
        if not cut:
            try:
                result = subprocess.run(command, cwd=root, env=process_env, capture_output=True, timeout=120)
            except subprocess.TimeoutExpired as error:
                (artifacts / f"{name}.log").write_bytes((error.stdout or b"") + (error.stderr or b""))
                raise
            (artifacts / f"{name}.log").write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"REPLAY_PROCESS_FAILED {name}: {(result.stdout + result.stderr).decode()}")
        else:
            with subprocess.Popen(
                command,
                cwd=root,
                env=process_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            ) as child:
                assert child.stdout is not None
                output = bytearray()
                deadline = time.monotonic() + 120  # Hang guard; ordering is proved by the explicit barrier.
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(child.stdout, selectors.EVENT_READ)
                        while b"\nBARRIER\n" not in output:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0 or not selector.select(remaining):
                                raise RuntimeError(f"REPLAY_BARRIER_UNAVAILABLE {name}")
                            chunk = os.read(child.stdout.fileno(), 65536)
                            if not chunk:
                                raise RuntimeError(f"REPLAY_EXITED_BEFORE_BARRIER {name}: {output.decode()}")
                            output.extend(chunk)
                    child.kill()
                    assert child.wait() < 0
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
                    (artifacts / f"{name}.log").write_bytes(output)
        receipts.append({"mode": mode, "cut": cut, "log": f"{name}.log"})

    with tempfile.TemporaryDirectory(prefix="replay-", dir=artifacts) as directory:
        work = Path(directory)
        baseline = work / "baseline"
        baseline.mkdir()
        invoke(baseline, "BASELINE")
        expected = json.loads((baseline / "result.json").read_text())
        assert expected["result"]["status"] == "COMPLETED"
        assert expected["result"]["execution_result"]["final_account"]["cash"] == "9994.60119940"
        assert expected["result"]["execution_result"]["final_account"]["fees"] == "1.99900060"
        (artifacts / "baseline.json").write_text(_canonical(expected))
        steps = expected["trace"]["steps"]
        selected = []
        for operation in ("ADMIT", "FILL"):
            selected.append(
                next(row["step"] for row in steps if any(i["op"] == operation for i in row["step"]["inputs"]))
            )
        # Each next-open operation includes canonical admission and its complete Fill.
        close = next(
            row["step"]
            for row in steps
            if any(i["op"] == "ADMIT" and i["payload"]["request"]["side"] == "SELL" for i in row["step"]["inputs"])
        )
        selected.append(close)
        selected.append(next(row["step"] for row in steps if row["step"]["cause"]["kind"] == "BAR"))
        cuts: list[str] = []
        for step in selected:
            index, start = step["index"], step["execution_start"]
            cuts.extend((f"BEFORE_PREPARE:{index}:{start}", f"PREPARED:{index}:{start}"))
            cuts.extend(f"EXECUTION_READY:{index}:{start + n}" for n in range(1, len(step["inputs"]) + 1))
            cuts.append(f"STEP_READY:{index}:{start + len(step['inputs'])}")
        cuts.append("DELIVERY:0:0")
        for index, cut in enumerate(dict.fromkeys(cuts)):
            state = work / f"cut-{index}"
            state.mkdir()
            invoke(state, "RUN", cut)
            invoke(state, "RESUME")
            assert json.loads((state / "result.json").read_text()) == expected, cut
        for mode in ("CANCELLED", "UNKNOWN", "FAILED", "INCOMPLETE"):
            state = work / mode
            state.mkdir()
            invoke(state, mode)
            result = json.loads((state / "result.json").read_text())
            assert result["result"]["outcome"]["status"] == mode
            assert result["result"]["status"] == ("INCOMPLETE" if mode == "UNKNOWN" else mode)
            assert not result["result"]["drained"]
        # Recompute every journal hash after mutations, so codec checks alone cannot pass this proof.
        for mutation in (2, 4, 5, *range(6, 19)):
            state = work / f"mutation-{mutation}"
            state.mkdir()
            shutil.copyfile(baseline / "runtime.sqlite3", state / "runtime.sqlite3")
            invoke(state, "MUTATE", mutation=mutation)
            invoke(state, "REFUSE_RELATION" if 6 <= mutation <= 15 else "REFUSE")
    (artifacts / "faults.json").write_text(_canonical({"schema_version": 1, "cases": receipts}))
    print(f"BACKTEST_REPLAY_REAL_PROCESS_CASES {len(receipts)}", flush=True)
