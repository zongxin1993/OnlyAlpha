"""Read-only, generation-bound comparison of the admitted stateless Boolean/integer slice.

Observations are diagnostics, never Calculation equivalence Evidence or trading Authority.
The native executable is trusted deployment input, not an untrusted-code sandbox.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import platform
import re
import selectors
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from threading import BoundedSemaphore
from typing import Protocol, cast

from onlyalpha.application.runtime_generation import OnlyRuntimeWorkBindingEvidence
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import OnlyCalculationRegistry, OnlyTradingCalculationBackendResolver
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.distribution import OnlyArtifactCalculationImplementation, OnlyDistributionArtifactManifest
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

from .artifact_store import OnlyLocalImmutableArtifactStore
from .registry import OnlyRuntimeGenerationRegistry

_PROTOCOL = "ONLYALPHA_PREDICATE_DIAGNOSTIC_V2"
_LIMIT = 65536
_COMPARISON_SLOT = BoundedSemaphore(1)
_ARTIFACT_LIMIT = 64 * 1024 * 1024
_NAMES = frozenset(
    f"onlyalpha.predicate.internal.{name}"
    for name in (
        "boolean.and",
        "boolean.or",
        "boolean.not",
        "terminal.eligibility",
        "terminal.entry_signal",
        "terminal.exit_signal",
    )
)

_INTEGER_NAMES = frozenset(
    f"onlyalpha.predicate.internal.compare.{op}.integer.refs" for op in ("eq", "ne", "lt", "le", "gt", "ge")
)


class _Incremental(Protocol):
    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlyPredicateComparisonObservation:
    canonical_json: str


class _Unavailable(ValueError):
    pass


def _token(value: bool | int | None) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _valid_input(value: bool | int | None, integer: bool) -> bool:
    if value is None:
        return True
    if not integer:
        return type(value) is bool
    # Transport budget only: reject before decimal conversion/JSON capture.
    return type(value) is int and value.bit_length() <= 851 and len(str(abs(value))) <= 256


def _valid_token(value: str) -> bool:
    return value in ("true", "false", "null") or re.fullmatch(r"0|-?[1-9][0-9]{0,255}", value) is not None


@dataclass(frozen=True, slots=True)
class OnlyPredicateComparisonService:
    artifacts: OnlyLocalImmutableArtifactStore
    generations: OnlyRuntimeGenerationRegistry

    def observe(
        self,
        binding: OnlyRuntimeWorkBindingEvidence,
        definition: OnlyCalculationDefinition,
        rows: tuple[tuple[bool | int | None, ...], ...],
        native: OnlyDistributionArtifactManifest,
    ) -> OnlyPredicateComparisonObservation:
        integer = definition.type_id in _INTEGER_NAMES
        valid_rows = (
            type(rows) is tuple
            and 1 <= len(rows) <= 128
            and 1 <= len(definition.inputs) <= 2
            and all(
                type(row) is tuple
                and len(row) == len(definition.inputs)
                and all(_valid_input(value, integer) for value in row)
                for row in rows
            )
        )
        context = {
            "domain": "onlyalpha.predicate-comparison-diagnostic",
            "schema_version": 2,
            "binding": asdict(binding),
            "definition_fingerprint": definition.fingerprint,
            "definition": definition.semantic_payload(),
            "initial_state": "STATELESS_FRESH",
            "input_encoding": "INTEGER_DECIMAL_TEXT" if integer else "NULLABLE_BOOLEAN",
            "inputs": (tuple(tuple(None if v is None else str(v) for v in row) for row in rows) if integer else rows)
            if valid_rows
            else None,
            "native_artifact": native.to_dict(),
        }
        payload: dict[str, object] = {"context": context, "status": "UNAVAILABLE"}
        admitted = False
        try:
            if not _COMPARISON_SLOT.acquire(blocking=False):
                raise _Unavailable("PREDICATE_COMPARISON_BUSY")
            admitted = True
            if definition.kind is not OnlyCalculationKind.PREDICATE or definition.type_id not in (
                _NAMES | _INTEGER_NAMES
            ):
                raise _Unavailable("PREDICATE_COMPARISON_UNSUPPORTED")
            if not valid_rows:
                raise _Unavailable("PREDICATE_COMPARISON_INPUT_INVALID")
            calculations = OnlyCalculationRegistry()
            only_register_trading_predicate_primitives(calculations)
            reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
            if definition != calculations.rematerialize_definition(
                reference, definition.parameters, definition.input_bindings
            ):
                raise _Unavailable("PREDICATE_COMPARISON_DEFINITION_MISMATCH")
            registration = calculations.resolve(
                definition.kind, definition.type_id, definition.semantic_version, OnlyCalculationBackendKind.TRADING
            )
            implementation = registration.implementation_manifest
            if implementation is None or registration.state_capability is not OnlyCalculationStateCapability.STATELESS:
                raise _Unavailable("PREDICATE_COMPARISON_IMPLEMENTATION_UNAVAILABLE")
            payload["python_implementation"] = implementation.implementation_fingerprint
            lines = [
                f"{i}\t{definition.type_id}\t{definition.semantic_version}\t" + "\t".join(_token(v) for v in row)
                for i, row in enumerate(rows)
            ]
            frame_size = len(_PROTOCOL) + 66 + sum(len(line) + 1 for line in lines)
            if frame_size + 9 * len(rows) > _LIMIT:
                raise _Unavailable("PREDICATE_COMPARISON_INPUT_LIMIT")
            with self.generations.hold_work_binding_evidence(binding.work_id) as current:
                if current != binding:
                    raise _Unavailable("PREDICATE_COMPARISON_BINDING_MISMATCH")
                self.generations.verify_hosted_generation(binding.runtime_generation_fingerprint)
                generation = self.generations.require_work_generation(
                    binding.work_id, binding.runtime_generation_fingerprint
                )
                expected = OnlyArtifactCalculationImplementation(
                    definition.kind.value,
                    definition.type_id,
                    definition.semantic_version,
                    "TRADING",
                    implementation.implementation_fingerprint,
                )
                if expected not in generation.implementations:
                    raise _Unavailable("PREDICATE_COMPARISON_GENERATION_MISMATCH")
                context["python_generation"] = generation.to_dict()
                if native.native_target is None or native.artifact_size > _ARTIFACT_LIMIT:
                    raise _Unavailable("PREDICATE_COMPARISON_ARTIFACT_INVALID")
                stored, content = self.artifacts.fetch_exact(native.artifact_sha256, max_bytes=_ARTIFACT_LIMIT)
                if stored != native:
                    raise _Unavailable("PREDICATE_COMPARISON_ARTIFACT_MISMATCH")
                context_id = only_canonical_fingerprint(context)
                header = f"{_PROTOCOL}\t{context_id}\n"
                request = (header + "\n".join(lines) + "\n").encode("ascii")
                if len(request) > _LIMIT:
                    raise _Unavailable("PREDICATE_COMPARISON_INPUT_LIMIT")
                payload["request_sha256"] = hashlib.sha256(request).hexdigest()
                backend = cast(
                    _Incremental, OnlyTradingCalculationBackendResolver(calculations).create(definition, object())
                )
                outputs = tuple(
                    backend.update(dict(zip((item.name for item in definition.inputs), row, strict=True)))["value"]
                    for row in rows
                )
                if any(v is not None and type(v) is not bool for v in outputs):
                    raise _Unavailable("PREDICATE_COMPARISON_PYTHON_OUTPUT_INVALID")
                payload["python_outputs"] = outputs
                expected_reply = (
                    header
                    + "\n".join(
                        f"{row}\tOK\t{_token(cast(bool | None, value))}"
                        for row, value in zip(lines, outputs, strict=True)
                    )
                    + "\n"
                ).encode("ascii")
                response = _run_native(content, request, native.native_target)
                payload["native_output_sha256"] = hashlib.sha256(response).hexdigest()
                _validate_response(response, len(rows))
                payload["native_frame"] = response.decode("ascii")
                payload["status"] = "MATCH" if response == expected_reply else "MISMATCH"
        except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            payload["status"] = "UNAVAILABLE"
            payload["reason"] = str(exc) or type(exc).__name__
        finally:
            if admitted:
                _COMPARISON_SLOT.release()
        return OnlyPredicateComparisonObservation(only_canonical_json(payload))


def _validate_response(response: bytes, count: int) -> None:
    if len(response) > _LIMIT or not response.endswith(b"\n") or b"\r" in response:
        raise _Unavailable("PREDICATE_COMPARISON_RESPONSE_INVALID")
    try:
        lines = response.decode("ascii").splitlines()
        header = lines[0].split("\t")
        if (
            len(header) != 2
            or header[0] != _PROTOCOL
            or len(header[1]) != 64
            or any(c not in "0123456789abcdef" for c in header[1])
            or len(lines) != count + 1
        ):
            raise ValueError
        for line in lines[1:]:
            fields = line.split("\t")
            if (
                not 5 <= len(fields) <= 7
                or not fields[0].isdigit()
                or fields[0] != str(int(fields[0]))
                or not 0 <= int(fields[0]) < 128
                or not 1 <= len(fields[1]) <= 192
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789._" for c in fields[1])
                or not 1 <= len(fields[2]) <= 32
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-" for c in fields[2])
                or any(not _valid_token(value) for value in fields[3:-2])
            ):
                raise ValueError
            if (fields[-2] == "OK" and fields[-1] in ("true", "false", "null")) or (
                fields[-2] == "ERROR" and fields[-1] in ("UnknownType", "UnknownVersion", "InvalidArity")
            ):
                continue
            raise ValueError
    except (ValueError, IndexError, UnicodeError) as exc:
        raise _Unavailable("PREDICATE_COMPARISON_RESPONSE_INVALID") from exc


def _run_native(content: bytes, request: bytes, target: str) -> bytes:
    if (
        sys.platform != "linux"
        or {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}.get(platform.machine())
        != target
    ):
        raise _Unavailable("PREDICATE_COMPARISON_TARGET_UNAVAILABLE")
    descriptor = os.memfd_create("onlyalpha-predicate-diagnostic", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        with os.fdopen(os.dup(descriptor), "wb") as artifact_stream:
            artifact_stream.write(content)
        os.fchmod(descriptor, 0o500)
        fcntl.fcntl(
            descriptor,
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
        )
        with tempfile.TemporaryDirectory(prefix="onlyalpha-predicate-diagnostic-") as directory:
            process = subprocess.Popen(
                [f"/proc/self/fd/{descriptor}"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"LANG": "C"},
                cwd=directory,
                close_fds=True,
                pass_fds=(descriptor,),
            )
            try:
                assert process.stdin is not None and process.stdout is not None
                deadline = time.monotonic() + 3.0
                output = bytearray()
                offset = 0
                with selectors.DefaultSelector() as selector:
                    for stream, event in (
                        (process.stdin, selectors.EVENT_WRITE),
                        (process.stdout, selectors.EVENT_READ),
                    ):
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, event)
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("PREDICATE_COMPARISON_TIMEOUT")
                        events = selector.select(remaining)
                        if not events:
                            raise TimeoutError("PREDICATE_COMPARISON_TIMEOUT")
                        for key, _ in events:
                            if key.fileobj is process.stdin:
                                offset += os.write(process.stdin.fileno(), request[offset : offset + 4096])
                                if offset == len(request):
                                    selector.unregister(process.stdin)
                                    process.stdin.close()
                            else:
                                chunk = os.read(process.stdout.fileno(), 4096)
                                if not chunk:
                                    selector.unregister(process.stdout)
                                    process.stdout.close()
                                output.extend(chunk)
                                if len(output) > _LIMIT:
                                    raise _Unavailable("PREDICATE_COMPARISON_OUTPUT_LIMIT")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("PREDICATE_COMPARISON_TIMEOUT")
                if process.wait(timeout=remaining) != 0:
                    raise _Unavailable("PREDICATE_COMPARISON_PROCESS_FAILED")
                return bytes(output)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                for pipe in (process.stdin, process.stdout):
                    if pipe is not None:
                        pipe.close()
    finally:
        os.close(descriptor)
