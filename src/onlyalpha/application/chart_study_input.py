"""Opaque disposable handoff issued only after the owning authorized history read."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from onlyalpha.application.source_read_access import OnlySourceReadPermission, OnlySourceReadSession
from onlyalpha.canonical import only_canonical_fingerprint

if TYPE_CHECKING:
    from onlyalpha.application.market_data_product import OnlyMarketDataBarWindowProjectionV1

_ISSUANCE = object()


@dataclass(frozen=True, slots=True, init=False)
class OnlyChartStudyClosedHistoryInput:
    """Not constructible from a DTO, uploaded array, closed flag or copied hash."""

    _window: OnlyMarketDataBarWindowProjectionV1 = field(repr=False)
    _session: OnlySourceReadSession = field(repr=False)
    _issuance: object = field(repr=False)
    _fingerprint: str

    def require_window(self) -> OnlyMarketDataBarWindowProjectionV1:
        if getattr(self, "_issuance", None) is not _ISSUANCE:
            raise ValueError("CHART_STUDY_INPUT_UNAVAILABLE")
        window = self._window
        if only_canonical_fingerprint(window) != self._fingerprint:
            raise ValueError("CHART_STUDY_INPUT_UNAVAILABLE")
        self._session.require_selection(window.source_selection, OnlySourceReadPermission.CLOSED_HISTORY)
        return window


def _only_issue_chart_study_closed_history_input(
    window: OnlyMarketDataBarWindowProjectionV1, session: OnlySourceReadSession
) -> OnlyChartStudyClosedHistoryInput:
    """Private owning-read issuance. The sole production caller is the verified range reader."""
    session.require_selection(window.source_selection, OnlySourceReadPermission.CLOSED_HISTORY)
    if (
        not window.closed_only
        or window.anchor_kind != "BEFORE_TIME"
        or window.requested_before_ns != window.resolved_end_ns
        or not window.coverage.complete
        or window.coverage.issues
        or window.coverage.gaps
        or not window.revision_evidence
        or window.history_projection_fingerprint is None
        or not 1 <= len(window.bars) <= 2000
        or len(window.bars) != window.requested_bar_count
        or any(not bar.closed for bar in window.bars)
        or any(left.bar_end_ns >= right.bar_end_ns for left, right in zip(window.bars, window.bars[1:], strict=False))
        or window.bars[0].bar_start_ns != window.resolved_start_ns
        or window.bars[-1].bar_end_ns != window.resolved_end_ns
    ):
        raise ValueError("CHART_STUDY_INPUT_UNAVAILABLE")
    result = object.__new__(OnlyChartStudyClosedHistoryInput)
    object.__setattr__(result, "_window", window)
    object.__setattr__(result, "_session", session)
    object.__setattr__(result, "_issuance", _ISSUANCE)
    object.__setattr__(result, "_fingerprint", only_canonical_fingerprint(window))
    return result
