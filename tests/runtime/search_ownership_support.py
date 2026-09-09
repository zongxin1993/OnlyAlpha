"""Offline exact-wheel process fixture for historical Search ownership tests."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_plugin_targets.registration import registrations as target_registrations
from onlyalpha_runtime_generation_manager import (
    OnlyHistoricalGenerationHostManager,
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)

from onlyalpha.calculation.artifact import only_calculation_distribution_artifact_manifest
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, only_quant_asset_distribution_artifact_manifest
from onlyalpha.research.search.parameter.model import OnlyParameterSearchAlgorithmManifestV1
from onlyalpha.research.search.symbolic.algorithm import OnlySymbolicSearchAlgorithmImplementationManifestV1
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
)

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def _wheel(project: Path, output: Path) -> Path:
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _support_wheel(name: str, output: Path) -> Path:
    distribution = metadata.distribution(name)
    wheel_metadata = distribution.read_text("WHEEL")
    assert wheel_metadata is not None
    tags = tuple(line[5:] for line in wheel_metadata.splitlines() if line.startswith("Tag: "))
    tag = next((item for item in tags if item.startswith(("py3-", "py2.py3-"))), tags[0])
    target = output / f"{name.replace('-', '_')}-{distribution.version}-{tag}.whl"
    output.mkdir(parents=True, exist_ok=True)
    assert distribution.files is not None
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(distribution.files, key=str):
            if not relative.parts or relative.parts[0] == "..":
                continue
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, Path(str(distribution.locate_file(relative))).read_bytes())
    return target


def _plain(wheel: Path, name: str, role: OnlyDistributionArtifactRole) -> OnlyDistributionArtifactManifest:
    content = wheel.read_bytes()
    return OnlyDistributionArtifactManifest(
        role=role,
        source_provenance_authority=(
            OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT
            if name.startswith("onlyalpha")
            else OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE
        ),
        source_repository=name,
        source_revision="1" * 40,
        distribution_name=name,
        distribution_version=metadata.version(name),
        artifact_logical_name=wheel.name,
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


@dataclass(frozen=True)
class ExactSearchProcesses:
    authority: OnlyRuntimeGenerationRegistry
    host: OnlyHistoricalGenerationHostManager
    catalog: OnlyQuantAssetCatalogGeneration
    generations: tuple[str, str]
    symbolic_algorithm: OnlySymbolicSearchAlgorithmImplementationManifestV1
    parameter_algorithm: OnlyParameterSearchAlgorithmManifestV1
    variant_generation: str
    variant_catalog: str


def build_exact_search_processes(root: Path) -> ExactSearchProcesses:
    """Build actual sealed G1/G2 with identical Catalog and different Support artifacts."""
    repository = Path(__file__).resolve().parents[2]
    projects = {
        "onlyalpha": repository,
        "onlyalpha-runtime-generation-manager": repository / "packages/onlyalpha-runtime-generation-manager",
        "onlyalpha-example-alpha": repository / "examples/onlyalpha-example-alpha",
        "onlyalpha-plugin-operators": repository / "plugs/onlyalpha-plugin-operators",
        "onlyalpha-plugin-indicators": repository / "plugs/onlyalpha-plugin-indicators",
        "onlyalpha-plugin-targets": repository / "plugs/onlyalpha-plugin-targets",
    }
    wheels = {name: _wheel(project, root / "wheels" / name) for name, project in projects.items()}
    core = _plain(wheels["onlyalpha"], "onlyalpha", OnlyDistributionArtifactRole.CORE)
    identity = OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)
    providers = (operator_provider(), indicator_provider(), alpha_provider())
    catalog = OnlyQuantAssetCatalogGeneration(providers)
    quant_artifacts = tuple(
        only_quant_asset_distribution_artifact_manifest(
            source_repository=provider.manifest.distribution_name,
            source_revision="2" * 40,
            artifact_logical_name=wheels[provider.manifest.distribution_name].name,
            artifact_bytes=wheels[provider.manifest.distribution_name].read_bytes(),
            tested_core_execution_fingerprint=identity.fingerprint,
            provider=provider,
        )
        for provider in providers
    )
    target = wheels["onlyalpha-plugin-targets"]
    target_artifact = only_calculation_distribution_artifact_manifest(
        source_repository="OnlyAlpha",
        source_revision="3" * 40,
        distribution_name="onlyalpha-plugin-targets",
        distribution_version=metadata.version("onlyalpha-plugin-targets"),
        artifact_logical_name=target.name,
        artifact_bytes=target.read_bytes(),
        tested_core_execution_fingerprint=identity.fingerprint,
        registrations=target_registrations(),
    )
    execution_support = ("pyarrow", "numpy", "pyyaml", "psycopg", "psycopg-binary")
    support = {name: _support_wheel(name, root / "support") for name in (*execution_support, "packaging")}
    artifacts = (
        core,
        _plain(
            wheels["onlyalpha-runtime-generation-manager"],
            "onlyalpha-runtime-generation-manager",
            OnlyDistributionArtifactRole.SUPPORT,
        ),
        target_artifact,
        *quant_artifacts,
        *(_plain(support[name], name, OnlyDistributionArtifactRole.SUPPORT) for name in execution_support),
    )
    additional = _plain(support["packaging"], "packaging", OnlyDistributionArtifactRole.SUPPORT)
    content = {wheel.name: wheel.read_bytes() for wheel in (*wheels.values(), *support.values())}
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    for artifact in (*artifacts, additional):
        store.put_once(artifact, content[artifact.artifact_logical_name])
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    authority = OnlyRuntimeGenerationRegistry(root / "authority")
    generations = []
    for index, selected in enumerate((artifacts, (*artifacts, additional))):
        validated = builder.build_validated(
            artifacts=selected,
            expected_catalog=catalog,
            environment_root=root / f"build-{index}",
        )
        authority.prepare(validated.manifest, actor="test-operator", occurred_at=NOW)
        authority.admit_ready(validated.validation_evidence, actor="test-validator", occurred_at=NOW)
        generations.append(validated.manifest.runtime_generation_fingerprint)
    assert generations[0] != generations[1]
    authority.activate_for_new_work(
        expected_current=None, target=generations[0], actor="test-operator", occurred_at=NOW
    )
    host = OnlyHistoricalGenerationHostManager(registry=authority, builder=builder, cache_root=root / "hosts")
    inspection = subprocess.run(
        [
            str(root / "build-0" / "bin" / "python"),
            "-I",
            "-c",
            "import json; "
            "from onlyalpha.research.search.symbolic.algorithm import only_deterministic_enumeration_implementation as s; "
            "from onlyalpha.research.search.parameter.algorithm import only_deterministic_coarse_to_fine_implementation as p; "
            "print(json.dumps({'symbolic':s().to_dict(),'parameter':p().to_dict()}))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert inspection.returncode == 0, inspection.stderr
    algorithms = json.loads(inspection.stdout)
    variant_generation, variant_catalog = _build_variant(root, wheels, artifacts, identity, authority)
    return ExactSearchProcesses(
        authority,
        host,
        catalog,
        (generations[0], generations[1]),
        OnlySymbolicSearchAlgorithmImplementationManifestV1.from_dict(algorithms["symbolic"]),
        OnlyParameterSearchAlgorithmManifestV1.from_dict(algorithms["parameter"]),
        variant_generation,
        variant_catalog,
    )


def _build_variant(
    root: Path,
    wheels: dict[str, Path],
    artifacts: tuple[OnlyDistributionArtifactManifest, ...],
    identity: OnlyCoreExecutionIdentity,
    authority: OnlyRuntimeGenerationRegistry,
) -> tuple[str, str]:
    """Change fixture bytes in a new wheel, regenerate RECORD, and seal exact B."""
    original = wheels["onlyalpha-example-alpha"]
    variant = root / "variant" / original.name
    variant.parent.mkdir()
    with zipfile.ZipFile(original) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    registration = "onlyalpha_example_alpha/registration.py"
    source = contents[registration].decode()
    assert '"example.factor.momentum",\n    "1",' in source
    source = source.replace('"example.factor.momentum",\n    "1",', '"example.factor.momentum",\n    "2",')
    assert 'OnlyWarmupDefinition(1, "declared upstream values are available"' in source
    source = source.replace(
        'OnlyWarmupDefinition(1, "declared upstream values are available"',
        'OnlyWarmupDefinition(2, "fixture B needs two upstream values"',
    )
    contents[registration] = source.encode()
    provider = "onlyalpha_example_alpha/provider.py"
    contents[provider] = contents[provider].replace(b'provider_version="1"', b'provider_version="2"')
    for backend in ("research.py", "trading.py"):
        name = f"onlyalpha_example_alpha/{backend}"
        contents[name] = contents[name].replace(b'semantic_version != "1"', b'semantic_version != "2"')
        contents[name] = contents[name].replace(
            b"short_weight * left + long_weight * right", b"short_weight * left - long_weight * right"
        )
        contents[name] = contents[name].replace(
            b"short_weight * short + long_weight * long", b"short_weight * short - long_weight * long"
        )
    record = next(name for name in contents if name.endswith(".dist-info/RECORD"))
    rows = []
    for name, content in sorted(contents.items()):
        if name != record:
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            rows.append((name, f"sha256={digest}", str(len(content))))
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows((*rows, (record, "", "")))
    contents[record] = stream.getvalue().encode()
    with zipfile.ZipFile(variant, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            archive.writestr(name, content)
    bootstrap = root / "variant-bootstrap"
    subprocess.run([sys.executable, "-m", "venv", str(bootstrap)], check=True, capture_output=True)
    # Resolve only the known wheel inputs already prepared offline above.
    available = {wheel.name: wheel for wheel in (*wheels.values(), *(root / "support").glob("*.whl"))}
    install_wheels = [
        str(variant if item.distribution_name == "onlyalpha-example-alpha" else available[item.artifact_logical_name])
        for item in artifacts
    ]
    completed = subprocess.run(
        [str(bootstrap / "bin" / "python"), "-I", "-m", "pip", "install", "--no-index", "--no-deps", *install_wheels],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    configuration = root / "variant-bootstrap-input.json"
    configuration.write_text(
        json.dumps(
            {
                "root": str(root),
                "artifacts": [item.to_dict() for item in artifacts],
                "variant_wheel": str(variant),
                "core_identity": identity.fingerprint,
            }
        )
    )
    script = Path(__file__).with_name("search_variant_builder.py")
    completed = subprocess.run(
        [str(bootstrap / "bin" / "python"), "-I", str(script), str(configuration)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = json.loads(completed.stdout)
    manifest = OnlyRuntimeGenerationManifest.from_dict(output["manifest"])
    evidence = OnlyRuntimeGenerationValidationEvidence.from_dict(output["evidence"])
    authority.prepare(manifest, actor="test-operator", occurred_at=NOW)
    authority.admit_ready(evidence, actor="test-validator", occurred_at=NOW)
    return manifest.runtime_generation_fingerprint, manifest.catalog_generation_fingerprint
