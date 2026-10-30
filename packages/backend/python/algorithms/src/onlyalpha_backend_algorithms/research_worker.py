"""One-shot pure Factor source/Definition resolution, never Research authorization.

No Factor observation is evaluated. Existing authoritative executable/equivalence
facts must separately match the returned actual installed implementation records.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, cast

from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire
from onlyalpha_plugin_operators.registration import registrations

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationDefinition
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
)
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1
from onlyalpha_backend_algorithms.worker_io import read, verify_installation

MAX_FRAME = 8 * 1024 * 1024
CONTRACT = "ONLYALPHA_PRIVATE_FACTOR_RESOLVE_V1"


def resolve(payload: dict[str, Any], artifact: str) -> dict[str, object]:
    if (
        set(payload) != {"schema_version", "source", "graph", "core_artifact"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
    ):
        raise ValueError("RESEARCH_RESOLUTION_INPUT_INVALID")
    core = verify_core(payload["core_artifact"])
    source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(payload["source"])
    validation = only_validate_private_factor_revision(source)
    manifest, source_bytes = OnlyPrivateFactorSourceArtifactManifestV1.materialize(source, validation)
    registry = OnlyCalculationRegistry()
    private = only_private_factor_backend_registrations(
        source,
        manifest,
        source_bytes,
        OnlyPrivateFactorAdapterV1(
            "RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], OnlyPrivateFactorIsolatedProgramHost()
        ),
        OnlyPrivateFactorAdapterV1("TRADING", _ADAPTER_FINGERPRINTS["TRADING"], OnlyPrivateFactorIsolatedProgramHost()),
    )
    for item in (*registrations(), *private):
        registry.register(item)
    graph = payload["graph"]
    if (
        set(graph) != {"schema_version", "nodes"}
        or type(graph["schema_version"]) is not int
        or graph["schema_version"] != 1
        or type(graph["nodes"]) is not list
        or not 1 <= len(graph["nodes"]) <= 128
    ):
        raise ValueError("RESEARCH_RESOLUTION_INPUT_INVALID")
    nodes: list[dict[str, object]] = []
    implementations: dict[str, dict[str, object]] = {}
    for raw in graph["nodes"]:
        if set(raw) != {"alias", "definition"}:
            raise ValueError("RESEARCH_RESOLUTION_INPUT_INVALID")
        definition = OnlyCalculationDefinition.from_dict(raw["definition"])
        for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
            registration = registry.resolve(definition.kind, definition.type_id, definition.semantic_version, backend)
            resolver = registration.definition_resolver
            if resolver is None or registration.implementation_manifest is None:
                raise ValueError("RESEARCH_IMPLEMENTATION_UNAVAILABLE")
            actual = resolver.resolve(definition.parameters, definition.input_bindings)
            if actual != definition:
                raise ValueError("RESEARCH_DEFINITION_MISMATCH")
            implementation = registration.implementation_manifest
            implementations[implementation.implementation_fingerprint] = dict(implementation.to_dict())
        nodes.append({"alias": raw["alias"], "definition": dict(definition.to_dict())})
    return {
        **core,
        "schema_version": 1,
        "contract": CONTRACT,
        "algorithm_artifact": artifact,
        "factor_revision_fingerprint": source.revision_fingerprint,
        "source_artifact": manifest.to_dict(),
        "validation_evidence": {
            **validation.to_dict(),
            "validation_evidence_fingerprint": validation.validation_evidence_fingerprint,
        },
        "graph": {"schema_version": 1, "nodes": nodes},
        "implementations": [implementations[key] for key in sorted(implementations)],
        "private_calculations": json.loads(
            only_canonical_json(
                sorted(
                    [
                        {
                            "type": r.type_definition.descriptor(),
                            "backend": r.backend.value,
                            "implementation_fingerprint": r.implementation_manifest.implementation_fingerprint,
                            "state_capability": None if r.state_capability is None else r.state_capability.value,
                            "checkpoint_schema_version": r.checkpoint_schema_version,
                        }
                        for r in private
                        if r.implementation_manifest is not None
                    ],
                    key=only_canonical_fingerprint,
                )
            )
        ),
        "source_projection_fingerprint": only_canonical_fingerprint(payload["source"]),
    }


def serve(root: Path, generation: str, artifact: str) -> None:
    verify_installation(root, artifact)
    reader, writer = sys.stdin.buffer, sys.stdout.buffer
    for sequence in (1, 2):
        size = struct.unpack("!I", read(reader, 4))[0]
        if not 0 < size <= MAX_FRAME:
            return
        request = wire.CalculationRequest.FromString(read(reader, size))
        if request.protocol_version != 1 or request.generation != generation or request.sequence != sequence:
            return
        response = wire.CalculationResponse(
            protocol_version=1, generation=generation, sequence=sequence, artifact_fingerprint=artifact
        )
        try:
            if sequence == 1 and request.WhichOneof("operation") == "handshake":
                result: dict[str, object] = {
                    "schema_version": 1,
                    "contract": CONTRACT,
                    "max_frame": MAX_FRAME,
                    "max_nodes": 128,
                }
            elif sequence == 2 and request.WhichOneof("operation") == "research_resolve":
                payload = json.loads(request.research_resolve.request_json)
                result = resolve(cast(dict[str, Any], payload), artifact)
                result["isolation"] = restrict()
            elif sequence == 2 and request.WhichOneof("operation") == "research_evaluate":
                from onlyalpha_backend_algorithms.research_evaluation import GraphEvaluator

                payload = json.loads(request.research_evaluate.request_json)
                if set(payload) != {"resolution", "rows", "root_fingerprint"}:
                    raise ValueError("RESEARCH_EVALUATION_INPUT_INVALID")
                result = resolve(payload["resolution"], artifact)
                program = GraphEvaluator(
                    payload["resolution"]["source"], payload["resolution"]["graph"], payload["root_fingerprint"]
                )
                isolation = restrict()
                result["evaluation"] = program.evaluate(payload["rows"])
                result["isolation"] = isolation
            elif sequence == 2 and request.WhichOneof("operation") == "research_prepare":
                from onlyalpha_backend_algorithms.research_preparation import prepare

                result = prepare(json.loads(request.research_prepare.request_json), artifact)
            else:
                raise ValueError("RESEARCH_RESOLUTION_OPERATION_INVALID")
            response.result.record_json = only_canonical_json(result).encode()
        except (ValueError, KeyError, TypeError, OverflowError, ArithmeticError, RecursionError):
            response.error.code = "REQUEST_REJECTED"
        data = response.SerializeToString(deterministic=True)
        if not 0 < len(data) <= MAX_FRAME:
            return
        writer.write(struct.pack("!I", len(data)) + data)
        writer.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--installation", required=True, type=Path)
    args = parser.parse_args()
    serve(args.installation, args.generation, args.artifact)


def verify_core(core: dict[str, Any]) -> dict[str, object]:
    """Verify the selected Core wheel's actual semantic SDK resources, no imports."""
    proof = verify_distribution(core, "onlyalpha", "onlyalpha", bootstrap=True)
    return {
        "core_artifact_sha256": proof["artifact_sha256"],
        "core_resources_fingerprint": proof["resources_fingerprint"],
    }


def verify_distribution(
    core: dict[str, Any], package: str, distribution: str, *, bootstrap: bool = False
) -> dict[str, object]:
    """Match selected wheel bytes to the actually installed mathematical resources."""
    import hashlib
    import zipfile

    if (
        set(core) != {"path", "sha256", "size", "distribution_version"}
        or type(core["size"]) is not int
        or not 0 < core["size"] <= 128 * 1024 * 1024
    ):
        raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
    # These are the actual mathematical/contract resources used by this executor.
    # Minimal package bootstrap differs from the full Core package bootstrap;
    # both bootstrap and worker bytes stay pinned by the installation artifact.
    installation = Path(__file__).parents[4]
    selected = json.loads((installation / "algorithm-installation.json").read_text())
    resources_by_name = {}
    for name, digest in selected["files"].items():
        prefix = f"/site-packages/{package}/"
        if prefix not in name:
            continue
        relative = package + "/" + name.split(prefix, 1)[1]
        if bootstrap and relative in {
            "onlyalpha/__init__.py",
            "onlyalpha/calculation/__init__.py",
            "onlyalpha/quant_assets/__init__.py",
        }:
            continue
        resources_by_name[relative] = digest
    path = Path(core["path"])
    if path.is_symlink() or path.stat().st_size != core["size"]:
        raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != core["sha256"]:
            raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
        stream.seek(0)
        try:
            with zipfile.ZipFile(stream) as archive:
                if len(set(archive.namelist())) != len(archive.namelist()):
                    raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
                total = 0
                for name, digest in resources_by_name.items():
                    info = archive.getinfo(name)
                    total += info.file_size
                    if info.file_size > MAX_FRAME or total > MAX_FRAME:
                        raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
                    if hashlib.sha256(archive.read(info)).hexdigest() != digest:
                        raise ValueError("RESEARCH_CORE_SDK_MISMATCH")
                version = core["distribution_version"]
                info = archive.getinfo(f"{distribution.replace('-', '_')}-{version}.dist-info/METADATA")
                if info.file_size > MAX_FRAME or total + info.file_size > MAX_FRAME:
                    raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
                metadata = archive.read(info).decode()
                if f"Name: {distribution}\n" not in metadata or f"Version: {version}\n" not in metadata:
                    raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID")
        except (zipfile.BadZipFile, KeyError, OSError, UnicodeError) as error:
            raise ValueError("RESEARCH_CORE_ARTIFACT_INVALID") from error
    if not resources_by_name:
        raise ValueError("RESEARCH_CORE_SDK_MISMATCH")
    return {
        "artifact_sha256": core["sha256"],
        "resources_fingerprint": only_canonical_fingerprint(resources_by_name),
    }


if __name__ == "__main__":
    main()
