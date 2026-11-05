"""真实原生 Runtime 发布与物理归档；不授予 Research 或交易权限。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from onlyalpha.canonical import only_canonical_fingerprint

from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
ROOT = Path(__file__).resolve().parents[4]
AT = "2026-10-29T01:00:00.123400Z"


def sealed(record: dict[str, Any], field: str) -> str:
    payload = dict(record)
    fingerprint = payload.pop(field)
    assert only_canonical_fingerprint(payload) == fingerprint
    return fingerprint


@pytest.fixture(scope="module")
def native_environment_case(tmp_path_factory: pytest.TempPathFactory, native_release_probe: Path) -> dict[str, Any]:
    """只准备受控安装；由测试中的 Rust owner 建立并验证正式 Runtime。"""
    from scripts.build_algorithm_sdk import install
    from scripts.dev_verification import source_inputs
    from scripts.embed_build_provenance import resolve_build_provenance_bytes

    temporary = tmp_path_factory.mktemp("native-environment")
    root, runtime = temporary / "release", temporary / "runtime"
    root.mkdir()
    artifact = install(root / "wheels", root / "algorithms")
    (root / "bin").mkdir()
    executable = root / "bin/onlyalpha-backend"
    shutil.copyfile(native_release_probe, executable)
    subprocess.run(["strip", "--strip-all", str(executable)], check=True, timeout=30)
    executable.chmod(0o500)
    (root / "source-provenance.json").write_bytes(resolve_build_provenance_bytes(ROOT))
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_root": str(root),
                "version": "0.11.1",
                "algorithm_artifact": artifact,
                "files": files,
                "source_inputs": source_inputs(ROOT),
            }
        )
    )
    # Keep the original immutable Factor source/revision fixture, including its
    # own semantic version. Rust independently derives the current native graph.
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    return {
        "root": root,
        "runtime": runtime,
        "executable": executable,
        "artifact": artifact,
        "vector": vector,
        "next": 0,
    }


def prepare(
    case: dict[str, Any],
    *,
    fresh: bool,
    root: Path | None = None,
    artifact: str | None = None,
    expect_error: bool = False,
) -> dict[str, Any]:
    release = root or case["root"]
    result = subprocess.run(
        [str(release / "bin/onlyalpha-backend")],
        input=json.dumps(
            {
                "op": "runtime-environment",
                "factor": case["vector"],
                "release_root": str(release),
                "runtime_root": str(case["runtime"]),
                "algorithm_artifact": artifact or case["artifact"],
                "fresh": fresh,
                "at": AT,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    assert ("error" in value) == expect_error, (value, result.stderr)
    return value


@pytest.mark.parametrize("stage", ["prepare", "inspect", "relocate"])
def test_native_environment_publication_uses_installed_algorithms_and_original_metadata_contracts(
    native_environment_case: dict[str, Any],
    schema_db: str,
    stage: str,
) -> None:
    """三次独立子进程验证发布、精确重开和安装位置变化。"""
    case = native_environment_case
    assert stage == ["prepare", "inspect", "relocate"][case["next"]]
    runtime = case["runtime"]
    if stage == "prepare":
        first = prepare(case, fresh=True)
        generation = sealed(first["manifest"], "runtime_generation_fingerprint")
        assert first["snapshot"] == {"active_for_new_work": None, "states": {generation: "READY"}}
        case.update(first=first, before=(runtime / "generation-events.jsonl").read_bytes(), next=1)
        return
    first, before = case["first"], case["before"]
    manifest = first["manifest"]
    generation = sealed(manifest, "runtime_generation_fingerprint")
    if stage == "relocate":
        from scripts.build_algorithm_sdk import install

        previous = case["root"]
        root = previous.parent / "relocated-release"
        root.mkdir()
        artifact = install(root / "wheels", root / "algorithms")
        (root / "bin").mkdir()
        shutil.copyfile(case["executable"], root / "bin/onlyalpha-backend")
        (root / "bin/onlyalpha-backend").chmod(0o500)
        shutil.copyfile(previous / "source-provenance.json", root / "source-provenance.json")
        original = json.loads((previous / "manifest.json").read_text())
        relocated = {
            **original,
            "runtime_root": str(root),
            "algorithm_artifact": artifact,
            "files": {
                str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*")
                if path.is_file()
            },
        }
        identity_files = {
            name: digest
            for name, digest in original["files"].items()
            if name.startswith(("wheels/", "bin/")) or name == "source-provenance.json"
        }
        assert {name: relocated["files"][name] for name in identity_files} == identity_files
        # Installation-local pyvenv/python_paths metadata may change; released
        # wheel/ELF/source bytes above remain exact immutable identities.
        (root / "manifest.json").write_text(json.dumps(relocated))
        rebuilt = prepare(case, fresh=False, root=root, artifact=artifact)
        assert rebuilt["manifest"] == manifest
        assert rebuilt["snapshot"] == first["snapshot"]
        assert rebuilt["proof"]["installed_proof_fingerprint"] != first["proof"]["installed_proof_fingerprint"]
        assert (runtime / "generation-events.jsonl").read_bytes() == before
        for record in [first, rebuilt]:
            proof = record["proof"]
            pin = sealed(proof, "installed_proof_fingerprint")
            retained = runtime / "runtime-generation-installed-proof" / generation / f"{pin}.json"
            assert json.loads(retained.read_text()) == proof
        case["next"] = 3
        return

    from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
        OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
        OnlyPrivateFactorSourceArtifactManifestV1,
    )
    from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

    assert first["snapshot"] == {"active_for_new_work": None, "states": {generation: "READY"}}
    assert prepare(case, fresh=False) == first
    assert (runtime / "generation-events.jsonl").read_bytes() == before
    assert json.loads((runtime / "runtime-generations" / f"{generation}.json").read_text()) == manifest
    archive_manifests = []
    for sha in manifest["artifact_sha256s"]:
        directory = runtime / "artifacts" / sha[:2] / sha
        record = json.loads((directory / "manifest.json").read_text())
        sealed(record, "manifest_fingerprint")
        archive_manifests.append(record)
        physical = directory / ("artifact.elf" if record["artifact_logical_name"].endswith(".elf") else "artifact.whl")
        original = physical.read_bytes()
        assert hashlib.sha256(original).hexdigest() == record["artifact_sha256"] == sha
        assert len(original) == record["artifact_size"]
    assert (
        sorted(record["manifest_fingerprint"] for record in archive_manifests)
        == manifest["artifact_manifest_fingerprints"]
    )
    native = [record for record in archive_manifests if record["role"] == "BACKEND_RUNTIME"]
    assert len(native) == 1 and native[0]["schema_version"] == 3
    assert len(native[0]["assets"]) == 24 and len(native[0]["implementations"]) == 80
    assert all(asset["semantic_version"] == "2" for asset in native[0]["assets"])
    assert {record["distribution_name"] for record in archive_manifests}.isdisjoint({"onlyalpha-plugin-operators"})
    assert manifest["providers"] == [
        {
            key: native[0][key]
            for key in ["provider_id", "provider_version", "provider_content_fingerprint", "artifact_sha256"]
        }
    ]
    validation = json.loads((runtime / "runtime-generation-validation" / f"{generation}.json").read_text())
    sealed(validation, "validation_evidence_fingerprint")
    expected = {
        "schema_version": 1,
        "validation_contract_version": "ONLYALPHA_RUNTIME_GENERATION_VALIDATION@1",
        "runtime_generation_fingerprint": generation,
        "core_execution_fingerprint": only_canonical_fingerprint(manifest["core_execution"]),
    }
    expected.update(
        {
            key: manifest[key]
            for key in [
                "artifact_manifest_fingerprints",
                "artifact_sha256s",
                "providers",
                "catalog_generation_fingerprint",
                "implementations",
                "private_factor_bindings",
            ]
        }
    )
    assert {key: value for key, value in validation.items() if key != "validation_evidence_fingerprint"} == expected
    events = [json.loads(line) for line in before.splitlines()]
    assert [event["kind"] for event in events] == ["GenerationPrepared", "GenerationValidated"]
    previous = None
    for index, event in enumerate(events, 1):
        assert event["sequence"] == index and event["previous_event_fingerprint"] == previous
        previous = sealed(event, "event_fingerprint")
    assert events[-1]["validation_evidence_fingerprint"] == validation["validation_evidence_fingerprint"]
    assert first["proof"]["catalog"]["schema_version"] == 1
    assert only_canonical_fingerprint(first["proof"]["catalog"]) == manifest["catalog_generation_fingerprint"]
    binding = manifest["private_factor_bindings"][0]
    pin = binding["runtime_artifact_fingerprint"]
    saved = json.loads((runtime / "artifacts/private-factor-runtime" / pin[:2] / f"{pin}.json").read_text())
    sealed(saved, "runtime_artifact_fingerprint")
    source = OnlyPrivateFactorSourceArtifactManifestV1.from_dict(saved["source_artifact"])
    assert source.to_dict() == saved["source_artifact"]
    revision = case["vector"]["revision"]
    fields = OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
    projected = OnlyPrivateFactorExecutableSourceRecordV1.from_dict({key: revision[key] for key in fields})
    assert projected.revision_fingerprint == revision["revision_fingerprint"]
    assert projected.source_sha256 == source.source_sha256
    source_root = (
        runtime
        / "artifacts/private-factor"
        / source.source_artifact_fingerprint[:2]
        / source.source_artifact_fingerprint
    )
    assert (source_root / "source.py").read_bytes() == revision["source_text"].encode()
    assert json.loads((source_root / "manifest.json").read_text()) == saved["source_artifact"]
    evidence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.from_dict(saved["equivalence_evidence"])
    assert evidence.to_dict() == saved["equivalence_evidence"]
    vectors = evidence.test_vector_set_fingerprint
    retained = json.loads(
        (runtime / "artifacts/private-factor-equivalence" / vectors[:2] / f"{vectors}.json").read_text()
    )
    assert only_canonical_fingerprint(retained) == vectors
    assert retained == first["proof"]["algorithm_observation"]["certification_vectors"]
    case["next"] = 2


def test_archived_native_bytes_missing_refuses_publication_without_journal_change(
    native_environment_case: dict[str, Any],
    schema_db: str,
    tmp_path: Path,
) -> None:
    case = {**native_environment_case, "runtime": tmp_path / "runtime"}
    first = prepare(case, fresh=True)
    native = next(
        record
        for record in first["proof"]["native_descriptor"]["implementations"]
        if record["calculation_type_reference"]["kind"] == "INDICATOR"
    )
    sha = native["resources"][0]["byte_sha256"]
    archive = case["runtime"] / "artifacts" / sha[:2] / sha / "artifact.elf"
    original = archive.read_bytes()
    before = (case["runtime"] / "generation-events.jsonl").read_bytes()
    held = tmp_path / "retained-original.elf"
    archive.rename(held)
    try:
        assert not archive.exists()
        assert prepare(case, fresh=False, expect_error=True) == {"error": "RESEARCH_RUNTIME_PROOF_INVALID"}
        assert not archive.exists(), "普通重开不得隐式重建损坏归档"
        assert (case["runtime"] / "generation-events.jsonl").read_bytes() == before
    finally:
        held.rename(archive)
    assert archive.read_bytes() == original
    assert prepare(case, fresh=False) == first
    assert (case["runtime"] / "generation-events.jsonl").read_bytes() == before
