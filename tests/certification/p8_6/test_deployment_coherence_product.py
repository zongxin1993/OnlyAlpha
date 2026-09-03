from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.operations.deployment import (
    SEMANTIC_STORE_IDENTITY_FILE,
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from scripts.database import _initialize_deployment
from tests.research.specification.support import registry, specification

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _environment(postgres_dsn: str) -> dict[str, str]:
    return {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
        "UV_CACHE_DIR": "/tmp/onlyalpha-uv-cache",
    }


def _semantic_directories(root: Path) -> None:
    layout = OnlyUserDataLayout(root)
    for path in (
        layout.research_dataset_root,
        layout.research_calculation_result_root,
        layout.research_statistics_result_root,
        layout.research_result_root,
        layout.research_artifact_root,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_health(
    port: int,
    expected_reason: str | None,
    *,
    timeout: float = 20,
    process: subprocess.Popen[str] | None = None,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1) as response:  # noqa: S310
                payload = json.load(response)
                last_payload = payload
                if expected_reason is None and response.status == 200:
                    return payload
        except HTTPError as error:
            payload = json.loads(error.read())
            last_payload = payload
            if error.code == 503 and payload.get("reason") == expected_reason:
                return payload
        except (URLError, TimeoutError):
            pass
        if process is not None and process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise AssertionError(f"API exited before readiness: {output}")
        time.sleep(0.05)
    raise AssertionError(f"API readiness did not reach expected reason {expected_reason}; last={last_payload!r}")


def _queued() -> OnlyResearchRun:
    spec = specification()
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000008610"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def test_wrong_namespace_api_is_not_ready_and_cannot_serve_product_routes(
    postgres_dsn: str,
    tmp_path: Path,
    backtest_product_config: Path,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path / "correct")
    wrong = tmp_path / "wrong"
    OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(wrong).research_root).initialize()
    _semantic_directories(wrong)
    port = _port()
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "onlyalpha_http_server.main",
            "--user-data-root",
            str(wrong),
            "--port",
            str(port),
            "--backtest-product-config",
            str(backtest_product_config),
        ],
        env=_environment(postgres_dsn),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        readiness = _wait_health(port, "SEMANTIC_STORE_IDENTITY_MISMATCH", process=api)
        assert readiness["checks"]["deployment_binding"] == "SEMANTIC_STORE_IDENTITY_MISMATCH"  # type: ignore[index]
        with pytest.raises(HTTPError) as blocked:
            urlopen(f"http://127.0.0.1:{port}/api/v2/research/catalog/calculations", timeout=2)  # noqa: S310
        assert blocked.value.code == 503
        assert json.loads(blocked.value.read())["reason"] == "SEMANTIC_STORE_IDENTITY_MISMATCH"
    finally:
        _stop(api)


@pytest.mark.parametrize("local_state", ("MISMATCH", "MISSING", "CORRUPT"))
def test_incoherent_worker_refuses_startup_and_cannot_claim(
    postgres_dsn: str,
    tmp_path: Path,
    local_state: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path / "correct")
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued())
    wrong = tmp_path / "wrong"
    if local_state == "MISMATCH":
        OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(wrong).research_root).initialize()
    elif local_state == "CORRUPT":
        research_root = OnlyUserDataLayout(wrong).research_root
        research_root.mkdir(parents=True)
        (research_root / SEMANTIC_STORE_IDENTITY_FILE).write_text("{}")
    _semantic_directories(wrong)
    worker = subprocess.run(
        [
            sys.executable,
            "-m",
            "onlyalpha.research.worker_main",
            "--user-data-root",
            str(wrong),
            "--polling-seconds",
            "0.05",
        ],
        env=_environment(postgres_dsn),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert worker.returncode != 0
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(_queued().run_id).state.value == "QUEUED"
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_attempt").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_worker_presence").fetchone() == (0,)


def test_two_workers_with_same_namespace_are_both_compatible(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    command = [
        sys.executable,
        "-m",
        "onlyalpha.research.worker_main",
        "--user-data-root",
        str(tmp_path),
        "--polling-seconds",
        "0.05",
    ]
    workers = tuple(
        subprocess.Popen(
            command,
            env=_environment(postgres_dsn),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(2)
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with psycopg.connect(postgres_dsn) as connection:
                count = connection.execute("SELECT count(*) FROM research_worker_presence").fetchone()
            if count == (2,):
                break
            if any(worker.poll() is not None for worker in workers):
                break
            time.sleep(0.05)
        assert count == (2,)
        assert all(worker.poll() is None for worker in workers)
    finally:
        for worker in workers:
            _stop(worker)
