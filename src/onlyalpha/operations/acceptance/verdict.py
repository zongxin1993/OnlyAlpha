"""Deterministic acceptance verdict reduction."""

from collections.abc import Sequence

from .models import OnlyAcceptanceEvidence, OnlyAcceptanceVerdict


class OnlyAcceptanceVerdictReducer:
    def reduce(self, evidences: Sequence[OnlyAcceptanceEvidence]) -> OnlyAcceptanceVerdict:
        required = tuple(item for item in evidences if item.required)
        if not required:
            return OnlyAcceptanceVerdict.NOT_EXECUTED
        for verdict in (
            OnlyAcceptanceVerdict.FAIL,
            OnlyAcceptanceVerdict.BLOCKED,
            OnlyAcceptanceVerdict.NOT_EXECUTED,
        ):
            if any(item.verdict is verdict for item in required):
                return verdict
        return OnlyAcceptanceVerdict.PASS
