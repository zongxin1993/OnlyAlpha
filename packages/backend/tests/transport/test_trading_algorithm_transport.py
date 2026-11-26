"""Installed Protobuf framing for source-only refusal and authorized Target resolution."""

from __future__ import annotations

import hashlib
import json
import os
import select
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

GENERATION = "a" * 64
MAX_FRAME = 8 * 1024 * 1024


def _frame(sequence: int, payload: dict[str, Any] | None) -> bytes:
    request = wire.CalculationRequest(protocol_version=1, generation=GENERATION, sequence=sequence)
    if payload is None:
        request.handshake.SetInParent()
    else:
        request.node.request_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    raw = request.SerializeToString(deterministic=True)
    return struct.pack("!I", len(raw)) + raw


def _handshake(process: subprocess.Popen[bytes]) -> wire.CalculationResponse:
    assert process.stdout is not None
    deadline = time.monotonic() + 10

    def read(count: int) -> bytes:
        result = bytearray()
        while len(result) < count:
            left = deadline - time.monotonic()
            assert left > 0 and select.select([process.stdout], [], [], left)[0], "worker handshake deadline"
            chunk = os.read(process.stdout.fileno(), count - len(result))
            if not chunk:
                process.wait(timeout=5)
                diagnostic = b"" if process.stderr is None else process.stderr.read()
                raise AssertionError(
                    "installed worker exited before its handshake: " + diagnostic.decode(errors="replace")
                )
            result.extend(chunk)
        return bytes(result)

    size = struct.unpack("!I", read(4))[0]
    assert 0 < size <= MAX_FRAME
    return wire.CalculationResponse.FromString(read(size))


def _run(root: Path, artifact: str, payloads: list[dict[str, Any]]) -> list[wire.CalculationResponse]:
    process = subprocess.Popen(
        [
            str(root / "bin/python"),
            "-B",
            "-I",
            "-m",
            "onlyalpha_backend_algorithms.trading_worker",
            "--generation",
            GENERATION,
            "--installation",
            str(root),
            "--artifact",
            artifact,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={},
    )
    try:
        assert process.stdin is not None
        process.stdin.write(_frame(1, None))
        process.stdin.flush()
        handshake = _handshake(process)
        assert handshake.protocol_version == 1 and handshake.generation == GENERATION
        assert handshake.sequence == 1 and handshake.artifact_fingerprint == artifact
        result = _record(handshake)
        assert result == {
            "schema_version": 1,
            "contract": "ONLYALPHA_TRADING_NUMERICS_V1",
            "max_nodes": 128,
            "max_frame": MAX_FRAME,
            "isolation": "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1",
        }

        # The normal handshake is the deterministic barrier. Observe the real
        # child restrictions; a static isolation label cannot satisfy this check.
        def status(pid: int) -> dict[str, str]:
            return dict(
                line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line
            )

        parent, child = status(os.getpid()), status(process.pid)
        assert child["NoNewPrivs"].strip() == "1" and child["Seccomp"].strip() == "2"
        assert int(child["Seccomp_filters"]) > int(parent["Seccomp_filters"])
        raw, stderr = process.communicate(input=b"".join(_frame(i, p) for i, p in enumerate(payloads, 2)), timeout=20)
        assert process.returncode == 0, stderr.decode(errors="replace")
        responses = [handshake]
        while raw:
            assert len(raw) >= 4
            size = struct.unpack("!I", raw[:4])[0]
            assert 0 < size <= MAX_FRAME and len(raw) >= size + 4
            response = wire.CalculationResponse.FromString(raw[4 : size + 4])
            assert response.protocol_version == 1 and response.generation == GENERATION
            assert response.artifact_fingerprint == artifact and response.sequence == len(responses) + 1
            responses.append(response)
            raw = raw[size + 4 :]
        assert len(responses) == len(payloads) + 1
        return responses
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def _record(response: wire.CalculationResponse) -> dict[str, Any]:
    assert response.WhichOneof("outcome") == "result", response
    return json.loads(response.result.record_json)


def _operation(op: str, **values: Any) -> dict[str, Any]:
    return {"schema_version": 1, "op": op, **values}


def _update(node: str, **values: str) -> dict[str, Any]:
    return _operation("UPDATE", node=node, inputs={k: {"type": "DECIMAL", "value": v} for k, v in values.items()})


def _private_definition(fixture: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from onlyalpha.calculation.definition import OnlyCalculationReference
    from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
    from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

    source = {key: fixture["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
    record = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(source)
    definition = execution.OnlyPrivateFactorDefinitionResolverV1(
        execution.only_private_factor_type_definition(record)
    ).resolve({}, {name: OnlyCalculationReference(None, "value", name) for name in record.input_contract})
    return source, dict(definition.to_dict())


def test_installed_trading_frames_refuse_source_only_initialization_and_control(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source, definition = _private_definition(fixture)
    initialize = _operation("INITIALIZE", sources=[source], nodes={"factor": definition})
    rejected = _run(
        root,
        artifact,
        [
            initialize,
            _update("factor", close="120", close_lag_20="100", volume="21", volume_mean_20="2"),
            _operation("RESTORE", checkpoint={"schema_version": 1, "nodes": {}}),
            _operation("CHECKPOINT"),
            _operation("CLOSE", cursor={"revision": 999}),
            _operation("CLOSE"),
        ],
    )
    for response in rejected[1:-1]:
        assert response.WhichOneof("outcome") == "error"
        assert response.error.code == "REQUEST_REJECTED"
    assert _record(rejected[-1]) == {"closed": True}


def test_installed_research_frames_resolve_only_target_metadata_without_rows(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    wheels = tmp_path / "wheels"
    artifact = install(wheels, root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source, factor = _private_definition(fixture)

    def wheel(pattern: str) -> dict[str, Any]:
        path = next(wheels.glob(pattern))
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "distribution_version": path.name.split("-")[1],
        }

    initialization = {
        "schema_version": 1,
        "contract": "ONLYALPHA_AUTHORING_SESSION_V1",
        "sources": [],
        "core_artifact": wheel("onlyalpha-*.whl"),
        "target_artifact": wheel("onlyalpha_backend_algorithms-*.whl"),
    }
    request = {
        "schema_version": 1,
        "contract": "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1",
        "type_reference": {"kind": "TARGET", "type_id": "onlyalpha.target.forward_return", "semantic_version": "1"},
        "parameters": {"exit_offset": {"type": "INTEGER", "value": 5}},
        "input_bindings": {
            name: {"node_fingerprint": None, "output_name": "value", "source": "bar.close"}
            for name in ("entry_price", "exit_price")
        },
    }

    def observe(
        payload: dict[str, Any], *, rejected: bool = False, sources: list[dict[str, Any]] | None = None
    ) -> wire.CalculationResponse:
        process = subprocess.Popen(
            [
                str(root / "bin/python"),
                "-B",
                "-I",
                "-m",
                "onlyalpha_backend_algorithms.research_worker",
                "--generation",
                GENERATION,
                "--installation",
                str(root),
                "--artifact",
                artifact,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={},
        )
        try:
            assert process.stdin is not None
            process.stdin.write(_frame(1, None))
            process.stdin.flush()
            handshake = _handshake(process)
            assert handshake.protocol_version == 1 and handshake.generation == GENERATION
            assert handshake.sequence == 1 and handshake.artifact_fingerprint == artifact
            assert _record(handshake)["contract"] == "ONLYALPHA_PRIVATE_FACTOR_RESOLVE_V1"
            selected_initialization = {
                **initialization,
                "sources": sources or [],
            }
            # The real worker is persistent after INITIALIZE. A final known
            # invalid resolve closes a successful session deterministically;
            # EOF/kill is not accepted as positive completion of this test.
            terminal = {**request, "schema_version": True}
            requests = [selected_initialization, payload, terminal]
            frames = []
            for sequence, item in enumerate(requests, 2):
                message = wire.CalculationRequest(protocol_version=1, generation=GENERATION, sequence=sequence)
                message.research_resolve.request_json = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
                raw = message.SerializeToString(deterministic=True)
                frames.append(struct.pack("!I", len(raw)) + raw)
            result, stderr = process.communicate(input=b"".join(frames), timeout=20)
            assert process.returncode == 0, stderr.decode(errors="replace")
            responses = []
            while result:
                assert len(result) >= 4
                size = struct.unpack("!I", result[:4])[0]
                assert 0 < size <= MAX_FRAME and len(result) >= size + 4
                response = wire.CalculationResponse.FromString(result[4 : size + 4])
                assert response.protocol_version == 1 and response.generation == GENERATION
                assert response.sequence == len(responses) + 2 and response.artifact_fingerprint == artifact
                responses.append(response)
                result = result[size + 4 :]
            assert len(responses) == (1 if sources else 2 if rejected else 3)
            if sources:
                return responses[0]
            admitted = _record(responses[0])
            assert admitted["contract"] == initialization["contract"]
            assert admitted["schema_version"] == 1 and admitted["algorithm_artifact"] == artifact
            assert admitted["source_artifacts"] == []
            assert admitted["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
            for kind in ("core", "target"):
                assert admitted[f"{kind}_artifact_sha256"] == initialization[f"{kind}_artifact"]["sha256"]
                assert len(admitted[f"{kind}_resources_fingerprint"]) == 64
            if not rejected:
                assert responses[2].WhichOneof("outcome") == "error"
                assert responses[2].error.code == "REQUEST_REJECTED"
            return responses[1]
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

    observed = _record(observe(request))
    definition = observed["definition"]
    assert {key: definition[key] for key in request["type_reference"]} == request["type_reference"]
    assert definition["input_bindings"] == request["input_bindings"]
    assert definition["parameters"] == {
        "entry_offset": {"type": "INTEGER", "value": 0},
        "exit_offset": {"type": "INTEGER", "value": 5},
    }
    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    assert observed["definition_fingerprint"] == OnlyCalculationDefinition.from_dict(definition).fingerprint
    assert [row["backend_kind"] for row in observed["implementations"]] == ["RESEARCH"]
    assert observed["trading_capability"] is None
    # Valid Target metadata must not make this a batch, Trading, or Factor endpoint.
    for invalid in (
        {**request, "rows": []},
        {**request, "schema_version": True},
        {**request, "definitions": [definition, definition]},
        {
            **request,
            "type_reference": {key: factor[key] for key in request["type_reference"]},
            "parameters": factor["parameters"],
            "input_bindings": factor["input_bindings"],
        },
    ):
        response = observe(invalid, rejected=True)
        assert response.WhichOneof("outcome") == "error"
        assert response.error.code == "REQUEST_REJECTED"
    for sources in ([source], [source, source]):
        response = observe(request, sources=sources)
        assert response.WhichOneof("outcome") == "error"
        assert response.error.code == "REQUEST_REJECTED"
