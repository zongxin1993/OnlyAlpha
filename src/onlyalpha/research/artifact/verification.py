"""Small pure verification helpers shared by Research Artifact profiles."""

from onlyalpha.research.evaluation.result import OnlyResearchStatisticRow
from onlyalpha.research.evaluation.result_identity import (
    only_research_statistics_result_content_fingerprint,
    only_research_statistics_result_fingerprint,
)

from .model import OnlyResearchArtifactStatisticsEntry, OnlyResearchArtifactStatisticsRow


def verify_statistics_groups(
    statistics_results: tuple[object, ...], rows: tuple[OnlyResearchArtifactStatisticsRow, ...]
) -> None:
    if any(not isinstance(item, OnlyResearchArtifactStatisticsEntry) for item in statistics_results):
        raise ValueError("Research Artifact Statistics catalog is invalid")
    entries = tuple(item for item in statistics_results if isinstance(item, OnlyResearchArtifactStatisticsEntry))
    catalog_identities = {item.statistics_fingerprint for item in entries}
    if {row.statistics_fingerprint for row in rows} - catalog_identities:
        raise ValueError("Research Artifact contains rows outside its catalog")
    for entry in entries:
        group = tuple(row for row in rows if row.statistics_fingerprint == entry.statistics_fingerprint)
        if len(group) != entry.row_count:
            raise ValueError("Research Artifact Statistics group row count mismatch")
        semantic_rows = tuple(
            OnlyResearchStatisticRow(
                row.ts_event_ns, row.statistic_value, row.sample_count, row.status
            ).semantic_payload()
            for row in group
        )
        content = only_research_statistics_result_content_fingerprint(semantic_rows)
        if content != entry.result_content_fingerprint:
            raise ValueError("Research Artifact Statistics content identity mismatch")
        result = only_research_statistics_result_fingerprint(entry.statistics_fingerprint, content)
        if result != entry.statistics_result_fingerprint:
            raise ValueError("Research Artifact Statistics Result identity mismatch")


__all__ = ["verify_statistics_groups"]
