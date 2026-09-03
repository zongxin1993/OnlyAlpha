"""Fenced Backtest Product Worker and the sole Product-to-Engine bridge."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from enum import StrEnum
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from onlyalpha.canonical import only_canonical_json
from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.market.product import OnlyMarketProductResourceResolver
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.strategy.store import OnlyStrategyRevisionReader

from .admission import OnlyBacktestAdmissionService
from .dataset_source import OnlyBacktestDatasetSourceFactory, OnlyBacktestEconomicFactReader
from .deployment import OnlyBacktestDeploymentCatalog
from .errors import OnlyBacktestError, OnlyBacktestErrorPhase, OnlyBacktestStateConflictError
from .evidence import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from .execution import (
    OnlyBacktestAttemptId,
    OnlyBacktestExecutionClaim,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestExecutionStore,
    OnlyBacktestWorkerInstanceId,
)
from .model import (
    OnlyBacktestExecutionSemanticBinding,
    OnlyBacktestRun,
    OnlyBacktestRunFailure,
    OnlyBacktestRunFailurePhase,
    OnlyBacktestRunState,
)
from .profiles import OnlyBacktestProfile, OnlyBacktestProfileRegistry


@dataclass(frozen=True, slots=True)
class OnlyBacktestRuntimeExecutionResult:
    result_fingerprint: str
    determinism_fingerprint: str
    artifacts: tuple[tuple[str, bytes, str], ...]

    def __post_init__(self) -> None:
        for value in (self.result_fingerprint, self.determinism_fingerprint):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("BACKTEST_RUNTIME_RESULT_IDENTITY_INVALID")
        names = tuple(item[0] for item in self.artifacts)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("BACKTEST_RUNTIME_RESULT_ARTIFACTS_INVALID")


class OnlyBacktestRuntimeExecutor(Protocol):
    def execute(self, run: OnlyBacktestRun) -> OnlyBacktestRuntimeExecutionResult: ...


class OnlyBacktestEnginePlanBuilder(Protocol):
    def build(
        self, run: OnlyBacktestRun
    ) -> tuple[OnlyEngineConfig, tuple[OnlyClusterRunConfig, ...], OnlyEngineServices]: ...


class OnlyBacktestProductEnginePlanBuilder:
    """Builds one typed Engine plan exclusively from verified Product authorities."""

    def __init__(
        self,
        *,
        user_data_root: Path,
        catalog: OnlyBacktestDeploymentCatalog,
        strategies: OnlyStrategyRevisionReader,
        datasets: OnlyResearchDatasetSnapshotStore,
        profiles: OnlyBacktestProfileRegistry,
        market_product_resources: OnlyMarketProductResourceResolver,
        economic_facts: OnlyBacktestEconomicFactReader | None = None,
    ) -> None:
        self._user_data_root = user_data_root
        self._catalog = catalog
        self._strategies = strategies
        self._datasets = datasets
        self._profiles = profiles
        services = only_default_engine_services(fail_fast=True)
        services.assembler.components.data_sources.register(OnlyBacktestDatasetSourceFactory(datasets, economic_facts))
        self._services = dataclass_replace(services, market_product_resources=market_product_resources)

    def build(
        self, run: OnlyBacktestRun
    ) -> tuple[OnlyEngineConfig, tuple[OnlyClusterRunConfig, ...], OnlyEngineServices]:
        specification = run.specification
        resolution = run.admission_resolution
        strategy = self._strategies.load_verified(resolution.strategy_fingerprint)
        verified = self._datasets.load_verified_table(resolution.base_dataset_snapshot_fingerprint)
        definition = verified.snapshot.definition
        document = self._catalog.document(specification.market_product_configuration_fingerprint)
        if tuple(item.instrument_id for item in document.instruments) != strategy.universe.instruments:
            raise OnlyBacktestError(
                OnlyBacktestErrorPhase.EXECUTION,
                "BACKTEST_PRODUCT_INSTRUMENT_SET_MISMATCH",
                run.run_id.value,
            )
        resolved_profiles: dict[str, OnlyBacktestProfile] = {}
        for kind, reference, fingerprint in (
            ("PORTFOLIO", specification.portfolio_profile, resolution.portfolio_profile_fingerprint),
            ("RISK", specification.risk_profile, resolution.risk_profile_fingerprint),
            ("EXECUTION", specification.execution_profile, resolution.execution_profile_fingerprint),
        ):
            profile = self._profiles.resolve_profile(kind, reference)
            if profile.fingerprint != fingerprint:
                raise OnlyBacktestError(OnlyBacktestErrorPhase.EXECUTION, "EXECUTION_SEMANTIC_DRIFT", kind)
            resolved_profiles[kind] = profile
        OnlyBacktestExecutionSemanticBinding.from_admission(specification, resolution)
        allocation_model = _fixed_capital_profile(resolved_profiles["PORTFOLIO"])
        _validate_risk_profile(resolved_profiles["RISK"])
        execution = _execution_profile(resolved_profiles["EXECUTION"])
        semantic_id = run.specification_fingerprint[:16]
        cluster_id = f"backtest-{semantic_id}"
        runtime_id = f"{cluster_id}-runtime"
        engine_id = OnlyEngineId(f"{cluster_id}-engine")
        account_id = "backtest-account"
        gateway_id = "virtual-main"
        universe_id = f"universe-{semantic_id}"
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "market": dict(document.market),
            "cluster": {
                "cluster_id": cluster_id,
                "account_id": account_id,
                "enabled": True,
                "runtime_type": "BACKTEST",
                "capital": {
                    "mode": allocation_model,
                    "amount": specification.initial_capital,
                    "currency": specification.base_currency,
                },
            },
            "runtime": {
                "engine_id": str(engine_id),
                "runtime_id": runtime_id,
                "type": "BACKTEST",
                "start_time": definition.time_range.start.isoformat(),
                "end_time": definition.time_range.end.isoformat(),
                "base_currency": specification.base_currency,
                "persistence": {"backend": "MEMORY", "checkpoint": {"enabled": False, "retain_last": 2}},
                "extensions": {"replay": {"stop_on_data_error": True}},
            },
            "reference_data": dict(document.reference_data),
            "universes": [
                {
                    "universe_id": universe_id,
                    "type": "STATIC",
                    "instruments": [str(item) for item in strategy.universe.instruments],
                }
            ],
            "data_sources": [
                {
                    "source_id": f"dataset-{semantic_id}",
                    "plugin": "onlyalpha-dataset-snapshot",
                    "data_version": f"snapshot-{resolution.base_dataset_snapshot_fingerprint[:16]}",
                    "batch_size": 1024,
                    "coverage": {"instrument_ids": [str(item) for item in strategy.universe.instruments]},
                    "extensions": {
                        "snapshot_fingerprint": resolution.base_dataset_snapshot_fingerprint,
                        "dataset_binding_fingerprint": resolution.dataset_binding_fingerprint,
                    },
                }
            ],
            "accounts": [
                {
                    "account_id": account_id,
                    "gateway_id": gateway_id,
                    "broker_fee_contract": execution["broker_fee_contract"],
                    "fee_reconciliation_policy": execution["fee_reconciliation_policy"],
                    "initial_cash": {"value": specification.initial_capital, "currency": specification.base_currency},
                }
            ],
            "brokers": [
                {
                    "gateway_id": gateway_id,
                    "plugin": "virtual",
                    "extensions": {
                        "matching": execution["matching"],
                        "slippage": execution["slippage"],
                        "latency": execution["latency"],
                    },
                }
            ],
            "strategy": {"fingerprint": resolution.strategy_fingerprint},
            "factors": [],
            "output": {"formats": ["JSON"], "overwrite": False},
        }
        from onlyalpha.fee.reconciliation_policy import only_standard_fee_reconciliation_policy

        currency = OnlyCurrency(specification.base_currency, 2)
        policies = self._services.assembler.components.fee_reconciliation_policies
        try:
            policies.require("STANDARD_FEE_RECONCILIATION", "1", currency)
        except ValueError as exc:
            if str(exc) != "FEE_RECONCILIATION_POLICY_NOT_INSTALLED":
                raise
            policies.register(only_standard_fee_reconciliation_policy(currency))
        config = OnlyClusterRunConfig.from_mapping(payload, source_path=f"<backtest-product:{run.run_id.value}>")
        return OnlyEngineConfig(engine_id, self._user_data_root), (config,), self._services


def _fixed_capital_profile(profile: OnlyBacktestProfile) -> str:
    if dict(profile.semantics) != {"allocation_model": "FIXED_CAPITAL"}:
        raise OnlyBacktestError(
            OnlyBacktestErrorPhase.EXECUTION,
            "BACKTEST_PORTFOLIO_PROFILE_UNSUPPORTED",
            profile.fingerprint,
        )
    return "FIXED_CAPITAL"


def _validate_risk_profile(profile: OnlyBacktestProfile) -> None:
    if dict(profile.semantics) != {"mandatory_system_rules": True, "optional_rules": []}:
        raise OnlyBacktestError(
            OnlyBacktestErrorPhase.EXECUTION,
            "BACKTEST_RISK_PROFILE_UNSUPPORTED",
            profile.fingerprint,
        )


def _execution_profile(profile: OnlyBacktestProfile) -> dict[str, object]:
    semantics = dict(profile.semantics)
    if semantics == {"broker_model": "VIRTUAL", "matching_policy": "NEXT_BAR"}:
        return {
            "broker_model": "VIRTUAL",
            "matching": {"type": "NEXT_BAR"},
            "slippage": {"type": "NONE"},
            "latency": {"submit_ns": 0, "acceptance_ns": 0, "fill_ns": 0, "cancel_ns": 0, "query_ns": 0},
            "broker_fee_contract": {
                "contract_id": "VIRTUAL_SIMULATION_ZERO_BROKER_FEES",
                "contract_version": "1",
            },
            "fee_reconciliation_policy": {
                "policy_id": "STANDARD_FEE_RECONCILIATION",
                "policy_version": "1",
            },
        }
    required = {
        "broker_model",
        "matching",
        "slippage",
        "latency",
        "broker_fee_contract",
        "fee_reconciliation_policy",
    }
    if set(semantics) != required or semantics["broker_model"] != "VIRTUAL":
        raise OnlyBacktestError(
            OnlyBacktestErrorPhase.EXECUTION,
            "BACKTEST_EXECUTION_PROFILE_UNSUPPORTED",
            profile.fingerprint,
        )
    return semantics


class OnlyEngineBacktestRuntimeExecutor:
    """Maps a verified Product plan into the existing Engine and Backtest Runtime."""

    def __init__(self, plans: OnlyBacktestEnginePlanBuilder) -> None:
        self._plans = plans

    def execute(self, run: OnlyBacktestRun) -> OnlyBacktestRuntimeExecutionResult:
        engine_config, clusters, services = self._plans.build(run)
        if not clusters:
            raise OnlyBacktestError(OnlyBacktestErrorPhase.EXECUTION, "BACKTEST_PLAN_EMPTY", run.run_id.value)
        engine = OnlyEngine(engine_config, services=services)
        for cluster in clusters:
            engine.add_cluster(cluster)
        result = engine.run()
        if result.status != "COMPLETED" or len(result.runtime_results) != 1:
            detail = "; ".join(result.failures) or "Engine did not produce exactly one Backtest Runtime result"
            raise OnlyBacktestError(OnlyBacktestErrorPhase.EXECUTION, "BACKTEST_ENGINE_FAILED", detail)
        runtime_result = result.runtime_results[0]
        result_fingerprint = getattr(runtime_result, "result_fingerprint", None)
        determinism_fingerprint = getattr(runtime_result, "determinism_fingerprint", None)
        to_dict = getattr(runtime_result, "to_dict", None)
        if (
            not isinstance(result_fingerprint, str)
            or not isinstance(determinism_fingerprint, str)
            or not callable(to_dict)
        ):
            raise OnlyBacktestError(
                OnlyBacktestErrorPhase.EXECUTION,
                "BACKTEST_RESULT_AUTHORITY_INVALID",
                run.run_id.value,
            )
        payload = only_canonical_json(to_dict()).encode("utf-8")
        return OnlyBacktestRuntimeExecutionResult(
            result_fingerprint,
            determinism_fingerprint,
            (("result.json", payload, "application/json"),),
        )


class OnlyBacktestWorkerOutcomeKind(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    CANCELLED = "CANCELLED"
    OWNERSHIP_LOST = "OWNERSHIP_LOST"


@dataclass(frozen=True, slots=True)
class OnlyBacktestWorkerOutcome:
    kind: OnlyBacktestWorkerOutcomeKind
    claim: OnlyBacktestExecutionClaim
    run: OnlyBacktestRun | None = None
    failure: OnlyBacktestRunFailure | None = None


class _LeaseControl:
    def __init__(
        self,
        store: OnlyBacktestExecutionStore,
        claim: OnlyBacktestExecutionClaim,
        policy: OnlyBacktestExecutionPolicy,
    ) -> None:
        self._store = store
        self._claim = claim
        self._policy = policy
        self._stop = Event()
        self._lost = Event()
        self._thread = Thread(target=self._run, name=f"backtest-lease-{claim.attempt.attempt_id.value}", daemon=True)

    @property
    def ownership_lost(self) -> bool:
        return self._lost.is_set()

    def __enter__(self) -> _LeaseControl:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._policy.heartbeat_interval.total_seconds()):
            try:
                self._store.heartbeat(self._claim, self._policy.lease_duration)
            except Exception:
                self._lost.set()
                return


class OnlyBacktestWorker:
    def __init__(
        self,
        *,
        worker_instance_id: OnlyBacktestWorkerInstanceId,
        store: OnlyBacktestExecutionStore,
        admission: OnlyBacktestAdmissionService,
        executor: OnlyBacktestRuntimeExecutor,
        evidence: OnlyBacktestEvidenceStore,
        policy: OnlyBacktestExecutionPolicy | None = None,
        lease_control_factory: Callable[
            [OnlyBacktestExecutionStore, OnlyBacktestExecutionClaim, OnlyBacktestExecutionPolicy], _LeaseControl
        ] = _LeaseControl,
    ) -> None:
        self.worker_instance_id = worker_instance_id
        self._store = store
        self._admission = admission
        self._executor = executor
        self._evidence = evidence
        self._policy = policy or OnlyBacktestExecutionPolicy()
        self._lease_control_factory = lease_control_factory
        self._reconciler = OnlyBacktestReconciler(store, evidence)

    def run_once(self) -> OnlyBacktestWorkerOutcome | None:
        if self._reconciler.run_once() is not None:
            return None
        self._store.expire_next(self._policy)
        if self._reconciler.run_once() is not None:
            return None
        claim = self._store.claim_next(
            self.worker_instance_id,
            OnlyBacktestAttemptId.new(),
            self._policy,
        )
        if claim is None:
            return None
        return self.execute_claim(claim)

    def execute_claim(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestWorkerOutcome:
        try:
            with self._lease_control_factory(self._store, claim, self._policy) as lease:
                current = self._store.load(claim.run.run_id)
                if current.state is OnlyBacktestRunState.CANCEL_REQUESTED:
                    return OnlyBacktestWorkerOutcome(
                        OnlyBacktestWorkerOutcomeKind.CANCELLED,
                        claim,
                        self._store.cancel(claim),
                    )
                admitted_binding = OnlyBacktestExecutionSemanticBinding.from_admission(
                    current.specification,
                    current.admission_resolution,
                )
                resolution = self._admission.resolve(current.specification)
                current_binding = OnlyBacktestExecutionSemanticBinding.from_admission(
                    current.specification,
                    resolution,
                )
                if current_binding != admitted_binding or resolution != current.admission_resolution:
                    raise OnlyBacktestError(
                        OnlyBacktestErrorPhase.EXECUTION,
                        "EXECUTION_SEMANTIC_DRIFT",
                        current.run_id.value,
                    )
                if lease.ownership_lost:
                    return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST, claim)
                executed = self._executor.execute(current)
                if lease.ownership_lost:
                    return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST, claim)
                manifest, artifacts = _manifest(current, executed)
                published = self._evidence.publish(manifest, artifacts)
                verified = self._evidence.load_verified(published.evidence_fingerprint)
                if verified != published:
                    raise OnlyBacktestError(
                        OnlyBacktestErrorPhase.EVIDENCE,
                        "BACKTEST_EVIDENCE_CORRUPT",
                        current.run_id.value,
                    )
                if lease.ownership_lost:
                    return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST, claim)
                completed = self._store.complete(
                    claim,
                    evidence_fingerprint=verified.evidence_fingerprint,
                    result_fingerprint=verified.result_fingerprint,
                    determinism_fingerprint=verified.determinism_fingerprint,
                )
                return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.COMPLETED, claim, completed)
        except OnlyBacktestStateConflictError:
            return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST, claim)
        except Exception as exc:
            failure = _failure(exc)
            try:
                run = self._store.fail(claim, failure, self._policy)
            except OnlyBacktestStateConflictError:
                return OnlyBacktestWorkerOutcome(OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST, claim, failure=failure)
            kind = (
                OnlyBacktestWorkerOutcomeKind.RETRY_PENDING
                if run.state is OnlyBacktestRunState.RUNNING
                else OnlyBacktestWorkerOutcomeKind.FAILED
            )
            return OnlyBacktestWorkerOutcome(kind, claim, run, failure)


class OnlyBacktestReconciler:
    def __init__(self, store: OnlyBacktestExecutionStore, evidence: OnlyBacktestEvidenceStore) -> None:
        self._store = store
        self._evidence = evidence

    def run_once(self) -> OnlyBacktestRun | None:
        run = self._store.load_reconciliation_candidate()
        if run is None:
            return None
        try:
            manifest = self._evidence.find_for_run(run.run_id.value)
        except ValueError:
            return self._store.reconcile_fail(
                run,
                OnlyBacktestRunFailure(
                    OnlyBacktestRunFailurePhase.EVIDENCE_COMMIT,
                    "BACKTEST_EVIDENCE_CORRUPT",
                    "Backtest Evidence failed verified recovery",
                ),
            )
        if manifest is None:
            if run.state is OnlyBacktestRunState.CANCEL_REQUESTED:
                return self._store.reconcile_cancel(run)
            return None
        if (
            manifest.specification_fingerprint != run.specification_fingerprint
            or manifest.admission_resolution_fingerprint != run.admission_resolution_fingerprint
            or manifest.strategy_fingerprint != run.admission_resolution.strategy_fingerprint
            or manifest.dataset_binding_fingerprint != run.admission_resolution.dataset_binding_fingerprint
        ):
            return self._store.reconcile_fail(
                run,
                OnlyBacktestRunFailure(
                    OnlyBacktestRunFailurePhase.EVIDENCE_COMMIT,
                    "BACKTEST_EVIDENCE_CORRUPT",
                    "Backtest Evidence provenance differs from durable admission",
                ),
            )
        return self._store.reconcile_complete(
            run,
            evidence_fingerprint=manifest.evidence_fingerprint,
            result_fingerprint=manifest.result_fingerprint,
            determinism_fingerprint=manifest.determinism_fingerprint,
        )


def _manifest(
    run: OnlyBacktestRun,
    result: OnlyBacktestRuntimeExecutionResult,
) -> tuple[OnlyBacktestEvidenceManifest, dict[str, bytes]]:
    artifacts = {name: payload for name, payload, _ in result.artifacts}
    entries = tuple(
        (name, hashlib.sha256(payload).hexdigest(), len(payload), media_type)
        for name, payload, media_type in result.artifacts
    )
    resolution = run.admission_resolution
    return (
        OnlyBacktestEvidenceManifest(
            backtest_run_id=run.run_id.value,
            specification_fingerprint=run.specification_fingerprint,
            admission_resolution_fingerprint=run.admission_resolution_fingerprint,
            strategy_fingerprint=resolution.strategy_fingerprint,
            dataset_binding_fingerprint=resolution.dataset_binding_fingerprint,
            base_dataset_snapshot_fingerprint=resolution.base_dataset_snapshot_fingerprint,
            market_product_composition_fingerprint=resolution.market_product_composition_fingerprint,
            portfolio_profile_fingerprint=resolution.portfolio_profile_fingerprint,
            risk_profile_fingerprint=resolution.risk_profile_fingerprint,
            execution_profile_fingerprint=resolution.execution_profile_fingerprint,
            kernel_semantics_version=resolution.kernel_semantics_version,
            implementation_fingerprints=resolution.implementation_fingerprints,
            result_fingerprint=result.result_fingerprint,
            determinism_fingerprint=result.determinism_fingerprint,
            artifacts=entries,
        ),
        artifacts,
    )


def _failure(exc: Exception) -> OnlyBacktestRunFailure:
    if isinstance(exc, OnlyBacktestError):
        phases = {
            OnlyBacktestErrorPhase.ADMISSION: OnlyBacktestRunFailurePhase.ADMISSION,
            OnlyBacktestErrorPhase.COMMAND: OnlyBacktestRunFailurePhase.OPERATIONAL,
            OnlyBacktestErrorPhase.OPERATIONAL: OnlyBacktestRunFailurePhase.OPERATIONAL,
            OnlyBacktestErrorPhase.EXECUTION: OnlyBacktestRunFailurePhase.EXECUTION,
            OnlyBacktestErrorPhase.EVIDENCE: OnlyBacktestRunFailurePhase.EVIDENCE_COMMIT,
        }
        phase = phases[exc.phase]
        return OnlyBacktestRunFailure(phase, exc.code, exc.detail)
    return OnlyBacktestRunFailure(
        OnlyBacktestRunFailurePhase.OPERATIONAL,
        "UNEXPECTED_WORKER_FAILURE",
        "Unexpected Backtest Worker failure",
    )


__all__ = [name for name in globals() if name.startswith("Only")]
