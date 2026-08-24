"""Official operator composition for Strategy Freeze and Promotion products."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.persistence.postgres.strategy_store import OnlyPostgresStrategyStore
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.dataset import OnlyVerifiedResearchDataset
from onlyalpha.research.operations.deployment import (
    OnlyResearchDeploymentError,
    OnlyResearchDeploymentErrorCode,
    OnlyResearchSemanticStoreId,
    OnlyResearchSemanticStoreIdentity,
)
from onlyalpha.research.result.result import OnlyResearchResult
from onlyalpha.research.run import OnlyResearchRun, OnlyResearchRunId
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.admission import OnlyStrategyTradingAdmissionService
from onlyalpha.strategy.equivalence import OnlyCalculationEquivalenceEvidenceStore
from onlyalpha.strategy.freeze import (
    OnlyStrategyFreezeOutcome,
    OnlyStrategyFreezeRequest,
    OnlyStrategyFreezeService,
)
from onlyalpha.strategy.promotion import (
    OnlyStrategyPromotionDecision,
    OnlyStrategyPromotionRecord,
    OnlyStrategyPromotionService,
    OnlyStrategyPromotionStage,
)
from onlyalpha.strategy.store import OnlyStrategyRevisionStore


class _ResearchRuns(Protocol):
    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun: ...


class _ResearchResults(Protocol):
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchResult: ...


class _CalculationResults(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class _Datasets(Protocol):
    def load_verified_table(self, snapshot_fingerprint: str) -> OnlyVerifiedResearchDataset: ...


class OnlyStrategyFreezeApplicationService:
    """Single product operation; callers provide only exact Candidate Freeze intent."""

    def __init__(self, service: OnlyStrategyFreezeService) -> None:
        self._service = service

    @classmethod
    def compose(
        cls,
        *,
        semantic_root: Path,
        postgres_dsn: str,
        semantic_namespace_id: OnlyResearchSemanticStoreId,
        runs: _ResearchRuns,
        research_results: _ResearchResults,
        calculation_results: _CalculationResults,
        datasets: _Datasets,
        specification_resolver: OnlyResearchSpecificationResolver,
        calculations: OnlyCalculationRegistry,
        audit_time: Callable[[], datetime],
    ) -> OnlyStrategyFreezeApplicationService:
        _assert_local_namespace(semantic_root, semantic_namespace_id)
        only_register_trading_predicate_primitives(calculations)
        catalog = OnlyPostgresStrategyStore(postgres_dsn, semantic_namespace_id)
        catalog.assert_namespace()
        evidence = OnlyCalculationEquivalenceEvidenceStore(semantic_root)
        return cls(
            OnlyStrategyFreezeService(
                runs=runs,
                research_results=research_results,
                calculation_results=calculation_results,
                datasets=datasets,
                specification_resolver=specification_resolver,
                admission=OnlyStrategyTradingAdmissionService(calculations, evidence),
                strategies=OnlyStrategyRevisionStore(semantic_root),
                catalog=catalog,
                audit_time=audit_time,
            )
        )

    def freeze(self, request: OnlyStrategyFreezeRequest) -> OnlyStrategyFreezeOutcome:
        return self._service.freeze(request)


class OnlyStrategyPromotionApplicationService:
    """Single product operation over verified Revision and predecessor-chain authorities."""

    def __init__(self, service: OnlyStrategyPromotionService) -> None:
        self._service = service

    @classmethod
    def compose(
        cls,
        *,
        semantic_root: Path,
        postgres_dsn: str,
        semantic_namespace_id: OnlyResearchSemanticStoreId,
        audit_time: Callable[[], datetime],
    ) -> OnlyStrategyPromotionApplicationService:
        _assert_local_namespace(semantic_root, semantic_namespace_id)
        ledger = OnlyPostgresStrategyStore(postgres_dsn, semantic_namespace_id)
        ledger.assert_namespace()
        return cls(
            OnlyStrategyPromotionService(
                OnlyStrategyRevisionStore(semantic_root),
                ledger,
                audit_time,
            )
        )

    def current_stage(self, strategy_fingerprint: str) -> OnlyStrategyPromotionStage:
        return self._service.current_stage(strategy_fingerprint)

    def promote(
        self,
        *,
        strategy_fingerprint: str,
        to_stage: OnlyStrategyPromotionStage,
        evidence_fingerprints: tuple[str, ...],
        decision: OnlyStrategyPromotionDecision,
        reason: str,
        actor: str,
    ) -> OnlyStrategyPromotionRecord:
        return self._service.record(
            strategy_fingerprint=strategy_fingerprint,
            to_stage=to_stage,
            evidence_fingerprints=evidence_fingerprints,
            decision=decision,
            reason=reason,
            actor=actor,
        )


def _assert_local_namespace(
    semantic_root: Path,
    expected: OnlyResearchSemanticStoreId,
) -> None:
    if OnlyResearchSemanticStoreIdentity(semantic_root).load_verified() != expected:
        raise OnlyResearchDeploymentError(OnlyResearchDeploymentErrorCode.SEMANTIC_STORE_IDENTITY_MISMATCH)


__all__ = ["OnlyStrategyFreezeApplicationService", "OnlyStrategyPromotionApplicationService"]
