from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual import (
    OnlyFixedLatencyModel,
    OnlyVirtualBrokerConfig,
    OnlyVirtualBrokerGateway,
)
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerFactory
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillPlanStatus
from onlyalpha_plugin_broker_virtual.submission_control import (
    OnlyVirtualSubmissionAction,
    OnlyVirtualSubmissionControl,
    OnlyVirtualSubmissionSimulation,
)

from onlyalpha.broker import (
    OnlyBrokerConnectionState,
    OnlyBrokerGatewayId,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState
from tests.support.virtual_broker import ACCOUNT, CNY, START, bar, order


def _gateway(
    simulation: OnlyVirtualSubmissionSimulation,
    *,
    acceptance_latency_ns: int = 0,
) -> tuple[OnlyBacktestClock, OnlyVirtualBrokerGateway, list[object]]:
    clock = OnlyBacktestClock(START)
    updates: list[object] = []
    gateway = OnlyVirtualBrokerGateway(
        OnlyVirtualBrokerConfig(
            OnlyBrokerGatewayId("submission-control"),
            ACCOUNT,
            CNY,
            OnlyMoney(Decimal("100000.00"), CNY),
            latency_model=OnlyFixedLatencyModel(0, acceptance_latency_ns, 0, 0),
            submission_simulation=simulation,
        ),
        OnlyRuntimeId("submission-control-runtime"),
        clock,
        updates.append,
    )
    gateway.connect()
    gateway.authenticate()
    updates.clear()
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    return clock, gateway, updates


def test_factory_parses_sorted_strong_submission_controls_with_stable_fingerprint() -> None:
    factory = OnlyVirtualBrokerFactory()
    config = factory.parse_config(
        {
            "simulation": {
                "submissions": [
                    {
                        "submission_index": 2,
                        "action": "accept_then_expire",
                        "reason": "EXPIRED_BY_SCENARIO",
                    },
                    {
                        "submission_index": 1,
                        "action": "reject_before_accepted",
                        "reason": "rejected by deterministic scenario",
                        "rejection_code": "SCENARIO_REJECTED",
                    },
                ]
            }
        }
    )
    reversed_config = factory.parse_config(
        {
            "simulation": {
                "submissions": list(
                    reversed(
                        [
                            {
                                "submission_index": 2,
                                "action": "accept_then_expire",
                                "reason": "EXPIRED_BY_SCENARIO",
                            },
                            {
                                "submission_index": 1,
                                "action": "reject_before_accepted",
                                "reason": "rejected by deterministic scenario",
                                "rejection_code": "SCENARIO_REJECTED",
                            },
                        ]
                    )
                )
            }
        }
    )

    assert tuple(item.submission_index for item in config.submission_simulation.submissions) == (1, 2)
    assert config.submission_simulation.fingerprint == reversed_config.submission_simulation.fingerprint
    assert len(config.submission_simulation.fingerprint) == 64


@pytest.mark.parametrize(
    "simulation, code",
    [
        (
            {"submissions": [{"submission_index": 0, "action": "REJECT_BEFORE_ACCEPTED"}]},
            "VIRTUAL_SUBMISSION_INDEX_INVALID",
        ),
        (
            {"submissions": [{"submission_index": 1, "action": "ACCEPT_OR_REJECT_RANDOMLY"}]},
            "VIRTUAL_SUBMISSION_ACTION_INVALID",
        ),
        (
            {
                "submissions": [
                    {"submission_index": 1, "action": "REJECT_BEFORE_ACCEPTED"},
                    {"submission_index": 1, "action": "ACCEPT_THEN_EXPIRE"},
                ]
            },
            "VIRTUAL_SUBMISSION_INDEX_DUPLICATE",
        ),
        (
            {
                "submissions": [
                    {
                        "submission_index": 1,
                        "action": "ACCEPT_THEN_EXPIRE",
                        "rejection_code": "NOT_APPLICABLE",
                    }
                ]
            },
            "VIRTUAL_SUBMISSION_REJECTION_CODE_NOT_APPLICABLE",
        ),
    ],
)
def test_invalid_submission_control_fails_closed(simulation: dict[str, object], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        OnlyVirtualBrokerFactory().parse_config({"simulation": simulation})


def test_reject_before_accepted_publishes_only_normalized_rejection_without_hold_or_plan() -> None:
    simulation = OnlyVirtualSubmissionSimulation(
        (
            OnlyVirtualSubmissionControl(
                1,
                OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED,
                "deterministic rejection",
                "PRODUCT_SCENARIO_REJECTED",
            ),
        )
    )
    _, gateway, updates = _gateway(simulation)

    gateway.submit_order(order(1))
    gateway.run_due()

    rejected = tuple(item for item in updates if isinstance(item, OnlyBrokerOrderRejectedUpdate))
    assert len(rejected) == 1
    assert rejected[0].rejection.code == "PRODUCT_SCENARIO_REJECTED"
    assert rejected[0].rejection.message == "deterministic rejection"
    assert not any(isinstance(item, OnlyBrokerOrderAcceptedUpdate) for item in updates)
    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.REJECTED
    assert gateway.query_open_orders(ACCOUNT) == ()
    assert gateway.fill_plan_store.list() == ()
    assert gateway.query_account(ACCOUNT).order_reserved_cash.amount == Decimal("0.00")


def test_accept_then_expire_orders_normalized_updates_and_releases_remaining_hold() -> None:
    simulation = OnlyVirtualSubmissionSimulation(
        (
            OnlyVirtualSubmissionControl(
                1,
                OnlyVirtualSubmissionAction.ACCEPT_THEN_EXPIRE,
                "PRODUCT_SCENARIO_EXPIRED",
            ),
        )
    )
    _, gateway, updates = _gateway(simulation)

    gateway.submit_order(order(1))
    gateway.run_due()

    lifecycle = tuple(
        item for item in updates if isinstance(item, OnlyBrokerOrderAcceptedUpdate | OnlyBrokerOrderExpiredUpdate)
    )
    assert tuple(type(item) for item in lifecycle) == (
        OnlyBrokerOrderAcceptedUpdate,
        OnlyBrokerOrderExpiredUpdate,
    )
    assert lifecycle[1].source_sequence == lifecycle[0].source_sequence + 1
    assert lifecycle[1].metadata["reason"] == "PRODUCT_SCENARIO_EXPIRED"
    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.EXPIRED
    assert gateway.query_open_orders(ACCOUNT) == ()
    assert gateway.fill_plan_store.list()[0].status is OnlyVirtualFillPlanStatus.EXPIRED
    assert gateway.query_trades(ACCOUNT) == ()
    assert gateway.query_account(ACCOUNT).order_reserved_cash.amount == Decimal("0.00")


def test_checkpoint_v3_restores_frozen_pending_submission_and_rejects_config_drift() -> None:
    reject = OnlyVirtualSubmissionSimulation(
        (
            OnlyVirtualSubmissionControl(
                1,
                OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED,
            ),
        )
    )
    clock, gateway, _ = _gateway(reject, acceptance_latency_ns=60_000_000_000)
    gateway.submit_order(order(1))
    checkpoint = gateway.capture_checkpoint()
    assert isinstance(checkpoint, dict)
    assert checkpoint["schema_version"] == 3
    assert checkpoint["simulation_fingerprint"] == reject.fingerprint

    restored_updates: list[object] = []
    restored = OnlyVirtualBrokerGateway(gateway.config, gateway.runtime_id, clock, restored_updates.append)
    restored.restore_checkpoint(checkpoint)
    clock.advance_to(clock.timestamp_ns() + 61_000_000_000)
    restored.run_due()
    assert len(tuple(item for item in restored_updates if isinstance(item, OnlyBrokerOrderRejectedUpdate))) == 1

    expire = OnlyVirtualSubmissionSimulation(
        (OnlyVirtualSubmissionControl(1, OnlyVirtualSubmissionAction.ACCEPT_THEN_EXPIRE),)
    )
    drifted = OnlyVirtualBrokerGateway(
        OnlyVirtualBrokerConfig(
            gateway.config.gateway_id,
            ACCOUNT,
            CNY,
            gateway.config.initial_cash,
            submission_simulation=expire,
        ),
        gateway.runtime_id,
        clock,
        lambda update: None,
    )
    with pytest.raises(ValueError, match="SIMULATION_FINGERPRINT_CONFLICT"):
        drifted.restore_checkpoint(checkpoint)
    assert drifted.connection_snapshot().state is OnlyBrokerConnectionState.FAILED
    assert drifted.state is OnlyPluginLifecycleState.FAILED


def test_checkpoint_v3_rejects_tampered_frozen_submission_action_and_v2_payload() -> None:
    simulation = OnlyVirtualSubmissionSimulation(
        (OnlyVirtualSubmissionControl(1, OnlyVirtualSubmissionAction.REJECT_BEFORE_ACCEPTED),)
    )
    clock, gateway, _ = _gateway(simulation, acceptance_latency_ns=60_000_000_000)
    gateway.submit_order(order(1))
    checkpoint = gateway.capture_checkpoint()
    assert isinstance(checkpoint, dict)

    tampered = deepcopy(checkpoint)
    scheduler = tampered["scheduler"]
    assert isinstance(scheduler, dict)
    actions = scheduler["actions"]
    assert isinstance(actions, list) and isinstance(actions[0], dict)
    scheduled_payload = actions[0]["payload"]
    assert isinstance(scheduled_payload, dict)
    scheduled_payload["control"] = None
    with pytest.raises(ValueError, match="SCHEDULED_SUBMISSION_CONTROL_CONFLICT"):
        gateway.restore_checkpoint(tampered)

    v2 = deepcopy(checkpoint)
    v2["schema_version"] = 2
    with pytest.raises(ValueError, match="CHECKPOINT_SCHEMA_UNSUPPORTED"):
        gateway.restore_checkpoint(v2)
    assert gateway.state is OnlyPluginLifecycleState.FAILED
