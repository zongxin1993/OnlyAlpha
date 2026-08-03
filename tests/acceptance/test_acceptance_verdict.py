from datetime import UTC, datetime

import pytest

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.operations.acceptance import (
    OnlyAcceptanceEvidence,
    OnlyAcceptanceVerdict,
    OnlyAcceptanceVerdictReducer,
)

pytestmark = pytest.mark.contract


def _evidence(verdict: OnlyAcceptanceVerdict, *, required: bool = True) -> OnlyAcceptanceEvidence:
    stamp = OnlyTimestamp.from_datetime(datetime(2026, 8, 3, tzinfo=UTC))
    return OnlyAcceptanceEvidence(
        f"evidence-{verdict.value}-{required}",
        "CASE",
        "CATEGORY",
        verdict,
        "REASON",
        stamp,
        stamp,
        required=required,
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    (
        ((OnlyAcceptanceVerdict.PASS,), OnlyAcceptanceVerdict.PASS),
        ((OnlyAcceptanceVerdict.PASS, OnlyAcceptanceVerdict.FAIL), OnlyAcceptanceVerdict.FAIL),
        ((OnlyAcceptanceVerdict.PASS, OnlyAcceptanceVerdict.BLOCKED), OnlyAcceptanceVerdict.BLOCKED),
        ((OnlyAcceptanceVerdict.PASS, OnlyAcceptanceVerdict.NOT_EXECUTED), OnlyAcceptanceVerdict.NOT_EXECUTED),
    ),
)
def test_required_evidence_reduces_by_strict_precedence(
    values: tuple[OnlyAcceptanceVerdict, ...], expected: OnlyAcceptanceVerdict
) -> None:
    assert OnlyAcceptanceVerdictReducer().reduce(tuple(_evidence(item) for item in values)) is expected


def test_optional_failure_does_not_change_required_pass() -> None:
    evidences = (_evidence(OnlyAcceptanceVerdict.PASS), _evidence(OnlyAcceptanceVerdict.FAIL, required=False))
    assert OnlyAcceptanceVerdictReducer().reduce(evidences) is OnlyAcceptanceVerdict.PASS
