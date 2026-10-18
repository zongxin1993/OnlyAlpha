"""Private generated-Protobuf process entry point. stdout is protocol only."""

from __future__ import annotations

import argparse
import os
import struct
import time
from typing import BinaryIO

from google.protobuf.message import DecodeError
from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

from onlyalpha_calculation_worker.artifact import manifest
from onlyalpha_calculation_worker.backend import Backend, resolve
from onlyalpha_calculation_worker.contracts import MAX_BATCH, MAX_FRAME, MAX_INSTANCES, decode, encode, sha
from onlyalpha_calculation_worker.node_backend import NodeBackend


def _read(stream: BinaryIO, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        data = stream.read(count - len(chunks))
        if not data:
            raise EOFError
        chunks.extend(data)
    return bytes(chunks)


def serve(generation: str, reader: BinaryIO, writer: BinaryIO) -> None:
    artifact = manifest().implementation_fingerprint
    backend = Backend(sha(generation), artifact)
    nodes = NodeBackend(generation, artifact)
    sequence = 0
    while True:
        try:
            size = struct.unpack("!I", _read(reader, 4))[0]
            if not 0 < size <= MAX_FRAME:
                return
            request = wire.CalculationRequest.FromString(_read(reader, size))
        except (EOFError, DecodeError):
            return
        if request.protocol_version != 1 or request.generation != generation or request.sequence != sequence + 1:
            return
        sequence = request.sequence
        response = wire.CalculationResponse(
            protocol_version=1, generation=generation, sequence=sequence, artifact_fingerprint=artifact
        )
        operation = request.WhichOneof("operation")
        started = time.perf_counter_ns()
        try:
            if operation == "handshake":
                result = {"schema_version": 1, "max_batch": MAX_BATCH, "max_instances": MAX_INSTANCES}
            elif operation == "resolve":
                result = resolve(decode(request.resolve.parameters_json))
            elif operation == "node":
                record = decode(request.node.request_json)
                if type(record) is not dict:
                    raise ValueError("NODE_REQUEST")
                if record.get("op") == "CREATE" and backend.instance_count() + len(nodes.nodes) >= MAX_INSTANCES:
                    raise ValueError("INSTANCE_BUDGET")
                result = nodes.dispatch(record)
            elif operation == "create":
                if backend.instance_count() + len(nodes.nodes) >= MAX_INSTANCES:
                    raise ValueError("INSTANCE_BUDGET")
                create_request = request.create
                result = backend.create(
                    decode(create_request.binding_json),
                    decode(create_request.definition_json),
                    decode(create_request.bar_type_json),
                    decode(create_request.parameters_json),
                    create_request.source_fingerprint,
                )
            elif operation == "update":
                update_request = request.update
                result = backend.update(
                    update_request.instance.scope,
                    update_request.instance.revision,
                    list(update_request.bars_json),
                    update_request.input_digest,
                )
            elif operation == "restore":
                restore_request = request.restore
                result = backend.restore(
                    restore_request.instance.scope,
                    restore_request.instance.revision,
                    restore_request.checkpoint_json,
                    restore_request.expected_sha256,
                )
            elif operation in {"reset", "checkpoint", "close"}:
                instance = getattr(request, operation)
                call = {"reset": backend.reset, "checkpoint": backend.capture, "close": backend.close}[operation]
                result = call(instance.scope, instance.revision)
            else:
                raise ValueError("OPERATION_INVALID")
            response.result.record_json = encode(result)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            # Known rejection leaves the selected candidate uncommitted.
            response.error.code = "REQUEST_REJECTED"
        response.diagnostic_compute_ns = time.perf_counter_ns() - started
        data = response.SerializeToString(deterministic=True)
        if len(data) > MAX_FRAME:
            return
        writer.write(struct.pack("!I", len(data)) + data)
        writer.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--generation")
    args = parser.parse_args()
    if args.describe:
        print(manifest().implementation_fingerprint)
        return
    if args.generation is None:
        parser.error("--generation is required")
    with os.fdopen(os.dup(0), "rb", buffering=0) as reader, os.fdopen(os.dup(1), "wb", buffering=0) as writer:
        serve(args.generation, reader, writer)


if __name__ == "__main__":
    main()
