"""Binding-to-policy authority proof consumed by the pure fee engine."""

from dataclasses import dataclass

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.fee.models import (
    OnlyBrokerFeeContractIdentity,
    OnlyFeeScheduleIdentity,
    OnlyMarketFeePackIdentity,
    only_fee_fingerprint,
)
from onlyalpha.fee.policy import OnlyResolvedFeePolicySet


@dataclass(frozen=True, slots=True)
class OnlyFeePolicyResolution:
    binding_fingerprint: str
    market_fee_pack: OnlyMarketFeePackIdentity
    broker_fee_contract: OnlyBrokerFeeContractIdentity
    scope_fingerprint: str
    resolved_schedules: tuple[OnlyFeeScheduleIdentity, ...]
    policies: OnlyResolvedFeePolicySet
    trading_day: OnlyTradingDay
    policy_fingerprint: str
    resolution_fingerprint: str

    def __post_init__(self) -> None:
        if self.policy_fingerprint != self.policies.fingerprint:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        policy_schedules = {
            (item.schedule_authority, item.schedule_id, item.schedule_version, item.schedule_fingerprint)
            for item in self.policies.policies
        }
        identities = {
            (item.authority, item.schedule_id, item.version, item.fingerprint) for item in self.resolved_schedules
        }
        if policy_schedules != identities:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        if self.resolution_fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        binding_fingerprint: str,
        market_fee_pack: OnlyMarketFeePackIdentity,
        broker_fee_contract: OnlyBrokerFeeContractIdentity,
        scope_fingerprint: str,
        resolved_schedules: tuple[OnlyFeeScheduleIdentity, ...],
        policies: OnlyResolvedFeePolicySet,
        trading_day: OnlyTradingDay,
    ) -> "OnlyFeePolicyResolution":
        ordered = tuple(
            sorted(
                resolved_schedules,
                key=lambda item: (item.authority.value, item.schedule_id, item.version, item.fingerprint),
            )
        )
        payload = (
            binding_fingerprint,
            market_fee_pack.to_dict(),
            broker_fee_contract.to_dict(),
            scope_fingerprint,
            tuple(item.to_dict() for item in ordered),
            policies.fingerprint,
            trading_day.to_dict(),
        )
        return cls(
            binding_fingerprint,
            market_fee_pack,
            broker_fee_contract,
            scope_fingerprint,
            ordered,
            policies,
            trading_day,
            policies.fingerprint,
            only_fee_fingerprint(payload),
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.binding_fingerprint,
            self.market_fee_pack.to_dict(),
            self.broker_fee_contract.to_dict(),
            self.scope_fingerprint,
            tuple(item.to_dict() for item in self.resolved_schedules),
            self.policy_fingerprint,
            self.trading_day.to_dict(),
        )


__all__ = ["OnlyFeePolicyResolution"]
