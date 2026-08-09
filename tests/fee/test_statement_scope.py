from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.evidence_scope import (
    OnlyExternalFeeEvidenceScope,
    OnlyExternalFeeEvidenceScopeType,
    OnlyFeeStatementScope,
)


def test_statement_scope_is_typed_half_open_and_illegal_combinations_fail() -> None:
    start = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    end = OnlyTimestamp.from_datetime(datetime(2026, 2, 1, tzinfo=UTC))
    statement = OnlyFeeStatementScope.create(
        broker_id="broker",
        account_id=OnlyAccountId("account"),
        period_start=start,
        period_end=end,
        currency=OnlyCurrency("CNY", 2),
        statement_id="jan",
    )
    scope = OnlyExternalFeeEvidenceScope.statement_period(statement)
    assert scope.statement is statement and start <= start < end
    with pytest.raises(ValueError, match="FEE_EVIDENCE_SCOPE_INVALID"):
        OnlyExternalFeeEvidenceScope(
            OnlyExternalFeeEvidenceScopeType.TRADE, trade_id=OnlyTradeId("t"), statement=statement
        )
    with pytest.raises(ValueError, match="FEE_STATEMENT_SCOPE_INVALID"):
        OnlyFeeStatementScope.create(
            broker_id="broker",
            account_id=OnlyAccountId("account"),
            period_start=end,
            period_end=start,
            currency=OnlyCurrency("CNY", 2),
            statement_id="bad",
        )
