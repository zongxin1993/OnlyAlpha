"""Immutable instruction-driven settlement domain models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.position.identifiers import OnlyPositionAllocationId
from onlyalpha.settlement.identifiers import OnlySettlementInstructionId


class OnlySettlementLegDirection(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class OnlySettlementInstructionStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    COMPLETED = "COMPLETED"


class OnlySettlementTransitionKind(StrEnum):
    ASSET_TRADE_AVAILABLE = "ASSET_TRADE_AVAILABLE"
    CASH_TRADE_AVAILABLE = "CASH_TRADE_AVAILABLE"
    CASH_WITHDRAWABLE = "CASH_WITHDRAWABLE"
    LEGAL_SETTLED = "LEGAL_SETTLED"


@dataclass(frozen=True, slots=True)
class OnlyCompiledSettlementPolicy(OnlyDomainModel):
    policy_id: str
    asset_booking_lag: int
    asset_trade_availability_lag: int
    cash_booking_lag: int
    cash_trade_availability_lag: int
    cash_withdrawal_lag: int
    legal_settlement_lag: int

    def __post_init__(self) -> None:
        if (
            not self.policy_id.strip()
            or min(
                self.asset_booking_lag,
                self.asset_trade_availability_lag,
                self.cash_booking_lag,
                self.cash_trade_availability_lag,
                self.cash_withdrawal_lag,
                self.legal_settlement_lag,
            )
            < 0
        ):
            raise ValueError("compiled Settlement policy requires identity and non-negative lags")


@dataclass(frozen=True, slots=True)
class OnlySettlementScheduleRequest(OnlyDomainModel):
    side: OnlyOrderSide
    trading_day: OnlyTradingDay


@dataclass(frozen=True, slots=True)
class OnlySettlementSchedule(OnlyDomainModel):
    asset_booked_on: OnlyTradingDay
    asset_trade_available_on: OnlyTradingDay
    cash_booked_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
    policy_id: str

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("Settlement schedule requires policy identity")


@dataclass(frozen=True, slots=True)
class OnlyAssetSettlementLeg(OnlyDomainModel):
    direction: OnlySettlementLegDirection
    quantity: OnlyQuantity
    booked_on: OnlyTradingDay
    trade_available_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay


@dataclass(frozen=True, slots=True)
class OnlyCashSettlementLeg(OnlyDomainModel):
    direction: OnlySettlementLegDirection
    legal_amount: OnlyMoney
    account_availability_amount: OnlyMoney
    booked_on: OnlyTradingDay
    trade_available_on: OnlyTradingDay
    withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay

    def __post_init__(self) -> None:
        if self.legal_amount.currency != self.account_availability_amount.currency:
            raise ValueError("Settlement cash leg requires one currency")
        if min(self.legal_amount.amount, self.account_availability_amount.amount) < 0:
            raise ValueError("Settlement cash leg amounts cannot be negative")


@dataclass(frozen=True, slots=True)
class OnlySettlementInstruction(OnlyDomainModel):
    instruction_id: OnlySettlementInstructionId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    position_id: OnlyPositionId
    position_cycle: int
    allocation_id: OnlyPositionAllocationId
    allocation_cycle: int
    side: OnlyOrderSide
    trade_quantity: OnlyQuantity
    gross_notional: OnlyMoney
    net_cash_flow: OnlyMoney
    trading_day: OnlyTradingDay
    schedule: OnlySettlementSchedule
    asset_leg: OnlyAssetSettlementLeg
    cash_leg: OnlyCashSettlementLeg
    market_profile_id: str
    market_profile_version: str
    compiled_rule_fingerprint: str
    reference_fingerprint: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if self.position_cycle < 1 or self.allocation_cycle < 1:
            raise ValueError("Settlement instruction requires positive lifecycle cycles")
        if self.trade_quantity.value <= 0 or self.asset_leg.quantity != self.trade_quantity:
            raise ValueError("Settlement instruction asset quantity is invalid")
        if len(self.content_fingerprint) != 64:
            raise ValueError("Settlement instruction content fingerprint must be SHA-256")


@dataclass(frozen=True, slots=True)
class OnlySettlementInstructionSnapshot(OnlyDomainModel):
    instruction: OnlySettlementInstruction
    asset_booked: bool
    asset_trade_available: bool
    cash_booked: bool
    cash_trade_available: bool
    cash_withdrawable: bool
    legal_settled: bool
    status: OnlySettlementInstructionStatus
    version: int
    record_sequence_head: int
    last_maturity_identity: str | None

    def __post_init__(self) -> None:
        if self.version < 1 or self.record_sequence_head < 0:
            raise ValueError("Settlement instruction version/record sequence is invalid")
        complete = (
            self.asset_trade_available and self.cash_trade_available and self.cash_withdrawable and self.legal_settled
        )
        expected = (
            OnlySettlementInstructionStatus.COMPLETED
            if complete
            else OnlySettlementInstructionStatus.PARTIALLY_EFFECTIVE
            if any(
                (
                    self.asset_booked,
                    self.asset_trade_available,
                    self.cash_booked,
                    self.cash_trade_available,
                    self.cash_withdrawable,
                    self.legal_settled,
                )
            )
            else OnlySettlementInstructionStatus.PENDING
        )
        if self.status is not expected:
            raise ValueError("Settlement instruction status disagrees with transition state")


@dataclass(frozen=True, slots=True)
class OnlySettlementDueTransition(OnlyDomainModel):
    instruction_id: OnlySettlementInstructionId
    effective_on: OnlyTradingDay
    transition: OnlySettlementTransitionKind


def only_settlement_instruction_content_payload(instruction: OnlySettlementInstruction) -> dict[str, object]:
    payload = instruction.to_dict()
    payload.pop("content_fingerprint", None)
    payload.pop("instruction_id", None)
    return payload


def only_settlement_instruction_content_fingerprint(instruction: OnlySettlementInstruction) -> str:
    encoded = json.dumps(
        only_settlement_instruction_content_payload(instruction), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
