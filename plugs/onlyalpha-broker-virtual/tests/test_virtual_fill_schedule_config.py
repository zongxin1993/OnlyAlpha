from decimal import Decimal

import pytest
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerFactory
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillScheduleMode,
)


def test_default_and_legacy_maximum_normalize_to_one_policy() -> None:
    factory = OnlyVirtualBrokerFactory()
    whole = factory.parse_config({"matching": {"type": "NEXT_BAR"}})
    maximum = factory.parse_config({"maximum_fill_quantity": "300"})
    assert whole.fill_schedule_mode is None and whole.maximum_fill_quantity is None
    assert maximum.fill_schedule_mode is None and maximum.maximum_fill_quantity == Decimal("300")


def test_explicit_quantity_and_ratio_schedules_parse_strictly() -> None:
    factory = OnlyVirtualBrokerFactory()
    quantity = factory.parse_config(
        {
            "matching": {
                "partial_fill": {
                    "mode": "SCHEDULE",
                    "dispatch_mode": "ONE_PER_BAR",
                    "steps": [
                        {"bar_offset": 1, "quantity": "300"},
                        {"bar_offset": 2, "quantity": "700"},
                    ],
                }
            }
        }
    )
    ratio = factory.parse_config(
        {
            "matching": {
                "partial_fill": {
                    "mode": "SCHEDULE",
                    "dispatch_mode": "ALL_DUE",
                    "steps": [
                        {"bar_offset": 1, "ratio": "0.3"},
                        {"bar_offset": 1, "ratio": "0.7"},
                    ],
                }
            }
        }
    )
    assert quantity.fill_schedule_mode is OnlyVirtualFillScheduleMode.SCHEDULE
    assert quantity.fill_dispatch_mode is OnlyVirtualFillDispatchMode.ONE_PER_BAR
    assert ratio.fill_dispatch_mode is OnlyVirtualFillDispatchMode.ALL_DUE


@pytest.mark.parametrize(
    "extensions, code",
    [
        (
            {
                "maximum_fill_quantity": "300",
                "matching": {
                    "partial_fill": {
                        "mode": "SCHEDULE",
                        "steps": [{"bar_offset": 1, "quantity": "1000"}],
                    }
                },
            },
            "VIRTUAL_FILL_POLICY_CONFLICT",
        ),
        (
            {"matching": {"partial_fill": {"mode": "SCHEDULE", "steps": []}}},
            "VIRTUAL_FILL_SCHEDULE_EMPTY",
        ),
        (
            {
                "matching": {
                    "partial_fill": {
                        "mode": "SCHEDULE",
                        "steps": [{"bar_offset": 0, "ratio": "1"}],
                    }
                }
            },
            "VIRTUAL_FILL_STEP_BAR_OFFSET_INVALID",
        ),
        (
            {
                "matching": {
                    "partial_fill": {
                        "mode": "SCHEDULE",
                        "steps": [{"bar_offset": 1, "quantity": "1", "ratio": "1"}],
                    }
                }
            },
            "VIRTUAL_FILL_STEP_VALUE_INVALID",
        ),
    ],
)
def test_invalid_fill_configuration_fails_closed(extensions: dict[str, object], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        OnlyVirtualBrokerFactory().parse_config(extensions)


def test_unknown_partial_fill_and_step_fields_are_rejected() -> None:
    factory = OnlyVirtualBrokerFactory()
    with pytest.raises(ValueError, match="unknown Virtual Broker partial_fill field"):
        factory.parse_config({"matching": {"partial_fill": {"mode": "WHOLE", "mystery": 1}}})
    with pytest.raises(ValueError, match="unknown Virtual Broker partial_fill step field"):
        factory.parse_config(
            {
                "matching": {
                    "partial_fill": {
                        "mode": "SCHEDULE",
                        "steps": [{"bar_offset": 1, "ratio": "1", "mystery": 1}],
                    }
                }
            }
        )
