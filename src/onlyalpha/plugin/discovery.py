"""Deterministic importlib.metadata Entry Point plugin discovery."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.errors import OnlyPluginDiscoveryError

ONLYALPHA_DATA_SOURCE_ENTRY_POINT = "onlyalpha.data_sources"
ONLYALPHA_BROKER_ENTRY_POINT = "onlyalpha.brokers"
ONLYALPHA_BROKER_FEE_CONTRACT_ENTRY_POINT = "onlyalpha.broker_fee_contracts"
ONLYALPHA_MARKET_PRODUCT_ENTRY_POINT = "onlyalpha.market_products"


@dataclass(frozen=True, slots=True)
class OnlyPluginDiscoveryFailure:
    group: str
    name: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class OnlyPluginDiscoveryRecord:
    group: str
    name: str
    plugin_id: str
    origin: str


@dataclass(frozen=True, slots=True)
class OnlyPluginDiscoveryReport:
    discovered: tuple[OnlyPluginDiscoveryRecord, ...]
    failures: tuple[OnlyPluginDiscoveryFailure, ...]


def only_discover_plugins(
    data_sources: object,
    brokers: object,
    broker_fee_contracts: object,
    market_products: object,
    *,
    fail_fast: bool,
) -> OnlyPluginDiscoveryReport:
    selected = metadata.entry_points()
    entries = [
        entry
        for group in (
            ONLYALPHA_DATA_SOURCE_ENTRY_POINT,
            ONLYALPHA_BROKER_ENTRY_POINT,
            ONLYALPHA_BROKER_FEE_CONTRACT_ENTRY_POINT,
            ONLYALPHA_MARKET_PRODUCT_ENTRY_POINT,
        )
        for entry in selected.select(group=group)
    ]
    records: list[OnlyPluginDiscoveryRecord] = []
    failures: list[OnlyPluginDiscoveryFailure] = []
    for entry in sorted(entries, key=lambda item: (item.group, item.name, item.value)):
        origin = OnlyPluginOrigin(OnlyPluginOriginType.ENTRY_POINT, f"{entry.group}:{entry.name}")
        try:
            loaded = entry.load()
            factory = (
                loaded()
                if isinstance(loaded, type) or (callable(loaded) and not hasattr(loaded, "descriptor"))
                else loaded
            )
            if entry.group == ONLYALPHA_DATA_SOURCE_ENTRY_POINT:
                registry = data_sources
            elif entry.group == ONLYALPHA_BROKER_ENTRY_POINT:
                registry = brokers
            elif entry.group == ONLYALPHA_BROKER_FEE_CONTRACT_ENTRY_POINT:
                registry = broker_fee_contracts
            else:
                registry = market_products
            register = getattr(registry, "register", None)
            if not callable(register):
                raise OnlyPluginDiscoveryError("PLUGIN_FACTORY_INVALID", "target registry has no register()")
            if entry.group in {
                ONLYALPHA_BROKER_FEE_CONTRACT_ENTRY_POINT,
                ONLYALPHA_MARKET_PRODUCT_ENTRY_POINT,
            }:
                register(factory)
            else:
                register(factory, origin=origin)
            descriptor = getattr(factory, "descriptor", None)
            plugin_id = getattr(factory, "plugin_id", getattr(descriptor, "plugin_id", entry.name))
            records.append(OnlyPluginDiscoveryRecord(entry.group, entry.name, str(plugin_id), str(origin)))
        except Exception as exc:
            code = getattr(exc, "code", "PLUGIN_LOAD_FAILED")
            failure = OnlyPluginDiscoveryFailure(entry.group, entry.name, code, str(exc))
            failures.append(failure)
            if fail_fast:
                raise OnlyPluginDiscoveryError(
                    code,
                    str(exc),
                    plugin_id=entry.name,
                    origin=str(origin),
                ) from exc
    return OnlyPluginDiscoveryReport(tuple(records), tuple(failures))
