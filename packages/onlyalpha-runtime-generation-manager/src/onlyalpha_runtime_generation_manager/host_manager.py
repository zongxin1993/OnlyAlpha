"""Single-flight host manager for exact generation-isolated Search workers."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Any, cast

from onlyalpha.application.search_generation_execution import (
    ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
    ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION,
    OnlyHistoricalGenerationArtifactMissing,
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationCorrupt,
    OnlyHistoricalGenerationExecutionError,
    OnlyHistoricalGenerationExecutionMismatch,
    OnlyHistoricalGenerationHostMismatch,
    OnlyHistoricalGenerationNotFound,
    OnlyHistoricalGenerationProtocolMismatch,
    OnlyHistoricalGenerationUnavailable,
    OnlyHistoricalGenerationWorkerUnavailable,
    OnlySearchGenerationExecutionFailureV1,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationWorkerHandshakeV1,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.runtime.generation import (
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
)

from .builder import OnlyRuntimeGenerationBuilder
from .registry import OnlyRuntimeGenerationRegistry


@dataclass(slots=True)
class _HostedWorker:
    process: subprocess.Popen[str]
    handshake: OnlySearchGenerationWorkerHandshakeV1
    lock: Lock


class OnlyHistoricalGenerationHostManager:
    """Infrastructure projection from one exact G to one reusable isolated process."""

    def __init__(
        self,
        *,
        registry: OnlyRuntimeGenerationRegistry,
        builder: OnlyRuntimeGenerationBuilder,
        cache_root: Path,
        startup_timeout_seconds: float = 30.0,
    ) -> None:
        if startup_timeout_seconds <= 0:
            raise ValueError("HISTORICAL_GENERATION_HOST_TIMEOUT_INVALID")
        self._registry = registry
        self._builder = builder
        self._cache_root = cache_root.resolve()
        self._startup_timeout = startup_timeout_seconds
        self._guard = RLock()
        self._generation_locks: dict[str, RLock] = {}
        self._workers: dict[str, _HostedWorker] = {}

    def execute(
        self,
        request: OnlySearchGenerationExecutionRequestV1,
    ) -> OnlySearchGenerationExecutionResponseV1:
        worker = self.acquire(request.runtime_generation_fingerprint)
        with worker.lock:
            if request.operation_kind not in worker.handshake.supported_capabilities:
                raise OnlyHistoricalGenerationCapabilityUnsupported(request.operation_kind.value)
            if worker.process.poll() is not None:
                self._forget(request.runtime_generation_fingerprint, worker)
                raise OnlyHistoricalGenerationWorkerUnavailable(request.runtime_generation_fingerprint)
            try:
                assert worker.process.stdin is not None
                worker.process.stdin.write(only_canonical_json(request.to_dict()) + "\n")
                worker.process.stdin.flush()
                payload = self._read_line(worker.process)
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._forget(request.runtime_generation_fingerprint, worker)
                raise OnlyHistoricalGenerationWorkerUnavailable(request.runtime_generation_fingerprint) from exc
            try:
                if "error_code" in payload:
                    failure = OnlySearchGenerationExecutionFailureV1.from_dict(payload)
                    if failure.runtime_generation_fingerprint != request.runtime_generation_fingerprint:
                        raise OnlyHistoricalGenerationHostMismatch(request.runtime_generation_fingerprint)
                    failure.raise_error()
                response = OnlySearchGenerationExecutionResponseV1.from_dict(payload)
                if (
                    response.runtime_generation_fingerprint != request.runtime_generation_fingerprint
                    or response.operation_kind is not request.operation_kind
                ):
                    raise OnlyHistoricalGenerationExecutionMismatch(request.runtime_generation_fingerprint)
            except (
                OnlyHistoricalGenerationProtocolMismatch,
                OnlyHistoricalGenerationHostMismatch,
                OnlyHistoricalGenerationExecutionMismatch,
            ):
                self._forget(request.runtime_generation_fingerprint, worker)
                raise
            return response

    def acquire(self, generation_fingerprint: str) -> _HostedWorker:
        lock = self._generation_lock(generation_fingerprint)
        with lock:
            with self._guard:
                existing = self._workers.get(generation_fingerprint)
            if existing is not None and existing.process.poll() is None:
                return existing
            if existing is not None:
                self._forget(generation_fingerprint, existing)
            manifest, evidence = self._load_exact(generation_fingerprint)
            environment = self._environment_root(generation_fingerprint)
            if not environment.exists():
                self._rebuild(manifest, evidence, environment)
            worker = self._spawn(environment, evidence)
            try:
                self._verify_handshake(worker.handshake, manifest, evidence)
            except Exception:
                self._terminate(worker.process)
                raise
            with self._guard:
                self._workers[generation_fingerprint] = worker
            return worker

    def evict(self, generation_fingerprint: str, *, delete_environment: bool = False) -> None:
        """Discard non-semantic hosted projections; immutable generation facts remain untouched."""

        lock = self._generation_lock(generation_fingerprint)
        with lock:
            with self._guard:
                worker = self._workers.pop(generation_fingerprint, None)
            if worker is not None:
                self._terminate(worker.process)
            if delete_environment:
                target = self._environment_root(generation_fingerprint)
                if target.parent != self._cache_root:
                    raise OnlyHistoricalGenerationHostMismatch(generation_fingerprint)
                shutil.rmtree(target, ignore_errors=True)

    def close(self) -> None:
        with self._guard:
            workers = tuple(self._workers.values())
            self._workers.clear()
        for worker in workers:
            self._terminate(worker.process)

    def _load_exact(
        self,
        generation_fingerprint: str,
    ) -> tuple[OnlyRuntimeGenerationManifest, OnlyRuntimeGenerationValidationEvidence]:
        try:
            manifest = self._registry.require_runtime_generation(generation_fingerprint)
            evidence = self._registry.load_validation_evidence(generation_fingerprint)
        except Exception as exc:
            code = str(exc)
            if code == "RUNTIME_GENERATION_NOT_FOUND":
                raise OnlyHistoricalGenerationNotFound(generation_fingerprint) from exc
            if code == "RUNTIME_GENERATION_UNAVAILABLE":
                raise OnlyHistoricalGenerationUnavailable(generation_fingerprint) from exc
            raise OnlyHistoricalGenerationCorrupt(generation_fingerprint) from exc
        if (
            manifest.runtime_generation_fingerprint != generation_fingerprint
            or evidence.runtime_generation_fingerprint != generation_fingerprint
            or not evidence.verifies(manifest)
        ):
            raise OnlyHistoricalGenerationCorrupt(generation_fingerprint)
        return manifest, evidence

    def _rebuild(
        self,
        manifest: OnlyRuntimeGenerationManifest,
        evidence: OnlyRuntimeGenerationValidationEvidence,
        environment: Path,
    ) -> None:
        try:
            rebuilt = self._builder.rebuild_validated(
                expected_manifest=manifest,
                environment_root=environment,
            )
        except Exception as exc:
            code = str(exc)
            if "ARTIFACT" in code and ("MISMATCH" not in code and "CORRUPT" not in code):
                raise OnlyHistoricalGenerationArtifactMissing(manifest.runtime_generation_fingerprint) from exc
            if "ARTIFACT" in code or "MISMATCH" in code or "INVALID" in code:
                raise OnlyHistoricalGenerationCorrupt(manifest.runtime_generation_fingerprint) from exc
            raise OnlyHistoricalGenerationUnavailable(manifest.runtime_generation_fingerprint) from exc
        if rebuilt.manifest != manifest or rebuilt.validation_evidence != evidence:
            shutil.rmtree(environment, ignore_errors=True)
            raise OnlyHistoricalGenerationCorrupt(manifest.runtime_generation_fingerprint)

    def _spawn(
        self,
        environment: Path,
        evidence: OnlyRuntimeGenerationValidationEvidence,
    ) -> _HostedWorker:
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            raise OnlyHistoricalGenerationCorrupt(evidence.runtime_generation_fingerprint)
        try:
            process = subprocess.Popen(
                [str(python), "-I", "-m", "onlyalpha_runtime_generation_manager.search_worker"],
                cwd=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=self._builder._isolated_environment(),
                shell=False,
            )
            assert process.stdin is not None
            process.stdin.write(
                only_canonical_json(
                    {
                        "schema_version": ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION,
                        "execution_contract_version": ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
                        "validation_evidence": evidence.to_dict(),
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            payload = self._read_line(process)
            if "error_code" in payload:
                failure = OnlySearchGenerationExecutionFailureV1.from_dict(payload)
                self._terminate(process)
                failure.raise_error()
            handshake = OnlySearchGenerationWorkerHandshakeV1.from_dict(payload)
            return _HostedWorker(process, handshake, Lock())
        except OnlyHistoricalGenerationWorkerUnavailable as exc:
            if "process" in locals():
                self._terminate(process)
            raise OnlyHistoricalGenerationCapabilityUnsupported(evidence.runtime_generation_fingerprint) from exc
        except OnlyHistoricalGenerationExecutionError:
            raise
        except (BrokenPipeError, OSError, ValueError) as exc:
            if "process" in locals():
                self._terminate(process)
            raise OnlyHistoricalGenerationCapabilityUnsupported(evidence.runtime_generation_fingerprint) from exc

    def _verify_handshake(
        self,
        handshake: OnlySearchGenerationWorkerHandshakeV1,
        manifest: OnlyRuntimeGenerationManifest,
        evidence: OnlyRuntimeGenerationValidationEvidence,
    ) -> None:
        if (
            handshake.runtime_generation_fingerprint != manifest.runtime_generation_fingerprint
            or handshake.core_execution_fingerprint != manifest.core_execution.fingerprint
            or handshake.catalog_generation_fingerprint != manifest.catalog_generation_fingerprint
            or handshake.validation_evidence_fingerprint != evidence.validation_evidence_fingerprint
        ):
            raise OnlyHistoricalGenerationHostMismatch(manifest.runtime_generation_fingerprint)

    def _read_line(self, process: subprocess.Popen[str]) -> dict[str, object]:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], self._startup_timeout)
        if not ready:
            self._terminate(process)
            raise OnlyHistoricalGenerationWorkerUnavailable("worker response timeout")
        line = process.stdout.readline()
        if not line:
            raise OnlyHistoricalGenerationWorkerUnavailable("worker closed its response stream")
        try:
            payload: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OnlyHistoricalGenerationProtocolMismatch("worker emitted non-JSON") from exc
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise OnlyHistoricalGenerationProtocolMismatch("worker envelope is not an object")
        return cast(dict[str, object], payload)

    def _generation_lock(self, generation_fingerprint: str) -> RLock:
        if len(generation_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in generation_fingerprint
        ):
            raise OnlyHistoricalGenerationProtocolMismatch("Runtime Generation fingerprint is invalid")
        with self._guard:
            return self._generation_locks.setdefault(generation_fingerprint, RLock())

    def _environment_root(self, generation_fingerprint: str) -> Path:
        return self._cache_root / generation_fingerprint

    def _forget(self, generation_fingerprint: str, worker: _HostedWorker) -> None:
        with self._guard:
            if self._workers.get(generation_fingerprint) is worker:
                self._workers.pop(generation_fingerprint, None)
        self._terminate(worker.process)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


__all__ = ["OnlyHistoricalGenerationHostManager"]
