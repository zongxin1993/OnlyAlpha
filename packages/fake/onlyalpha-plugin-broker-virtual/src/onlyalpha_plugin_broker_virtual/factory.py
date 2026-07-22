"""Virtual Broker plugin Factory and extension parser."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha_plugin_broker_virtual.config import OnlyVirtualBrokerConfig
from onlyalpha_plugin_broker_virtual.descriptor import ONLY_VIRTUAL_PLUGIN_DESCRIPTOR
from onlyalpha_plugin_broker_virtual.gateway import OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.latency import OnlyFixedLatencyModel
from onlyalpha_plugin_broker_virtual.slippage import OnlyFixedSlippageModel


@dataclass(frozen=True, slots=True)
class OnlyVirtualBrokerPluginConfig:
    matching_type: str
    slippage_type: str
    maximum_fill_quantity: Decimal | None
    submit_latency_ns: int
    acceptance_latency_ns: int
    fill_latency_ns: int
    cancel_latency_ns: int
    query_latency_ns: int
    slippage_offset: Decimal | None


class OnlyVirtualBrokerFactory:
    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return ONLY_VIRTUAL_PLUGIN_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyVirtualBrokerPluginConfig:
        unknown = set(extensions) - {"matching", "latency", "slippage", "maximum_fill_quantity"}
        if unknown:
            raise ValueError(f"unknown Virtual Broker extensions: {', '.join(sorted(unknown))}")
        matching = extensions.get("matching", {})
        slippage = extensions.get("slippage", {})
        latency = extensions.get("latency", {})
        if not isinstance(matching, Mapping) or not isinstance(slippage, Mapping) or not isinstance(latency, Mapping):
            raise ValueError("broker matching/slippage/latency extensions must be mappings")
        unknown_matching = set(matching) - {"type", "maximum_fill_quantity"}
        unknown_slippage = set(slippage) - {"type", "price_offset"}
        unknown_latency = set(latency) - {"submit_ns", "acceptance_ns", "fill_ns", "cancel_ns", "query_ns"}
        if unknown_matching or unknown_slippage or unknown_latency:
            raise ValueError("unknown Virtual Broker nested extension field")
        return OnlyVirtualBrokerPluginConfig(
            str(matching.get("type", "NEXT_BAR")).upper(),
            str(slippage.get("type", "NONE")).upper(),
            (
                None
                if extensions.get("maximum_fill_quantity", matching.get("maximum_fill_quantity")) is None
                else Decimal(str(extensions.get("maximum_fill_quantity", matching.get("maximum_fill_quantity"))))
            ),
            int(latency.get("submit_ns", 0)),
            int(latency.get("acceptance_ns", 0)),
            int(latency.get("fill_ns", 0)),
            int(latency.get("cancel_ns", 0)),
            int(latency.get("query_ns", 0)),
            None if slippage.get("price_offset") is None else Decimal(str(slippage["price_offset"])),
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
            if config.matching_type != "NEXT_BAR":
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "NEXT_BAR matching is required"))
            if config.slippage_type not in {"NONE", "FIXED"}:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "unsupported slippage type"))
            if config.maximum_fill_quantity is not None and config.maximum_fill_quantity <= 0:
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "maximum fill must be positive"))
            if (
                min(
                    config.submit_latency_ns,
                    config.acceptance_latency_ns,
                    config.fill_latency_ns,
                    config.cancel_latency_ns,
                    config.query_latency_ns,
                )
                < 0
            ):
                issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "latency cannot be negative"))
        return tuple(issues)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        config = request.plugin_config
        if not isinstance(config, OnlyVirtualBrokerPluginConfig):
            raise TypeError("Virtual Broker Factory requires OnlyVirtualBrokerPluginConfig")
        broker_config = OnlyVirtualBrokerConfig(
            request.gateway_id,
            request.account_id,
            request.initial_cash.currency,
            request.initial_cash,
            maximum_fill_quantity=None
            if config.maximum_fill_quantity is None
            else OnlyQuantity(config.maximum_fill_quantity, 8),
            latency_model=OnlyFixedLatencyModel(
                config.submit_latency_ns,
                config.acceptance_latency_ns,
                config.fill_latency_ns,
                config.cancel_latency_ns,
                config.query_latency_ns,
            ),
            slippage_model=(
                None
                if config.slippage_type == "NONE"
                else OnlyFixedSlippageModel(OnlyPrice(config.slippage_offset or Decimal(0), 8))
            ),
        )
        gateway = OnlyVirtualBrokerGateway(
            broker_config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )
        return OnlyBrokerComponent(gateway, gateway, gateway)
