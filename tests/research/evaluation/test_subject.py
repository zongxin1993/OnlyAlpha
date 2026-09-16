from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from onlyalpha.research.evaluation import (
    OnlyExactEvaluationIntentResolverV1,
    OnlyExactEvaluationIntentSubjectV1,
    OnlyResearchEvaluationError,
)
from onlyalpha.research.memory.query import (
    OnlyExactEvaluationHistorySelectorV1,
    OnlyExactSemanticHistorySelectorV1,
    OnlyExactStatisticsReferenceV1,
)
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.specification import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.research.sweep.definition import (
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
)
from tests.research.specification.support import registry, scientific_specification, specification
from tests.runtime_generation_support import OnlyTestRuntimeGenerationAuthority


def _scientific(*, dataset: str = "a" * 64, swept: bool = False) -> OnlyResearchSpecification:
    base = scientific_specification(dataset)
    calculations = base.calculations
    if swept:
        feature, target = calculations
        feature = replace(
            feature,
            sweep_dimensions=(
                OnlyResearchSweepParameterDimension(
                    OnlyResearchSweepParameterTarget("short", "period"),
                    (1, 3),
                ),
            ),
        )
        calculations = feature, target
    return replace(base, calculations=calculations)


class _RuntimeResolution:
    def __init__(self) -> None:
        self._resolver = OnlyResearchSpecificationResolver(registry())

    def resolve(self, runtime_generation_fingerprint, candidate):  # type: ignore[no-untyped-def]
        assert runtime_generation_fingerprint == "f" * 64
        return OnlyResearchAdmissionResolutionEvidence.from_resolution(self._resolver.resolve(candidate))


def _provenance(locator: str) -> OnlyResearchAuthoringProvenance:
    values = {
        "experiment_id": "exp-" + "1" * 24,
        "source_repository": "private-alpha",
        "source_revision": "2" * 40,
        "source_tree": "3" * 40,
        "candidate_provider_id": "private.factor",
        "candidate_provider_version": "1",
        "candidate_provider_content_fingerprint": "4" * 64,
        "catalog_generation_fingerprint": "e" * 64,
    }
    return OnlyResearchAuthoringProvenance(
        1,
        values["experiment_id"],
        values["source_repository"],
        values["source_revision"],
        values["source_tree"],
        values["candidate_provider_id"],
        values["candidate_provider_version"],
        values["candidate_provider_content_fingerprint"],
        values["catalog_generation_fingerprint"],
        only_research_execution_generation_fingerprint(**values),
        locator,
    )


class _Authoring:
    def __init__(self, provenance: OnlyResearchAuthoringProvenance) -> None:
        self.provenance = provenance

    def load_descriptor_verified(self, fingerprint: str) -> dict[str, object]:
        assert fingerprint == self.provenance.execution_generation_fingerprint
        return {
            "execution_generation_fingerprint": fingerprint,
            "provenance": self.provenance.identity_dict(),
        }


def _resolve(specification_value: OnlyResearchSpecification):
    runtime = OnlyTestRuntimeGenerationAuthority()
    runtime.bind_new_work("work", actor="test", occurred_at=object())
    resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime,
        runtime_resolution=_RuntimeResolution(),
    )
    return resolver.resolve(specification_value, runtime_work_id="work")


def test_real_scientific_intent_resolves_deterministically_across_fresh_resolvers() -> None:
    first = _resolve(_scientific())
    second = _resolve(OnlyResearchSpecification.from_dict(_scientific().to_dict()))

    assert first == second
    assert OnlyExactEvaluationIntentSubjectV1.from_dict(first.to_dict()) == first
    assert first.subject_fingerprint == second.subject_fingerprint
    assert first.statistics_fingerprints == tuple(sorted(first.statistics_fingerprints))


def test_subject_fingerprint_is_stable_in_a_fresh_process() -> None:
    subject = _resolve(_scientific())
    script = """
import json, sys
from onlyalpha.research.evaluation import OnlyExactEvaluationIntentSubjectV1
print(OnlyExactEvaluationIntentSubjectV1.from_dict(json.load(sys.stdin)).subject_fingerprint)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(subject.to_dict()),
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == subject.subject_fingerprint


def test_auxiliary_published_series_does_not_make_the_evaluated_factor_output_ambiguous() -> None:
    scientific = _scientific()
    assert scientific.evidence is not None
    with_auxiliary = replace(
        scientific,
        evidence=OnlyResearchScientificEvidenceSpec(
            scientific.evidence.candidate_calculation_id,
            (
                *scientific.evidence.published_series,
                OnlyResearchSeriesSelector("feature", "short", "value"),
            ),
        ),
    )

    assert _resolve(with_auxiliary).output_name == "factor_value"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("graph_fingerprint", "0" * 64),
        ("candidate_node_fingerprint", "1" * 64),
        ("output_name", "other"),
        ("candidate_fingerprint", "2" * 64),
        ("dataset_snapshot_fingerprint", "3" * 64),
        ("specification_fingerprint", "4" * 64),
        ("result_plan_fingerprint", "5" * 64),
        ("statistics_fingerprints", ("6" * 64,)),
        ("catalog_generation_fingerprint", "7" * 64),
        ("runtime_generation_fingerprint", "8" * 64),
        ("authoring_generation_fingerprint", "9" * 64),
    ],
)
def test_every_subject_dimension_changes_the_subject_fingerprint(field: str, value: object) -> None:
    subject = _resolve(_scientific())
    assert replace(subject, **{field: value}).subject_fingerprint != subject.subject_fingerprint


def test_post_run_result_and_search_context_do_not_redefine_intent_subject() -> None:
    subject = _resolve(_scientific())
    semantic = OnlyExactSemanticHistorySelectorV1(
        subject.graph_fingerprint,
        subject.candidate_node_fingerprint,
        subject.output_name,
    )

    def selector(result: str, search: str | None) -> OnlyExactEvaluationHistorySelectorV1:
        return OnlyExactEvaluationHistorySelectorV1(
            semantic,
            subject.candidate_fingerprint,
            subject.dataset_snapshot_fingerprint,
            subject.specification_fingerprint,
            subject.result_plan_fingerprint,
            subject.catalog_generation_fingerprint,
            subject.runtime_generation_fingerprint,
            subject.authoring_generation_fingerprint,
            tuple(OnlyExactStatisticsReferenceV1(item, result) for item in subject.statistics_fingerprints),
            search,
        )

    assert selector("a" * 64, "b" * 64).intent_subject == selector("c" * 64, None).intent_subject == subject


def test_physical_authoring_locator_is_not_subject_identity() -> None:
    first_provenance = _provenance("/first/path")
    second_provenance = _provenance("/other/path")
    runtime = OnlyTestRuntimeGenerationAuthority()
    runtime.bind_new_work("work", actor="test", occurred_at=object())
    resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime,
        runtime_resolution=_RuntimeResolution(),
        authoring_generations=_Authoring(first_provenance),
    )

    first = resolver.resolve(_scientific(), runtime_work_id="work", authoring_provenance=first_provenance)
    second = resolver.resolve(_scientific(), runtime_work_id="work", authoring_provenance=second_provenance)

    assert first == second


def test_ambiguous_candidate_and_missing_runtime_authority_fail_closed() -> None:
    swept = _scientific(swept=True)
    runtime = OnlyTestRuntimeGenerationAuthority()
    runtime.bind_new_work("work", actor="test", occurred_at=object())
    resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime,
        runtime_resolution=_RuntimeResolution(),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="EVALUATION_SUBJECT_AMBIGUOUS"):
        resolver.resolve(swept, runtime_work_id="work")
    subjects = resolver.resolve_all(swept, runtime_work_id="work")
    assert len(subjects) == 2
    assert subjects == tuple(sorted(subjects, key=lambda item: item.candidate_fingerprint))

    runtime = OnlyTestRuntimeGenerationAuthority()
    resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime,
        runtime_resolution=_RuntimeResolution(),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="EVALUATION_SUBJECT_AUTHORITY_MISSING"):
        resolver.resolve(_scientific(), runtime_work_id="missing")


def test_unsupported_specification_and_corrupt_resolution_authority_fail_closed() -> None:
    with pytest.raises(OnlyResearchEvaluationError, match="EVALUATION_SUBJECT_SCHEMA_UNSUPPORTED"):
        _resolve(specification())

    class _CorruptResolution:
        def resolve(self, runtime_generation_fingerprint, candidate):  # type: ignore[no-untyped-def]
            return object()

    runtime = OnlyTestRuntimeGenerationAuthority()
    runtime.bind_new_work("work", actor="test", occurred_at=object())
    resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=runtime,
        runtime_resolution=_CorruptResolution(),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="EVALUATION_SUBJECT_AUTHORITY_CORRUPT"):
        resolver.resolve(_scientific(), runtime_work_id="work")
