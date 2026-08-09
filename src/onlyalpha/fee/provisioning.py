"""Strict static provisioning for Broker account fee-contract snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import cast

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract, OnlyBrokerFeeContractRegistry
from onlyalpha.fee.formula import OnlyFeeFormula, OnlyFeeRateTerm
from onlyalpha.fee.models import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyFeeAuthority,
    OnlyFeeCalculationBasis,
    OnlyFeeCalculationPipeline,
    OnlyFeeCalculationScope,
    OnlyFeeEconomicDirection,
    OnlyFeeResolutionPolicy,
    OnlyFeeRoundingMode,
    OnlyFeeType,
)
from onlyalpha.fee.policy import OnlyFeeRule
from onlyalpha.fee.rounding import OnlyFeeRoundingPolicy
from onlyalpha.fee.schedules import OnlyBrokerFeeSchedule


class OnlyBrokerFeeContractDocumentError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(f"BROKER_FEE_CONTRACT_DOCUMENT_INVALID: {message}")


class OnlyBrokerFeeContractDocumentLoader:
    """Parse one closed-schema Authority document; it performs no I/O."""

    @classmethod
    def load(cls, raw: Mapping[str, object]) -> OnlyBrokerFeeContract:
        try:
            cls._fields(
                raw,
                {"schema_version", "contract_id", "contract_version", "broker_id", "account_scope", "schedules"},
                "$",
            )
            if cls._text(raw, "schema_version", "$") != "1":
                raise OnlyBrokerFeeContractDocumentError("unsupported schema_version")
            contract_id = cls._text(raw, "contract_id", "$")
            version = cls._text(raw, "contract_version", "$")
            broker_id = cls._text(raw, "broker_id", "$")
            scope = cls._scope(cls._mapping(raw.get("account_scope"), "$.account_scope"))
            schedules_raw = cls._sequence(raw.get("schedules"), "$.schedules")
            if not schedules_raw:
                raise OnlyBrokerFeeContractDocumentError("$.schedules cannot be empty")
            schedules = tuple(
                cls._schedule(
                    cls._mapping(value, f"$.schedules[{index}]"),
                    path=f"$.schedules[{index}]",
                    contract_id=contract_id,
                    contract_version=version,
                    broker_id=broker_id,
                    account_scope=scope,
                )
                for index, value in enumerate(schedules_raw)
            )
            return OnlyBrokerFeeContract.create(
                contract_id=contract_id,
                contract_version=version,
                broker_id=broker_id,
                account_scope=scope,
                schedules=schedules,
            )
        except OnlyBrokerFeeContractDocumentError:
            raise
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise OnlyBrokerFeeContractDocumentError(str(exc)) from exc

    @classmethod
    def install(cls, raw: Mapping[str, object], registry: OnlyBrokerFeeContractRegistry) -> OnlyBrokerFeeContract:
        contract = cls.load(raw)
        registry.register(contract)
        return contract

    @classmethod
    def _scope(cls, raw: Mapping[str, object]) -> OnlyBrokerFeeAccountScope:
        cls._fields(raw, {"scope_type", "account_id"}, "$.account_scope", optional={"account_id"})
        scope_type = OnlyBrokerFeeAccountScopeType(cls._text(raw, "scope_type", "$.account_scope"))
        account_value = raw.get("account_id")
        account_id = None
        if account_value is not None:
            if not isinstance(account_value, str) or not account_value.strip():
                raise OnlyBrokerFeeContractDocumentError("$.account_scope.account_id must be non-empty text")
            account_id = OnlyAccountId(account_value.strip())
        return OnlyBrokerFeeAccountScope(scope_type, account_id)

    @classmethod
    def _schedule(
        cls,
        raw: Mapping[str, object],
        *,
        path: str,
        contract_id: str,
        contract_version: str,
        broker_id: str,
        account_scope: OnlyBrokerFeeAccountScope,
    ) -> OnlyBrokerFeeSchedule:
        cls._fields(
            raw,
            {
                "schedule_id",
                "version",
                "effective_from",
                "effective_to",
                "currency",
                "source",
                "rules",
            },
            path,
            optional={"effective_to"},
        )
        source = cls._text(raw, "source", path)
        expected_source = f"BROKER_CONTRACT:{contract_id}:{contract_version}"
        if source != expected_source:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.source must equal {expected_source}")
        currency_raw = cls._mapping(raw.get("currency"), f"{path}.currency")
        cls._fields(currency_raw, {"code", "precision"}, f"{path}.currency")
        if cls._text(currency_raw, "code", f"{path}.currency") != "CNY":
            raise OnlyBrokerFeeContractDocumentError(f"{path}.currency.code must be CNY")
        precision = currency_raw.get("precision")
        if type(precision) is not int or precision != 2:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.currency.precision must be 2")
        rules_raw = cls._sequence(raw.get("rules"), f"{path}.rules")
        if not rules_raw:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.rules cannot be empty")
        return OnlyBrokerFeeSchedule(
            cls._text(raw, "schedule_id", path),
            cls._text(raw, "version", path),
            cls._date(raw, "effective_from", path),
            None if raw.get("effective_to") is None else cls._date(raw, "effective_to", path),
            OnlyCurrency("CNY", 2),
            source,
            tuple(
                cls._rule(cls._mapping(value, f"{path}.rules[{index}]"), f"{path}.rules[{index}]")
                for index, value in enumerate(rules_raw)
            ),
            broker_id,
            account_scope,
        )

    @classmethod
    def _rule(cls, raw: Mapping[str, object], path: str) -> OnlyFeeRule:
        cls._fields(
            raw,
            {
                "rule_id",
                "fee_type",
                "authority",
                "economic_direction",
                "basis",
                "rate",
                "calculation_scope",
                "resolution_policy",
                "minimum",
                "maximum",
                "side",
                "offset",
                "rounding_quantum",
                "rounding_mode",
                "pipeline",
            },
            path,
            optional={"minimum", "maximum", "side", "offset"},
        )
        authority = OnlyFeeAuthority(cls._text(raw, "authority", path))
        if authority not in {OnlyFeeAuthority.BROKER, OnlyFeeAuthority.PLATFORM}:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.authority is not Broker-owned")
        return OnlyFeeRule(
            cls._text(raw, "rule_id", path),
            OnlyFeeType(cls._text(raw, "fee_type", path)),
            authority,
            OnlyFeeEconomicDirection(cls._text(raw, "economic_direction", path)),
            OnlyFeeFormula(
                (
                    OnlyFeeRateTerm(
                        OnlyFeeCalculationBasis(cls._text(raw, "basis", path)),
                        cls._decimal(raw, "rate", path),
                    ),
                )
            ),
            OnlyFeeCalculationScope(cls._text(raw, "calculation_scope", path)),
            OnlyFeeResolutionPolicy(cls._text(raw, "resolution_policy", path)),
            cls._optional_decimal(raw, "minimum", path),
            cls._optional_decimal(raw, "maximum", path),
            cls._optional_side(raw, path),
            cls._optional_offset(raw, path),
            None,
            OnlyFeeRoundingPolicy(
                cls._decimal(raw, "rounding_quantum", path),
                OnlyFeeRoundingMode(cls._text(raw, "rounding_mode", path)),
            ),
            OnlyFeeCalculationPipeline(cls._text(raw, "pipeline", path)),
        )

    @staticmethod
    def _fields(raw: Mapping[str, object], required: set[str], path: str, *, optional: set[str] | None = None) -> None:
        optional = optional or set()
        unknown = sorted(set(raw) - required)
        missing = sorted(required - optional - set(raw))
        if unknown:
            raise OnlyBrokerFeeContractDocumentError(f"unknown field {path}.{unknown[0]}")
        if missing:
            raise OnlyBrokerFeeContractDocumentError(f"missing field {path}.{missing[0]}")

    @staticmethod
    def _mapping(value: object, path: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
            raise OnlyBrokerFeeContractDocumentError(f"{path} must be an object")
        return cast(Mapping[str, object], value)

    @staticmethod
    def _sequence(value: object, path: str) -> Sequence[object]:
        if not isinstance(value, list | tuple):
            raise OnlyBrokerFeeContractDocumentError(f"{path} must be an array")
        return value

    @staticmethod
    def _text(raw: Mapping[str, object], name: str, path: str) -> str:
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise OnlyBrokerFeeContractDocumentError(f"{path}.{name} must be non-empty text")
        return value.strip()

    @classmethod
    def _date(cls, raw: Mapping[str, object], name: str, path: str) -> date:
        try:
            return date.fromisoformat(cls._text(raw, name, path))
        except ValueError as exc:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.{name} must be an ISO date") from exc

    @classmethod
    def _decimal(cls, raw: Mapping[str, object], name: str, path: str) -> Decimal:
        value = raw.get(name)
        if not isinstance(value, str):
            raise OnlyBrokerFeeContractDocumentError(f"{path}.{name} must be a quoted Decimal string")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise OnlyBrokerFeeContractDocumentError(f"{path}.{name} is not a Decimal") from exc
        if not result.is_finite():
            raise OnlyBrokerFeeContractDocumentError(f"{path}.{name} must be finite")
        return result

    @classmethod
    def _optional_decimal(cls, raw: Mapping[str, object], name: str, path: str) -> Decimal | None:
        return None if raw.get(name) is None else cls._decimal(raw, name, path)

    @staticmethod
    def _optional_side(raw: Mapping[str, object], path: str) -> OnlyOrderSide | None:
        value = raw.get("side")
        if value is None:
            return None
        if not isinstance(value, str):
            raise OnlyBrokerFeeContractDocumentError(f"{path}.side must be text or null")
        return OnlyOrderSide(value)

    @staticmethod
    def _optional_offset(raw: Mapping[str, object], path: str) -> OnlyOffset | None:
        value = raw.get("offset")
        if value is None:
            return None
        if not isinstance(value, str):
            raise OnlyBrokerFeeContractDocumentError(f"{path}.offset must be text or null")
        return OnlyOffset(value)


def only_provision_broker_fee_contract(
    contract: OnlyBrokerFeeContract, registry: OnlyBrokerFeeContractRegistry
) -> None:
    """Install an immutable snapshot once while rejecting identity conflicts."""

    try:
        installed = registry.require(contract.contract_id, contract.contract_version)
    except ValueError as exc:
        if str(exc) != "BROKER_FEE_CONTRACT_NOT_INSTALLED":
            raise
        registry.register(contract)
        return
    if installed.fingerprint != contract.fingerprint:
        raise ValueError("BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT")


__all__ = [
    "OnlyBrokerFeeContractDocumentError",
    "OnlyBrokerFeeContractDocumentLoader",
    "only_provision_broker_fee_contract",
]
