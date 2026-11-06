"""Installed private Factor SPI over the existing private Protobuf Node framing."""

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


def test_installed_trading_frames_execute_restore_and_reject_foreign_control(tmp_path: Path) -> None:
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source, definition = _private_definition(fixture)
    initialize = _operation("INITIALIZE", sources=[source], nodes={"factor": definition})
    operands = {"close": "120", "close_lag_20": "100", "volume": "21", "volume_mean_20": "2"}
    # The Python SPI receives explicit operands; native windows and graph cursors
    # are exercised by the actual installed Rust graph tests.
    prefix = [_update("factor", **operands) for _ in range(20)]
    tail = [
        _update("factor", **operands),
        _update("factor", **{**operands, "close": "121", "close_lag_20": "101", "volume": "1"}),
        _update("factor", **{**operands, "volume": "0", "volume_mean_20": "0"}),
        _operation("CHECKPOINT"),
        _operation("CLOSE"),
    ]
    responses = _run(root, artifact, [initialize, *prefix, _operation("CHECKPOINT"), *tail])
    before = _record(responses[22])
    assert set(before) == {"schema_version", "nodes"}
    assert set(before["nodes"]) == {"factor"}
    state = before["nodes"]["factor"]
    assert state["state_capability"] == "STATELESS"
    assert state["checkpoint_schema_version"] is None and state["state"] is None
    for response in responses[2:22]:
        observation = _record(response)
        assert set(observation) == {"outputs", "state"}
        assert observation["outputs"]["value"]["type"] == "DECIMAL"
        assert Decimal(observation["outputs"]["value"]["value"]) == Decimal("2.1")
        assert observation["state"] == state
    assert Decimal(_record(responses[23])["outputs"]["value"]["value"]) == Decimal("2.1")
    assert Decimal(_record(responses[24])["outputs"]["value"]["value"]) == Decimal("0.099009900990")
    assert _record(responses[25])["outputs"]["value"] == {"type": "NULL", "value": None}
    after = _record(responses[26])
    assert after == before
    for response in responses[23:26]:
        assert set(_record(response)) == {"outputs", "state"}
        assert _record(response)["state"] == state
    assert _record(responses[27]) == {"closed": True}
    fresh = _run(root, artifact, [initialize, _operation("RESTORE", checkpoint=before), *tail])
    assert _record(fresh[2]) == before
    assert [_record(response) for response in fresh[3:]] == [_record(response) for response in responses[23:]]
    # Foreign lifecycle fields and altered private implementation/state bindings
    # are rejected without advancing the active numerical session.
    for kind in ("state", "definition", "implementation", "schema"):
        tampered = copy.deepcopy(before)
        node = tampered["nodes"]["factor"]
        if kind == "state":
            node["state"] = {"inputs": {"value": ["not-decimal"]}}
        elif kind == "definition":
            node["definition"]["warmup"]["minimum_observations"] += 1
        elif kind == "implementation":
            node["implementation_fingerprint"] = "f" * 64
        else:
            node["checkpoint_schema_version"] = 1
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
        assert _record(rejected[4]) == _record(rejected[1]) == before
    assert not any(key in after for key in ("cursor", "receipt", "grant", "runtime_generation", "authority"))


def test_installed_research_frames_observe_actual_trading_capabilities_without_rows(tmp_path: Path) -> None:
    """Actual installed metadata SPI, independent of Rust backend compilation."""
    from scripts.build_algorithm_sdk import ROOT, install

    root = tmp_path / "installed"
    artifact = install(tmp_path / "wheels", root)
    fixture = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    source, definition = _private_definition(fixture)
    initialization = {
        "schema_version": 1,
        "contract": "ONLYALPHA_AUTHORING_SESSION_V1",
        "sources": [source],
        "core_artifact": None,
        "target_artifact": None,
    }
    request = {
        "schema_version": 1,
        "contract": "ONLYALPHA_BOUND_CALCULATION_RESOLVE_V1",
        "type_reference": {key: definition[key] for key in ("kind", "type_id", "semantic_version")},
        "parameters": definition["parameters"],
        "input_bindings": definition["input_bindings"],
    }
    assert "rows" not in request and "input" not in request
    # Independent observations use the installed registry directly, not the
    # AuthoringSession or worker request implementation under test.
    oracle = subprocess.run(
        [
            str(root / "bin/python"),
            "-B",
            "-I",
            "-c",
            """
import json,sys
from onlyalpha.algorithm.type_declaration import type_declaration
from onlyalpha.calculation.definition import OnlyCalculationDefinition,OnlyCalculationBackendKind
from onlyalpha_backend_algorithms.research_resolution import registry_for_sources
payload=json.load(sys.stdin)
registry,artifacts=registry_for_sources(payload['sources'])
definition=OnlyCalculationDefinition.from_dict(payload['definition'])
research=registry.resolve(definition.kind,definition.type_id,definition.semantic_version,OnlyCalculationBackendKind.RESEARCH)
trading=registry.resolve(definition.kind,definition.type_id,definition.semantic_version,OnlyCalculationBackendKind.TRADING)
assert research.implementation_manifest is not None and trading.implementation_manifest is not None and trading.state_capability is not None
assert research.definition_resolver.resolve(definition.parameters,definition.input_bindings)==definition
print(json.dumps({'source_artifacts':artifacts,'resolution':{'definition':dict(definition.to_dict()),'definition_fingerprint':definition.fingerprint,'type_declaration':type_declaration(research.type_definition),'implementations':[dict(r.implementation_manifest.to_dict()) for r in (research,trading)],'trading_capability':{'implementation_fingerprint':trading.implementation_manifest.implementation_fingerprint,'state_capability':trading.state_capability.value,'checkpoint_schema_version':trading.checkpoint_schema_version}}}))
""",
        ],
        input=json.dumps({"sources": [source], "definition": definition}).encode(),
        capture_output=True,
        env={},
        timeout=20,
    )
    assert oracle.returncode == 0, oracle.stderr.decode(errors="replace")
    expected = json.loads(oracle.stdout)
    assert expected["resolution"]["trading_capability"]["state_capability"] == "STATELESS"
    assert expected["resolution"]["trading_capability"]["checkpoint_schema_version"] is None

    def observe(
        payload: dict[str, Any], *, rejected: bool = False, duplicate_source: bool = False
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
                "sources": [source, source] if duplicate_source else [source],
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
            assert len(responses) == (1 if duplicate_source else 2 if rejected else 3)
            if duplicate_source:
                return responses[0]
            assert _record(responses[0]) == {
                "schema_version": 1,
                "contract": initialization["contract"],
                "algorithm_artifact": artifact,
                "core_artifact_sha256": None,
                "core_resources_fingerprint": None,
                "target_artifact_sha256": None,
                "target_resources_fingerprint": None,
                "source_artifacts": expected["source_artifacts"],
                "isolation": "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1",
            }
            if not rejected:
                assert responses[2].WhichOneof("outcome") == "error"
                assert responses[2].error.code == "REQUEST_REJECTED"
            return responses[1]
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

    assert _record(observe(request)) == expected["resolution"]
    # Resolve is strictly scalar metadata, not a batch definitions/row endpoint.
    # Duplicate owner registrations must also fail during the real initialization.
    for invalid in (
        {**request, "rows": []},
        {**request, "schema_version": True},
        {**request, "definitions": [definition, definition]},
    ):
        response = observe(invalid, rejected=True)
        assert response.WhichOneof("outcome") == "error"
        assert response.error.code == "REQUEST_REJECTED"
    response = observe(request, duplicate_source=True)
    assert response.WhichOneof("outcome") == "error"
    assert response.error.code == "REQUEST_REJECTED"
