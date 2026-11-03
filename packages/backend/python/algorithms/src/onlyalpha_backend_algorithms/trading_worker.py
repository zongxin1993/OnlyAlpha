"""Private framed installed arithmetic; no Trading cursors, receipts or grants."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, cast

from google.protobuf.message import DecodeError
from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

from onlyalpha.algorithm.codec import _pairs, exact, sha
from onlyalpha.calculation.definition import (
    OnlyCalculationScalar,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.trading_session import TradingGraphSession
from onlyalpha_backend_algorithms.worker_io import read, verify_installation

MAX_FRAME = 8 * 1024 * 1024
CONTRACT = "ONLYALPHA_TRADING_NUMERICS_V1"


def _request(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_pairs)
    if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("TRADING_NUMERICS_REQUEST_INVALID")
    return value


def serve(root: Path, generation: str, artifact: str) -> None:
    sha(generation)
    sha(artifact)
    verify_installation(root, artifact)
    # Import-time installed descriptors/bytes and Arrow initialization have
    # completed. Source construction and every authored math call follow restrict.
    isolation = restrict()
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    sequence = 0
    session: TradingGraphSession | None = None
    while True:
        try:
            size = struct.unpack("!I", read(reader, 4))[0]
            if not 0 < size <= MAX_FRAME:
                return
            request = wire.CalculationRequest.FromString(read(reader, size))
        except (EOFError, DecodeError):
            return
        if request.protocol_version != 1 or request.generation != generation or request.sequence != sequence + 1:
            return
        sequence = request.sequence
        response = wire.CalculationResponse(
            protocol_version=1, generation=generation, sequence=sequence, artifact_fingerprint=artifact
        )
        closed = False
        updating = False
        try:
            if sequence == 1 and request.WhichOneof("operation") == "handshake":
                result: object = {
                    "schema_version": 1,
                    "contract": CONTRACT,
                    "max_nodes": 128,
                    "max_frame": MAX_FRAME,
                    "isolation": isolation,
                }
            elif sequence > 1 and request.WhichOneof("operation") == "node":
                payload = _request(request.node.request_json)
                operation = payload.get("op")
                if operation == "INITIALIZE":
                    exact(payload, {"schema_version", "op", "sources", "nodes"})
                    if session is not None:
                        raise ValueError("TRADING_NUMERICS_ALREADY_INITIALIZED")
                    candidate = TradingGraphSession(payload["sources"], payload["nodes"])
                    result = candidate.checkpoint()
                    session = candidate
                elif operation == "CLOSE":
                    exact(payload, {"schema_version", "op"})
                    result = {"closed": True}
                    closed = True
                elif session is None:
                    raise ValueError("TRADING_NUMERICS_NOT_INITIALIZED")
                elif operation == "UPDATE":
                    exact(payload, {"schema_version", "op", "node", "inputs"})
                    if type(payload["inputs"]) is not dict or type(payload["node"]) is not str:
                        raise ValueError("TRADING_NUMERICS_INPUT_INVALID")
                    values: dict[str, object] = {
                        name: only_calculation_scalar_from_dict(value, "Trading numeric input")
                        for name, value in payload["inputs"].items()
                    }
                    # A lost/error result after this point must close this channel.
                    # Only Rust can decide how its acknowledged history is recovered.
                    updating = True
                    outputs = session.update(payload["node"], values)
                    state = session.checkpoint()["nodes"][payload["node"]]
                    result = {
                        "outputs": {
                            name: only_calculation_scalar_to_dict(cast(OnlyCalculationScalar, value))
                            for name, value in outputs.items()
                        },
                        "state": state,
                    }
                elif operation == "CHECKPOINT":
                    exact(payload, {"schema_version", "op"})
                    result = session.checkpoint()
                elif operation == "RESTORE":
                    exact(payload, {"schema_version", "op", "checkpoint"})
                    session.restore(payload["checkpoint"])
                    result = session.checkpoint()
                else:
                    raise ValueError("TRADING_NUMERICS_OPERATION_INVALID")
            else:
                raise ValueError("TRADING_NUMERICS_OPERATION_INVALID")
            response.result.record_json = only_canonical_json(result).encode()
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError):
            if updating:
                return
            response.error.code = "REQUEST_REJECTED"
        raw = response.SerializeToString(deterministic=True)
        if not 0 < len(raw) <= MAX_FRAME:
            return
        writer.write(struct.pack("!I", len(raw)) + raw)
        writer.flush()
        if closed:
            return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--installation", required=True, type=Path)
    args = parser.parse_args()
    serve(args.installation, args.generation, args.artifact)


if __name__ == "__main__":
    main()
