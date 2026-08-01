import pytest

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.execution import OnlyExecutionCapability, OnlyExecutionOperationKind, only_resolve_execution_capability
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide


@pytest.mark.parametrize(
    ("operation_kind", "account_ledger_parity", "expected"),
    (
        (OnlyExecutionOperationKind.TRADE_FILL, True, OnlyExecutionCapability.DURABLE_TRADE),
        (OnlyExecutionOperationKind.ORDER_TERMINAL, True, OnlyExecutionCapability.DURABLE_TERMINAL),
        (OnlyExecutionOperationKind.TRADE_FILL, False, OnlyExecutionCapability.LEGACY_UNMIGRATED),
        (OnlyExecutionOperationKind.ORDER_TERMINAL, False, OnlyExecutionCapability.LEGACY_UNMIGRATED),
    ),
)
def test_generic_t0_long_close_requires_single_account_ledger_authority(
    operation_kind: OnlyExecutionOperationKind,
    account_ledger_parity: bool,
    expected: OnlyExecutionCapability,
) -> None:
    assert (
        only_resolve_execution_capability(
            operation_kind=operation_kind,
            market_profile_id="GENERIC_T0_CASH",
            account_type=OnlyAccountType.CASH,
            order_type=OnlyOrderType.LIMIT,
            order_side=OnlyOrderSide.SELL,
            offset=OnlyOffset.CLOSE,
            position_side=OnlyPositionSide.LONG,
            position_effect=OnlyPositionEffect.CLOSE,
            position_mode=OnlyPositionMode.NETTING,
            has_margin=False,
            account_ledger_parity=account_ledger_parity,
        )
        is expected
    )
