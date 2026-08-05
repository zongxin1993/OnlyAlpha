"""Converters from Manager-owned replay authority to execution projection state."""

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.manager import OnlyFeeExecutionAuthoritySnapshot
from onlyalpha.settlement.models import OnlySettlementInstructionSnapshot
from onlyalpha.transaction.projection import (
    OnlyFeeExecutionState,
    OnlyFeeInstructionReplay,
    OnlyFeeRecordReplay,
    OnlySettlementExecutionState,
    OnlySettlementRecordReplay,
)


def only_fee_execution_state(authority: OnlyFeeExecutionAuthoritySnapshot) -> OnlyFeeExecutionState:
    instruction = authority.instruction
    replay = OnlyFeeInstructionReplay(
        instruction.instruction_id,
        instruction.runtime_id,
        instruction.cluster_id,
        instruction.account_id,
        instruction.order_id,
        instruction.trade_id,
        instruction.calculation_source,
        instruction.idempotency_key,
        OnlyTimestamp.from_datetime(instruction.created_at),
    )
    records = tuple(
        OnlyFeeRecordReplay(
            item.fee_record_id,
            item.instruction_id,
            item.account_id,
            item.order_id,
            item.trade_id,
            OnlyMoney(item.charged, OnlyCurrency(item.currency, instruction.fee_breakdown.total.currency.precision)),
            item.fee_type,
        )
        for item in authority.records
    )
    return OnlyFeeExecutionState(
        replay,
        records,
        instruction.fee_breakdown.total,
        instruction.fee_breakdown,
        authority.version,
        authority.record_sequence_head,
    )


def only_settlement_execution_state(
    authority: OnlySettlementInstructionSnapshot,
) -> OnlySettlementExecutionState:
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


__all__ = ["only_fee_execution_state", "only_settlement_execution_state", "only_settlement_record_replay"]
