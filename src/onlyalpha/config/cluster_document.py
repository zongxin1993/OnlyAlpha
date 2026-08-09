"""Native single-Cluster product configuration document."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from onlyalpha.config.document import (
    OnlyClusterConfigError,
    OnlyOutputConfig,
    OnlyRuntimeAssemblyPlan,
    OnlyRuntimeConfig,
    _OnlyClusterDocumentParser,
)
from onlyalpha.config.models import (
    OnlyAccountRuntimeConfig,
    OnlyBrokerRuntimeConfig,
    OnlyClusterImportConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyFactorImportConfig,
    OnlyJsonMapping,
    OnlyJsonValue,
    OnlyMarketConfig,
    OnlyMarketFeePackConfig,
    OnlyReferenceDataConfig,
    OnlyStrategyImportConfig,
    OnlyUniverseConfig,
    _load_document,
    _normalize_mapping,
)
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.fee.provisioning import OnlyBrokerFeeContractDocumentLoader
from onlyalpha.market.models import OnlyMarketProfileId


@dataclass(frozen=True, slots=True)
class OnlyClusterRunConfig:
    """Validated product document defining exactly one Cluster."""

    schema_version: str
    cluster: OnlyClusterImportConfig
    runtime: OnlyRuntimeConfig
    reference_data: OnlyReferenceDataConfig
    universes: tuple[OnlyUniverseConfig, ...]
    data_sources: tuple[OnlyDataSourceRuntimeConfig, ...]
    accounts: tuple[OnlyAccountRuntimeConfig, ...]
    brokers: tuple[OnlyBrokerRuntimeConfig, ...]
    strategy: OnlyStrategyImportConfig
    factors: tuple[OnlyFactorImportConfig, ...]
    output: OnlyOutputConfig
    market: OnlyMarketConfig
    source_path: Path
    normalized_payload: OnlyJsonMapping
    broker_fee_contract_authorities: tuple[OnlyBrokerFeeContract, ...] = ()

    @property
    def cluster_id(self) -> OnlyClusterId:
        return self.cluster.cluster_id

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self.runtime.runtime_id

    @property
    def runtime_type(self) -> str:
        return self.runtime.runtime_type

    @property
    def start_time(self) -> datetime | None:
        return self.runtime.start_time

    @property
    def end_time(self) -> datetime | None:
        return self.runtime.end_time

    @classmethod
    def load(cls, path: str | Path) -> OnlyClusterRunConfig:
        source = Path(path).expanduser().resolve()
        return cls._parse(_load_document(source), source)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
        *,
        source_path: str | Path = "<mapping>",
    ) -> OnlyClusterRunConfig:
        normalized = _normalize_mapping(cast(Mapping[object, object], payload), "$")
        return cls._parse(normalized, Path(source_path))

    @classmethod
    def _parse(cls, root: OnlyJsonMapping, source: Path) -> OnlyClusterRunConfig:
        if "clusters" in root:
            raise OnlyClusterConfigError("single-Cluster documents must use 'cluster', not 'clusters'")
        parser = _OnlyClusterDocumentParser(source, root)
        cluster_raw = parser._map(root.get("cluster"), "$.cluster")
        cluster_id = parser._str(cluster_raw.get("cluster_id"), "$.cluster.cluster_id")
        runtime_raw: dict[str, object] = dict(parser._map(root.get("runtime"), "$.runtime"))
        runtime_raw["runtime_id"] = str(runtime_raw.get("runtime_id", f"{cluster_id}-runtime"))
        runtime_raw["type"] = str(cluster_raw.get("runtime_type", runtime_raw.get("type", "BACKTEST")))
        engine_raw = parser._map(root.get("engine", {}), "$.engine")
        runtime = parser._runtime(
            _normalize_mapping(cast(Mapping[object, object], runtime_raw), "$.runtime"), engine_raw
        )
        reference_data = parser._reference(
            parser._map(root.get("reference_data"), "$.reference_data"), runtime.base_currency
        )
        strategy_raw = parser._map(root.get("strategy"), "$.strategy")
        factors_raw = parser._list(root.get("factors", []), "$.factors")
        combined_cluster: dict[str, object] = dict(cluster_raw)
        combined_cluster.pop("runtime_type", None)
        combined_cluster["strategy"] = strategy_raw
        combined_cluster["factors"] = factors_raw
        cluster = parser._cluster(
            _normalize_mapping(cast(Mapping[object, object], combined_cluster), "$.cluster"), "$.cluster"
        )
        universes = parser._universes(parser._list(root.get("universes", []), "$.universes"))
        data_sources = parser._sources(parser._list(root.get("data_sources"), "$.data_sources"))
        accounts = parser._accounts(parser._list(root.get("accounts"), "$.accounts"), runtime.base_currency)
        brokers = parser._brokers(parser._list(root.get("brokers"), "$.brokers"))
        output = parser._output(parser._map(root.get("output", {}), "$.output"))
        market = _parse_market(parser, root)
        broker_fee_contract_authorities = _parse_broker_fee_contract_authorities(parser, root)
        schema_version = parser._str(root.get("schema_version", "1.0"), "$.schema_version")
        normalized_root: dict[str, object] = dict(root)
        normalized_reference = dict(parser._map(root.get("reference_data"), "$.reference_data"))
        normalized_reference["ashare_instruments"] = cast(
            OnlyJsonValue,
            [item.to_dict() for item in reference_data.ashare_registry.records],
        )
        normalized_root["reference_data"] = normalized_reference
        normalized_runtime = dict(runtime_raw)
        normalized_runtime["persistence"] = runtime.persistence.to_dict()
        normalized_root["runtime"] = normalized_runtime
        normalized_payload = _normalize_mapping(cast(Mapping[object, object], normalized_root), "$")

        # Reuse the shared reference validator without retaining a multi-Cluster
        # document in the product model.
        OnlyRuntimeAssemblyPlan(
            schema_version,
            runtime,
            reference_data,
            universes,
            data_sources,
            accounts,
            brokers,
            market,
            (cluster,),
            output,
            source,
            normalized_payload,
            broker_fee_contract_authorities,
        )
        return cls(
            schema_version,
            cluster,
            runtime,
            reference_data,
            universes,
            data_sources,
            accounts,
            brokers,
            cluster.strategy,
            cluster.factors,
            output,
            market,
            source,
            normalized_payload,
            broker_fee_contract_authorities,
        )


def _parse_market(parser: _OnlyClusterDocumentParser, root: OnlyJsonMapping) -> OnlyMarketConfig:
    if "market_simulation" in root:
        raise OnlyClusterConfigError("UNKNOWN_FIELD: market_simulation; use required 'market'")
    raw = parser._map(root.get("market"), "$.market")
    profile_value = parser._str(raw.get("profile"), "$.market.profile")
    try:
        profile = OnlyMarketProfileId(profile_value)
    except ValueError as exc:
        raise OnlyClusterConfigError(f"unknown market profile: {profile_value}") from exc
    version_value = raw.get("version")
    version = None if version_value is None else parser._str(version_value, "$.market.version")
    overrides = parser._map(raw.get("overrides", {}), "$.market.overrides")
    if "fees" in raw:
        raise OnlyClusterConfigError("UNKNOWN_FIELD: $.market.fees; use $.market.fee_pack")
    fee_pack_raw = parser._map(raw.get("fee_pack"), "$.market.fee_pack")
    pack_id = parser._str(fee_pack_raw.get("pack_id"), "$.market.fee_pack.pack_id")
    pack_version = parser._str(fee_pack_raw.get("pack_version"), "$.market.fee_pack.pack_version")
    return OnlyMarketConfig(
        profile,
        OnlyMarketFeePackConfig(pack_id, pack_version),
        version,
        overrides,
    )


def _parse_broker_fee_contract_authorities(
    parser: _OnlyClusterDocumentParser, root: OnlyJsonMapping
) -> tuple[OnlyBrokerFeeContract, ...]:
    raw = parser._map(root.get("authorities", {}), "$.authorities")
    unknown = sorted(set(raw) - {"broker_fee_contracts"})
    if unknown:
        raise OnlyClusterConfigError(f"UNKNOWN_FIELD: $.authorities.{unknown[0]}")
    documents = parser._list(raw.get("broker_fee_contracts", []), "$.authorities.broker_fee_contracts")
    contracts = tuple(
        OnlyBrokerFeeContractDocumentLoader.load(parser._map(value, f"$.authorities.broker_fee_contracts[{index}]"))
        for index, value in enumerate(documents)
    )
    identities = [(item.contract_id, item.contract_version) for item in contracts]
    if len(set(identities)) != len(identities):
        raise OnlyClusterConfigError("BROKER_FEE_CONTRACT_DUPLICATE_VERSION")
    return contracts
