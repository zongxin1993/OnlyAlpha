"""Pure managed ChartBatch process; exact installation, no business imports."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, cast

from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire
from onlyalpha_plugin_indicators.chart_factory import ChartFactory

from onlyalpha.canonical import only_canonical_json
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.worker_io import read
from onlyalpha_backend_algorithms.worker_io import verify_installation as verify_installation

MAX_FRAME = 8 * 1024 * 1024


def serve(root: Path, artifact: str) -> None:
    verify_installation(root, artifact)
    factory = ChartFactory()
    catalog = cast(list[dict[str, Any]], factory.catalog())
    # Load the installed Arrow conversion code before closing filesystem/network.
    # These are transient pure arithmetic observations, never a readiness grant.
    for row in catalog:
        d = row["descriptor"]
        definition = factory.resolve(d["type_id"], d["semantic_version"], row["support"]["default_parameters"])
        inputs: dict[str, list[object]] = {
            p.name: ([0, 60_000_000_000] if p.name == "start_ns" else ["1", "2"]) for p in definition.inputs
        }
        factory.execute(
            d["type_id"],
            d["semantic_version"],
            row["support"]["default_parameters"],
            inputs,
            row["implementation_fingerprint"],
        )
    isolation = restrict()
    sequence = 0
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            size = struct.unpack("!I", read(reader, 4))[0]
            if not 0 < size <= MAX_FRAME:
                return
            request = wire.CalculationRequest.FromString(read(reader, size))
        except EOFError:
            return
        if request.protocol_version != 1 or request.generation != artifact or request.sequence != sequence + 1:
            return
        sequence = request.sequence
        response = wire.CalculationResponse(
            protocol_version=1, generation=artifact, sequence=sequence, artifact_fingerprint=artifact
        )
        try:
            if request.WhichOneof("operation") == "handshake":
                result = {"schema_version": 1, "max_rows": 2001, "max_frame": MAX_FRAME, "isolation": isolation}
            elif request.WhichOneof("operation") == "chart":
                raw = request.chart.request_json
                if len(raw) > MAX_FRAME:
                    raise ValueError("CHART_FRAME")
                payload = json.loads(raw)
                if payload == {"op": "CATALOG"}:
                    result = {"artifact_fingerprint": factory.artifact, "entries": catalog}
                elif (
                    set(payload) == {"op", "type_id", "semantic_version", "parameters", "implementation_fingerprint"}
                    and payload["op"] == "RESOLVE"
                ):
                    definition = factory.resolve(payload["type_id"], payload["semantic_version"], payload["parameters"])
                    result = {
                        "definition": dict(definition.to_dict()),
                        "definition_fingerprint": definition.fingerprint,
                    }
                elif (
                    set(payload)
                    == {
                        "op",
                        "type_id",
                        "semantic_version",
                        "parameters",
                        "implementation_fingerprint",
                        "inputs",
                        "input_fingerprint",
                    }
                    and payload["op"] == "EXECUTE"
                ):
                    result = factory.execute(
                        payload["type_id"],
                        payload["semantic_version"],
                        payload["parameters"],
                        payload["inputs"],
                        payload["implementation_fingerprint"],
                    )
                    result["input_fingerprint"] = payload["input_fingerprint"]
                else:
                    raise ValueError("CHART_OPERATION_INVALID")
            else:
                raise ValueError("CHART_OPERATION_INVALID")
            response.result.record_json = only_canonical_json(result).encode()
        except (ValueError, KeyError, TypeError, OverflowError, ArithmeticError):
            response.error.code = "REQUEST_REJECTED"
        data = response.SerializeToString(deterministic=True)
        if not 0 < len(data) <= MAX_FRAME:
            return
        writer.write(struct.pack("!I", len(data)) + data)
        writer.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", required=True)
    parser.add_argument("--installation", required=True, type=Path)
    args = parser.parse_args()
    serve(args.installation, args.generation)


if __name__ == "__main__":
    main()
