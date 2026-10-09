"""Mandatory source consumption, physical baseline and no legacy in-place upgrade."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pyarrow.parquet as pq
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.artifact.errors import OnlyResearchArtifactError
from onlyalpha.research.dataset.sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1
from tests.research.artifact.test_calculation_v2 import _publication, _root

pytestmark = pytest.mark.contract


def _bytes(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("forgery", ("missing", "copy", "portable", "hashes", "e1", "mutated_context"))
def test_source_input_cannot_be_forged_before_staging_or_successful_reuse(tmp_path, existing, forgery):
    publish, _, _, _, _, _ = _publication(tmp_path)
    if existing:
        publish()
    original = publish.__kwdefaults__["verified_input"]
    if forgery == "copy":
        invalid = replace(original)
    elif forgery == "portable":
        invalid = OnlyRetainedSealedChartInputEvidenceV1.from_dict(original.retained.to_dict())
    elif forgery == "hashes":
        invalid = {"snapshot_fingerprint": original.retained.to_dict()["dataset_snapshot_fingerprint"]}
    elif forgery == "e1":
        invalid = {"status": "EXECUTED_UNPUBLISHED", "source": original.retained.to_dict(), "attested": True}
    elif forgery == "mutated_context":
        invalid = original
        object.__setattr__(invalid, "runtime_generation_fingerprint", "f" * 64)
    else:
        invalid = None
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_INVALID"):
        publish(verified_input=invalid)
    assert _bytes(tmp_path) == before
    assert not tuple((tmp_path / "artifacts").rglob(".stage-*"))


@pytest.mark.parametrize("existing", (False, True))
def test_original_physical_source_loss_blocks_publication_but_not_portable_read(tmp_path, existing):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish() if existing else None
    (tmp_path / "source-owner.json").rename(tmp_path / "unavailable-source.json")
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_INVALID"):
        publish()
    assert _bytes(tmp_path) == before
    if artifact is not None:
        assert store.load_verified(
            artifact.manifest.artifact_content_fingerprint,
            research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
        )


def test_physical_baseline_sections_have_exact_schema_content_and_typed_empty_scientific_facts(tmp_path):
    publish, _, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    required = {
        "artifact_manifest.json",
        "market.parquet",
        "graphs.json",
        "variables.parquet",
        "readiness.parquet",
        "calculation_evidence.json",
        "sealed_input_evidence.json",
        "signals.parquet",
        "statistics.parquet",
    }
    assert required <= {path.name for path in root.iterdir() if path.is_file()}
    assert json.loads((root / "sealed_input_evidence.json").read_text()) == artifact.manifest.sealed_input.to_dict()
    assert json.loads((root / "graphs.json").read_text()) == [
        {"calculation_fingerprint": item.calculation_fingerprint, "graph": item.calculation_graph.to_dict()}
        for item in artifact.manifest.calculations
    ]
    assert json.loads((root / "calculation_evidence.json").read_text()) == [
        item.to_dict() for item in artifact.manifest.selected_evidence
    ]
    assert pq.read_table(root / "market.parquet").num_rows == artifact.dataset_table.num_rows
    assert pq.read_table(root / "variables.parquet").num_rows == pq.read_table(root / "readiness.parquet").num_rows
    from onlyalpha.research.artifact.scientific_store import _SIGNALS, _STATISTICS

    for name, schema in (("signals.parquet", _SIGNALS), ("statistics.parquet", _STATISTICS)):
        table = pq.read_table(root / name)
        assert table.num_rows == 0 and table.schema == schema


@pytest.mark.parametrize(
    "path",
    (
        "market.parquet",
        "graphs.json",
        "variables.parquet",
        "readiness.parquet",
        "calculation_evidence.json",
        "sealed_input_evidence.json",
        "signals.parquet",
        "statistics.parquet",
    ),
)
def test_no_required_section_can_be_missing_or_replaced(tmp_path, path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    (root / path).unlink()
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_verified(
            artifact.manifest.artifact_content_fingerprint,
            research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
        )
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        publish()
    assert _bytes(tmp_path) == before


@pytest.mark.parametrize("dimension", ("source_reference", "evidence", "materialization", "segments"))
def test_rehashed_source_bytes_cannot_hide_missing_mandatory_relation(tmp_path, dimension):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    payload = deepcopy(artifact.manifest.to_dict())
    del payload["sealed_input"][dimension]
    raw = only_canonical_json(payload["sealed_input"]).encode()
    (root / "sealed_input_evidence.json").write_bytes(raw)
    descriptor = next(item for item in payload["files"] if item["relative_path"] == "sealed_input_evidence.json")
    descriptor.update(byte_sha256=hashlib.sha256(raw).hexdigest(), byte_size=len(raw))
    (root / "artifact_manifest.json").write_text(only_canonical_json(payload))
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_verified(
            artifact.manifest.artifact_content_fingerprint,
            research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
        )
    assert _bytes(tmp_path) == before


def test_existing_unproven_schema_two_is_rejected_without_any_upgrade_or_overwrite(tmp_path):
    publish, store, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    root = _root(tmp_path, artifact.manifest.artifact_content_fingerprint)
    payload = artifact.manifest.to_dict()
    del payload["sealed_input"]
    (root / "sealed_input_evidence.json").unlink()
    payload["files"] = [
        item for item in payload["files"] if item["relative_path"] in artifact.manifest.partition_descriptors
    ]
    for path in root.iterdir():
        if path.is_file() and path.name != "artifact_manifest.json":
            path.unlink()
    (root / "artifact_manifest.json").write_text(only_canonical_json(payload))
    before = _bytes(tmp_path)
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        store.load_verified(
            artifact.manifest.artifact_content_fingerprint,
            research_result_fingerprint=artifact.manifest.result.research_result_fingerprint,
        )
    with pytest.raises(OnlyResearchArtifactError, match="ARTIFACT_CORRUPT"):
        publish()
    assert _bytes(tmp_path) == before
