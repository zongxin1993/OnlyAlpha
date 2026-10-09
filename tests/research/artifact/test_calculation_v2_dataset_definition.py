"""Fully rehashed copied facts must still agree with their Dataset Definition."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pyarrow.parquet as pq
import pytest

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.research.artifact.calculation_v2_model import OnlyResearchCalculationArtifactManifestV2
from onlyalpha.research.artifact.calculation_v2_verification import only_verify_calculation_artifact_tables_v2
from onlyalpha.research.calculation.identity import only_research_calculation_fingerprint
from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultV2
from onlyalpha.research.calculation.result_v2_identity import only_research_calculation_result_fingerprint_v2
from onlyalpha.research.dataset.identity import only_snapshot_fingerprint
from onlyalpha.research.result import OnlyResearchResultAssembler
from tests.research.artifact.test_calculation_v2 import _publication, _root
from tests.research.calculation.test_result_v2_store import AUDIT

pytestmark = pytest.mark.contract


def test_complete_rehashed_artifact_cannot_retain_bars_outside_its_requested_range(tmp_path):
    publish, _, _, _, _, _ = _publication(tmp_path)
    artifact = publish()
    manifest = artifact.manifest
    definition = replace(
        manifest.dataset.definition,
        time_range=OnlyTimeRange(
            manifest.dataset.definition.time_range.start + timedelta(days=365),
            manifest.dataset.definition.time_range.end + timedelta(days=365),
        ),
    )
    snapshot_id = only_snapshot_fingerprint(
        definition,
        manifest.dataset.dataset_schema,
        manifest.dataset.content_fingerprint,
        manifest.dataset.row_count,
        manifest.dataset.construction_fingerprint,
    )
    dataset = replace(manifest.dataset, definition=definition, snapshot_fingerprint=snapshot_id)
    original = manifest.calculations[0]
    calculation_id = only_research_calculation_fingerprint(snapshot_id, original.calculation_graph_fingerprint)
    calculation_result_id = only_research_calculation_result_fingerprint_v2(
        calculation_id, original.result_content_fingerprint
    )
    calculation = replace(
        original,
        dataset_snapshot_fingerprint=snapshot_id,
        calculation_fingerprint=calculation_id,
        calculation_result_fingerprint=calculation_result_id,
    )
    evidence = replace(
        manifest.selected_evidence[0],
        dataset_snapshot_fingerprint=snapshot_id,
        calculation_fingerprint=calculation_id,
        calculation_result_fingerprint=calculation_result_id,
    )
    plan = replace(
        manifest.result.plan,
        dataset_snapshot_fingerprint=snapshot_id,
        calculations=tuple(
            replace(item, calculation_fingerprint=calculation_id) for item in manifest.result.plan.calculations
        ),
        published_series=tuple(
            replace(item, calculation_fingerprint=calculation_id) for item in manifest.result.plan.published_series
        ),
    )
    retained = artifact.calculations[original.calculation_fingerprint]
    result = OnlyResearchResultAssembler(
        None,
        audit_time=lambda: AUDIT,
        readiness_result_store=SimpleNamespace(
            load_verified=lambda _: OnlyResearchCalculationResultV2(calculation, retained.outputs, retained.readiness),
        ),
    ).assemble(plan)
    files = tuple(
        sorted(
            (
                replace(
                    item, relative_path=item.relative_path.replace(original.calculation_fingerprint, calculation_id)
                )
                for item in manifest.files
            ),
            key=lambda item: item.relative_path,
        )
    )
    mutated = replace(
        manifest,
        result=result.manifest,
        dataset=dataset,
        calculations=(calculation,),
        selected_evidence=(evidence,),
        files=files,
    )
    assert OnlyResearchCalculationArtifactManifestV2.from_dict(mutated.to_dict()) == mutated
    assert mutated.artifact_content_fingerprint != manifest.artifact_content_fingerprint
    root = _root(tmp_path, manifest.artifact_content_fingerprint)
    tables = {
        item.relative_path.replace(original.calculation_fingerprint, calculation_id): pq.read_table(
            root / item.relative_path
        )
        for item in manifest.files
    }
    with pytest.raises(ValueError, match="Bar outside requested range"):
        only_verify_calculation_artifact_tables_v2(mutated, tables)
