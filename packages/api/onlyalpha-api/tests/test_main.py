from __future__ import annotations

import onlyalpha_api.main as server
import pytest

from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus


def test_servers_require_explicit_roots() -> None:
    with pytest.raises(SystemExit) as full:
        server.main([])
    assert full.value.code == 2


@pytest.mark.parametrize(
    ("evidence", "error"),
    (
        (OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ()), None),
        (
            OnlyResearchReadiness(OnlyResearchReadinessStatus.NOT_READY, (), "SCHEMA_INCOMPATIBLE"),
            "SCHEMA_INCOMPATIBLE",
        ),
    ),
)
def test_product_verification_retains_exact_ready_or_failure_evidence(
    evidence: OnlyResearchReadiness,
    error: str | None,
) -> None:
    class Probe:
        def inspect(self) -> OnlyResearchReadiness:
            return evidence

    verification = server._ResearchProductVerification(Probe())  # type: ignore[arg-type]
    if error is None:
        verification.verify()
    else:
        with pytest.raises(RuntimeError, match=error):
            verification.verify()
    assert verification.evidence is evidence
