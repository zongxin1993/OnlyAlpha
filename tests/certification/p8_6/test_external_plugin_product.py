from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
import pytest
from onlyalpha_test_plugin.research_calculation import EXTERNAL_IDENTITY
from psycopg import sql

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchDeploymentStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchArtifactProfileReader,
    OnlyResearchArtifactStoreError,
    OnlyResearchResultStoreError,
    OnlyResearchSpecification,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentCoherenceVerifier,
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.research.run import OnlyResearchRunId
from onlyalpha.runtime.defaults import only_default_engine_services
from scripts.database import _backup, _initialize_deployment, _restore_test
from tests.certification.p8_6.support import external_definition
from tests.research.calculation.support import snapshot

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, *, method: str = "GET", body: object | None = None, headers: dict[str, str] | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        payload = error.read()
        return error.code, {} if not payload else json.loads(payload)


def _wait_for(url: str, predicate, *, timeout: float = 30.0):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    last: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            status, body = _request(url)
            if predicate(status, body):
                return body
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(0.05)
    raise AssertionError(f"authoritative condition was not reached: {url}; last={last!r}")


def _stop(process: subprocess.Popen[str], *, signum: int = signal.SIGTERM) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signum)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _semantic_readers(root: Path):  # type: ignore[no-untyped-def]
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    return (
        OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations),
        OnlyResearchArtifactProfileReader(layout.research_artifact_root),
    )


def test_external_calculation_runs_through_real_api_worker_engine_and_artifact_query(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate, partitions = snapshot()
    committed = datasets.commit(candidate, partitions)
    authored = external_definition(committed.definition)
    port = _port()
    base = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
        "UV_CACHE_DIR": "/tmp/onlyalpha-uv-cache",
    }
    api_command = [
        sys.executable,
        "-m",
        "onlyalpha_api.main",
        "--user-data-root",
        str(tmp_path),
        "--port",
        str(port),
    ]
    worker_command = [
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
    ]
    api = subprocess.Popen(
        api_command,
        cwd=Path.cwd(),
        env=environment,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    worker: subprocess.Popen[str] | None = None
    target_name: str | None = None
    admin_dsn: str | None = None
    try:
        _wait_for(f"{base}/health/ready", lambda status, body: status == 200 and body["status"] == "READY")
        _, catalog = _request(f"{base}/api/v2/research/catalog/calculations")
        assert EXTERNAL_IDENTITY.type_id in {item["type_reference"]["type_id"] for item in catalog["calculations"]}

        status, resolution = _request(
            f"{base}/api/v2/research/definitions/resolve",
            method="POST",
            body=dict(authored.to_dict()),
        )
        assert status == 200
        idempotency_key = "00000000-0000-4000-8000-000000008601"
        status, submission = _request(
            f"{base}/api/v2/research/runs",
            method="POST",
            body={"specification": resolution["exact_specification"]},
            headers={"Idempotency-Key": idempotency_key},
        )
        assert status == 202, submission
        queued = submission["run"]
        assert queued["state"] == "QUEUED"
        replay_status, replay = _request(
            f"{base}/api/v2/research/runs",
            method="POST",
            body={"specification": resolution["exact_specification"]},
            headers={"Idempotency-Key": idempotency_key},
        )
        assert replay_status == 202 and replay["submission_disposition"] == "REUSED"
        assert replay["run"]["run_id"] == queued["run_id"]

        worker = subprocess.Popen(
            worker_command,
            cwd=Path.cwd(),
            env=environment,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        completed = _wait_for(
            f"{base}/api/v2/research/runs/{queued['run_id']}",
            lambda status, body: status == 200 and body["state"] == "COMPLETED",
            timeout=60,
        )
        result = completed["result_ref"]
        artifact = completed["artifact_ref"]
        assert result and artifact
        summary_status, summary = _request(f"{base}/api/v2/research/artifacts/{result}")
        variables_status, variables = _request(f"{base}/api/v2/research/artifacts/{result}/variables")
        assert summary_status == variables_status == 200, (summary, variables)
        assert summary["research_result_fingerprint"] == result
        assert any(item["output_name"] == "value" for item in variables["series"])

        _stop(worker)
        worker = None
        _stop(api)
        backup = tmp_path.parent / f"{tmp_path.name}.dump"
        metadata_path = _backup(postgres_dsn, backup)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        tdb = datetime.fromisoformat(metadata["created_at"])
        assert metadata["backup_sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
        restore_root = tmp_path.parent / f"{tmp_path.name}-restored"
        shutil.copytree(tmp_path, restore_root)
        tfs = datetime.now(UTC)
        assert tfs >= tdb

        target_name = "onlyalpha_restore_test"
        target_dsn = postgres_dsn.rsplit("/", 1)[0] + f"/{target_name}"
        admin_dsn = postgres_dsn.rsplit("/", 1)[0] + "/postgres"
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (target_name,),
            )
            connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target_name)))
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
        _restore_test(postgres_dsn, target_dsn, backup, queued["run_id"])
        restored_run = OnlyPostgresResearchRunStore(target_dsn).load(OnlyResearchRunId(queued["run_id"]))
        assert restored_run.state.value == "COMPLETED"
        assert restored_run.research_result_fingerprint == result
        assert restored_run.artifact_content_fingerprint == artifact
        assert OnlyResearchDeploymentCoherenceVerifier(
            OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(restore_root).research_root),
            OnlyPostgresResearchDeploymentStore(target_dsn),
        ).verify()

        specification = OnlyResearchSpecification.from_dict(resolution["exact_specification"])
        services = only_default_engine_services(fail_fast=True)
        workload = (
            OnlyResearchSpecificationResolver(services.assembler.components.calculations)
            .resolve(specification)
            .workload
        )
        result_reader, artifact_reader = _semantic_readers(restore_root)
        restored_result = result_reader.load_verified(workload.result_plan.fingerprint)
        restored_artifact = artifact_reader.load_verified(result)
        assert restored_result.manifest.research_result_fingerprint == result
        assert restored_artifact.manifest.artifact_content_fingerprint == artifact

        restored_environment = {**environment, "ONLYALPHA_POSTGRES_DSN": target_dsn}
        restored_api_command = [*api_command[:-3], str(restore_root), "--port", str(port)]
        api = subprocess.Popen(
            restored_api_command,
            cwd=Path.cwd(),
            env=restored_environment,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for(f"{base}/health/ready", lambda status, body: status == 200 and body["status"] == "READY")
        _, restarted = _request(f"{base}/api/v2/research/runs/{queued['run_id']}")
        _, restored_summary = _request(f"{base}/api/v2/research/artifacts/{result}")
        assert restarted == completed
        assert restored_summary == summary
        _stop(api)

        missing_result_root = tmp_path.parent / f"{tmp_path.name}-missing-result"
        shutil.copytree(restore_root, missing_result_root)
        shutil.rmtree(OnlyUserDataLayout(missing_result_root).research_result_root)
        with pytest.raises(OnlyResearchResultStoreError):
            _semantic_readers(missing_result_root)[0].load_verified(workload.result_plan.fingerprint)

        missing_artifact_root = tmp_path.parent / f"{tmp_path.name}-missing-artifact"
        shutil.copytree(restore_root, missing_artifact_root)
        shutil.rmtree(OnlyUserDataLayout(missing_artifact_root).research_artifact_root)
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(missing_artifact_root)[1].load_verified(result)

        corrupt_artifact_root = tmp_path.parent / f"{tmp_path.name}-corrupt-artifact"
        shutil.copytree(restore_root, corrupt_artifact_root)
        manifest = next(OnlyUserDataLayout(corrupt_artifact_root).research_artifact_root.rglob("*manifest.json"))
        manifest.write_text("{}", encoding="utf-8")
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(corrupt_artifact_root)[1].load_verified(result)
        with pytest.raises(OnlyResearchArtifactStoreError):
            artifact_reader.load_verified("f" * 64)

        incoherent_root = tmp_path.parent / f"{tmp_path.name}-incoherent"
        OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(incoherent_root).research_root).initialize()
        assert OnlyPostgresResearchRunStore(target_dsn).load(restored_run.run_id).state.value == "COMPLETED"
        with pytest.raises(OnlyResearchDeploymentError) as incoherent:
            OnlyResearchDeploymentCoherenceVerifier(
                OnlyResearchSemanticStoreIdentity(OnlyUserDataLayout(incoherent_root).research_root),
                OnlyPostgresResearchDeploymentStore(target_dsn),
            ).verify()
        assert incoherent.value.code is OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH
        with pytest.raises(OnlyResearchArtifactStoreError):
            _semantic_readers(incoherent_root)[1].load_verified(result)
    finally:
        if worker is not None:
            _stop(worker)
        _stop(api)
        if target_name is not None and admin_dsn is not None:
            with psycopg.connect(admin_dsn, autocommit=True) as connection:
                connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (target_name,),
                )
                connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target_name)))
