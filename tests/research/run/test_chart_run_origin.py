from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.application.chart_calculation_run_admission import only_chart_calculation_queued_run
from onlyalpha.persistence.postgres.research_run_store import _COLUMNS, OnlyPostgresResearchRunStore
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError
from tests.application.test_chart_calculation_admission import NOW
from tests.application.test_chart_calculation_compilation import compilation
from tests.support.chart_calculation_compilation import prepared_input


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("origin_kind", "GENERAL"),
        ("specification_schema_version", 2),
        ("calculation_execution_evidence_fingerprints", None),
        ("authoring_provenance", {}),
        ("failure_detail", "hidden discarded field"),
        ("failure_code", "HIDDEN"),
        ("admission_resolution_fingerprint", "f" * 64),
    ],
)
def test_chart_row_requires_exact_columns_and_admission_relation(tmp_path: Path, field: str, value: object) -> None:
    frozen = compilation(prepared_input(tmp_path))
    run = only_chart_calculation_queued_run(frozen, queued_at=NOW)
    row = dict(zip(_COLUMNS, OnlyPostgresResearchRunStore._values(run), strict=True))
    assert OnlyPostgresResearchRunStore._decode(row) == run
    row[field] = value
    if field == "admission_resolution_fingerprint":
        # Row shape alone cannot prove compilation ownership; the owning composite verifier must.
        from onlyalpha.application.chart_calculation_run_admission import only_verify_chart_calculation_run

        with pytest.raises(ValueError, match="CHART_RUN_ADMISSION_RELATION_CORRUPT"):
            only_verify_chart_calculation_run(OnlyPostgresResearchRunStore._decode(row), frozen)
    else:
        with pytest.raises(OnlyResearchRunIntegrityError):
            OnlyPostgresResearchRunStore._decode(row)
