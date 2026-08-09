from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence, OnlyExternalFeeEvidenceMode
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope, OnlyFeeStatementScope
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger, OnlyFeeApplicationRecord
from onlyalpha.fee.models import (
    OnlyFeeAuthority,
    OnlyFeeCalculationScope,
    OnlyFeeComponentIdentity,
    OnlyFeeEconomicDirection,
    OnlyFeeResolutionPolicy,
    OnlyFeeType,
    OnlyLocalFeeFinality,
)
from onlyalpha.fee.reconciliation_query import OnlyFeeApplicationLocalFactQuery

_CURRENCY = OnlyCurrency("CNY", 2)
_ACCOUNT = OnlyAccountId("account")


def _ts(day: int) -> OnlyTimestamp:
    return OnlyTimestamp.from_datetime(datetime(2026, 1, day, tzinfo=UTC))


def _record(sequence: int, account: OnlyAccountId, effective_at: OnlyTimestamp) -> OnlyFeeApplicationRecord:
    money = OnlyMoney(Decimal("1.00"), _CURRENCY)
    identity = OnlyFeeComponentIdentity(
        OnlyFeeType.BROKER_COMMISSION,
        OnlyFeeAuthority.BROKER,
        "commission",
        "schedule",
        "1",
        "0" * 64,
        "rule",
        "1" * 64,
        OnlyFeeCalculationScope.FILL,
        OnlyFeeResolutionPolicy.ORDER_FIXED,
        OnlyFeeEconomicDirection.CHARGE,
    )
    return OnlyFeeApplicationRecord(
        f"record-{sequence}",
        f"application-{sequence}",
        OnlyRuntimeId("runtime"),
        account,
        OnlyClusterId("cluster"),
        OnlyInstrumentId(OnlySymbol("TEST"), OnlyVenueId("XSHG")),
        OnlyOrderId(f"order-{sequence}"),
        OnlyTradeId(f"trade-{sequence}"),
        identity,
        money,
        money,
        money,
        OnlyMoney(Decimal("0.00"), _CURRENCY),
        money,
        money,
        OnlyLocalFeeFinality.MODEL_CONFIRMED,
        effective_at,
        sequence,
    )


def test_statement_query_uses_broker_account_currency_and_half_open_period() -> None:
    ledger = OnlyFeeApplicationLedger()
    ledger._records = [
        _record(1, _ACCOUNT, _ts(1)),
        _record(2, _ACCOUNT, _ts(15)),
        _record(3, _ACCOUNT, _ts(20)),
        _record(4, OnlyAccountId("other"), _ts(15)),
    ]
    ledger._rebuild_indexes()
    statement = OnlyFeeStatementScope.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        period_start=_ts(1),
        period_end=_ts(20),
        currency=_CURRENCY,
        statement_id="jan-part",
    )
    evidence = OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=OnlyExternalFeeEvidenceScope.statement_period(statement),
        mode=OnlyExternalFeeEvidenceMode.ALL_IN,
        external_reference="jan-part",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=OnlyMoney(Decimal("2.00"), _CURRENCY),
        reported_components=(),
        effective_at=_ts(20),
        received_at=_ts(20),
    )
    selected = OnlyFeeApplicationLocalFactQuery(ledger, broker_id="broker", account_id=_ACCOUNT).query(evidence)
    assert tuple(item.sequence for item in selected) == (1, 2)
