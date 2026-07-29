from dataclasses import replace

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.runtime.recovery.validation import (
    OnlyPostRecoveryCheckStatus,
    OnlyPostRecoveryValidationCheck,
    OnlyPostRecoveryValidationReport,
)


def _check(code: str, scope: str, status: OnlyPostRecoveryCheckStatus) -> OnlyPostRecoveryValidationCheck:
    return OnlyPostRecoveryValidationCheck(code, status, scope, "expected", "actual", "detail")


def test_report_canonicalizes_checks_and_has_stable_fingerprint() -> None:
    first = _check("B", "two", OnlyPostRecoveryCheckStatus.NOT_APPLICABLE)
    second = _check("A", "one", OnlyPostRecoveryCheckStatus.PASSED)
    report = OnlyPostRecoveryValidationReport(OnlyRuntimeId("runtime"), (first, second))
    reordered = OnlyPostRecoveryValidationReport(OnlyRuntimeId("runtime"), (second, first))
    assert report.checks == (second, first)
    assert report.authority_fingerprint == reordered.authority_fingerprint
    assert report.passed
    assert len(report.authority_fingerprint) == 64


def test_report_rejects_duplicate_identity_and_declared_wrong_fingerprint() -> None:
    check = _check("A", "one", OnlyPostRecoveryCheckStatus.PASSED)
    with pytest.raises(ValueError, match="duplicate"):
        OnlyPostRecoveryValidationReport(OnlyRuntimeId("runtime"), (check, check))
    with pytest.raises(ValueError, match="fingerprint"):
        OnlyPostRecoveryValidationReport(OnlyRuntimeId("runtime"), (check,), "0" * 64)


def test_failed_check_fails_report_but_not_applicable_does_not() -> None:
    applicable = OnlyPostRecoveryValidationReport(
        OnlyRuntimeId("runtime"),
        (_check("A", "one", OnlyPostRecoveryCheckStatus.NOT_APPLICABLE),),
    )
    failed = replace(
        applicable,
        checks=(_check("A", "one", OnlyPostRecoveryCheckStatus.FAILED),),
        authority_fingerprint="",
    )
    assert applicable.passed
    assert not failed.passed


@pytest.mark.parametrize("code,scope", (("", "scope"), ("code", ""), (" ", "scope")))
def test_check_requires_stable_nonempty_identity(code: str, scope: str) -> None:
    with pytest.raises(ValueError, match="required"):
        _check(code, scope, OnlyPostRecoveryCheckStatus.PASSED)
