from dataclasses import replace

from onlyalpha.broker import OnlyBrokerGatewayId
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.execution import (
    ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION,
    OnlyExecutionFillIdentity,
    OnlyExecutionFillIdentityKind,
    only_execution_fill_identity,
)
from tests.execution.factories.trade_planning_factory import only_test_generic_t0_trade_planning_context


def test_fill_identity_priority_scope_and_stability() -> None:
    update = only_test_generic_t0_trade_planning_context().update
    venue = OnlyExecutionFillIdentity.from_update(update)
    assert venue.canonical_kind is OnlyExecutionFillIdentityKind.VENUE_TRADE_ID
    assert only_execution_fill_identity(venue) == only_execution_fill_identity(venue)
    external = replace(venue, venue_trade_id=None)
    assert external.canonical_kind is OnlyExecutionFillIdentityKind.EXTERNAL_EVENT_ID
    trade = replace(external, external_event_id=None)
    assert trade.canonical_kind is OnlyExecutionFillIdentityKind.TRADE_ID
    baseline = only_execution_fill_identity(venue)
    assert (
        len(
            {
                baseline,
                only_execution_fill_identity(replace(venue, runtime_id=OnlyRuntimeId("other"))),
                only_execution_fill_identity(replace(venue, gateway_id=OnlyBrokerGatewayId("other"))),
                only_execution_fill_identity(replace(venue, account_id=OnlyAccountId("other"))),
                only_execution_fill_identity(replace(venue, order_id=type(venue.order_id)("other"))),
            }
        )
        == 5
    )
    assert ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION == 1
