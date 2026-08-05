from dataclasses import replace

from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyOrderRequestId
from onlyalpha.domain.time import OnlyTimestamp
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
