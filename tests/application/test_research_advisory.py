from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.research.advisory_routes import create_advisory_router

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.application.research_advisory import (
    OnlyGetResearchNearDuplicateAdvisoryV1,
    OnlyResearchNearDuplicateAdvisoryBundleV1,
    OnlyResearchNearDuplicateAdvisoryEntryV1,
    OnlyResearchNearDuplicateQueryService,
)
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.kernel.command import OnlyUnsupportedProductCommand
from onlyalpha.kernel.query import OnlyProductQuery
from onlyalpha.research.evaluation.subject import OnlyExactEvaluationIntentSubjectV1
from onlyalpha.research.memory.advisory import (
    STRUCTURED_ALGORITHM_ID,
    STRUCTURED_ALGORITHM_VERSION,
    OnlyNearDuplicateQueryV1,
    OnlyNearDuplicateResultStatus,
    OnlyNearDuplicateResultV1,
    OnlyNearDuplicateThresholdPolicyV1,
)
from tests.research.specification.support import specification

SHA = "a" * 64
PROJECTION = "b" * 64
CUT = "c" * 64


def _bundle() -> OnlyResearchNearDuplicateAdvisoryBundleV1:
    policy = OnlyNearDuplicateThresholdPolicyV1("structured-default", "1", Decimal("0.5"), Decimal("0.8"), 10)
    query = OnlyNearDuplicateQueryV1(SHA, PROJECTION, CUT, SHA, policy.policy_fingerprint, 10)
    result = OnlyNearDuplicateResultV1(
        query.query_fingerprint,
        PROJECTION,
        CUT,
        1,
        STRUCTURED_ALGORITHM_ID,
        STRUCTURED_ALGORITHM_VERSION,
        policy.policy_id,
        policy.policy_version,
        policy.policy_fingerprint,
        SHA,
        OnlyNearDuplicateResultStatus.ADVISORY_OK,
        (),
    )
    return OnlyResearchNearDuplicateAdvisoryBundleV1(
        SHA,
        PROJECTION,
        CUT,
        STRUCTURED_ALGORITHM_ID,
        STRUCTURED_ALGORITHM_VERSION,
        policy,
        (OnlyResearchNearDuplicateAdvisoryEntryV1(SHA, SHA, result),),
    )


def test_query_is_read_only_and_does_not_accept_scientific_identity() -> None:
    assert issubclass(OnlyGetResearchNearDuplicateAdvisoryV1, OnlyProductQuery)
    assert "subject_fingerprint" not in OnlyGetResearchNearDuplicateAdvisoryV1.__annotations__
    assert "representation_fingerprint" not in OnlyGetResearchNearDuplicateAdvisoryV1.__annotations__


def test_bundle_round_trip_and_tamper_detection() -> None:
    bundle = _bundle()
    assert OnlyResearchNearDuplicateAdvisoryBundleV1.from_dict(bundle.to_dict()) == bundle
    tampered = bundle.to_dict()
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        OnlyResearchNearDuplicateAdvisoryBundleV1.from_dict(tampered)
    second = replace(bundle.entries[0], subject_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="ordered"):
        replace(bundle, entries=(bundle.entries[0], second))
    with pytest.raises(ValueError, match="duplicate"):
        replace(bundle, entries=(bundle.entries[0], replace(bundle.entries[0])))


def test_product_boundary_registers_query_without_command() -> None:
    bundle = _bundle()
    kernel = OnlyAlphaKernelHost()
    kernel.start()

    class Commands:
        def submit_research_run(self, *_args: object) -> None:
            raise AssertionError

        def request_research_run_cancellation(self, *_args: object) -> None:
            raise AssertionError

    class Queries:
        def get_run(self, *_args: object) -> None:
            raise AssertionError

        def list_runs(self, **_kwargs: object) -> None:
            raise AssertionError

    class Advisory:
        def get(self, _query: OnlyGetResearchNearDuplicateAdvisoryV1) -> OnlyResearchNearDuplicateAdvisoryBundleV1:
            return bundle

    boundary = only_compose_research_product_boundary(
        admission=kernel,
        commands=Commands(),  # type: ignore[arg-type]
        queries=Queries(),  # type: ignore[arg-type]
        near_duplicate_queries=Advisory(),  # type: ignore[arg-type]
    )
    query = OnlyGetResearchNearDuplicateAdvisoryV1(specification(), runtime_work_id="existing-work")
    assert boundary.queries.dispatch(query) == bundle
    with pytest.raises(OnlyUnsupportedProductCommand):
        boundary.commands.dispatch(query)  # type: ignore[arg-type]


def test_service_keeps_all_subjects_and_loads_one_snapshot_per_request() -> None:
    spec = specification()
    policy = OnlyNearDuplicateThresholdPolicyV1("structured-default", "1", Decimal("0.5"), Decimal("0.8"), 10)

    def subject(candidate: str) -> OnlyExactEvaluationIntentSubjectV1:
        return OnlyExactEvaluationIntentSubjectV1(
            SHA,
            "d" * 64,
            "value",
            candidate,
            spec.dataset_snapshot_fingerprint,
            spec.specification_fingerprint,
            "e" * 64,
            ("f" * 64,),
            "1" * 64,
            "2" * 64,
            None,
        )

    subjects = tuple(sorted((subject("3" * 64), subject("4" * 64)), key=lambda item: item.subject_fingerprint))

    class SubjectResolver:
        def resolve_all(self, *_args: object, **_kwargs: object) -> tuple[OnlyExactEvaluationIntentSubjectV1, ...]:
            return subjects

    class SpecificationResolver:
        def resolve(self, _specification: object) -> object:
            return SimpleNamespace(candidates=())

    class SnapshotBuilder:
        def __init__(self) -> None:
            self.active_calls = 0
            self.pinned_calls: list[str] = []
            self.snapshot = SimpleNamespace(
                projection_revision=PROJECTION,
                source_cut_fingerprint=CUT,
                index_build_revision=SHA,
            )

        def load_active_snapshot_verified(self) -> object:
            self.active_calls += 1
            return self.snapshot

        def load_snapshot_verified(self, revision: str) -> object:
            self.pinned_calls.append(revision)
            return self.snapshot

    builder = SnapshotBuilder()
    service = OnlyResearchNearDuplicateQueryService(
        specification_resolver=SpecificationResolver(),  # type: ignore[arg-type]
        subject_resolver=SubjectResolver(),  # type: ignore[arg-type]
        advisory_builder=builder,  # type: ignore[arg-type]
        threshold_policy=policy,
    )
    active = service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work"))
    assert len(active.entries) == 2
    assert [item.subject_fingerprint for item in active.entries] == sorted(
        item.subject_fingerprint for item in active.entries
    )
    assert {item.result.status for item in active.entries} == {OnlyNearDuplicateResultStatus.ADVISORY_UNAVAILABLE}
    assert builder.active_calls == 1
    pinned = service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work", projection_revision=PROJECTION))
    assert pinned.projection_revision == PROJECTION
    assert builder.active_calls == 1
    assert builder.pinned_calls == [PROJECTION]

    class NoFallbackBuilder(SnapshotBuilder):
        def load_snapshot_verified(self, revision: str) -> object:
            self.pinned_calls.append(revision)
            raise ValueError("pinned revision is corrupt")

    no_fallback = NoFallbackBuilder()
    no_fallback_service = OnlyResearchNearDuplicateQueryService(
        specification_resolver=SpecificationResolver(),  # type: ignore[arg-type]
        subject_resolver=SubjectResolver(),  # type: ignore[arg-type]
        advisory_builder=no_fallback,  # type: ignore[arg-type]
        threshold_policy=policy,
    )
    with pytest.raises(ValueError, match="corrupt"):
        no_fallback_service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work", PROJECTION))
    assert no_fallback.active_calls == 0


def test_http_route_dispatches_only_the_product_query_contract() -> None:
    bundle = _bundle()

    class Queries:
        def dispatch(self, query: object) -> object:
            assert isinstance(query, OnlyGetResearchNearDuplicateAdvisoryV1)
            return bundle

    app = FastAPI()
    app.include_router(create_advisory_router(SimpleNamespace(queries=Queries())))
    response = TestClient(app).post(
        "/api/v2/research/advisory/near-duplicates",
        json={"specification": specification().to_dict(), "runtime_work_id": "work"},
    )
    assert response.status_code == 200
    assert response.json()["bundle_fingerprint"] == bundle.bundle_fingerprint
    assert "product_command_id" not in response.json()
