"""Single-flight host manager for exact generation-isolated Search workers."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, RLock
from typing import TYPE_CHECKING, Any, cast

from onlyalpha.application.search_generation_execution import (
    ONLYALPHA_CHART_CALCULATION_EXECUTION_MAX_WIRE_BYTES,
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
    OnlySearchGenerationOperationV1,
    OnlySearchGenerationWorkerHandshakeV1,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.runtime.generation import (
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
)

from .builder import OnlyRuntimeGenerationBuilder
from .registry import OnlyRuntimeGenerationRegistry

if TYPE_CHECKING:
    from onlyalpha.application.chart_calculation_execution import OnlyChartCalculationExecutionProjectionV1


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
        self._chart_execution_lock = Lock()

    def execute(
        self,
        request: OnlySearchGenerationExecutionRequestV1,
    ) -> OnlySearchGenerationExecutionResponseV1:
        if request.operation_kind is OnlySearchGenerationOperationV1.EXECUTE_CHART_CALCULATION_PROJECTION:
            raise OnlyHistoricalGenerationCapabilityUnsupported("numeric execution requires issued Chart port")
        worker = (
            self._acquire(request.runtime_generation_fingerprint, historical_compilation=True)
            if request.operation_kind is OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_CALCULATION_PUBLICATION
            else self.acquire(request.runtime_generation_fingerprint)
        )
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

    def execute_chart_calculation(
        self, capability: object, *, cancellation: Event | None = None
    ) -> OnlyChartCalculationExecutionProjectionV1:
        from onlyalpha.application.chart_calculation_execution import (
            OnlyChartCalculationExecutionProjectionV1,
            _only_consume_chart_execution_request,
            _OnlyIssuedChartCalculationExecutionRequest,
            only_require_chart_execution_not_cancelled,
        )

        request = _only_consume_chart_execution_request(capability)
        assert isinstance(capability, _OnlyIssuedChartCalculationExecutionRequest)
        only_require_chart_execution_not_cancelled(cancellation)
        if not self._chart_execution_lock.acquire(blocking=False):
            raise OnlyHistoricalGenerationWorkerUnavailable("Chart numeric host is busy")
        worker = None
        locked = False
        generation = request.compilation.runtime_generation_fingerprint
        try:
            # Reconstruction is the existing Infrastructure lifecycle, not numeric
            # execution. D2 normally warmed this exact environment. A cold/missing
            # environment fails closed until explicitly prepared by that owner.
            generation_lock = self._generation_lock(generation)
            if not generation_lock.acquire(blocking=False):
                raise OnlyHistoricalGenerationWorkerUnavailable("exact generation startup is busy")
            try:
                worker = self._acquire(generation, historical_compilation=False, allow_rebuild=False)
            finally:
                generation_lock.release()
            locked = worker.lock.acquire(blocking=False)
            if not locked:
                raise OnlyHistoricalGenerationWorkerUnavailable("exact generation host is busy")
            operation = OnlySearchGenerationOperationV1.EXECUTE_CHART_CALCULATION_PROJECTION
            if operation not in worker.handshake.supported_capabilities:
                raise OnlyHistoricalGenerationCapabilityUnsupported(operation.value)
            # Eligibility sampled after acquisition, immediately before dispatch, not
            # before an unbounded queue. No database transaction spans numeric work.
            capability.validate_dispatch()
            self._load_exact(generation)
            envelope = OnlySearchGenerationExecutionRequestV1(generation, operation, request.to_dict())
            raw = self._exchange_chart(
                worker.process, envelope.to_dict(), cancellation, dispatch_guard=capability.hold_dispatch()
            )
            if worker.process.poll() is not None:
                raise OnlyHistoricalGenerationWorkerUnavailable("Chart worker lost before completion")
            if "error_code" in raw:
                failure = OnlySearchGenerationExecutionFailureV1.from_dict(raw)
                if failure.runtime_generation_fingerprint != generation:
                    raise OnlyHistoricalGenerationHostMismatch(generation)
                failure.raise_error()
            response = OnlySearchGenerationExecutionResponseV1.from_dict(raw)
            if response.runtime_generation_fingerprint != generation or response.operation_kind is not operation:
                raise OnlyHistoricalGenerationExecutionMismatch("Chart response envelope differs")
            projection = OnlyChartCalculationExecutionProjectionV1.from_dict(response.result_payload, request=request)
            self._load_exact(generation)
            capability.validate_dispatch()
            only_require_chart_execution_not_cancelled(cancellation)
            return projection
        except Exception:
            if worker is not None and locked:
                self._forget(generation, worker)
            raise
        finally:
            if worker is not None and locked:
                worker.lock.release()
            self._chart_execution_lock.release()

    def _exchange_chart(
        self,
        process: subprocess.Popen[str],
        request: Mapping[str, object],
        cancellation: Event | None,
        *,
        dispatch_guard: AbstractContextManager[None] | None = None,
    ) -> dict[str, object]:
        """Bound both pipe directions and the whole line, including partial-line stalls."""
        if process.poll() is not None or process.stdin is None or process.stdout is None:
            raise OnlyHistoricalGenerationWorkerUnavailable("Chart worker unavailable")
        payload = (only_canonical_json(request) + "\n").encode("utf-8")
        if len(payload) > ONLYALPHA_CHART_CALCULATION_EXECUTION_MAX_WIRE_BYTES:
            raise OnlyHistoricalGenerationProtocolMismatch("Chart request exceeds transport limit")
        input_fd, output_fd = process.stdin.fileno(), process.stdout.fileno()
        input_blocking, output_blocking = os.get_blocking(input_fd), os.get_blocking(output_fd)
        deadline = time.monotonic() + self._startup_timeout
        received = bytearray()
        sent = 0
        fences = ExitStack()
        try:
            os.set_blocking(input_fd, False)
            os.set_blocking(output_fd, False)
            if dispatch_guard is not None:
                fences.enter_context(dispatch_guard)
            while True:
                if cancellation is not None and cancellation.is_set():
                    from onlyalpha.application.chart_calculation import OnlyChartCalculationError

                    raise OnlyChartCalculationError("CHART_EXECUTION_CANCELLED")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OnlyHistoricalGenerationWorkerUnavailable("Chart execution response timeout")
                readable, writable, _ = select.select(
                    [output_fd], [input_fd] if sent < len(payload) else [], [], min(remaining, 0.1)
                )
                if writable:
                    sent += os.write(input_fd, payload[sent : sent + 65536])
                    if sent == len(payload):
                        # Linearization: the complete command becomes visible while
                        # original Run and Runtime are fenced. Numerical wait holds no fence.
                        fences.close()
                if readable:
                    chunk = os.read(output_fd, 65536)
                    if not chunk:
                        raise OnlyHistoricalGenerationWorkerUnavailable("Chart worker closed response stream")
                    received.extend(chunk)
                    if len(received) > ONLYALPHA_CHART_CALCULATION_EXECUTION_MAX_WIRE_BYTES:
                        raise OnlyHistoricalGenerationProtocolMismatch("Chart response exceeds transport limit")
                    if b"\n" in received:
                        line, trailing = bytes(received).split(b"\n", 1)
                        if trailing or sent != len(payload):
                            raise OnlyHistoricalGenerationProtocolMismatch("Chart response framing differs")
                        raw: Any = json.loads(line)
                        if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
                            raise OnlyHistoricalGenerationProtocolMismatch("Chart response is not an object")
                        return cast(dict[str, object], raw)
        except (BrokenPipeError, OSError) as exc:
            raise OnlyHistoricalGenerationWorkerUnavailable("Chart worker transport lost") from exc
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise OnlyHistoricalGenerationProtocolMismatch("Chart worker emitted invalid JSON") from exc
        except ValueError as exc:
            if getattr(exc, "code", None) == "CHART_EXECUTION_CANCELLED":
                raise
            raise OnlyHistoricalGenerationWorkerUnavailable("Chart worker pipe closed") from exc
        finally:
            fences.close()
            if not process.stdin.closed:
                os.set_blocking(input_fd, input_blocking)
            if not process.stdout.closed:
                os.set_blocking(output_fd, output_blocking)

    def acquire(self, generation_fingerprint: str) -> _HostedWorker:
        return self._acquire(generation_fingerprint, historical_compilation=False)

    def _acquire(
        self, generation_fingerprint: str, *, historical_compilation: bool, allow_rebuild: bool = True
    ) -> _HostedWorker:
        lock = self._generation_lock(generation_fingerprint)
        with lock:
            # Revalidate before cache reuse: a compilation worker is not permission
            # for any legacy operation to execute against a retired Generation.
            manifest, evidence = (
                self._load_exact(generation_fingerprint, historical_compilation=True)
                if historical_compilation
                else self._load_exact(generation_fingerprint)
            )
            with self._guard:
                existing = self._workers.get(generation_fingerprint)
            environment = self._environment_root(generation_fingerprint)
            if not allow_rebuild and not environment.is_dir():
                raise OnlyHistoricalGenerationWorkerUnavailable("exact Chart host environment is not prepared")
            if existing is not None and existing.process.poll() is None:
                return existing
            if existing is not None:
                self._forget(generation_fingerprint, existing)
            if not environment.exists():
                if not allow_rebuild:
                    raise OnlyHistoricalGenerationWorkerUnavailable("exact Chart host environment is not prepared")
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
        *,
        historical_compilation: bool = False,
    ) -> tuple[OnlyRuntimeGenerationManifest, OnlyRuntimeGenerationValidationEvidence]:
        try:
            manifest = (
                self._registry.require_historical_generation(generation_fingerprint)
                if historical_compilation
                else self._registry.require_runtime_generation(generation_fingerprint)
            )
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
            payload = self._exchange_chart(
                process,
                {
                    "schema_version": ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION,
                    "execution_contract_version": ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
                    "validation_evidence": evidence.to_dict(),
                },
                None,
            )
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
            if "process" in locals():
                self._terminate(process)
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
