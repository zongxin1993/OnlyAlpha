"""Converters from Runtime-owned durable authority to projection state."""

from onlyalpha.fee.ledger import OnlyFeeApplicationAuthoritySnapshot
from onlyalpha.settlement.models import OnlySettlementInstructionSnapshot
from onlyalpha.transaction.projection import (
    OnlyFeeApplicationState,
    OnlySettlementExecutionState,
    OnlySettlementRecordReplay,
)


def only_fee_application_state(authority: OnlyFeeApplicationAuthoritySnapshot) -> OnlyFeeApplicationState:
    return OnlyFeeApplicationState(
        authority.instruction,
        authority.records,
        authority.instruction.total_charges,
        authority.instruction.total_rebates,
        authority.version,
        authority.record_sequence_head,
    )


def only_settlement_execution_state(authority: OnlySettlementInstructionSnapshot) -> OnlySettlementExecutionState:
    instruction = authority.instruction
    return OnlySettlementExecutionState(
        str(instruction.instruction_id),
        instruction.account_id,
        instruction.instrument_id,
        instruction.order_id,
        str(instruction.trade_id),
        instruction.trade_quantity.value,
        instruction.gross_notional,
        authority.asset_trade_available,
        authority.cash_trade_available,
        authority.cash_withdrawable,
        authority.legal_settled,
        instruction.schedule.asset_trade_available_on,
        instruction.schedule.cash_trade_available_on,
        instruction.schedule.cash_withdrawable_on,
        instruction.schedule.legal_settlement_on,
        authority.version,
        authority.record_sequence_head,
        instruction,
    )


def only_settlement_record_replay(
    authority: OnlySettlementInstructionSnapshot,
) -> tuple[OnlySettlementRecordReplay, ...]:
    del authority
    return ()


__all__ = ["only_fee_application_state", "only_settlement_execution_state", "only_settlement_record_replay"]
