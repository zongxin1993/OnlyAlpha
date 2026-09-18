from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import (
    OnlyHistoricalExecutableRuntimeGenerationResolver,
    OnlyHistoricalGenerationHostManager,
    OnlyLocalImmutableArtifactStore,
    OnlyRuntimeGenerationBuilder,
    OnlyRuntimeGenerationRegistry,
)
from onlyalpha_runtime_generation_manager import builder as runtime_builder_module
from onlyalpha_runtime_generation_manager.catalog_context import OnlyRuntimeGenerationExactCatalogDescriptorReader
from onlyalpha_runtime_generation_manager.hosted import _verify_installed_wheel
from onlyalpha_test_strategy_provider.provider import quant_asset_provider

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextUnavailable,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets import (
    ONLY_PRIVATE_ALPHA_API_V1,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaIsolatedProgramHost,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.runtime.generation import (
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_hosted_verification_fails_closed_for_unmapped_wheel_data_files(tmp_path: Path) -> None:
    wheel = tmp_path / "onlyalpha-0.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "onlyalpha-0.9.9.dist-info/METADATA",
            f"Name: onlyalpha\nVersion: {metadata.version('onlyalpha')}\n",
        )
        archive.writestr(
            "onlyalpha-0.9.9.dist-info/RECORD",
            "onlyalpha-0.9.9.data/data/unverified.txt,sha256=AA,1\n",
        )

    with pytest.raises(RuntimeError, match="RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH"):
        _verify_installed_wheel(wheel)


def _build_wheel(project: Path, output: Path) -> Path:
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output), str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def _installed_distribution_wheel(name: str, output: Path) -> Path:
    distribution = metadata.distribution(name)
    wheel_metadata = distribution.read_text("WHEEL")
    assert wheel_metadata is not None
    tags = tuple(line.removeprefix("Tag: ") for line in wheel_metadata.splitlines() if line.startswith("Tag: "))
    tag = next((item for item in tags if item.startswith(("py3-", "py2.py3-"))), tags[0])
    normalized = name.replace("-", "_")
    target = output / f"{normalized}-{distribution.version}-{tag}.whl"
    output.mkdir(parents=True, exist_ok=True)
    files = distribution.files
    assert files is not None
    included = tuple(item for item in files if item.parts and item.parts[0] != "..")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(included, key=str):
            content = Path(distribution.locate_file(relative)).read_bytes()
            info = zipfile.ZipInfo(str(relative), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return target


def _plain_artifact(
    wheel: Path,
    *,
    role: OnlyDistributionArtifactRole,
    authority: OnlyArtifactSourceProvenanceAuthority,
    repository: str,
    revision: str,
) -> OnlyDistributionArtifactManifest:
    content = wheel.read_bytes()
    distribution = metadata.distribution(_wheel_distribution_name(wheel))
    return OnlyDistributionArtifactManifest(
        role=role,
        source_provenance_authority=authority,
        source_repository=repository,
        source_revision=revision,
        distribution_name=distribution.metadata["Name"],
        distribution_version=distribution.version,
        artifact_logical_name=wheel.name,
        artifact_sha256=hashlib.sha256(content).hexdigest(),
        artifact_size=len(content),
    )


def _wheel_distribution_name(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        content = archive.read(metadata_name).decode("utf-8")
    return next(line[6:] for line in content.splitlines() if line.startswith("Name: "))


def test_builder_installs_exact_distribution_fixture_in_clean_environment_and_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    manager_wheel = _build_wheel(
        repository / "packages/onlyalpha-runtime-generation-manager",
        tmp_path / "manager-wheel",
    )
    strategy_wheel = _build_wheel(
        repository / "tests/fixtures/runtime_strategy_provider",
        tmp_path / "strategy-wheel",
    )
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity(
        core_artifact.distribution_name,
        core_artifact.distribution_version,
        core_artifact.artifact_sha256,
    )
    provider = quant_asset_provider()
    strategy_bytes = strategy_wheel.read_bytes()
    strategy_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-test-strategy-provider",
        source_revision="2" * 40,
        artifact_logical_name=strategy_wheel.name,
        artifact_bytes=strategy_bytes,
        tested_core_execution_fingerprint=core_identity.fingerprint,
        provider=provider,
    )
    manager_bytes = manager_wheel.read_bytes()
    manager_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="3" * 40,
        distribution_name="onlyalpha-runtime-generation-manager",
        distribution_version="0.9.9",
        artifact_logical_name=manager_wheel.name,
        artifact_sha256=hashlib.sha256(manager_bytes).hexdigest(),
        artifact_size=len(manager_bytes),
    )
    pyarrow_artifact = _plain_artifact(
        pyarrow_wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision=f"release-{metadata.version('pyarrow')}",
    )
    artifacts = (core_artifact, manager_artifact, strategy_artifact, pyarrow_artifact)
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(manager_artifact, manager_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    store.put_once(pyarrow_artifact, pyarrow_wheel.read_bytes())
    builder = OnlyRuntimeGenerationBuilder(store, Path(sys.executable))
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    first = builder.build_validated(
        artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-a"
    )
    second = builder.build_validated(
        artifacts=artifacts, expected_catalog=catalog, environment_root=tmp_path / "runtime-b"
    )
    assert first == second
    assert first.manifest.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert first.validation_evidence.verifies(first.manifest)
    assert first.manifest.runtime_generation_fingerprint == second.manifest.runtime_generation_fingerprint
    revision = OnlyPrivateAlphaRevision.from_draft(
        OnlyPrivateAlphaDraft(
            alpha_id="private.alpha.runtime_native",
            semantic_version="1",
            source_text=(
                "def calculate(api, inputs, parameters):\n"
                "    return {'value': api.sub(inputs['close'], parameters['offset'])}\n"
            ),
            alpha_api_version=1,
            alpha_api_contract_fingerprint=ONLY_PRIVATE_ALPHA_API_V1.api_contract_fingerprint,
            input_contract={"close": {"type": "DECIMAL"}},
            parameter_contract={"offset": {"type": "DECIMAL"}},
            output_contract={"value": {"type": "DECIMAL"}},
            description="Runtime native",
            economic_rationale="Historical rebuild proof",
            category="test",
        )
    )
    closure = OnlyPrivateAlphaExecutableClosureV1.create(
        revision,
        ({"close": Decimal("2")},),
        {"offset": Decimal("1")},
        host=OnlyPrivateAlphaIsolatedProgramHost(3),
    )
    native_provider = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            "private.runtime.factor",
            revision.revision_fingerprint,
            OnlyQuantAssetKind.ALPHA,
            OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
        ),
        calculation_registrations=closure.registrations,
        private_alpha_snapshot=closure.provider_snapshot,
    )
    native_catalog = OnlyQuantAssetCatalogGeneration((provider, native_provider))
    native_manifest = builder.bind_private_alpha_closure(
        base_manifest=first.manifest,
        expected_catalog=native_catalog,
        closure=closure,
    )
    assert builder.rebuild_private_alpha_providers(native_manifest)[0].descriptor() == native_provider.descriptor()

    def current_adapter_forbidden(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("CURRENT_PRIVATE_ALPHA_ADAPTER_SUBSTITUTION_FORBIDDEN")

    monkeypatch.setattr(runtime_builder_module, "OnlyPrivateAlphaAdapterV1", current_adapter_forbidden)
    native_rebuilt = builder.rebuild_validated(
        expected_manifest=native_manifest,
        environment_root=tmp_path / "runtime-native-rebuilt",
    )
    assert native_rebuilt.manifest == native_manifest
    native_bundle = builder.rebuild_catalog_context_bundle(
        expected_manifest=native_manifest,
        environment_root=tmp_path / "runtime-native-catalog",
    )
    assert only_canonical_fingerprint(native_bundle["catalog"]) == only_canonical_fingerprint(
        native_catalog.descriptor()
    )
    hosted_native = subprocess.run(
        [
            str(tmp_path / "runtime-native-catalog" / "bin" / "python"),
            "-I",
            "-c",
            "from decimal import Decimal; from pathlib import Path; import json; import pyarrow as pa; "
            "from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind, OnlyCalculationReference; "
            "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
            "from onlyalpha_runtime_generation_manager.hosted import only_load_hosted_quant_asset_catalog; "
            "e=OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads(Path('onlyalpha-runtime-generation-validation.json').read_text())); "
            "r=only_load_hosted_quant_asset_catalog(e).calculation_registry(); "
            "research=r.resolve(OnlyCalculationKind.FACTOR,'private.alpha.runtime_native','1',OnlyCalculationBackendKind.RESEARCH); "
            "definition=research.definition_resolver.resolve({'offset':Decimal('1')},{'close':OnlyCalculationReference(None,'close','close')}); "
            "assert research.provider.execute(definition,{'close':pa.array([Decimal('2')],type=pa.decimal128(38,12))})['value'].to_pylist()==[Decimal('1.000000000000')]; "
            "trading=r.resolve(OnlyCalculationKind.FACTOR,'private.alpha.runtime_native','1',OnlyCalculationBackendKind.TRADING); "
            "assert trading.provider.create(definition,object()).update({'close':Decimal('2')})=={'value':Decimal('1')}",
        ],
        cwd=tmp_path / "runtime-native-catalog",
        capture_output=True,
        text=True,
        check=False,
    )
    assert hosted_native.returncode == 0, hosted_native.stdout + hosted_native.stderr
    authority_root = tmp_path / "exact-catalog-authority"
    authority = OnlyRuntimeGenerationRegistry(authority_root)
    authority.prepare(first.manifest, actor="operator", occurred_at=NOW)
    authority.admit_ready(first.validation_evidence, actor="validator", occurred_at=NOW)
    authority.prepare(native_manifest, actor="operator", occurred_at=NOW)
    authority.admit_ready(native_rebuilt.validation_evidence, actor="validator", occurred_at=NOW)
    generation = first.manifest.runtime_generation_fingerprint
    host = OnlyHistoricalGenerationHostManager(
        registry=OnlyRuntimeGenerationRegistry(authority_root),
        builder=builder,
        cache_root=tmp_path / "historical-search-hosts",
    )
    worker = host.acquire(generation)
    assert worker.handshake.runtime_generation_fingerprint == generation
    assert host.acquire(generation) is worker
    worker.process.kill()
    worker.process.wait(timeout=5)
    restarted = host.acquire(generation)
    assert restarted is not worker
    assert restarted.handshake == worker.handshake
    host.evict(generation, delete_environment=True)
    rebuilt = host.acquire(generation)
    assert rebuilt.handshake == worker.handshake
    parent_modules = set(sys.modules)
    packaging_wheel = _installed_distribution_wheel("packaging", tmp_path / "support-wheel-g2")
    packaging_artifact = _plain_artifact(
        packaging_wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="PyPA-packaging",
        revision=f"release-{metadata.version('packaging')}",
    )
    store.put_once(packaging_artifact, packaging_wheel.read_bytes())
    second_generation = builder.build_validated(
        artifacts=(*artifacts, packaging_artifact),
        expected_catalog=catalog,
        environment_root=tmp_path / "runtime-g2-proof",
    )
    g2 = second_generation.manifest.runtime_generation_fingerprint
    assert g2 != generation
    assert second_generation.manifest.catalog_generation_fingerprint == (first.manifest.catalog_generation_fingerprint)
    authority.prepare(second_generation.manifest, actor="operator", occurred_at=NOW)
    authority.admit_ready(second_generation.validation_evidence, actor="validator", occurred_at=NOW)
    g1_worker = host.acquire(generation)
    g2_worker = host.acquire(g2)
    assert g1_worker.process.pid != g2_worker.process.pid
    assert g1_worker.handshake.runtime_generation_fingerprint == generation
    assert g2_worker.handshake.runtime_generation_fingerprint == g2
    assert g1_worker.handshake.catalog_generation_fingerprint == (g2_worker.handshake.catalog_generation_fingerprint)
    assert set(sys.modules) == parent_modules
    host.close()
    fresh_reader = OnlyRuntimeGenerationExactCatalogDescriptorReader(
        OnlyRuntimeGenerationRegistry(authority_root),
        builder,
        tmp_path / "exact-catalog-environments",
    )
    exact_context = OnlyExactCatalogContextQueryService(
        fresh_reader, fresh_reader, fresh_reader, fresh_reader
    ).get_exact_catalog_context(catalog.generation_fingerprint)
    assert exact_context.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert exact_context == OnlyExactCatalogContextQueryService(
        fresh_reader, fresh_reader, fresh_reader, fresh_reader
    ).get_exact_catalog_context(catalog.generation_fingerprint)
    native_context = OnlyExactCatalogContextQueryService(
        fresh_reader, fresh_reader, fresh_reader, fresh_reader
    ).get_exact_catalog_context(native_catalog.generation_fingerprint)
    assert native_context.catalog_generation_fingerprint == native_catalog.generation_fingerprint
    assert {item.provider_id for item in native_context.ordered_providers} == {
        provider.manifest.provider_id,
        native_provider.manifest.provider_id,
    }
    hosted = subprocess.run(
        [
            str(tmp_path / "runtime-a" / "bin" / "python"),
            "-I",
            "-c",
            "from pathlib import Path; import json; "
            "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
            "from onlyalpha_runtime_generation_manager.hosted import only_verify_hosted_runtime_generation; "
            "e=OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads("
            "Path('onlyalpha-runtime-generation-validation.json').read_text())); "
            "only_verify_hosted_runtime_generation(e)",
        ],
        cwd=tmp_path / "runtime-a",
        capture_output=True,
        text=True,
        check=False,
    )
    assert hosted.returncode == 0, hosted.stdout + hosted.stderr
    installed_provider = next(
        (tmp_path / "runtime-b").glob("lib/python*/site-packages/onlyalpha_test_strategy_provider/provider.py")
    )
    installed_provider.write_bytes(installed_provider.read_bytes() + b"\n")
    mismatched_host = subprocess.run(
        [
            str(tmp_path / "runtime-b" / "bin" / "python"),
            "-I",
            "-c",
            "from pathlib import Path; import json; "
            "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
            "from onlyalpha_runtime_generation_manager.hosted import only_verify_hosted_runtime_generation; "
            "e=OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads("
            "Path('onlyalpha-runtime-generation-validation.json').read_text())); "
            "only_verify_hosted_runtime_generation(e)",
        ],
        cwd=tmp_path / "runtime-b",
        capture_output=True,
        text=True,
        check=False,
    )
    assert mismatched_host.returncode != 0
    assert "RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH" in mismatched_host.stderr

    class _HistoricalManifest:
        def resolve(self, revision, *, exact_generation_fingerprint=None):  # type: ignore[no-untyped-def]
            del revision
            assert exact_generation_fingerprint == first.manifest.runtime_generation_fingerprint
            return first.manifest

    reconstructed = OnlyHistoricalExecutableRuntimeGenerationResolver(  # type: ignore[arg-type]
        _HistoricalManifest(),
        builder,
    ).resolve(
        object(),  # type: ignore[arg-type]
        exact_generation_fingerprint=first.manifest.runtime_generation_fingerprint,
        environment_root=tmp_path / "historical-runtime",
    )
    assert reconstructed.manifest.runtime_generation_fingerprint == first.manifest.runtime_generation_fingerprint

    artifact_path, _ = store._paths(strategy_artifact.artifact_sha256)
    artifact_path.write_bytes(b"corrupt")
    with pytest.raises(OnlyExactCatalogContextUnavailable):
        OnlyExactCatalogContextQueryService(
            fresh_reader, fresh_reader, fresh_reader, fresh_reader
        ).get_exact_catalog_context(catalog.generation_fingerprint)
    artifact_path.unlink()
    with pytest.raises(OnlyExactCatalogContextUnavailable):
        OnlyExactCatalogContextQueryService(
            fresh_reader, fresh_reader, fresh_reader, fresh_reader
        ).get_exact_catalog_context(catalog.generation_fingerprint)
    with pytest.raises(ValueError, match="HISTORICAL_IMPLEMENTATION_UNAVAILABLE"):
        OnlyHistoricalExecutableRuntimeGenerationResolver(  # type: ignore[arg-type]
            _HistoricalManifest(),
            builder,
        ).resolve(
            object(),  # type: ignore[arg-type]
            exact_generation_fingerprint=first.manifest.runtime_generation_fingerprint,
            environment_root=tmp_path / "corrupt-historical-runtime",
        )


def test_catalog_mismatch_never_produces_a_generation(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    strategy_wheel = _build_wheel(
        repository / "tests/fixtures/runtime_strategy_provider",
        tmp_path / "strategy-wheel",
    )
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    provider = quant_asset_provider()
    strategy_bytes = strategy_wheel.read_bytes()
    strategy_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-test-strategy-provider",
        source_revision="2" * 40,
        artifact_logical_name=strategy_wheel.name,
        artifact_bytes=strategy_bytes,
        tested_core_execution_fingerprint=OnlyCoreExecutionIdentity(
            "onlyalpha", "0.9.9", core_artifact.artifact_sha256
        ).fingerprint,
        provider=provider,
    )
    pyarrow_artifact = _plain_artifact(
        pyarrow_wheel,
        role=OnlyDistributionArtifactRole.SUPPORT,
        authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        repository="Apache-Arrow",
        revision=f"release-{metadata.version('pyarrow')}",
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core_artifact, core_bytes)
    store.put_once(strategy_artifact, strategy_bytes)
    store.put_once(pyarrow_artifact, pyarrow_wheel.read_bytes())
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_CATALOG_MISMATCH"):
        OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
            artifacts=(core_artifact, strategy_artifact, pyarrow_artifact),
            expected_catalog=OnlyQuantAssetCatalogGeneration(()),
            environment_root=tmp_path / "rejected-runtime",
        )
    assert not (tmp_path / "rejected-runtime").exists()


def test_builder_rejects_duplicate_distribution_identity_before_environment_creation(tmp_path: Path) -> None:
    first_bytes = b"first-wheel"
    second_bytes = b"second-wheel"
    common = {
        "source_provenance_authority": OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "source_repository": "OnlyAlpha",
        "source_revision": "1" * 40,
        "distribution_name": "onlyalpha",
        "distribution_version": "0.9.9",
        "artifact_logical_name": "onlyalpha-0.9.9-py3-none-any.whl",
    }
    core = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        artifact_sha256=hashlib.sha256(first_bytes).hexdigest(),
        artifact_size=len(first_bytes),
        **common,
    )
    duplicate = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        artifact_sha256=hashlib.sha256(second_bytes).hexdigest(),
        artifact_size=len(second_bytes),
        **common,
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    store.put_once(core, first_bytes)
    store.put_once(duplicate, second_bytes)
    environment = tmp_path / "runtime"
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_ARTIFACT_MISMATCH"):
        OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
            artifacts=(core, duplicate),
            expected_catalog=OnlyQuantAssetCatalogGeneration(()),
            environment_root=environment,
        )
    assert not environment.exists()


def test_builder_clean_installs_alpha_distribution_fixture_with_exact_support_artifact(tmp_path: Path) -> None:
    from onlyalpha_test_alpha_provider.provider import quant_asset_provider as alpha_provider

    repository = Path(__file__).resolve().parents[3]
    core_wheel = _build_wheel(repository, tmp_path / "core-wheel")
    alpha_wheel = _build_wheel(repository / "tests/fixtures/runtime_alpha_provider", tmp_path / "alpha-wheel")
    pyarrow_wheel = _installed_distribution_wheel("pyarrow", tmp_path / "support-wheel")
    core_bytes = core_wheel.read_bytes()
    core_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.CORE,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        source_repository="OnlyAlpha",
        source_revision="1" * 40,
        distribution_name="onlyalpha",
        distribution_version="0.9.9",
        artifact_logical_name=core_wheel.name,
        artifact_sha256=hashlib.sha256(core_bytes).hexdigest(),
        artifact_size=len(core_bytes),
    )
    core_identity = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", core_artifact.artifact_sha256)
    provider = alpha_provider()
    alpha_bytes = alpha_wheel.read_bytes()
    alpha_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="OnlyAlpha-test-alpha-provider",
        source_revision="2" * 40,
        artifact_logical_name=alpha_wheel.name,
        artifact_bytes=alpha_bytes,
        tested_core_execution_fingerprint=core_identity.fingerprint,
        provider=provider,
    )
    support_bytes = pyarrow_wheel.read_bytes()
    support_artifact = OnlyDistributionArtifactManifest(
        role=OnlyDistributionArtifactRole.SUPPORT,
        source_provenance_authority=OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        source_repository="Apache-Arrow",
        source_revision="pyarrow-25.0.0",
        distribution_name="pyarrow",
        distribution_version=metadata.version("pyarrow"),
        artifact_logical_name=pyarrow_wheel.name,
        artifact_sha256=hashlib.sha256(support_bytes).hexdigest(),
        artifact_size=len(support_bytes),
    )
    store = OnlyLocalImmutableArtifactStore(tmp_path / "artifacts")
    for manifest, content in (
        (core_artifact, core_bytes),
        (alpha_artifact, alpha_bytes),
        (support_artifact, support_bytes),
    ):
        store.put_once(manifest, content)
    generation = OnlyRuntimeGenerationBuilder(store, Path(sys.executable)).build(
        artifacts=(core_artifact, alpha_artifact, support_artifact),
        expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
        environment_root=tmp_path / "runtime",
    )
    assert {item.provider_id for item in generation.providers} == {"example.alpha.library"}
    assert {item.backend for item in generation.implementations} == {"RESEARCH", "TRADING"}

    changed_implementation = replace(
        alpha_artifact.implementations[0],
        implementation_fingerprint=(
            "f" * 64 if alpha_artifact.implementations[0].implementation_fingerprint != "f" * 64 else "e" * 64
        ),
    )
    mismatched_artifact = replace(
        alpha_artifact,
        implementations=(changed_implementation, *alpha_artifact.implementations[1:]),
    )
    mismatch_store = OnlyLocalImmutableArtifactStore(tmp_path / "mismatch-artifacts")
    for manifest, content in (
        (core_artifact, core_bytes),
        (mismatched_artifact, alpha_bytes),
        (support_artifact, support_bytes),
    ):
        mismatch_store.put_once(manifest, content)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH"):
        OnlyRuntimeGenerationBuilder(mismatch_store, Path(sys.executable)).build(
            artifacts=(core_artifact, mismatched_artifact, support_artifact),
            expected_catalog=OnlyQuantAssetCatalogGeneration((provider,)),
            environment_root=tmp_path / "mismatched-runtime",
        )
    assert not (tmp_path / "mismatched-runtime").exists()
