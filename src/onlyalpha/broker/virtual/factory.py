"""Virtual Broker configuration factory."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from onlyalpha.broker.factory import OnlyBrokerBuildRequest
from onlyalpha.broker.virtual.commission import OnlyFixedCommissionModel
from onlyalpha.broker.virtual.config import OnlyVirtualBrokerConfig
from onlyalpha.domain.value import OnlyMoney


class OnlyVirtualBrokerFactory:
    @property
    def factory_id(self) -> str:
        return "VIRTUAL"

    def create(self, request: OnlyBrokerBuildRequest) -> OnlyVirtualBrokerConfig:
        raw = request.config.extensions
        commission = raw.get("commission", {})
        if not isinstance(commission, Mapping):
            raise ValueError("broker.extensions.commission must be a mapping")
        commission_type = str(commission.get("type", "NONE")).upper()
        if commission_type == "FIXED":
            amount = commission.get("fixed_amount", "0")
            if isinstance(amount, Mapping):
                amount = amount.get("value", "0")
            commission_model = OnlyFixedCommissionModel(
                OnlyMoney(Decimal(str(amount)), request.account.initial_cash.currency)
            )
        elif commission_type == "NONE":
            commission_model = OnlyFixedCommissionModel(OnlyMoney(Decimal("0"), request.account.initial_cash.currency))
        else:
            raise ValueError(f"unsupported Virtual Broker commission: {commission_type}")
        matching = raw.get("matching", {})
        slippage = raw.get("slippage", {})
        if not isinstance(matching, Mapping) or str(matching.get("type", "NEXT_BAR")).upper() != "NEXT_BAR":
            raise ValueError("first-phase Virtual Broker requires NEXT_BAR matching")
        if not isinstance(slippage, Mapping) or str(slippage.get("type", "NONE")).upper() != "NONE":
            raise ValueError("first-phase Virtual Broker requires NONE slippage")
        return OnlyVirtualBrokerConfig(
            request.config.gateway_id,
            request.account.account_id,
            request.assembly_plan.runtime.base_currency,
            request.account.initial_cash,
            commission_model=commission_model,
        )
