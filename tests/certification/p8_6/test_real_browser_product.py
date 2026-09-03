from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.run import OnlyResearchRunId
from scripts.database import _initialize_deployment
from tests.research.calculation.support import snapshot

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _assert_port_available(port: int) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))


def _wait_url(url: str, process: subprocess.Popen[str], *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            if process.poll() is not None:
                break
        time.sleep(0.05)
    raise AssertionError(f"service did not become available: {url}; returncode={process.poll()}")


def _stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_real_chromium_product_vertical_survives_refresh_close_and_reopen(
    postgres_dsn: str,
    tmp_path: Path,
    backtest_product_config: Path,
) -> None:
    api_port = 8000
    web_port = 4173
    _assert_port_available(api_port)
    _assert_port_available(web_port)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate, partitions = snapshot()
    committed = datasets.commit(candidate, partitions)
    definition = committed.definition
    barrier = tmp_path / "browser-closed.barrier"
    worker_started = tmp_path / "worker-started.barrier"
    evidence_path = tmp_path / "real-browser-evidence.json"
    environment = {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
        "UV_CACHE_DIR": "/tmp/onlyalpha-uv-cache",
        "ONLYALPHA_REAL_E2E_ALLOW_WORKER": str(barrier),
        "ONLYALPHA_REAL_E2E_WORKER_STARTED": str(worker_started),
        "ONLYALPHA_REAL_E2E_EVIDENCE": str(evidence_path),
        "ONLYALPHA_REAL_E2E_INSTRUMENTS": ", ".join(str(item) for item in definition.instruments),
        "ONLYALPHA_REAL_E2E_START": definition.time_range.start.isoformat(),
        "ONLYALPHA_REAL_E2E_END": definition.time_range.end.isoformat(),
    }
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "onlyalpha_http_server.main",
            "--user-data-root",
            str(tmp_path),
            "--port",
            str(api_port),
            "--backtest-product-config",
            str(backtest_product_config),
        ],
        env=environment,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    web = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(web_port)],
        cwd=Path("packages/onlyalpha-web-console"),
        env=environment,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker: subprocess.Popen[str] | None = None
    worker_failure: list[str] = []
    harness_stop = Event()

    def start_worker_after_browser_close() -> None:
        nonlocal worker
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not barrier.is_file() and not harness_stop.is_set():
            time.sleep(0.02)
        if harness_stop.is_set():
            return
        if not barrier.is_file():
            worker_failure.append("browser close barrier was not published")
            return
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "onlyalpha.research.worker_main",
                "--user-data-root",
                str(tmp_path),
                "--polling-seconds",
                "0.05",
                "--lease-seconds",
                "30",
                "--heartbeat-seconds",
                "12",
            ],
            env=environment,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        worker_started.write_text("STARTED", encoding="utf-8")

    starter = Thread(target=start_worker_after_browser_close, name="real-browser-worker-barrier")
    starter.start()
    try:
        _wait_url(f"http://127.0.0.1:{api_port}/health/ready", api)
        _wait_url(f"http://127.0.0.1:{web_port}/research/new", web)
        completed = subprocess.run(
            [
                "./node_modules/.bin/playwright",
                "test",
                "--config=playwright.real.config.ts",
            ],
            cwd=Path("packages/onlyalpha-web-console"),
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
        starter.join(timeout=5)
        assert not starter.is_alive() and not worker_failure
        assert evidence_path.is_file()
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert evidence["candidate_count"] == 2
        assert evidence["instruments"] == ["A.XNAS", "B.XNAS"]
        assert isinstance(evidence["feature_value"], str)
        assert evidence["signal_points"] > 0
        assert evidence["statistics_points"] > 0
        run = OnlyPostgresResearchRunStore(postgres_dsn).load(OnlyResearchRunId(evidence["run_id"]))
        assert run.state.value == "COMPLETED"
        assert run.research_result_fingerprint == evidence["result"]
        assert run.artifact_content_fingerprint == evidence["artifact"]
    finally:
        harness_stop.set()
        _stop(worker)
        _stop(web)
        _stop(api)
        starter.join(timeout=1)
