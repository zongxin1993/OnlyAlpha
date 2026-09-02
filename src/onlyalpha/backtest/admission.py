"""Fail-closed Backtest Product admission over existing semantic authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.dataset import (
    OnlyResearchDatasetEconomicBinding,
    OnlyResearchDatasetSnapshotStore,
)
from onlyalpha.runtime.backtest.input_requirements import OnlyKernelEconomicInputRequirement
from onlyalpha.strategy.promotion import OnlyStrategyPromotionStage
from onlyalpha.strategy.revision import OnlyStrategyRevision
from onlyalpha.strategy.store import OnlyStrategyRevisionReader

from .errors import OnlyBacktestError, OnlyBacktestErrorPhase
from .model import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestProfileReference,
    OnlyBacktestSpecification,
)


class _PromotionAuthority(Protocol):
    def current_stage(self, strategy_fingerprint: str) -> OnlyStrategyPromotionStage: ...


class _DatasetBindingAuthority(Protocol):
    def load_verified(self, fingerprint: str) -> OnlyResearchDatasetEconomicBinding: ...


class _ProfileAuthority(Protocol):
    def resolve_profile_fingerprint(self, kind: str, reference: OnlyBacktestProfileReference) -> str: ...


@dataclass(frozen=True, slots=True)
class OnlyBacktestMarketProductAdmission:
    composition_fingerprint: str
    required_economic_inputs: tuple[OnlyKernelEconomicInputRequirement, ...]
    implementation_fingerprints: tuple[str, ...]


class _MarketProductAuthority(Protocol):
    def resolve_for_backtest(
        self,
        configuration_fingerprint: str,
        strategy: OnlyStrategyRevision,
    ) -> OnlyBacktestMarketProductAdmission: ...


class OnlyBacktestAdmissionService:
    def __init__(
        self,
        *,
        strategies: OnlyStrategyRevisionReader,
        promotions: _PromotionAuthority,
        dataset_bindings: _DatasetBindingAuthority,
        datasets: OnlyResearchDatasetSnapshotStore,
        market_products: _MarketProductAuthority,
        profiles: _ProfileAuthority,
        kernel_semantics_version: str,
    ) -> None:
        if not kernel_semantics_version.strip():
            raise ValueError("Kernel semantics version is required")
        self._strategies = strategies
        self._promotions = promotions
        self._dataset_bindings = dataset_bindings
        self._datasets = datasets
        self._market_products = market_products
        self._profiles = profiles
        self._kernel_semantics_version = kernel_semantics_version

    def resolve(self, specification: OnlyBacktestSpecification) -> OnlyBacktestAdmissionResolution:
        strategy = self._load_strategy(specification.strategy_fingerprint)
        stage = self._promotions.current_stage(specification.strategy_fingerprint)
        if stage is OnlyStrategyPromotionStage.RESEARCH:
            _reject("STRATEGY_NOT_ADMITTED_TO_BACKTEST", specification.strategy_fingerprint)
        binding = self._load_binding(specification.dataset_binding_fingerprint)
        dataset = self._load_dataset(binding.base_dataset_snapshot_fingerprint)
        self._verify_strategy_dataset(strategy, dataset.snapshot.definition)
        market = self._market_products.resolve_for_backtest(
            specification.market_product_configuration_fingerprint,
            strategy,
        )
        if market.composition_fingerprint != binding.market_product_composition_fingerprint:
            _reject(
                "MARKET_PRODUCT_CONFIGURATION_MISMATCH",
                "Dataset binding and resolved Market Product composition differ",
            )
        self._verify_economic_closure(binding, market.required_economic_inputs)
        implementation_fingerprints = tuple(
            sorted(
                {
                    *(item.trading_implementation_fingerprint for item in strategy.implementation_bindings),
                    *market.implementation_fingerprints,
                }
            )
        )
        return OnlyBacktestAdmissionResolution(
            strategy_revision_schema_version=strategy.schema_version,
            strategy_fingerprint=str(strategy.strategy_fingerprint),
            dataset_binding_fingerprint=binding.fingerprint,
            base_dataset_snapshot_fingerprint=binding.base_dataset_snapshot_fingerprint,
            market_product_composition_fingerprint=market.composition_fingerprint,
            portfolio_profile_fingerprint=self._profile("PORTFOLIO", specification.portfolio_profile),
            risk_profile_fingerprint=self._profile("RISK", specification.risk_profile),
            execution_profile_fingerprint=self._profile("EXECUTION", specification.execution_profile),
            kernel_semantics_version=self._kernel_semantics_version,
            implementation_fingerprints=implementation_fingerprints,
        )

    def _load_strategy(self, fingerprint: str) -> OnlyStrategyRevision:
        try:
            strategy = self._strategies.load_verified(fingerprint)
        except Exception as exc:
            _reject(str(getattr(exc, "code", "STRATEGY_NOT_FOUND")), fingerprint, cause=exc)
        if str(strategy.strategy_fingerprint) != fingerprint:
            _reject("STRATEGY_CORRUPT", fingerprint)
        return strategy

    def _load_binding(self, fingerprint: str) -> OnlyResearchDatasetEconomicBinding:
        try:
            binding = self._dataset_bindings.load_verified(fingerprint)
        except Exception as exc:
            _reject(str(getattr(exc, "code", "DATASET_BINDING_NOT_FOUND")), fingerprint, cause=exc)
        if binding.fingerprint != fingerprint:
            _reject("DATASET_BINDING_CORRUPT", fingerprint)
        return binding

    def _load_dataset(self, fingerprint: str):  # type: ignore[no-untyped-def]
        try:
            return self._datasets.load_verified_table(fingerprint)
        except Exception as exc:
            code = getattr(exc, "code", "DATASET_NOT_FOUND")
            _reject(str(code), fingerprint, cause=exc)

    @staticmethod
    def _verify_strategy_dataset(strategy: OnlyStrategyRevision, definition) -> None:  # type: ignore[no-untyped-def]
        contract = strategy.market_input_contract
        if (
            strategy.universe.instruments != definition.instruments
            or contract.bar_specification != definition.bar_specification
            or contract.aggregation_source is not definition.aggregation_source
            or contract.adjustment_type is not definition.adjustment_type
            or contract.adjustment_reference != definition.adjustment_reference
        ):
            _reject("DATASET_CONTRACT_MISMATCH", "Strategy Market Input Contract and Dataset differ")

    @staticmethod
    def _verify_economic_closure(
        binding: OnlyResearchDatasetEconomicBinding,
        requirements: tuple[OnlyKernelEconomicInputRequirement, ...],
    ) -> None:
        available = {(item.fact_family, item.reference_price_kind) for item in binding.economic_facts}
        required = {(item.fact_family, item.reference_price_kind) for item in requirements}
        missing = required - available
        if missing:
            detail = ",".join(
                f"{family.value}:{'' if kind is None else kind.value}"
                for family, kind in sorted(missing, key=lambda item: (item[0].value, str(item[1])))
            )
            _reject("ECONOMIC_FACT_BINDING_INCOMPLETE", detail)
        for manifest in binding.economic_facts:
            if (
                manifest.record_count == 0
                and (
                    manifest.fact_family,
                    manifest.reference_price_kind,
                )
                in required
            ):
                _reject("ECONOMIC_FACT_BINDING_INCOMPLETE", "required economic manifest is empty")

    def _profile(self, kind: str, reference: OnlyBacktestProfileReference) -> str:
        try:
            fingerprint = self._profiles.resolve_profile_fingerprint(kind, reference)
        except Exception as exc:
            _reject("BACKTEST_PROFILE_NOT_FOUND", f"{kind}:{reference.profile_id}@{reference.version}", cause=exc)
        expected = only_canonical_fingerprint(
            {"kind": kind, "profile_id": reference.profile_id, "version": reference.version}
        )
        if fingerprint != expected:
            _reject("BACKTEST_PROFILE_CORRUPT", f"{kind}:{reference.profile_id}@{reference.version}")
        return fingerprint


def _reject(code: str, detail: str, *, cause: Exception | None = None):  # type: ignore[no-untyped-def]
    error = OnlyBacktestError(OnlyBacktestErrorPhase.ADMISSION, code, detail)
    if cause is not None:
        raise error from cause
    raise error


__all__ = [name for name in globals() if name.startswith("Only")]
