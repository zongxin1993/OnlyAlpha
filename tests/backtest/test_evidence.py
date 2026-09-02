import hashlib

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
        market_product_composition_fingerprint="e" * 64,
        kernel_semantics_version="kernel-v1",
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
