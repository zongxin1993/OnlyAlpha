"""Actual installed math worker and framed protocol; not Human/Product acceptance."""

import hashlib
import json
import struct
import subprocess
import zipfile
from pathlib import Path

from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1
from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from scripts.build_algorithm_sdk import install


def test_selected_installed_preparation_rejects_rehashed_foreign_operator_resources(tmp_path: Path) -> None:
    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())

    def wheel(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "distribution_version": path.name.split("-")[1],
        }

    operator = next(wheels.glob("onlyalpha_plugin_operators-*.whl"))
    request = {
        "schema_version": 1,
        "source": {
            key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
        },
        "graph": vector["graph"],
        "core_artifact": wheel(next(wheels.glob("onlyalpha-*.whl"))),
        "operator_artifact": wheel(operator),
    }

    def exchange(payload: dict[str, object]) -> wire.CalculationResponse:
        handshake = wire.CalculationRequest(
            protocol_version=1, generation="a" * 64, sequence=1, handshake=wire.CalculationEmpty()
        )
        prepare = wire.CalculationRequest(
            protocol_version=1,
            generation="a" * 64,
            sequence=2,
            research_prepare=wire.ResearchPrepare(request_json=only_canonical_json(payload).encode()),
        )
        frames = b"".join(
            struct.pack("!I", len(raw)) + raw
            for message in (handshake, prepare)
            for raw in (message.SerializeToString(deterministic=True),)
        )
        child = subprocess.run(
            [
                str(installation / "bin/python"),
                "-B",
                "-I",
                "-m",
                "onlyalpha_backend_algorithms.research_worker",
                "--generation",
                "a" * 64,
                "--artifact",
                artifact,
                "--installation",
                str(installation),
            ],
            input=frames,
            capture_output=True,
            check=False,
            timeout=30,
            env={},
        )
        assert child.returncode == 0, child.stderr.decode()
        responses, remaining = [], child.stdout
        while remaining:
            size = struct.unpack("!I", remaining[:4])[0]
            assert 0 < size <= 8 * 1024 * 1024
            responses.append(wire.CalculationResponse.FromString(remaining[4 : 4 + size]))
            remaining = remaining[4 + size :]
        assert len(responses) == 2
        assert [r.sequence for r in responses] == [1, 2]
        assert all(r.artifact_fingerprint == artifact and r.generation == "a" * 64 for r in responses)
        return responses[1]

    response = exchange(request)
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
    assert actual["contract"] == "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
    assert actual["equivalence_evidence"]["test_vector_set_fingerprint"] == only_canonical_fingerprint(
        actual["certification_vectors"]
    )
    assert actual["operator_artifact_sha256"] == request["operator_artifact"]["sha256"]
    assert (
        actual["operator_provider_manifest"]["source"]["distribution_version"]
        == request["operator_artifact"]["distribution_version"]
    )
    foreign = tmp_path / operator.name
    with zipfile.ZipFile(operator) as source, zipfile.ZipFile(foreign, "w") as output:
        for name in source.namelist():
            raw = source.read(name)
            output.writestr(name, raw + b"\n# foreign\n" if name.endswith("/registration.py") else raw)
    assert wheel(foreign)["sha256"] != wheel(operator)["sha256"]
    denied = exchange({**request, "operator_artifact": wheel(foreign)})
    assert denied.WhichOneof("outcome") == "error"
    assert denied.error.code == "REQUEST_REJECTED"
