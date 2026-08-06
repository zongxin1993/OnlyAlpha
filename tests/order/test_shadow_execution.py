from unittest.mock import Mock

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.execution.models import OnlyExecutionSubmissionOutcome
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.service import OnlyOrderService
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskReservationState
from onlyalpha.runtime.streaming.execution import (
    OnlyExecutionSubmissionCapability,
    OnlyShadowExecutionService,
)
from tests.order.fee_contract import only_test_zero_fee_contract


def test_shadow_submit_is_suppressed_without_external_identity() -> None:
    service = OnlyShadowExecutionService()
    order = Mock()

    result = service.submit_order(order)

    assert OnlyExecutionSubmissionCapability.SHADOW.value == "SHADOW"
    assert result.outcome is OnlyExecutionSubmissionOutcome.SUPPRESSED
    assert not result.received
    assert service.submissions == (order,)


def test_shadow_suppression_fails_order_and_releases_every_reservation(
    order_manager,
    order_request,
    risk_service,
) -> None:
    position_reservations = Mock()
    cash_reservations = Mock()
    margin_reservations = Mock()
    service = OnlyOrderService(
        order_manager,
        OnlyShadowExecutionService(),
        OnlyInMemoryOrderEventPublisher(),
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        position_reservations,
        cash_reservations,
        margin_reservations,
        only_test_zero_fee_contract,
    )

    result = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))

    assert result.snapshot is not None
    assert result.snapshot.status is OnlyOrderStatus.FAILED
    assert result.snapshot.venue_order_id is None
    reservation = risk_service.reservations.get_for_order(result.order_id)
    assert reservation is not None
    assert reservation.state is OnlyRiskReservationState.RELEASED
    assert reservation.release_reason is OnlyRiskReleaseReason.EXECUTION_SUPPRESSED
    position_reservations.reserve.assert_called_once()
    position_reservations.release.assert_called_once_with(
        result.order_id,
        OnlyTimestamp.from_unix_nanos(1),
        broker_confirmed=True,
    )
    cash_reservations.reserve.assert_called_once()
    cash_reservations.release.assert_called_once_with(result.order_id, OnlyTimestamp.from_unix_nanos(1))
    margin_reservations.reserve.assert_called_once()
    margin_reservations.release.assert_called_once_with(result.order_id, OnlyTimestamp.from_unix_nanos(1))
