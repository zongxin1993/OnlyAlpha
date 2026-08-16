from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.research.query.support import query_case


def test_same_artifact_query_is_deterministic_across_fresh_process_and_hash_seed(tmp_path) -> None:
    *_, candidate, _, _ = query_case(tmp_path)
    artifact_root = tmp_path / "research-artifacts"
    script = """
import json, sys
from onlyalpha.research import OnlyParquetResearchArtifactStore, OnlyResearchQueryService, OnlyResearchStatisticSeriesQuery
root, result = sys.argv[1:]
service = OnlyResearchQueryService(OnlyParquetResearchArtifactStore(__import__('pathlib').Path(root)))
catalog = service.list_statistics(result)
page = service.get_statistic_series(OnlyResearchStatisticSeriesQuery(result, catalog.statistics[0].statistics_fingerprint, limit=2))
print(json.dumps({'catalog': [item.statistics_fingerprint for item in catalog.statistics], 'points': [(item.ts_event_ns, None if item.statistic_value is None else format(item.statistic_value, 'f'), item.sample_count, item.status) for item in page.points], 'has_more': page.has_more, 'cursor': page.next_after_ts_event_ns}, sort_keys=True, separators=(',', ':')))
"""
    outputs = []
    for seed in ("1", "997"):
        working = tmp_path / f"process-{seed}"
        working.mkdir()
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        completed = subprocess.run(
            [sys.executable, "-c", script, str(artifact_root), candidate.research_result_fingerprint],
            cwd=working,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(completed.stdout))
    assert outputs[0] == outputs[1]
