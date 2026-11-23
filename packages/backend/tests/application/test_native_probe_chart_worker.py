"""Technical probe ELF roles must preserve the production private worker contract."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest
from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

from packages.backend.tests.application.conftest import build_native_probe
from packages.backend.tests.application.test_strategy_research_evidence import _build_strategy_evidence_owner_binary


@pytest.fixture(scope="module", params=["command-postgres-probe", "backtest_owner_probe"])
def executable(request: pytest.FixtureRequest) -> Path:
    if request.param == "command-postgres-probe":
        return build_native_probe(release=True)
    return _build_strategy_evidence_owner_binary(release=True, target_name="backtest_owner_probe")


def frame(generation: str, *, sequence: int = 1) -> bytes:
    request = wire.CalculationRequest(protocol_version=1, generation=generation, sequence=sequence)
    request.chart.request_json = b'{"op":"CATALOG"}'
    raw = request.SerializeToString(deterministic=True)
    return struct.pack("!I", len(raw)) + raw


def invoke(executable: Path, payload: bytes, *extra: str) -> subprocess.CompletedProcess:
    # Match the production role's empty environment and root working directory.
    # communicate closes stdin and waits for the actual child, including on EOF.
    return subprocess.run(
        [str(executable), "--native-chart-worker", *extra],
        input=payload, capture_output=True, env={}, cwd="/", timeout=10,
    )


def test_diagnostic_startup_markers_do_not_change_native_descriptor(native_release_probe: Path) -> None:
    results=[]
    for enabled in (False,True):
        env=dict(os.environ)
        env.pop("ONLYALPHA_RUNTIME_PREPARATION_DIAGNOSTICS",None)
        if enabled: env["ONLYALPHA_RUNTIME_PREPARATION_DIAGNOSTICS"]="1"
        result=subprocess.run([str(native_release_probe),"--describe-research-runtime"],env=env,
                              capture_output=True,timeout=30,check=True)
        results.append(json.loads(result.stdout))
        if enabled:
            assert b"[probe-startup] phase=process_entry elapsed_us=" in result.stderr
            assert b"[probe-startup] phase=tokio_ready elapsed_us=" in result.stderr
        else:
            assert b"[probe-startup]" not in result.stderr
    assert results[0]==results[1]


def test_probe_catalog_binds_actual_elf_and_joins_on_eof(executable: Path) -> None:
    artifact = hashlib.sha256(executable.read_bytes()).hexdigest()
    result = invoke(executable, frame(artifact))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert len(result.stdout) >= 4, "worker must return a framed CATALOG response"
    size = struct.unpack("!I", result.stdout[:4])[0]
    assert 0 < size <= 8 * 1024 * 1024 and len(result.stdout) == size + 4
    response = wire.CalculationResponse.FromString(result.stdout[4:])
    assert (response.protocol_version, response.generation, response.sequence, response.artifact_fingerprint) == (
        1, artifact, 1, artifact,
    )
    assert response.WhichOneof("outcome") == "result"
    catalog = json.loads(response.result.record_json)
    assert set(catalog) == {"schema_version", "isolation", "capabilities"}
    assert catalog["schema_version"] == 1
    assert catalog["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    capabilities = catalog["capabilities"]
    assert len(capabilities) == 14
    assert len({(row["type_id"], row["semantic_version"]) for row in capabilities}) == 14


@pytest.mark.parametrize("invalid", ["wrong-artifact", "wrong-sequence", "bad-frame", "extra-argument"])
def test_probe_worker_rejects_invalid_role_or_protocol(executable: Path, invalid: str) -> None:
    artifact = hashlib.sha256(executable.read_bytes()).hexdigest()
    payload = frame("0" * 64 if invalid == "wrong-artifact" else artifact,
                    sequence=2 if invalid == "wrong-sequence" else 1)
    if invalid == "bad-frame":
        payload = b"\x00\x00\x00\x01\xff"
    result = invoke(executable, payload, *(["extra"] if invalid == "extra-argument" else []))
    assert result.returncode != 0
    assert result.stdout == b"", "rejected input must not produce a capability response"
