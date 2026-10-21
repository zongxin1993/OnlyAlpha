"""Selectable Backtest inputs projected from existing immutable owners."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onlyalpha.research.dataset import OnlyDatasetEconomicBindingStore, OnlyResearchDatasetSnapshotStore
from onlyalpha.strategy.revision import OnlyStrategyRevision
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore

from .admission import OnlyBacktestAdmissionService
from .deployment import OnlyBacktestDeploymentCatalog
from .errors import OnlyBacktestError, OnlyBacktestIntegrityError, OnlyBacktestProofUnavailableError
from .model import OnlyBacktestLimitPolicy, OnlyBacktestProfileReference, OnlyBacktestSpecification


class OnlyBacktestCreationQuery:
    def __init__(
        self,
        *,
        strategies: OnlyFrozenStrategyRevisionStore,
        datasets: OnlyResearchDatasetSnapshotStore,
        bindings: OnlyDatasetEconomicBindingStore,
        catalog: OnlyBacktestDeploymentCatalog,
        admission: OnlyBacktestAdmissionService,
        generation: Callable[[], str],
        validate_specification: Callable[[OnlyBacktestSpecification, OnlyStrategyRevision], None],
    ) -> None:
        self._strategies = strategies
        self._datasets = datasets
        self._bindings = bindings
        self._catalog = catalog
        self._admission = admission
        self._generation = generation
        self._validate_specification = validate_specification

    def get(self) -> dict[str, Any]:
        try:
            return self._read_context()
        except OnlyBacktestError:
            raise
        except OSError as exc:
            raise OnlyBacktestProofUnavailableError("Backtest creation input proof is unavailable") from exc
        except Exception as exc:
            code = getattr(exc, "code", "")
            if isinstance(code, str) and code.endswith(("_NOT_FOUND", "_UNAVAILABLE")):
                raise OnlyBacktestProofUnavailableError("Backtest creation input proof is unavailable") from exc
            raise OnlyBacktestIntegrityError(
                "BACKTEST_CREATION_CONTEXT_CORRUPT", "Existing input inventory failed verification"
            ) from exc

    def _read_context(self) -> dict[str, Any]:
        generation = self._generation()
        options: list[dict[str, Any]] = []
        denied: list[dict[str, str]] = []
        bindings = self._bindings.verified_bindings()
        # Discover through the owning metadata reader. Admission verifies the
        # physical table only after its decode budget has been established.
        datasets = {
            item.base_dataset_snapshot_fingerprint: self._datasets.load(item.base_dataset_snapshot_fingerprint)
            for item in bindings
        }
        for fingerprint in self._strategies.frozen_strategy_fingerprints():
            strategy = self._strategies.load_verified(fingerprint)
            for binding in bindings:
                dataset = datasets[binding.base_dataset_snapshot_fingerprint]
                definition = dataset.definition
                if dataset.row_count > 4096:
                    denied.append(
                        {
                            "strategy_fingerprint": fingerprint,
                            "code": "BACKTEST_NATIVE_DATASET_ROW_BOUND",
                            "detail": "Select a sealed dataset with at most 4096 bars",
                        }
                    )
                    continue
                if (
                    strategy.universe.instruments != definition.instruments
                    or strategy.market_input_contract.bar_semantic != definition.bar_semantic
                ):
                    continue
                for configuration in self._catalog.configuration_fingerprints:
                    document = self._catalog.document(configuration)
                    if tuple(item.instrument_id for item in document.instruments) != strategy.universe.instruments:
                        continue
                    currency = document.instruments[0].settlement_currency.code
                    specification = OnlyBacktestSpecification(
                        fingerprint,
                        binding.fingerprint,
                        configuration,
                        OnlyBacktestProfileReference("fixed-capital", "1"),
                        OnlyBacktestProfileReference("default-risk", "1"),
                        OnlyBacktestProfileReference("virtual-next-bar", "1"),
                        currency,
                        "10000.00",
                        schema_version=2,
                        order_policy=OnlyBacktestLimitPolicy("1", "1", "1", "1", 1),
                    )
                    try:
                        self._validate_specification(specification, strategy)
                        self._admission.resolve(specification)
                    except OnlyBacktestError as exc:
                        denied.append({"strategy_fingerprint": fingerprint, "code": exc.code, "detail": exc.detail})
                        continue
                    options.append(
                        {
                            "strategy_fingerprint": fingerprint,
                            "dataset_binding_fingerprint": binding.fingerprint,
                            "market_product_configuration_fingerprint": configuration,
                            "base_currency": currency,
                            "instruments": [str(item) for item in strategy.universe.instruments],
                            "start": definition.time_range.start.isoformat(),
                            "end": definition.time_range.end.isoformat(),
                            "row_count": dataset.row_count,
                        }
                    )
        return {"schema_version": 1, "runtime_generation_fingerprint": generation, "options": options, "denied": denied}
