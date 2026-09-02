"""Production Market Product SPI adapter for Backtest admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.product import (
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductConfig,
    OnlyMarketProductFactoryRegistry,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductResourceResolver,
)
from onlyalpha.research.dataset import OnlyResearchDatasetDefinition
from onlyalpha.runtime.backtest.input_requirements import (
    OnlyKernelEconomicInputRequirement,
    only_kernel_economic_input_requirements,
)
from onlyalpha.strategy.revision import OnlyStrategyRevision

from .admission import OnlyBacktestMarketProductAdmission


@dataclass(frozen=True, slots=True)
class OnlyBacktestMarketProductConfiguration:
    config: OnlyMarketProductConfig

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "plugin_id": str(self.config.plugin_id),
                "product_id": str(self.config.product_id),
                "product_version": str(self.config.product_version),
                "config": self.config.config.values,
            }
        )


class OnlyBacktestMarketProductConfigurationRegistry:
    def __init__(self, configurations: tuple[OnlyBacktestMarketProductConfiguration, ...] = ()) -> None:
        self._configurations: dict[str, OnlyBacktestMarketProductConfiguration] = {}
        for configuration in configurations:
            self.register(configuration)

    def register(self, configuration: OnlyBacktestMarketProductConfiguration) -> None:
        current = self._configurations.get(configuration.fingerprint)
        if current is not None and current != configuration:
            raise ValueError("MARKET_PRODUCT_CONFIGURATION_IDENTITY_CONFLICT")
        self._configurations[configuration.fingerprint] = configuration

    def resolve(self, fingerprint: str) -> OnlyBacktestMarketProductConfiguration:
        try:
            configuration = self._configurations[fingerprint]
        except KeyError as exc:
            raise ValueError("MARKET_PRODUCT_CONFIGURATION_NOT_FOUND") from exc
        if configuration.fingerprint != fingerprint:
            raise ValueError("MARKET_PRODUCT_CONFIGURATION_CORRUPT")
        return configuration


class _InstrumentAuthority(Protocol):
    def resolve_exact(self, instrument_ids: tuple[OnlyInstrumentId, ...]) -> tuple[OnlyInstrument, ...]: ...


class OnlyMarketProductBacktestAdmissionAdapter:
    def __init__(
        self,
        *,
        factories: OnlyMarketProductFactoryRegistry,
        configurations: OnlyBacktestMarketProductConfigurationRegistry,
        resources: OnlyMarketProductResourceResolver,
        instruments: _InstrumentAuthority,
    ) -> None:
        self._factories = factories
        self._configurations = configurations
        self._resources = resources
        self._instruments = instruments

    def resolve_for_backtest(
        self,
        configuration_fingerprint: str,
        strategy: OnlyStrategyRevision,
        dataset: OnlyResearchDatasetDefinition,
    ) -> OnlyBacktestMarketProductAdmission:
        configuration = self._configurations.resolve(configuration_fingerprint)
        binding = self._factories.resolve(
            configuration.config,
            OnlyMarketProductResolutionContext(
                self._resources,
                self._instruments.resolve_exact(strategy.universe.instruments),
            ),
        )
        trading_day = OnlyTradingDay(date.fromisoformat(dataset.time_range.start.date().isoformat()))
        requirements: set[OnlyKernelEconomicInputRequirement] = set()
        policy_fingerprints = set()
        for instrument_id in strategy.universe.instruments:
            policy = binding.policy_compiler.compile(
                OnlyMarketPolicyCompilationRequest(
                    instrument_id,
                    trading_day,
                    binding.reference_authority,
                    as_of=dataset.time_range.start,
                    effective_trading_profile=binding.effective_trading_profile,
                )
            )
            requirements.update(only_kernel_economic_input_requirements(policy))
            policy_fingerprints.add(policy.identity.policy_fingerprint)
        implementations = {
            binding.reference_authority.identity.authority_fingerprint,
            binding.policy_compiler.identity.authority_fingerprint,
            binding.market_fee_pack.identity.fingerprint,
            *policy_fingerprints,
        }
        return OnlyBacktestMarketProductAdmission(
            composition_fingerprint=binding.composition_identity.fingerprint,
            required_economic_inputs=tuple(
                sorted(
                    requirements,
                    key=lambda item: (
                        item.fact_family.value,
                        "" if item.reference_price_kind is None else item.reference_price_kind.value,
                    ),
                )
            ),
            implementation_fingerprints=tuple(sorted(implementations)),
        )


__all__ = [name for name in globals() if name.startswith("Only")]
