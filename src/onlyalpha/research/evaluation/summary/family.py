"""Known Statistics family/schema discriminants."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from .identity import RESEARCH_SUMMARY_STATISTICS_DOMAIN, RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION


class OnlyResearchStatisticsFamily(StrEnum):
    FEATURE_TARGET_CORRELATION_SERIES_V1 = "FEATURE_TARGET_CORRELATION_SERIES_V1"
    SUMMARY_STATISTICS_V1 = "SUMMARY_STATISTICS_V1"


def only_research_statistics_family(manifest: Mapping[str, object]) -> OnlyResearchStatisticsFamily:
    domain = manifest.get("domain")
    version = manifest.get("schema_version")
    if domain is None and version == 1:
        return OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
    if domain == RESEARCH_SUMMARY_STATISTICS_DOMAIN and version == RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION:
        return OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1
    raise ValueError(f"unsupported Statistics schema/domain: {domain!r}/{version!r}")


__all__ = ["OnlyResearchStatisticsFamily", "only_research_statistics_family"]
