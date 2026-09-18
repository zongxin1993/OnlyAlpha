from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server import create_research_app
from onlyalpha_http_server.research.advisory_routes import create_advisory_router

from onlyalpha.application.product_boundary import only_compose_research_product_boundary
from onlyalpha.application.research_advisory import (
    OnlyGetResearchNearDuplicateAdvisoryV1,
    OnlyResearchAdvisoryAuthorityUnavailable,
    OnlyResearchAdvisoryInvariantViolation,
    OnlyResearchAdvisoryProjectionCorrupt,
    OnlyResearchAdvisoryRequestInvalid,
    OnlyResearchAdvisoryRevisionNotFound,
    OnlyResearchAdvisoryUnsupported,
    OnlyResearchNearDuplicateAdvisoryBundleV1,
    OnlyResearchNearDuplicateAdvisoryBundleV2,
    OnlyResearchNearDuplicateAdvisoryEntryV1,
    OnlyResearchNearDuplicateQueryService,
    only_load_research_near_duplicate_advisory_bundle,
)
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.kernel import OnlyAlphaKernelHost
from onlyalpha.kernel.command import OnlyUnsupportedProductCommand
from onlyalpha.kernel.query import OnlyProductQuery
from onlyalpha.research.evaluation.subject import (
    OnlyExactEvaluationIntentResolverV1,
    OnlyExactEvaluationIntentSubjectV1,
)
from onlyalpha.research.memory.advisory import (
    STRUCTURED_ALGORITHM_ID,
    STRUCTURED_ALGORITHM_VERSION,
    OnlyNearDuplicateQueryV1,
    OnlyNearDuplicateResultStatus,
    OnlyNearDuplicateResultV1,
    OnlyNearDuplicateThresholdPolicyV1,
    OnlyResearchAdvisorySourceRefV1,
    OnlyVerifiedResearchAdvisorySnapshotV1,
    only_build_research_advisory_index,
    only_build_research_advisory_representation,
)
from onlyalpha.research.memory.projector import OnlyExperimentMemoryProjectionV1
from onlyalpha.research.memory.source_manifest import MANDATORY_FAMILIES, OnlyExperimentMemorySourceCutManifestV1
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.source_cut import OnlySourceClosedCutV1
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.support import registry, scientific_specification, specification

SHA = "a" * 64
PROJECTION = "b" * 64
CUT = "c" * 64
V1_FIXTURE = Path(__file__).parents[2] / "test-data/contracts/research_near_duplicate_advisory_bundle_v1.json"


def _bundle() -> OnlyResearchNearDuplicateAdvisoryBundleV2:
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
    return OnlyResearchNearDuplicateAdvisoryBundleV2(
        SHA,
        PROJECTION,
        CUT,
        SHA,
        10,
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
    assert bundle.schema_version == 2
    assert OnlyResearchNearDuplicateAdvisoryBundleV2.from_dict(bundle.to_dict()) == bundle
    tampered = bundle.to_dict()
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="fingerprint"):
        OnlyResearchNearDuplicateAdvisoryBundleV2.from_dict(tampered)
    second = replace(bundle.entries[0], subject_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="ordered"):
        replace(bundle, entries=(bundle.entries[0], second))
    with pytest.raises(ValueError, match="duplicate"):
        replace(bundle, entries=(bundle.entries[0], replace(bundle.entries[0])))


def test_historical_v1_fixture_exact_load_and_round_trip() -> None:
    payload = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    bundle = OnlyResearchNearDuplicateAdvisoryBundleV1.from_dict(payload)
    current = _bundle()
    assert bundle.schema_version == 1
    assert current.schema_version == 2
    assert bundle.bundle_fingerprint != current.bundle_fingerprint
    assert set(bundle.to_dict()) == {
        "schema_version",
        "specification_fingerprint",
        "projection_revision",
        "source_cut_fingerprint",
        "retrieval_algorithm_id",
        "retrieval_algorithm_version",
        "threshold_policy",
        "entries",
        "bundle_fingerprint",
    }
    assert bundle.to_dict() == payload
    assert bundle.bundle_fingerprint == payload["bundle_fingerprint"]
    assert only_load_research_near_duplicate_advisory_bundle(payload) == bundle


def test_historical_v1_does_not_require_v2_relation_proof() -> None:
    payload = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    entry = dict(payload["entries"][0])
    entry["representation_fingerprint"] = "d" * 64
    payload["entries"] = [entry]
    payload.pop("bundle_fingerprint")
    payload["bundle_fingerprint"] = only_canonical_fingerprint(payload)

    bundle = OnlyResearchNearDuplicateAdvisoryBundleV1.from_dict(payload)
    assert bundle.entries[0].representation_fingerprint == "d" * 64


def test_versioned_loader_rejects_cross_version_shapes_and_unknown_schema() -> None:
    historical = json.loads(V1_FIXTURE.read_text(encoding="utf-8"))
    current = _bundle().to_dict()
    assert isinstance(
        only_load_research_near_duplicate_advisory_bundle(historical), OnlyResearchNearDuplicateAdvisoryBundleV1
    )
    assert isinstance(
        only_load_research_near_duplicate_advisory_bundle(current), OnlyResearchNearDuplicateAdvisoryBundleV2
    )

    historical_declared_v2 = {**historical, "schema_version": 2}
    with pytest.raises(ValueError):
        only_load_research_near_duplicate_advisory_bundle(historical_declared_v2)

    current_declared_v1 = {**current, "schema_version": 1}
    with pytest.raises(ValueError):
        only_load_research_near_duplicate_advisory_bundle(current_declared_v1)

    historical_with_v2_fields = {**historical, "index_build_revision": SHA, "requested_result_limit": 10}
    with pytest.raises(ValueError):
        only_load_research_near_duplicate_advisory_bundle(historical_with_v2_fields)

    for field in ("index_build_revision", "requested_result_limit"):
        missing = dict(current)
        missing.pop(field)
        with pytest.raises(ValueError):
            only_load_research_near_duplicate_advisory_bundle(missing)

    unknown = {**current, "schema_version": 99}
    with pytest.raises(ValueError, match="unsupported"):
        only_load_research_near_duplicate_advisory_bundle(unknown)


def _repack_bundle(payload: dict[str, object]) -> dict[str, object]:
    payload = dict(payload)
    payload.pop("bundle_fingerprint", None)
    payload["bundle_fingerprint"] = only_canonical_fingerprint(payload)
    return payload


def _repack_result(result: dict[str, object]) -> dict[str, object]:
    result = dict(result)
    result.pop("result_fingerprint", None)
    result["result_fingerprint"] = only_canonical_fingerprint(result)
    return result


@pytest.mark.parametrize("tamper", ("representation", "limit", "result_query", "index", "policy"))
def test_bundle_rejects_valid_but_mismatched_query_provenance(tamper: str) -> None:
    bundle = _bundle()
    payload = bundle.to_dict()
    entry = payload["entries"][0]
    assert isinstance(entry, dict)
    result = entry["result"]
    assert isinstance(result, dict)
    if tamper == "representation":
        entry["representation_fingerprint"] = "d" * 64
    elif tamper == "limit":
        payload["requested_result_limit"] = 9
    elif tamper == "result_query":
        result["query_fingerprint"] = "0" * 64
        entry["result"] = _repack_result(result)
    elif tamper == "index":
        other_query = OnlyNearDuplicateQueryV1(
            bundle.entries[0].representation_fingerprint,
            bundle.projection_revision,
            bundle.source_cut_fingerprint,
            "e" * 64,
            bundle.threshold_policy.policy_fingerprint,
            bundle.requested_result_limit,
        )
        result["query_fingerprint"] = other_query.query_fingerprint
        result["index_build_revision"] = "e" * 64
        entry["result"] = _repack_result(result)
    else:
        result["threshold_policy_fingerprint"] = "e" * 64
        entry["result"] = _repack_result(result)
    with pytest.raises(ValueError):
        OnlyResearchNearDuplicateAdvisoryBundleV2.from_dict(_repack_bundle(payload))


def test_bundle_rejects_a_result_from_another_representation() -> None:
    bundle = _bundle()
    payload = bundle.to_dict()
    entry = payload["entries"][0]
    assert isinstance(entry, dict)
    result = dict(entry["result"])
    policy = bundle.threshold_policy
    other_query = OnlyNearDuplicateQueryV1(
        "d" * 64,
        bundle.projection_revision,
        bundle.source_cut_fingerprint,
        bundle.index_build_revision,
        policy.policy_fingerprint,
        bundle.requested_result_limit,
    )
    result["query_fingerprint"] = other_query.query_fingerprint
    entry["result"] = _repack_result(result)
    with pytest.raises(ValueError):
        OnlyResearchNearDuplicateAdvisoryBundleV2.from_dict(_repack_bundle(payload))


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
        def get(self, _query: OnlyGetResearchNearDuplicateAdvisoryV1) -> OnlyResearchNearDuplicateAdvisoryBundleV2:
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
    with pytest.raises(OnlyResearchAdvisoryInvariantViolation, match="candidate graph is unavailable"):
        service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work"))
    assert builder.active_calls == 1
    with pytest.raises(OnlyResearchAdvisoryInvariantViolation, match="candidate graph is unavailable"):
        service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work", projection_revision=PROJECTION))
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

    class UnexpectedSnapshotBuilder(SnapshotBuilder):
        def load_active_snapshot_verified(self) -> object:
            raise TypeError("programmer error")

    unexpected_service = OnlyResearchNearDuplicateQueryService(
        specification_resolver=SpecificationResolver(),  # type: ignore[arg-type]
        subject_resolver=SubjectResolver(),  # type: ignore[arg-type]
        advisory_builder=UnexpectedSnapshotBuilder(),  # type: ignore[arg-type]
        threshold_policy=policy,
    )
    with pytest.raises(TypeError, match="programmer error"):
        unexpected_service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work"))

    class UnavailableSnapshotBuilder(SnapshotBuilder):
        def load_active_snapshot_verified(self) -> object:
            raise OnlyResearchAdvisoryAuthorityUnavailable("source down")

    unavailable_service = OnlyResearchNearDuplicateQueryService(
        specification_resolver=SpecificationResolver(),  # type: ignore[arg-type]
        subject_resolver=SubjectResolver(),  # type: ignore[arg-type]
        advisory_builder=UnavailableSnapshotBuilder(),  # type: ignore[arg-type]
        threshold_policy=policy,
    )
    with pytest.raises(OnlyResearchAdvisoryAuthorityUnavailable, match="source down"):
        unavailable_service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work"))


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
    assert response.json()["schema_version"] == 2
    assert response.json()["bundle_fingerprint"] == bundle.bundle_fingerprint
    assert "product_command_id" not in response.json()
    response_schema = app.openapi()["components"]["schemas"]["ResearchNearDuplicateAdvisoryResponseDto"]
    assert response_schema["properties"]["schema_version"]["const"] == 2


def test_real_specification_to_d1_to_http_vertical_is_read_only() -> None:
    spec = scientific_specification()
    specification_resolver = OnlyResearchSpecificationResolver(registry())
    resolution = specification_resolver.resolve(spec)
    evidence = OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution)
    runtime_fingerprint = "1" * 64
    catalog_fingerprint = "2" * 64

    class RuntimeAuthority:
        def require_work_binding(self, work_id: str) -> object:
            return SimpleNamespace(work_id=work_id, runtime_generation_fingerprint=runtime_fingerprint)

        def require_runtime_generation(self, fingerprint: str) -> object:
            assert fingerprint == runtime_fingerprint
            return SimpleNamespace(
                runtime_generation_fingerprint=runtime_fingerprint,
                catalog_generation_fingerprint=catalog_fingerprint,
            )

    class RuntimeResolution:
        def resolve(self, fingerprint: str, _specification: object) -> object:
            assert fingerprint == runtime_fingerprint
            return evidence

    subject_resolver = OnlyExactEvaluationIntentResolverV1(
        runtime_generations=RuntimeAuthority(),  # type: ignore[arg-type]
        runtime_resolution=RuntimeResolution(),  # type: ignore[arg-type]
    )
    subjects = subject_resolver.resolve_all(spec, runtime_work_id="work")
    assert len(subjects) == 1
    subject = subjects[0]
    candidate = next(
        item for item in resolution.candidates if item.candidate_fingerprint == subject.candidate_fingerprint
    )

    manifest = OnlyExperimentMemorySourceCutManifestV1.from_cuts(
        [OnlySourceClosedCutV1(family, 1, ()) for family in MANDATORY_FAMILIES]
    )
    projection = OnlyExperimentMemoryProjectionV1(manifest, ())
    historical = only_build_research_advisory_representation(
        subject=subject,
        graph=candidate.graph,
        specification=spec,
        source_ref=OnlyResearchAdvisorySourceRefV1("RESEARCH_RESULT", "result/1", "result-1", "3" * 64),
        projection_revision=projection.revision_fingerprint,
        source_cut_fingerprint=manifest.manifest_fingerprint,
    )
    index = only_build_research_advisory_index(
        projection.revision_fingerprint,
        manifest.manifest_fingerprint,
        (historical,),
    )
    snapshot = OnlyVerifiedResearchAdvisorySnapshotV1(
        projection,
        index.representations,
        index,
        {historical.source_ref: historical},
    )

    class SnapshotBuilder:
        def load_active_snapshot_verified(self) -> OnlyVerifiedResearchAdvisorySnapshotV1:
            return snapshot

        def load_snapshot_verified(self, revision: str) -> OnlyVerifiedResearchAdvisorySnapshotV1:
            assert revision == snapshot.projection_revision
            return snapshot

    policy = OnlyNearDuplicateThresholdPolicyV1("structured-default", "1", Decimal("0.5"), Decimal("0.8"), 10)
    service = OnlyResearchNearDuplicateQueryService(
        specification_resolver=specification_resolver,
        subject_resolver=subject_resolver,
        advisory_builder=SnapshotBuilder(),  # type: ignore[arg-type]
        threshold_policy=policy,
    )
    kernel = OnlyAlphaKernelHost()
    kernel.start()

    class Commands:
        def submit_research_run(self, *_args: object) -> None:
            raise AssertionError("advisory query must not create a Research Run")

        def request_research_run_cancellation(self, *_args: object) -> None:
            raise AssertionError("advisory query must not cancel a Research Run")

    class Queries:
        def get_run(self, *_args: object) -> None:
            raise AssertionError("advisory query must not read the Run authority")

        def list_runs(self, **_kwargs: object) -> None:
            raise AssertionError("advisory query must not list the Run authority")

    boundary = only_compose_research_product_boundary(
        admission=kernel,
        commands=Commands(),  # type: ignore[arg-type]
        queries=Queries(),  # type: ignore[arg-type]
        near_duplicate_queries=service,
    )
    app = FastAPI()
    app.include_router(create_advisory_router(boundary))
    response = TestClient(app).post(
        "/api/v2/research/advisory/near-duplicates",
        json={"specification": spec.to_dict(), "runtime_work_id": "work"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["entries"][0]["result"]["status"] == "ADVISORY_OK"
    assert payload["entries"][0]["result"]["matches"]
    assert payload["entries"][0]["result"]["query_fingerprint"]
    assert payload["entries"][0]["result"]["result_fingerprint"]
    assert (
        payload["bundle_fingerprint"]
        == service.get(OnlyGetResearchNearDuplicateAdvisoryV1(spec, "work")).bundle_fingerprint
    )
    assert "product_command_id" not in payload
    kernel.stop()


@pytest.mark.parametrize(
    ("error", "status"),
    (
        (OnlyResearchAdvisoryRequestInvalid("bad request"), 400),
        (OnlyResearchAdvisoryUnsupported("unsupported"), 400),
        (OnlyResearchAdvisoryRevisionNotFound("missing"), 404),
        (OnlyResearchAdvisoryAuthorityUnavailable("down"), 503),
        (OnlyResearchAdvisoryProjectionCorrupt("corrupt"), 500),
        (OnlyResearchAdvisoryInvariantViolation("invariant"), 500),
    ),
)
def test_advisory_http_error_mapping_preserves_failure_truth(error: Exception, status: int) -> None:
    class Queries:
        def dispatch(self, _query: object) -> object:
            raise error

    class ReadyProbe:
        def inspect(self) -> OnlyResearchReadiness:
            return OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ())

    app = create_research_app(
        reader=SimpleNamespace(),  # type: ignore[arg-type]
        product_boundary=SimpleNamespace(queries=Queries()),  # type: ignore[arg-type]
        calculation_registry=SimpleNamespace(),  # type: ignore[arg-type]
        definition_resolver=SimpleNamespace(universe_resolver=None),  # type: ignore[arg-type]
        readiness_probe=ReadyProbe(),  # type: ignore[arg-type]
        near_duplicate_advisory=object(),
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v2/research/advisory/near-duplicates",
        json={"specification": specification().to_dict(), "runtime_work_id": "work"},
    )
    assert response.status_code == status
    assert response.json()["code"] == error.code  # type: ignore[attr-defined]


def test_advisory_unexpected_value_error_is_not_a_client_error() -> None:
    class Queries:
        def dispatch(self, _query: object) -> object:
            raise ValueError("unexpected internal defect")

    class ReadyProbe:
        def inspect(self) -> OnlyResearchReadiness:
            return OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ())

    app = create_research_app(
        reader=SimpleNamespace(),  # type: ignore[arg-type]
        product_boundary=SimpleNamespace(queries=Queries()),  # type: ignore[arg-type]
        calculation_registry=SimpleNamespace(),  # type: ignore[arg-type]
        definition_resolver=SimpleNamespace(universe_resolver=None),  # type: ignore[arg-type]
        readiness_probe=ReadyProbe(),  # type: ignore[arg-type]
        near_duplicate_advisory=object(),
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v2/research/advisory/near-duplicates",
        json={"specification": specification().to_dict(), "runtime_work_id": "work"},
    )
    assert response.status_code == 500
