import pytest

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.execution import OnlyExecutionCapability, only_resolve_execution_capability
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.transaction import OnlyRuntimeOperationKind


@pytest.mark.parametrize(
    ("operation_kind", "account_ledger_parity", "expected"),
    (
        (OnlyRuntimeOperationKind.TRADE_FILL, True, OnlyExecutionCapability.DURABLE_TRADE),
        (OnlyRuntimeOperationKind.ORDER_TERMINAL, True, OnlyExecutionCapability.DURABLE_TERMINAL),
        (OnlyRuntimeOperationKind.TRADE_FILL, False, OnlyExecutionCapability.UNSUPPORTED),
        (OnlyRuntimeOperationKind.ORDER_TERMINAL, False, OnlyExecutionCapability.UNSUPPORTED),
    ),
)
def test_generic_t0_long_close_requires_single_account_ledger_authority(
    operation_kind: OnlyRuntimeOperationKind,
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
