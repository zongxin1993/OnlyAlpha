"""Typed read-only projection from existing Research authorities into Search."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast

from onlyalpha.research.evaluation.summary.result import OnlyResearchSummaryStatisticsResult
from onlyalpha.research.evaluation.summary.scalar import (
    OnlyResearchSummaryScalar,
    OnlyResearchSummaryScalarStatus,
)
from onlyalpha.research.experiment import OnlySearchIterationPlanV1, OnlySearchIterationResultV1

from .errors import OnlyParameterSearchError
from .model import OnlyParameterGraphProposalV1, OnlyParameterSearchPolicyV1


class OnlyParameterIterationResultReader(Protocol):
    def load_iteration_result_verified(self, fingerprint: str) -> OnlySearchIterationResultV1: ...


class OnlyParameterIterationPlanReader(Protocol):
    def load_iteration_plan_verified(self, fingerprint: str) -> OnlySearchIterationPlanV1: ...


class OnlyParameterResearchResultReader(Protocol):
    def load_verified(self, locator_fingerprint: str) -> OnlyParameterResearchResultValue: ...


class OnlyParameterStatisticsResultReader(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyParameterStatisticsResultValue: ...


class OnlyParameterResearchResultValue(Protocol):
    @property
    def manifest(self) -> object: ...


class OnlyParameterStatisticsResultValue(Protocol):
    @property
    def manifest(self) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlyParameterResearchEvidenceV1:
    """Ephemeral typed view; numeric facts remain owned by Research Statistics."""

    iteration_result_fingerprint: str
    proposal: OnlyParameterGraphProposalV1
    metric_scalars: Mapping[str, OnlyResearchSummaryScalar]
    research_attempted: bool
    available: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_scalars", MappingProxyType(dict(self.metric_scalars)))


class OnlyParameterResearchEvidenceReader:
    def __init__(
        self,
        *,
        iteration_results: OnlyParameterIterationResultReader,
        iteration_plans: OnlyParameterIterationPlanReader,
        research_results: OnlyParameterResearchResultReader,
        statistics_results: OnlyParameterStatisticsResultReader,
    ) -> None:
        self._iterations = iteration_results
        self._plans = iteration_plans
        self._research = research_results
        self._statistics = statistics_results

    def load_required(
        self,
        *,
        iteration_result_fingerprint: str,
        proposal: OnlyParameterGraphProposalV1,
        policy: OnlyParameterSearchPolicyV1,
    ) -> OnlyParameterResearchEvidenceV1:
        try:
            iteration = self._iterations.load_iteration_result_verified(iteration_result_fingerprint)
            if iteration.iteration_result_fingerprint != iteration_result_fingerprint:
                raise ValueError("Iteration Result identity differs")
            plan = self._plans.load_iteration_plan_verified(iteration.iteration_plan_fingerprint)
            if (
                plan.iteration_plan_fingerprint != iteration.iteration_plan_fingerprint
                or plan.proposal_fingerprint != proposal.proposal_fingerprint
            ):
                raise ValueError("Iteration Result/Plan/Proposal identity differs")
            reference = iteration.research_result_reference
            if reference is None:
                if iteration.research_attempted:
                    return OnlyParameterResearchEvidenceV1(iteration_result_fingerprint, proposal, {}, True, False)
                raise OnlyParameterSearchError("MISSING_REQUIRED_EVIDENCE", iteration_result_fingerprint)
            research = self._research.load_verified(reference.locator_fingerprint)
            manifest = cast(Any, research.manifest)
            if manifest.research_result_fingerprint != reference.result_fingerprint:
                raise ValueError("Research Result identity differs")
            scalars: dict[str, OnlyResearchSummaryScalar] = {}
            for item in manifest.statistics_results:
                result = self._statistics.load_verified(item.statistics_fingerprint)
                result_manifest = cast(Any, result.manifest)
                if result_manifest.statistics_result_fingerprint != item.statistics_result_fingerprint:
                    raise ValueError("Statistics Result identity differs")
                if not isinstance(result, OnlyResearchSummaryStatisticsResult):
                    continue
                for scalar in _walk_scalars(result.summary):
                    existing = scalars.get(scalar.metric_id)
                    if existing is not None and existing != scalar:
                        raise ValueError("duplicate metric identity has conflicting values")
                    scalars[scalar.metric_id] = scalar
            missing = set(policy.required_metric_ids) - set(scalars)
            if missing:
                raise OnlyParameterSearchError("MISSING_REQUIRED_EVIDENCE", ",".join(sorted(missing)))
            if any(
                scalars[metric_id].status is not OnlyResearchSummaryScalarStatus.VALID
                for metric_id in policy.required_metric_ids
            ):
                return OnlyParameterResearchEvidenceV1(iteration_result_fingerprint, proposal, scalars, True, False)
            return OnlyParameterResearchEvidenceV1(iteration_result_fingerprint, proposal, scalars, True, True)
        except OnlyParameterSearchError:
            raise
        except Exception as exc:
            raise OnlyParameterSearchError("CORRUPT_REFERENCE", iteration_result_fingerprint) from exc


def _walk_scalars(value: object) -> tuple[OnlyResearchSummaryScalar, ...]:
    if isinstance(value, OnlyResearchSummaryScalar):
        return (value,)
    if isinstance(value, tuple):
        return tuple(item for value_item in value for item in _walk_scalars(value_item))
    if is_dataclass(value):
        return tuple(item for field in fields(value) for item in _walk_scalars(getattr(value, field.name)))
    return ()


__all__ = [name for name in globals() if name.startswith("OnlyParameter")]
