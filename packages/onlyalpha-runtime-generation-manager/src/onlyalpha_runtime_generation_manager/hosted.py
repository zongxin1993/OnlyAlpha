"""Fail-closed verification that this process hosts one validated generation."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import sys
import sysconfig
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.distribution import OnlyArtifactCalculationImplementation
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

from .builder import _HOSTED_GENERATION_SEAL, _normalized_distribution_name


def only_verify_hosted_runtime_generation(
    expected: OnlyRuntimeGenerationValidationEvidence,
) -> None:
    """Recompute executable closure before the process may claim formal work."""

    root = Path(sys.prefix).resolve()
    executable = Path(sys.executable).absolute()
    if root not in executable.parents:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")
    try:
        payload: Any = json.loads((root / _HOSTED_GENERATION_SEAL).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        sealed = OnlyRuntimeGenerationValidationEvidence.from_dict(cast(dict[str, object], payload))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH") from exc
    if sealed != expected:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")

    wheels = tuple(sorted((root / "artifacts").glob("*.whl")))
    actual_sha256s = tuple(sorted(_sha256(path) for path in wheels))
    if actual_sha256s != expected.artifact_sha256s:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")
    for wheel in wheels:
        _verify_installed_wheel(wheel)

    catalog = only_discover_quant_asset_providers()
    if catalog.generation_fingerprint != expected.catalog_generation_fingerprint:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")
    providers = tuple(
        sorted(
            (
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
            )
            for provider in catalog.providers
        )
    )
    expected_providers = tuple(
        sorted(
            (item.provider_id, item.provider_version, item.provider_content_fingerprint) for item in expected.providers
        )
    )
    if providers != expected_providers:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")
    if _installed_implementations() != expected.implementations:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")


def _installed_implementations() -> tuple[OnlyArtifactCalculationImplementation, ...]:
    result: list[OnlyArtifactCalculationImplementation] = []
    registry = OnlyCalculationRegistry()
    entries = metadata.entry_points().select(group="onlyalpha.calculations")
    for entry in sorted(entries, key=lambda item: (item.name, item.value)):
        loaded = entry.load()
        registrations = loaded() if callable(loaded) else tuple(loaded)
        for registration in registrations:
            registry.register(registration)
    only_register_research_predicate_primitives(registry)
    only_register_trading_predicate_primitives(registry)
    for registration in registry.backend_registrations():
        manifest = registration.implementation_manifest
        if manifest is None:
            raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")
        definition = registration.type_definition
        result.append(
            OnlyArtifactCalculationImplementation(
                definition.kind.value,
                definition.type_id,
                definition.semantic_version,
                registration.backend.value,
                manifest.implementation_fingerprint,
            )
        )
    return tuple(sorted(result))


def _verify_installed_wheel(wheel: Path) -> None:
    purelib = Path(sysconfig.get_path("purelib")).resolve()
    platlib = Path(sysconfig.get_path("platlib")).resolve()
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = tuple(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
            record_names = tuple(name for name in archive.namelist() if name.endswith(".dist-info/RECORD"))
            if len(metadata_names) != 1 or len(record_names) != 1:
                raise ValueError
            metadata_text = archive.read(metadata_names[0]).decode("utf-8")
            name = next(line[6:] for line in metadata_text.splitlines() if line.startswith("Name: "))
            version = next(line[9:] for line in metadata_text.splitlines() if line.startswith("Version: "))
            installed = metadata.distribution(name)
            if installed.version != version or _normalized_distribution_name(
                installed.metadata["Name"]
            ) != _normalized_distribution_name(name):
                raise ValueError
            rows = csv.reader(io.StringIO(archive.read(record_names[0]).decode("utf-8")))
            for relative, digest, size in rows:
                if (
                    not digest
                    or not size
                    or relative.startswith("../")
                    or relative.endswith((".dist-info/INSTALLER", ".dist-info/REQUESTED", ".dist-info/direct_url.json"))
                ):
                    continue
                algorithm, encoded = digest.split("=", 1)
                if algorithm != "sha256":
                    raise ValueError
                candidates = (purelib / relative, platlib / relative)
                target = next((item for item in candidates if item.is_file()), None)
                if target is None:
                    raise ValueError
                content = target.read_bytes()
                actual = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
                if actual != encoded or len(content) != int(size):
                    raise ValueError
    except (KeyError, OSError, StopIteration, TypeError, ValueError, zipfile.BadZipFile) as exc:
        raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["only_verify_hosted_runtime_generation"]
