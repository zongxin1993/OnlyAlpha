from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderRequestId, OnlySymbol, OnlyVenueId
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.risk.enums import OnlyOrderRiskChange
from onlyalpha.risk.service import OnlyRiskService


def _request(side: OnlyOrderSide, offset: OnlyOffset) -> OnlyOrderRequest:
    return OnlyOrderRequest(
        OnlyOrderRequestId(f"{side.value}-{offset.value}"),
        OnlyInstrumentId(OnlySymbol("TEST"), OnlyVenueId("XSHG")),
        side,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("1"), 0),
        offset=offset,
        price=OnlyPrice(Decimal("10.00"), 2),
    )


def test_risk_authority_classifies_cash_long_and_futures_short_close_as_reducing() -> None:
    service = object.__new__(OnlyRiskService)
    assert (
        service.classify_order_change(_request(OnlyOrderSide.SELL, OnlyOffset.CLOSE), None)
        is OnlyOrderRiskChange.RISK_REDUCING
    )
    assert (
        service.classify_order_change(_request(OnlyOrderSide.BUY, OnlyOffset.CLOSE), None)
        is OnlyOrderRiskChange.RISK_REDUCING
    )
    assert (
        service.classify_order_change(_request(OnlyOrderSide.BUY, OnlyOffset.OPEN), None)
        is OnlyOrderRiskChange.RISK_INCREASING
    )


def test_blocked_gate_fails_closed_for_unknown_and_neutral() -> None:
    from tests.fee.test_fee_reconciliation_transaction import _decision
    from tests.fee.test_reconciliation_blockers import _gate_after

    evidence, decision = _decision("5.23")
    from dataclasses import replace

    from onlyalpha.fee.reconciliation import OnlyFeeReconciliationStatus

    state = _gate_after(replace(decision, status=OnlyFeeReconciliationStatus.TRADING_BLOCKED, adjustments=()), evidence)
    gate = OnlyFeeReconciliationRiskGate()
    gate.restore(state)
    with pytest.raises(ValueError, match="CLASSIFICATION_UNKNOWN"):
        gate.require_order_allowed(evidence.account_id, OnlyOrderRiskChange.UNKNOWN)
    with pytest.raises(ValueError, match="TRADING_BLOCKED"):
        gate.require_order_allowed(evidence.account_id, OnlyOrderRiskChange.RISK_NEUTRAL)
    gate.require_order_allowed(evidence.account_id, OnlyOrderRiskChange.RISK_REDUCING)
