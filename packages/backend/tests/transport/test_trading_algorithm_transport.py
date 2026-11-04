"""Installed pure arithmetic over the existing private Protobuf Node framing."""

from __future__ import annotations

import copy
import json
import os
import select
import struct
import subprocess
import time
from decimal import Decimal
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


def test_installed_trading_frames_execute_restore_and_reject_foreign_control(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    names = (
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    )
    initialize = _operation(
        "INITIALIZE",
        sources=[{key: fixture["revision"][key] for key in names}],
        nodes={str(i): node["definition"] for i, node in enumerate(fixture["graph"]["nodes"])},
    )
    operations = [initialize]
    operations += [_update("0", value=str(100 + i)) for i in range(20)]
    operations += [_update("1", value="1") for _ in range(20)]
    operations += [
        _operation("CHECKPOINT"),
        _update("0", value="120"),
        _update("1", value="21"),
        _update("2", close="120", close_lag_20="100", volume="21", volume_mean_20="2"),
        _operation("CHECKPOINT"),
        _operation("CLOSE"),
    ]
    responses = _run(root, artifact, operations)
    before = _record(responses[42])
    assert set(before) == {"schema_version", "nodes"}
    assert before["nodes"]["0"]["state"]["inputs"]["value"] == [str(100 + i) for i in range(20)]
    assert _record(responses[43])["outputs"]["value"]["type"] == "DECIMAL"
    assert Decimal(_record(responses[43])["outputs"]["value"]["value"]) == Decimal("100")
    assert Decimal(_record(responses[44])["outputs"]["value"]["value"]) == Decimal("2")
    assert Decimal(_record(responses[45])["outputs"]["value"]["value"]) == Decimal("2.1")
    after = _record(responses[46])
    for index, key in ((43, "0"), (44, "1"), (45, "2")):
        observation = _record(responses[index])
        assert set(observation) == {"outputs", "state"}
        assert observation["state"] == after["nodes"][key]
    assert _record(responses[47]) == {"closed": True}
    fresh = _run(root, artifact, [initialize, _operation("RESTORE", checkpoint=before), *operations[42:]])
    assert _record(fresh[2]) == before
    assert _record(fresh[-2]) == after
    # These are mathematical states only. Foreign lifecycle/authority fields are
    # rejected without advancing the active numerical session.
    tampered = copy.deepcopy(before)
    tampered["nodes"]["1"]["state"]["inputs"]["value"] = ["not-decimal"]
    rejected = _run(
        root,
        artifact,
        [
            initialize,
            _operation("RESTORE", checkpoint=tampered),
            _operation("CHECKPOINT", cursor={"revision": 999}),
            _operation("CHECKPOINT"),
            _operation("CLOSE"),
        ],
    )
    assert rejected[2].WhichOneof("outcome") == "error"
    assert rejected[3].WhichOneof("outcome") == "error"
    assert _record(rejected[4]) == _record(rejected[1])
    assert not any(key in after for key in ("cursor", "receipt", "grant", "runtime_generation", "authority"))


def test_installed_research_frames_observe_actual_trading_capabilities_without_rows(tmp_path: Path) -> None:
    """Actual installed metadata SPI, independent of Rust backend compilation."""
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    names = (
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    )
    request = {
        "schema_version": 1,
        "contract": "ONLYALPHA_TRADING_NODE_CAPABILITIES_V1",
        "sources": [{key: fixture["revision"][key] for key in names}],
        "definitions": [node["definition"] for node in fixture["graph"]["nodes"]],
    }
    assert "rows" not in request and "input" not in request
    # Independent expected observations come from the actual installed owning
    # registry and exact definitions, never a copied capability literal.
    oracle = subprocess.run(
        [
            str(root / "bin/python"),
            "-B",
            "-I",
            "-c",
            """
import json,sys
from onlyalpha.calculation.definition import OnlyCalculationDefinition,OnlyCalculationBackendKind
from onlyalpha_backend_algorithms.research_resolution import registry_for_sources
request=json.load(sys.stdin)
registry,_=registry_for_sources(request['sources'])
rows=[]
for raw in request['definitions']:
    definition=OnlyCalculationDefinition.from_dict(raw)
    actual=registry.resolve(definition.kind,definition.type_id,definition.semantic_version,OnlyCalculationBackendKind.TRADING)
    assert actual.implementation_manifest is not None and actual.state_capability is not None
    rows.append({'node_fingerprint':definition.fingerprint,'implementation_fingerprint':actual.implementation_manifest.implementation_fingerprint,'state_capability':actual.state_capability.value,'checkpoint_schema_version':actual.checkpoint_schema_version})
print(json.dumps(sorted(rows,key=lambda row:row['node_fingerprint'])))
""",
        ],
        input=json.dumps(request).encode(),
        capture_output=True,
        env={},
        timeout=20,
    )
    assert oracle.returncode == 0, oracle.stderr.decode(errors="replace")
    expected = json.loads(oracle.stdout)
    assert any(row["state_capability"] == "CHECKPOINTABLE" for row in expected)

    def observe(payload: dict[str, Any]) -> wire.CalculationResponse:
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
            message = wire.CalculationRequest(protocol_version=1, generation=GENERATION, sequence=2)
            message.research_resolve.request_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            raw = message.SerializeToString(deterministic=True)
            result, stderr = process.communicate(input=struct.pack("!I", len(raw)) + raw, timeout=20)
            assert process.returncode == 0, stderr.decode(errors="replace")
            assert len(result) >= 4
            size = struct.unpack("!I", result[:4])[0]
            assert 0 < size <= MAX_FRAME and len(result) == size + 4
            response = wire.CalculationResponse.FromString(result[4:])
            assert response.protocol_version == 1 and response.generation == GENERATION
            assert response.sequence == 2 and response.artifact_fingerprint == artifact
            return response
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

    observed = _record(observe(request))
    assert observed == {
        "schema_version": 1,
        "contract": request["contract"],
        "nodes": expected,
        "isolation": "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1",
    }
    # Mathematical rows, unexpected schemas and duplicate nodes are not this
    # metadata-only contract; none may initialize a numerical session.
    for invalid in (
        {**request, "rows": []},
        {**request, "schema_version": True},
        {**request, "definitions": request["definitions"] * 2},
    ):
        assert observe(invalid).WhichOneof("outcome") == "error"
