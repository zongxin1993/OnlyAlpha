"""Exact schema/domain dispatch for coexisting Statistics result families."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ..errors import OnlyResearchStatisticsResultStoreError
from ..result import OnlyResearchStatisticsResult
from .family import OnlyResearchStatisticsFamily, only_research_statistics_family
from .result import OnlyResearchSummaryStatisticsResult


class _LegacyReader(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class _SummaryReader(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchSummaryStatisticsResult: ...


class OnlyResearchStatisticsResultReader:
    def __init__(self, root: Path, legacy_reader: _LegacyReader, summary_reader: _SummaryReader) -> None:
        self._root = root
        self._legacy_reader = legacy_reader
        self._summary_reader = summary_reader

    def load_verified(
        self, statistics_fingerprint: str
    ) -> OnlyResearchStatisticsResult | OnlyResearchSummaryStatisticsResult:
        if not _valid_sha(statistics_fingerprint):
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_NOT_FOUND", "invalid fingerprint")
        target = self._root / "sha256" / statistics_fingerprint[:2] / statistics_fingerprint
        if not target.is_dir():
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_NOT_FOUND", statistics_fingerprint)
        try:
            payload = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Statistics manifest must be an object")
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_CORRUPT", str(exc)) from exc
        try:
            family = only_research_statistics_family(payload)
        except ValueError as exc:
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_SCHEMA_UNSUPPORTED", str(exc)) from exc
        if family is OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1:
            return self._legacy_reader.load_verified(statistics_fingerprint)
        return self._summary_reader.load_verified(statistics_fingerprint)


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = ["OnlyResearchStatisticsResultReader"]
