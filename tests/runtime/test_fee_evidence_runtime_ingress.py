from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence, OnlyExternalFeeEvidenceMode
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime

pytestmark = pytest.mark.integration


def _evidence(
    runtime: OnlyBacktestRuntime,
    *,
    broker: str = "virtual",
    account: OnlyAccountId | None = None,
    currency: OnlyCurrency | None = None,
) -> OnlyExternalFeeEvidence:
    at = OnlyTimestamp.from_datetime(datetime(2026, 1, 5, 1, 30, tzinfo=UTC))
    actual_currency = currency or OnlyCurrency("CNY", 2)
    account_id = account or OnlyAccountId(str(runtime.config.default_account_id))
    return OnlyExternalFeeEvidence.create(
        broker_id=broker,
        account_id=account_id,
        scope=OnlyExternalFeeEvidenceScope.trade(OnlyTradeId("external-trade")),
        mode=OnlyExternalFeeEvidenceMode.COMMISSION_ONLY,
        external_reference="external-trade-fee",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=OnlyMoney(Decimal("1.00"), actual_currency),
        reported_components=(),
        effective_at=at,
        received_at=at,
    )


def test_runtime_ingress_validates_authority_and_commits_blocker(
    make_runtime: Callable[[str], OnlyBacktestRuntime],
) -> None:
    runtime = make_runtime("fee-ingress")
    runtime.add_cluster("engine", OnlyDemoCluster(OnlyClusterConfig("demo")))
    runtime.initialize()
    evidence = _evidence(runtime)
    result = runtime.submit_fee_evidence(evidence)
    assert result.transaction is not None and result.transaction.projection_ready
    state = runtime.fee_reconciliation_risk_gate.get(evidence.account_id)
    assert state is not None and state.blocked and state.active_blockers[0].evidence_id == evidence.evidence_id

    with pytest.raises(ValueError, match="BROKER_AUTHORITY_CONFLICT"):
        runtime.submit_fee_evidence(_evidence(runtime, broker="wrong"))
    with pytest.raises(ValueError, match="ACCOUNT_AUTHORITY_CONFLICT"):
        runtime.submit_fee_evidence(_evidence(runtime, account=OnlyAccountId("wrong")))
    with pytest.raises(ValueError, match="CURRENCY_MISMATCH"):
        runtime.submit_fee_evidence(_evidence(runtime, currency=OnlyCurrency("USD", 2)))
