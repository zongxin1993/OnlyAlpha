from copy import copy
from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.risk.enums import OnlyRiskRejectionCode


def _evaluate(harness, request):
    return harness.risk.evaluate_order(
        request,
        harness.risk.make_evaluation_context(
            harness.cluster_id,
            harness.account_id,
            OnlyTimestamp.from_unix_nanos(1),
        ),
    )


def test_mandatory_instrument_exists_and_status_fail_before_order(build_harness, order_request) -> None:
    harness = build_harness()
    missing = replace(
        order_request,
        request_id=OnlyOrderRequestId("missing"),
        instrument_id=OnlyInstrumentId.parse("UNKNOWN.XSHG"),
    )
    decision = _evaluate(harness, missing)
    assert decision.rejection is not None
    assert decision.rejection.code is OnlyRiskRejectionCode.INSTRUMENT_NOT_FOUND


def test_price_and_quantity_increment_are_rejected(build_harness, order_request) -> None:
    harness = build_harness()
    bad_price = replace(
        order_request,
        request_id=OnlyOrderRequestId("bad-price"),
        price=OnlyPrice(Decimal("10.03"), 2),
    )
    assert _evaluate(harness, bad_price).rejection.code is OnlyRiskRejectionCode.INVALID_PRICE_INCREMENT  # type: ignore[union-attr]
    bad_quantity = replace(
        order_request,
        request_id=OnlyOrderRequestId("bad-quantity"),
        quantity=OnlyQuantity(Decimal("150"), 0),
    )
    assert _evaluate(harness, bad_quantity).rejection.code is OnlyRiskRejectionCode.INVALID_QUANTITY_INCREMENT  # type: ignore[union-attr]


def test_unsupported_order_type_is_rejected_by_mandatory_rule(build_harness, order_request) -> None:
    harness = build_harness()
    unsupported = copy(order_request)
    object.__setattr__(unsupported, "order_type", OnlyOrderType.STOP_LIMIT)
    decision = _evaluate(harness, unsupported)
    assert decision.rejection is not None
    assert decision.rejection.code is OnlyRiskRejectionCode.UNSUPPORTED_ORDER_TYPE
