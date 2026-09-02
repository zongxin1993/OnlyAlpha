"""Verified deployment catalog for Backtest Product composition inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Protocol

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.market.product import OnlyMarketProductResourceResolver, OnlyMarketReferenceAuthority

from .market_adapter import (
    OnlyBacktestMarketProductConfiguration,
    OnlyBacktestMarketProductConfigurationRegistry,
)


class OnlyBacktestDeploymentCatalog:
    """Exact operator-provisioned Product documents, never user admission paths."""

    def __init__(self, documents: tuple[OnlyClusterRunConfig, ...]) -> None:
        if not documents:
            raise ValueError("BACKTEST_PRODUCT_CONFIGURATION_REQUIRED")
        self._documents: dict[str, OnlyClusterRunConfig] = {}
        instruments: dict[OnlyInstrumentId, OnlyInstrument] = {}
        configurations = OnlyBacktestMarketProductConfigurationRegistry()
        for document in documents:
            configuration = OnlyBacktestMarketProductConfiguration(document.market)
            current = self._documents.get(configuration.fingerprint)
            if current is not None and current.normalized_payload != document.normalized_payload:
                raise ValueError("BACKTEST_PRODUCT_CONFIGURATION_CONFLICT")
            self._documents[configuration.fingerprint] = document
            configurations.register(configuration)
            for instrument in document.reference_data.instruments:
                prior = instruments.get(instrument.instrument_id)
                if prior is not None and prior != instrument:
                    raise ValueError("BACKTEST_INSTRUMENT_AUTHORITY_CONFLICT")
                instruments[instrument.instrument_id] = instrument
        self.configurations = configurations
        self._instruments = instruments

    @property
    def configuration_fingerprints(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    def document(self, configuration_fingerprint: str) -> OnlyClusterRunConfig:
        try:
            return self._documents[configuration_fingerprint]
        except KeyError as exc:
            raise ValueError("MARKET_PRODUCT_CONFIGURATION_NOT_FOUND") from exc

    def resolve_exact(self, instrument_ids: tuple[OnlyInstrumentId, ...]) -> tuple[OnlyInstrument, ...]:
        try:
            values = tuple(self._instruments[item] for item in instrument_ids)
        except KeyError as exc:
            raise ValueError("BACKTEST_INSTRUMENT_NOT_FOUND") from exc
        if tuple(item.instrument_id for item in values) != instrument_ids:
            raise ValueError("BACKTEST_INSTRUMENT_AUTHORITY_CORRUPT")
        return values


def only_load_backtest_deployment_catalog(paths: tuple[Path, ...]) -> OnlyBacktestDeploymentCatalog:
    """Load exact operator-owned deployment documents outside Product admission."""
    documents: list[OnlyClusterRunConfig] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("schema")
            documents.append(OnlyClusterRunConfig.from_mapping(raw, source_path=str(path)))
        except Exception as exc:
            raise ValueError(f"BACKTEST_PRODUCT_CONFIGURATION_DOCUMENT_INVALID: {path}") from exc
    return OnlyBacktestDeploymentCatalog(tuple(documents))


class OnlyBacktestMarketProductResourceRegistry(OnlyMarketProductResourceResolver):
    def __init__(
        self,
        references: Mapping[str, OnlyMarketReferenceAuthority] | None = None,
        fee_packs: Mapping[tuple[str, str], OnlyMarketFeePack] | None = None,
    ) -> None:
        self._references = dict(references or {})
        self._fee_packs = dict(fee_packs or {})

    def register_reference(self, resource_id: str, authority: OnlyMarketReferenceAuthority) -> None:
        if not resource_id.strip():
            raise ValueError("MARKET_REFERENCE_RESOURCE_ID_INVALID")
        current = self._references.get(resource_id)
        if current is not None and current != authority:
            raise ValueError("MARKET_REFERENCE_AUTHORITY_CONFLICT")
        self._references[resource_id] = authority

    def require_reference_authority(self, resource_id: str) -> OnlyMarketReferenceAuthority:
        try:
            return self._references[resource_id]
        except KeyError as exc:
            raise ValueError(f"MARKET_REFERENCE_AUTHORITY_NOT_FOUND: {resource_id}") from exc

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack:
        try:
            return self._fee_packs[(pack_id, pack_version)]
        except KeyError as exc:
            raise ValueError(f"MARKET_FEE_PACK_NOT_FOUND: {pack_id}@{pack_version}") from exc


class OnlyBacktestMarketProductResourceProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def load_reference(self, payload: Mapping[str, object]) -> OnlyMarketReferenceAuthority: ...


def only_load_backtest_market_product_resources(
    paths: tuple[Path, ...],
) -> OnlyBacktestMarketProductResourceRegistry:
    providers: dict[str, OnlyBacktestMarketProductResourceProvider] = {}
    entries = metadata.entry_points().select(group="onlyalpha.backtest_market_product_resources")
    for entry in sorted(entries, key=lambda item: (item.name, item.value)):
        loaded = entry.load()
        provider = loaded() if isinstance(loaded, type) else loaded
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip() or provider_id in providers:
            raise ValueError("BACKTEST_MARKET_RESOURCE_PROVIDER_INVALID")
        providers[provider_id] = provider
    registry = OnlyBacktestMarketProductResourceRegistry()
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, dict)
                or set(raw) != {"schema_version", "provider_id", "resource_id", "payload"}
                or raw["schema_version"] != 1
                or not isinstance(raw["provider_id"], str)
                or not isinstance(raw["resource_id"], str)
                or not isinstance(raw["payload"], dict)
            ):
                raise ValueError("schema")
            provider = providers[raw["provider_id"]]
            authority = provider.load_reference(raw["payload"])
            registry.register_reference(raw["resource_id"], authority)
        except Exception as exc:
            raise ValueError(f"BACKTEST_MARKET_RESOURCE_DOCUMENT_INVALID: {path}") from exc
    return registry


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
