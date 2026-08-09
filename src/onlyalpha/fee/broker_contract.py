"""Versioned Broker fee-contract authority."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.fee.models import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeContractIdentity,
    only_fee_fingerprint,
)
from onlyalpha.fee.schedules import OnlyBrokerFeeSchedule, OnlyBrokerFeeScheduleRegistry


@dataclass(frozen=True, slots=True)
class OnlyBrokerFeeContract:
    contract_id: str
    contract_version: str
    broker_id: str
    account_scope: OnlyBrokerFeeAccountScope
    schedules: tuple[OnlyBrokerFeeSchedule, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.contract_version.strip() or not self.broker_id.strip():
            raise ValueError("broker fee contract identity cannot be empty")
        registry = OnlyBrokerFeeScheduleRegistry()
        for schedule in self.schedules:
            if schedule.broker_id != self.broker_id or schedule.account_scope != self.account_scope:
                raise ValueError("BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE")
            registry.register(schedule)
        if self.fingerprint != only_fee_fingerprint(self.authority_payload()):
            raise ValueError("BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        *,
        contract_id: str,
        contract_version: str,
        broker_id: str,
        account_scope: OnlyBrokerFeeAccountScope,
        schedules: tuple[OnlyBrokerFeeSchedule, ...] = (),
    ) -> "OnlyBrokerFeeContract":
        ordered = tuple(sorted(schedules, key=lambda value: (value.schedule_id, value.version)))
        payload = (
            contract_id,
            contract_version,
            broker_id,
            account_scope.to_dict(),
            tuple(item.fingerprint for item in ordered),
        )
        return cls(
            contract_id,
            contract_version,
            broker_id,
            account_scope,
            ordered,
            only_fee_fingerprint(payload),
        )

    @property
    def identity(self) -> OnlyBrokerFeeContractIdentity:
        return OnlyBrokerFeeContractIdentity(
            self.contract_id,
            self.contract_version,
            self.broker_id,
            self.account_scope,
            self.fingerprint,
        )

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.contract_id,
            self.contract_version,
            self.broker_id,
            self.account_scope.to_dict(),
            tuple(item.fingerprint for item in self.schedules),
        )

    def validate_compatibility(self, *, broker_id: str, account_id: OnlyAccountId) -> None:
        if self.broker_id != broker_id:
            raise ValueError("BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE")
        if (
            self.account_scope.scope_type is OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT
            and self.account_scope.account_id != account_id
        ):
            raise ValueError("BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE")


class OnlyBrokerFeeContractRegistry:
    def __init__(self) -> None:
        self._contracts: dict[tuple[str, str], OnlyBrokerFeeContract] = {}

    def register(self, contract: OnlyBrokerFeeContract) -> None:
        self.validate_registration(contract)
        self._contracts[(contract.contract_id, contract.contract_version)] = contract

    def validate_registration(self, contract: OnlyBrokerFeeContract) -> None:
        key = (contract.contract_id, contract.contract_version)
        current = self._contracts.get(key)
        if current is not None:
            if current.fingerprint != contract.fingerprint:
                raise ValueError("BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT")
            raise ValueError("BROKER_FEE_CONTRACT_DUPLICATE_VERSION")

    def validate_installations(self, contracts: tuple[OnlyBrokerFeeContract, ...]) -> None:
        staged: dict[tuple[str, str], OnlyBrokerFeeContract] = {}
        for contract in contracts:
            key = (contract.contract_id, contract.contract_version)
            current = staged.get(key)
            if current is not None:
                if current.fingerprint != contract.fingerprint:
                    raise ValueError("BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT")
                raise ValueError("BROKER_FEE_CONTRACT_DUPLICATE_VERSION")
            self.validate_registration(contract)
            staged[key] = contract

    def install_all(self, contracts: tuple[OnlyBrokerFeeContract, ...]) -> None:
        self.validate_installations(contracts)
        updated = dict(self._contracts)
        updated.update({(item.contract_id, item.contract_version): item for item in contracts})
        self._contracts = updated

    def require(self, contract_id: str, contract_version: str) -> OnlyBrokerFeeContract:
        try:
            return self._contracts[(contract_id, contract_version)]
        except KeyError as exc:
            raise ValueError("BROKER_FEE_CONTRACT_NOT_INSTALLED") from exc


def only_simulation_zero_broker_fee_contract(broker_id: str) -> OnlyBrokerFeeContract:
    scope = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.ALL_ACCOUNTS)
    normalized = broker_id.upper().replace("-", "_")
    return OnlyBrokerFeeContract.create(
        contract_id=f"{normalized}_SIMULATION_ZERO_BROKER_FEES",
        contract_version="1",
        broker_id=broker_id,
        account_scope=scope,
    )


__all__ = [
    "OnlyBrokerFeeContract",
    "OnlyBrokerFeeContractRegistry",
    "only_simulation_zero_broker_fee_contract",
]
