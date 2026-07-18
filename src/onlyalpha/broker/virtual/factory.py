"""Virtual Broker plugin Factory and extension parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.broker.virtual.commission import OnlyFixedCommissionModel
from onlyalpha.broker.virtual.config import OnlyVirtualBrokerConfig
from onlyalpha.broker.virtual.gateway import (
    ONLY_VIRTUAL_PLUGIN_DESCRIPTOR,
    OnlyVirtualBrokerGateway,
)
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor


@dataclass(frozen=True, slots=True)
class OnlyVirtualBrokerPluginConfig:
    commission_type: str
    commission_amount: Decimal
    matching_type: str
    slippage_type: str


class OnlyVirtualBrokerFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_VIRTUAL_PLUGIN_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyVirtualBrokerPluginConfig:
        commission = extensions.get("commission", {})
        if not isinstance(commission, Mapping):
            raise ValueError("broker.extensions.commission must be a mapping")
        commission_type = str(commission.get("type", "NONE")).upper()
        amount = commission.get("fixed_amount", "0")
        if isinstance(amount, Mapping):
            amount = amount.get("value", "0")
        matching = extensions.get("matching", {})
        slippage = extensions.get("slippage", {})
        if not isinstance(matching, Mapping) or not isinstance(slippage, Mapping):
            raise ValueError("broker matching/slippage extensions must be mappings")
        return OnlyVirtualBrokerPluginConfig(
            commission_type,
            Decimal(str(amount)),
            str(matching.get("type", "NEXT_BAR")).upper(),
            str(slippage.get("type", "NONE")).upper(),
        )

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues: list[OnlyPluginValidationIssue] = []
        capabilities = self.descriptor.capabilities
        if not isinstance(capabilities, OnlyBrokerPluginCapabilities):
            issues.append(OnlyPluginValidationIssue("PLUGIN_DESCRIPTOR_INVALID", "invalid capabilities"))
        else:
            issues.extend(
                OnlyPluginValidationIssue(
                    "PLUGIN_CAPABILITY_NOT_SUPPORTED",
                    f"Virtual Broker does not support {name}",
                    name,
                )
                for name in capabilities.missing(request.requested_capabilities)
            )
        config = request.plugin_config
        if not isinstance(config, OnlyVirtualBrokerPluginConfig):
            issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid Virtual Broker config"))
        else:
            if config.commission_type not in {"FIXED", "NONE"}:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "unsupported commission type"))
            if config.matching_type != "NEXT_BAR":
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "NEXT_BAR matching is required"))
            if config.slippage_type != "NONE":
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "NONE slippage is required"))
        return tuple(issues)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyVirtualBrokerGateway:
        config = request.plugin_config
        if not isinstance(config, OnlyVirtualBrokerPluginConfig):
            raise TypeError("Virtual Broker Factory requires OnlyVirtualBrokerPluginConfig")
        commission = Decimal(0) if config.commission_type == "NONE" else config.commission_amount
        broker_config = OnlyVirtualBrokerConfig(
            request.gateway_id,
            request.account_id,
            request.initial_cash.currency,
            request.initial_cash,
            commission_model=OnlyFixedCommissionModel(OnlyMoney(commission, request.initial_cash.currency)),
        )
        return OnlyVirtualBrokerGateway(
            broker_config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )
