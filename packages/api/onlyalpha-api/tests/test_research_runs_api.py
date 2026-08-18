from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from onlyalpha_api import create_research_app
from onlyalpha_api.research.run_errors import run_error_response

from onlyalpha.research.artifact.errors import OnlyResearchArtifactStoreError
from onlyalpha.research.command import (
    OnlyResearchCommandService,
    OnlyResearchRunPageCursor,
    OnlyResearchRunQueryService,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmissionRecord,
)
from onlyalpha.research.run import (
    OnlyPostgresSchemaIncompatibleError,
    OnlyResearchRun,
    OnlyResearchRunAdmissionError,
    OnlyResearchRunAdmissionService,
    OnlyResearchRunId,
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunStoreUnavailableError,
)
from onlyalpha.research.specification import (
    OnlyResearchSpecificationError,
    OnlyResearchSpecificationPhase,
    OnlyResearchSpecificationResolver,
)
from tests.research.specification.support import registry, specification

NOW = datetime(2026, 8, 18, 1, 2, 3, tzinfo=UTC)
KEY = "00000000-0000-4000-8000-000000000501"


class _Reader:
    def load_verified(self, _fingerprint: str):  # type: ignore[no-untyped-def]
        raise OnlyResearchArtifactStoreError("RESEARCH_ARTIFACT_NOT_FOUND", "missing")


class _Dataset:
    def __init__(self) -> None:
        self.loads = 0

    def load_verified_table(self, _fingerprint: str) -> object:
        self.loads += 1
        return object()


class _Store:
    def __init__(self) -> None:
        self.runs: dict[OnlyResearchRunId, OnlyResearchRun] = {}
        self.submissions: dict[OnlyResearchSubmissionKey, OnlyResearchSubmissionRecord] = {}

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        self.runs[run.run_id] = run
        return run

    def find_submission(self, key: OnlyResearchSubmissionKey) -> OnlyResearchSubmissionRecord | None:
        return self.submissions.get(key)

    def create_queued_submission(
        self, run: OnlyResearchRun, key: OnlyResearchSubmissionKey, fingerprint: str
    ) -> OnlyResearchSubmissionRecord:
        existing = self.submissions.get(key)
        if existing is not None:
            return existing
        record = OnlyResearchSubmissionRecord(key, fingerprint, run.run_id)
        self.runs[run.run_id] = run
        self.submissions[key] = record
        return record

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        try:
            return self.runs[run_id]
        except KeyError as exc:
            raise OnlyResearchRunNotFoundError(run_id.value) from exc

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun:
        self.runs[previous.run_id] = transitioned
        return transitioned

    def list_recent(self, *, limit: int, after: OnlyResearchRunPageCursor | None = None) -> tuple[OnlyResearchRun, ...]:
        runs = sorted(self.runs.values(), key=lambda item: (item.queued_at, item.run_id), reverse=True)
        if after is not None:
            runs = [item for item in runs if (item.queued_at, item.run_id) < (after.queued_at, after.run_id)]
        return tuple(runs[:limit])


def _client():  # type: ignore[no-untyped-def]
    store, dataset = _Store(), _Dataset()
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=dataset,  # type: ignore[arg-type]
        run_store=store,  # type: ignore[arg-type]
        now_utc=lambda: NOW,
        run_id_factory=lambda: OnlyResearchRunId("00000000-0000-4000-8000-000000000510"),
    )
    command = OnlyResearchCommandService(admission=admission, store=store, now_utc=lambda: NOW)  # type: ignore[arg-type]
    query = OnlyResearchRunQueryService(store)  # type: ignore[arg-type]
    return dataset, store, TestClient(create_research_app(_Reader(), command, query))  # type: ignore[arg-type]


def test_submit_replay_get_list_and_cancel_contract() -> None:
    dataset, _, client = _client()
    payload = {"specification": dict(specification().to_dict())}
    created = client.post("/api/v2/research/runs", headers={"Idempotency-Key": KEY}, json=payload)
    assert created.status_code == 202
    body = created.json()
    run_id = body["run"]["run_id"]
    assert created.headers["location"] == f"/api/v2/research/runs/{run_id}"
    assert body["submission_disposition"] == "CREATED"
    assert body["run"]["revision"] == "0"
    assert body["run"]["specification"] == payload["specification"]

    replay = client.post("/api/v2/research/runs", headers={"Idempotency-Key": KEY}, json=payload)
    assert replay.status_code == 202
    assert replay.json()["submission_disposition"] == "REUSED"
    assert replay.json()["run"]["run_id"] == run_id
    assert dataset.loads == 1

    fetched = client.get(f"/api/v2/research/runs/{run_id}")
    listed = client.get("/api/v2/research/runs", params={"limit": 50})
    assert fetched.status_code == listed.status_code == 200
    assert listed.json()["runs"][0]["run_id"] == run_id
    assert "specification" not in listed.json()["runs"][0]

    cancelled = client.post(f"/api/v2/research/runs/{run_id}/cancellation")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"
    assert cancelled.json()["revision"] == "1"


def test_run_http_validation_and_errors_are_stable() -> None:
    _, _, client = _client()
    payload = {"specification": dict(specification().to_dict())}
    cases = (
        (client.post("/api/v2/research/runs", json=payload), 400, "RESEARCH_IDEMPOTENCY_KEY_INVALID"),
        (
            client.post("/api/v2/research/runs", headers={"Idempotency-Key": "bad"}, json=payload),
            400,
            "RESEARCH_IDEMPOTENCY_KEY_INVALID",
        ),
        (
            client.post(
                "/api/v2/research/runs",
                headers={"Idempotency-Key": KEY},
                json={**payload, "unknown": True},
            ),
            400,
            "RESEARCH_REQUEST_INVALID",
        ),
        (client.get("/api/v2/research/runs/not-a-uuid"), 400, "RESEARCH_RUN_ID_INVALID"),
        (
            client.get("/api/v2/research/runs/00000000-0000-4000-8000-000000000599"),
            404,
            "RESEARCH_RUN_NOT_FOUND",
        ),
        (client.get("/api/v2/research/runs", params={"limit": 0}), 400, "RESEARCH_RUN_PAGE_LIMIT_INVALID"),
    )
    for response, status, code in cases:
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert set(response.json()["error"]) == {"phase", "code", "detail"}


def test_full_route_methods_are_narrow_and_artifact_routes_remain_get_only() -> None:
    _, _, client = _client()
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert set(paths["/api/v2/research/runs"]) == {"get", "post"}
    assert set(paths["/api/v2/research/runs/{run_id}"]) == {"get"}
    assert set(paths["/api/v2/research/runs/{run_id}/cancellation"]) == {"post"}
    for path, operations in paths.items():
        if path.startswith("/api/v2/research/artifacts"):
            assert set(operations) == {"get"}
        assert not set(operations) & {"put", "patch", "delete"}


def test_run_error_mapper_covers_stable_admission_persistence_and_internal_classes() -> None:
    cases = (
        (OnlyResearchRunAdmissionError("missing", code="RESEARCH_DATASET_NOT_FOUND"), 404),
        (OnlyResearchRunAdmissionError("corrupt", code="RESEARCH_DATASET_CORRUPT"), 500),
        (OnlyResearchRunAdmissionError("invalid"), 400),
        (
            OnlyResearchSpecificationError(OnlyResearchSpecificationPhase.SCHEMA, "RESEARCH_SPEC_INVALID", "invalid"),
            400,
        ),
        (OnlyResearchRunStoreUnavailableError("down"), 503),
        (OnlyPostgresSchemaIncompatibleError("old"), 500),
        (OnlyResearchRunIntegrityError("corrupt"), 500),
        (RuntimeError("internal"), 500),
    )
    for error, expected_status in cases:
        status, body = run_error_response(error)
        assert status == expected_status
        assert body.error.code
        assert body.error.detail
