from dataclasses import replace

from onlyalpha.runtime.recovery.authority_views import OnlyRuntimeBoundaryAuthorityView
from onlyalpha.runtime.recovery.validation import (
    OnlyPostRecoveryCheckStatus,
    OnlyRuntimeBoundaryAuthorityCheck,
    only_default_post_recovery_authority_validator,
)
from tests.runtime.recovery.support.authority_fixture import OnlyPostRecoveryAuthorityFixture


def _status(context, code: str) -> OnlyPostRecoveryCheckStatus:  # type: ignore[no-untyped-def]
    checks = OnlyRuntimeBoundaryAuthorityCheck().evaluate(context)
    return next(item.status for item in checks if item.code == code)


def test_default_authority_fixture_passes_every_default_checker() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create()
    assert only_default_post_recovery_authority_validator().validate(fixture.context()).passed


def test_default_transaction_authority_fixture_passes_every_default_checker() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create(with_transaction=True)
    assert only_default_post_recovery_authority_validator().validate(fixture.context()).passed


def test_runtime_boundary_keeps_inbound_and_event_bus_diagnostics_distinct() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create()
    boundary = fixture.context().runtime_boundary_view
    inbound = replace(boundary, broker_inbound_count=1)
    pending = replace(boundary, event_bus_pending_count=1)
    assert (
        _status(
            fixture.context(runtime_boundary_view=inbound),
            "POST_RECOVERY_SEMANTIC_QUIESCENCE_NOT_PROVEN",
        ).value
        == "FAILED"
    )
    assert (
        _status(fixture.context(runtime_boundary_view=inbound), "POST_RECOVERY_EVENT_BUS_NOT_DRAINED").value == "PASSED"
    )
    assert (
        _status(
            fixture.context(runtime_boundary_view=pending),
            "POST_RECOVERY_SEMANTIC_QUIESCENCE_NOT_PROVEN",
        ).value
        == "PASSED"
    )
    assert (
        _status(fixture.context(runtime_boundary_view=pending), "POST_RECOVERY_EVENT_BUS_NOT_DRAINED").value == "FAILED"
    )


def test_market_data_queue_does_not_invalidate_a_sealed_semantic_boundary() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create()
    boundary: OnlyRuntimeBoundaryAuthorityView = replace(
        fixture.context().runtime_boundary_view, market_data_inbound_count=1
    )
    assert (
        _status(
            fixture.context(runtime_boundary_view=boundary),
            "POST_RECOVERY_SEMANTIC_QUIESCENCE_NOT_PROVEN",
        ).value
        == "PASSED"
    )


def test_driver_frontier_proof_is_required_even_with_empty_physical_queues() -> None:
    fixture = OnlyPostRecoveryAuthorityFixture.create()
    boundary = replace(fixture.context().runtime_boundary_view, driver_frontier_stable=False)
    assert (
        _status(
            fixture.context(runtime_boundary_view=boundary),
            "POST_RECOVERY_SEMANTIC_QUIESCENCE_NOT_PROVEN",
        ).value
        == "FAILED"
    )
