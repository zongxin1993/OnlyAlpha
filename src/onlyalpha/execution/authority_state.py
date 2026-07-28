"""Converters from Manager-owned replay authority to execution projection state."""

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.manager import OnlyFeeExecutionAuthoritySnapshot
from onlyalpha.settlement.manager import OnlySettlementExecutionAuthoritySnapshot

from .projection import (
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
    authority: OnlySettlementExecutionAuthoritySnapshot,
) -> OnlySettlementExecutionState:
    currency = authority.cash_currency
    if currency is None:
        raise ValueError("Settlement execution authority does not contain cash currency")
    instruction = authority.instruction
    return OnlySettlementExecutionState(
        instruction.instruction_id,
        OnlyAccountId(instruction.account_id),
        OnlyInstrumentId.parse(instruction.instrument_id),
        OnlyOrderId(instruction.source_order_id),
        instruction.source_trade_id,
        instruction.asset_quantity,
        OnlyMoney(instruction.cash_amount, currency),
        authority.asset_released,
        authority.trade_cash_released,
        authority.withdrawable_cash_released,
        authority.legal_settled,
        instruction.asset_available_on,
        instruction.cash_trade_available_on,
        instruction.cash_withdrawable_on,
        instruction.legal_settlement_on,
        authority.version,
        authority.record_sequence_head,
    )


def only_settlement_record_replay(
    authority: OnlySettlementExecutionAuthoritySnapshot,
) -> tuple[OnlySettlementRecordReplay, ...]:
    currency = authority.cash_currency
    if currency is None:
        raise ValueError("Settlement execution authority does not contain cash currency")
    return tuple(
        OnlySettlementRecordReplay(
            item.instruction_id,
            OnlyAccountId(item.account_id),
            OnlyInstrumentId.parse(item.instrument_id),
            OnlyOrderId(item.source_order_id),
            item.source_trade_id,
            item.processed_on,
            item.available_quantity,
            OnlyMoney(item.trade_available_cash, currency),
            OnlyMoney(item.withdrawable_cash, currency),
            item.legal_settled,
            item.sequence,
        )
        for item in authority.records
    )


__all__ = ["only_fee_execution_state", "only_settlement_execution_state", "only_settlement_record_replay"]
