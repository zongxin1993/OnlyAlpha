from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.research_run_store import (
    OnlyPostgresResearchRunStore,
)
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
from tests.certification.research_product.support import (
    provision_product_api_master_key,
)
from tests.research.specification.support import registry, specification
from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


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


@pytest.mark.parametrize("local_state", ("MISMATCH", "MISSING", "CORRUPT"))
def test_incoherent_worker_refuses_startup_and_cannot_claim(
    postgres_dsn: str,
    tmp_path: Path,
    local_state: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path / "correct")
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(_queued())
    wrong = tmp_path / "wrong"
    if local_state == "MISMATCH":
        OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(wrong).research_root).initialize()
    elif local_state == "CORRUPT":
        research_root = OnlyUserDataLayout(wrong).research_root
        research_root.mkdir(parents=True)
        (research_root / SEMANTIC_STORE_IDENTITY_FILE).write_text("{}")
    _semantic_directories(wrong)
    provision_product_api_master_key(wrong)
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
    provision_product_api_master_key(tmp_path)
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
