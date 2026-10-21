import hashlib
from dataclasses import replace

import pytest

from onlyalpha.backtest import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore


def _manifest() -> OnlyBacktestEvidenceManifest:
    data = b"canonical-result"
    return OnlyBacktestEvidenceManifest(
        backtest_run_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        specification_fingerprint="a" * 64,
        admission_resolution_fingerprint="b" * 64,
        strategy_fingerprint="c" * 64,
        dataset_binding_fingerprint="d" * 64,
        base_dataset_snapshot_fingerprint="2" * 64,
        market_product_composition_fingerprint="e" * 64,
        portfolio_profile_fingerprint="3" * 64,
        risk_profile_fingerprint="4" * 64,
        execution_profile_fingerprint="5" * 64,
        kernel_semantics_version="kernel-v1",
        implementation_fingerprints=("6" * 64,),
        result_fingerprint="f" * 64,
        determinism_fingerprint="1" * 64,
        artifacts=(("result.json", hashlib.sha256(data).hexdigest(), len(data), "application/json"),),
    )


def test_evidence_store_is_content_addressed_and_verifies_bytes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = _manifest()
    store = OnlyBacktestEvidenceStore(tmp_path)
    assert store.publish(manifest, {"result.json": b"canonical-result"}) == manifest
    assert store.load_verified(manifest.evidence_fingerprint) == manifest
    assert store.publish(manifest, {"result.json": b"canonical-result"}) == manifest

    (
        tmp_path
        / "backtest"
        / "evidence"
        / "sha256"
        / manifest.evidence_fingerprint[:2]
        / manifest.evidence_fingerprint
        / "result.json"
    ).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="CORRUPT"):
        store.load_verified(manifest.evidence_fingerprint)


@pytest.mark.parametrize("name", ("../result.json", "/result.json", "a/../../result.json", ".", ".."))
def test_evidence_rejects_unsafe_artifact_paths(name: str) -> None:
    manifest = _manifest()
    with pytest.raises(ValueError, match="PATH_INVALID"):
        replace(manifest, artifacts=((name, "a" * 64, 0, "application/json"),))


def test_native_result_cannot_be_certified_by_rehashed_ids_and_a_drain_boolean(tmp_path) -> None:
    import json
    from datetime import UTC, datetime

    from onlyalpha.backtest import OnlyBacktestQueryService
    from onlyalpha.backtest.errors import OnlyBacktestIntegrityError
    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy, OnlyBacktestRunState
    from onlyalpha.backtest.worker import OnlyBacktestRuntimeExecutionResult
    from onlyalpha.backtest.worker import _manifest as manifest_for
    from tests.backtest.test_worker import _run

    historical = _run(datetime(2026, 10, 21, tzinfo=UTC))
    specification = replace(
        historical.specification, schema_version=2, order_policy=OnlyBacktestLimitPolicy("1", "10", "11", "1", 1)
    )
    run = type(historical).queued(
        run_id=historical.run_id,
        specification=specification,
        admission_resolution=historical.admission_resolution,
        queued_at=historical.queued_at,
    )
    # Structurally linked IDs cannot authenticate a different/missing native
    # transcript, configuration, Generation or final seal.
    result = {"result_fingerprint": "5" * 64, "determinism_fingerprint": "6" * 64}
    runtime = {
        "schema_version": 1,
        "implementation": "RUST",
        "backtest_run_id": run.run_id.value,
        "specification_fingerprint": run.specification_fingerprint,
        "admission_resolution_fingerprint": run.admission_resolution_fingerprint,
        "strategy_fingerprint": run.specification.strategy_fingerprint,
        "dataset_binding_fingerprint": run.specification.dataset_binding_fingerprint,
        "result_fingerprint": "5" * 64,
        "runtime_generation_fingerprint": "f" * 64,
    }
    files = {
        "result.json": result,
        "runtime.json": runtime,
        "replay-proof.json": {"execution_result": result, "status": "COMPLETED", "drained": True},
    }
    executed = OnlyBacktestRuntimeExecutionResult(
        "5" * 64,
        "6" * 64,
        tuple((name, json.dumps(value).encode(), "application/json") for name, value in sorted(files.items())),
    )
    manifest, artifacts = manifest_for(run, executed)
    evidence = OnlyBacktestEvidenceStore(tmp_path)
    evidence.publish(manifest, artifacts)
    completed = replace(
        run,
        state=OnlyBacktestRunState.COMPLETED,
        revision=1,
        started_at=run.queued_at,
        finished_at=run.queued_at,
        evidence_fingerprint=manifest.evidence_fingerprint,
        result_fingerprint=manifest.result_fingerprint,
        determinism_fingerprint=manifest.determinism_fingerprint,
    )

    class Runs:
        def load(self, _):
            return completed

    with pytest.raises(OnlyBacktestIntegrityError, match="CORRUPT"):
        OnlyBacktestQueryService(Runs(), evidence).result(run.run_id)
