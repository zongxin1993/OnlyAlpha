"""Market-neutral immutable fee domain vocabulary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Self

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, only_decimal


class OnlyFeeAuthority(StrEnum):
    MARKET = "MARKET"
    VENUE = "VENUE"
    REGULATOR = "REGULATOR"
    CLEARING = "CLEARING"
    BROKER = "BROKER"
    PLATFORM = "PLATFORM"


class OnlyFeeType(StrEnum):
    STAMP_DUTY = "STAMP_DUTY"
    TRANSFER_FEE = "TRANSFER_FEE"
    EXCHANGE_FEE = "EXCHANGE_FEE"
    CLEARING_FEE = "CLEARING_FEE"
    REGULATORY_FEE = "REGULATORY_FEE"
    BROKER_COMMISSION = "BROKER_COMMISSION"
    PLATFORM_FEE = "PLATFORM_FEE"
    CONTRACT_FEE = "CONTRACT_FEE"
    OPEN_FEE = "OPEN_FEE"
    CLOSE_FEE = "CLOSE_FEE"
    CLOSE_TODAY_FEE = "CLOSE_TODAY_FEE"
    MAKER_FEE = "MAKER_FEE"
    TAKER_FEE = "TAKER_FEE"


class OnlyFeeCalculationBasis(StrEnum):
    NOTIONAL = "NOTIONAL"
    QUANTITY = "QUANTITY"
    CONTRACTS = "CONTRACTS"


class OnlyFeeEconomicDirection(StrEnum):
    CHARGE = "CHARGE"
    REBATE = "REBATE"


class OnlyFeeCalculationScope(StrEnum):
    FILL = "FILL"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"


class OnlyFeeResolutionPolicy(StrEnum):
    FILL_EFFECTIVE = "FILL_EFFECTIVE"
    ORDER_FIXED = "ORDER_FIXED"


class OnlyFeeScheduleAuthority(StrEnum):
    MARKET = "MARKET"
    BROKER = "BROKER"


class OnlyBrokerFeeAccountScopeType(StrEnum):
    ALL_ACCOUNTS = "ALL_ACCOUNTS"
    EXACT_ACCOUNT = "EXACT_ACCOUNT"


class OnlyFeeRoundingMode(StrEnum):
    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"
    CEILING = "CEILING"
    FLOOR = "FLOOR"


class OnlyFeeCalculationPipeline(StrEnum):
    BOUNDS_THEN_ROUND = "BOUNDS_THEN_ROUND"
    ROUND_THEN_BOUNDS = "ROUND_THEN_BOUNDS"


class OnlyLocalFeeFinality(StrEnum):
    ESTIMATED = "ESTIMATED"
    MODEL_PROVISIONAL = "MODEL_PROVISIONAL"
    MODEL_CONFIRMED = "MODEL_CONFIRMED"


@dataclass(frozen=True, slots=True)
class OnlyFeeBasisValues(OnlyDomainModel):
    notional: OnlyMoney
    quantity: Decimal
    contracts: Decimal

    def __post_init__(self) -> None:
        quantity = only_decimal(self.quantity)
        contracts = only_decimal(self.contracts)
        if self.notional.amount < 0 or quantity < 0 or contracts < 0:
            raise ValueError("fee basis values cannot be negative")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "contracts", contracts)

    def value(self, basis: OnlyFeeCalculationBasis) -> Decimal:
        if basis is OnlyFeeCalculationBasis.NOTIONAL:
            return self.notional.amount
        if basis is OnlyFeeCalculationBasis.QUANTITY:
            return self.quantity
        return self.contracts


@dataclass(frozen=True, slots=True)
class OnlyFeeSubject(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId


@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleIdentity(OnlyDomainModel):
    authority: OnlyFeeScheduleAuthority
    schedule_id: str
    version: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.schedule_id.strip() or not self.version.strip():
            raise ValueError("fee schedule identity cannot be empty")
        _require_digest(self.fingerprint, "schedule fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeAccountScope(OnlyDomainModel):
    scope_type: OnlyBrokerFeeAccountScopeType
    account_id: OnlyAccountId | None = None

    def __post_init__(self) -> None:
        if self.scope_type is OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS and self.account_id is not None:
            raise ValueError("ALL_ACCOUNTS broker fee scope cannot name an account")
        if self.scope_type is OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT and self.account_id is None:
            raise ValueError("EXACT_ACCOUNT broker fee scope requires an account")


@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleFamilyIdentity(OnlyDomainModel):
    authority: OnlyFeeScheduleAuthority
    schedule_id: str
    scope_fingerprint: str

    def __post_init__(self) -> None:
        if not self.schedule_id.strip():
            raise ValueError("fee schedule family ID cannot be empty")
        _require_digest(self.scope_fingerprint, "schedule scope fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyMarketFeePackIdentity(OnlyDomainModel):
    pack_id: str
    pack_version: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.pack_id.strip() or not self.pack_version.strip():
            raise ValueError("market fee pack identity cannot be empty")
        _require_digest(self.fingerprint, "market fee pack fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeContractIdentity(OnlyDomainModel):
    contract_id: str
    contract_version: str
    broker_id: str
    account_scope: OnlyBrokerFeeAccountScope
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.contract_version.strip() or not self.broker_id.strip():
            raise ValueError("broker fee contract identity cannot be empty")
        _require_digest(self.fingerprint, "broker fee contract fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeApplicabilityScopeIdentity(OnlyDomainModel):
    market_profile_id: str
    market: str
    venue: str
    instrument_class: str
    broker_id: str
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    charge_currency: OnlyCurrency
    fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.market_profile_id.strip(),
                self.market.strip(),
                self.venue.strip(),
                self.instrument_class.strip(),
                self.broker_id.strip(),
            )
        ):
            raise ValueError("order fee applicability scope cannot be empty")
        _require_digest(self.fingerprint, "order fee applicability scope fingerprint")
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")

    @classmethod
    def create(
        cls,
        *,
        market_profile_id: str,
        market: str,
        venue: str,
        instrument_class: str,
        broker_id: str,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        charge_currency: OnlyCurrency,
    ) -> OnlyOrderFeeApplicabilityScopeIdentity:
        payload = (
            market_profile_id,
            market,
            venue,
            instrument_class,
            broker_id,
            str(account_id),
            str(instrument_id),
            charge_currency.to_dict(),
        )
        return cls(
            market_profile_id,
            market,
            venue,
            instrument_class,
            broker_id,
            account_id,
            instrument_id,
            charge_currency,
            only_fee_fingerprint(payload),
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.market_profile_id,
            self.market,
            self.venue,
            self.instrument_class,
            self.broker_id,
            str(self.account_id),
            str(self.instrument_id),
            self.charge_currency.to_dict(),
        )


@dataclass(frozen=True, slots=True)
class OnlyFeeComponentIdentity(OnlyDomainModel):
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    source_id: str
    schedule_id: str
    schedule_version: str
    schedule_fingerprint: str
    rule_id: str
    rule_fingerprint: str
    calculation_scope: OnlyFeeCalculationScope
    resolution_policy: OnlyFeeResolutionPolicy
    economic_direction: OnlyFeeEconomicDirection

    def __post_init__(self) -> None:
        if not all(
            (self.source_id.strip(), self.schedule_id.strip(), self.schedule_version.strip(), self.rule_id.strip())
        ):
            raise ValueError("fee component identity cannot be empty")
        _require_digest(self.schedule_fingerprint, "schedule fingerprint")
        _require_digest(self.rule_fingerprint, "rule fingerprint")

    @property
    def sort_key(self) -> tuple[str, ...]:
        return tuple(
            str(value)
            for value in (
                self.fee_type.value,
                self.authority.value,
                self.source_id,
                self.schedule_id,
                self.schedule_version,
                self.rule_id,
                self.calculation_scope.value,
                self.resolution_policy.value,
                self.economic_direction.value,
            )
        )


@dataclass(frozen=True, slots=True)
class OnlyFeeTargetComponent(OnlyDomainModel):
    identity: OnlyFeeComponentIdentity
    raw_amount: OnlyMoney
    bounded_amount: OnlyMoney
    target_amount: OnlyMoney
    local_finality: OnlyLocalFeeFinality

    def __post_init__(self) -> None:
        monies = (self.raw_amount, self.bounded_amount, self.target_amount)
        if len({item.currency for item in monies}) != 1 or any(item.amount < 0 for item in monies):
            raise ValueError("fee target component currency/amount is invalid")


@dataclass(frozen=True, slots=True)
class OnlyFeeAssessment(OnlyDomainModel):
    schema_version = 2

    assessment_id: str
    subject: OnlyFeeSubject
    trade_id: OnlyTradeId | None
    components: tuple[OnlyFeeTargetComponent, ...]
    total_charges: OnlyMoney
    total_rebates: OnlyMoney
    policy_fingerprint: str
    resolution_fingerprint: str
    local_finality: OnlyLocalFeeFinality
    binding: OnlyOrderFeePolicyBinding

    def __post_init__(self) -> None:
        if not self.assessment_id.strip():
            raise ValueError("fee assessment identity cannot be empty")
        _require_digest(self.policy_fingerprint, "policy fingerprint")
        _require_digest(self.resolution_fingerprint, "resolution fingerprint")
        if self.total_charges.currency != self.total_rebates.currency:
            raise ValueError("fee assessment currency mismatch")
        if self.total_charges.amount < 0 or self.total_rebates.amount < 0:
            raise ValueError("fee assessment totals cannot be negative")
        if len({item.identity for item in self.components}) != len(self.components):
            raise ValueError("fee assessment component identity must be unique")
        currency = self.total_charges.currency
        if any(item.target_amount.currency != currency for item in self.components):
            raise ValueError("fee assessment component currency mismatch")
        charges = sum(
            (
                item.target_amount.amount
                for item in self.components
                if item.identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
            ),
            Decimal(0),
        )
        rebates = sum(
            (
                item.target_amount.amount
                for item in self.components
                if item.identity.economic_direction is OnlyFeeEconomicDirection.REBATE
            ),
            Decimal(0),
        )
        if charges != self.total_charges.amount or rebates != self.total_rebates.amount:
            raise ValueError("fee assessment totals disagree with components")
        if self.binding.order_id != self.subject.order_id:
            raise ValueError("fee assessment binding scope mismatch")


@dataclass(frozen=True, slots=True)
class OnlyOrderFeePolicyBinding(OnlyDomainModel):
    schema_version = 2

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId
    market_profile_id: str
    market_profile_version: str
    market_fee_pack: OnlyMarketFeePackIdentity
    broker_fee_contract: OnlyBrokerFeeContractIdentity
    applicability_scope: OnlyOrderFeeApplicabilityScopeIdentity
    order_fixed_schedules: tuple[OnlyFeeScheduleIdentity, ...]
    fill_effective_families: tuple[OnlyFeeScheduleFamilyIdentity, ...]
    charge_currency: OnlyCurrency
    bound_at: OnlyTimestamp
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.market_profile_id.strip() or not self.market_profile_version.strip():
            raise ValueError("order fee binding requires a market profile identity")
        if len({(item.authority, item.schedule_id) for item in self.fill_effective_families}) != len(
            self.fill_effective_families
        ):
            raise ValueError("fill-effective schedule families must be unique")
        if len({(item.authority, item.schedule_id, item.version) for item in self.order_fixed_schedules}) != len(
            self.order_fixed_schedules
        ):
            raise ValueError("order-fixed schedule identities must be unique")
        if self.applicability_scope.account_id != self.account_id:
            raise ValueError("order fee applicability account conflicts with binding")
        if self.applicability_scope.instrument_id != self.instrument_id:
            raise ValueError("order fee applicability instrument conflicts with binding")
        if self.applicability_scope.market_profile_id != self.market_profile_id:
            raise ValueError("order fee applicability profile conflicts with binding")
        if self.applicability_scope.charge_currency != self.charge_currency:
            raise ValueError("order fee applicability currency conflicts with binding")
        _require_digest(self.fingerprint, "binding fingerprint")
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("ORDER_FEE_BINDING_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        order_id: OnlyOrderId,
        instrument_id: OnlyInstrumentId,
        market_profile_id: str,
        market_profile_version: str,
        market_fee_pack: OnlyMarketFeePackIdentity,
        broker_fee_contract: OnlyBrokerFeeContractIdentity,
        applicability_scope: OnlyOrderFeeApplicabilityScopeIdentity,
        order_fixed_schedules: tuple[OnlyFeeScheduleIdentity, ...],
        fill_effective_families: tuple[OnlyFeeScheduleFamilyIdentity, ...],
        charge_currency: OnlyCurrency,
        bound_at: OnlyTimestamp,
    ) -> OnlyOrderFeePolicyBinding:
        payload = (
            str(runtime_id),
            str(account_id),
            str(cluster_id),
            str(order_id),
            str(instrument_id),
            market_profile_id,
            market_profile_version,
            market_fee_pack.to_dict(),
            broker_fee_contract.to_dict(),
            applicability_scope.to_dict(),
            tuple(item.to_dict() for item in order_fixed_schedules),
            tuple(item.to_dict() for item in fill_effective_families),
            charge_currency.to_dict(),
            bound_at.to_dict(),
        )
        return cls(
            runtime_id,
            account_id,
            cluster_id,
            order_id,
            instrument_id,
            market_profile_id,
            market_profile_version,
            market_fee_pack,
            broker_fee_contract,
            applicability_scope,
            order_fixed_schedules,
            fill_effective_families,
            charge_currency,
            bound_at,
            only_fee_fingerprint(payload),
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            str(self.runtime_id),
            str(self.account_id),
            str(self.cluster_id),
            str(self.order_id),
            str(self.instrument_id),
            self.market_profile_id,
            self.market_profile_version,
            self.market_fee_pack.to_dict(),
            self.broker_fee_contract.to_dict(),
            self.applicability_scope.to_dict(),
            tuple(item.to_dict() for item in self.order_fixed_schedules),
            tuple(item.to_dict() for item in self.fill_effective_families),
            self.charge_currency.to_dict(),
            self.bound_at.to_dict(),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        if payload.get("schema_version") != cls.schema_version:
            raise OnlySerializationError("UNSUPPORTED_ORDER_FEE_BINDING_SCHEMA")
        return super(OnlyOrderFeePolicyBinding, cls).from_dict(payload)


def only_fee_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, OnlyDomainModel):
        return value.to_dict()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    raise TypeError(f"unsupported fee fingerprint value: {type(value).__name__}")


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
