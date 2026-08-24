import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from onlyalpha.domain.enums import OnlyAggregationSource
from onlyalpha.strategy import OnlyStrategyStoreError
from onlyalpha.strategy.store import OnlyStrategyRevisionStore
from tests.strategy.p9_support import p9_strategy_case


def test_strategy_store_commit_load_exists_and_concurrent_reuse(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")

    with ThreadPoolExecutor(max_workers=4) as executor:
        committed = tuple(executor.map(store.commit, (revision,) * 8))

    assert all(item == revision for item in committed)
    assert store.exists(str(revision.strategy_fingerprint))
    assert store.load_verified(str(revision.strategy_fingerprint)) == revision


@pytest.mark.parametrize("corruption", ["manifest", "unexpected", "path", "symlink"])
def test_strategy_store_fails_closed_on_corruption(tmp_path, corruption) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(revision)
    fingerprint = str(revision.strategy_fingerprint)
    target = tmp_path / "semantic" / "strategy" / "revisions" / "sha256" / fingerprint[:2] / fingerprint
    manifest = target / "manifest.json"
    if corruption == "manifest":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["revision"]["strategy_fingerprint"] = "0" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    elif corruption == "unexpected":
        (target / "extra").write_text("x", encoding="utf-8")
    elif corruption == "path":
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["strategy_fingerprint"] = "0" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    else:
        manifest.unlink()
        manifest.symlink_to(tmp_path / "missing")

    with pytest.raises(OnlyStrategyStoreError) as error:
        store.load_verified(fingerprint)
    assert error.value.code == "STRATEGY_CORRUPT"


def test_strategy_store_detects_deterministic_conflict_without_overwrite(tmp_path, monkeypatch) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    store = OnlyStrategyRevisionStore(tmp_path / "semantic")
    store.commit(revision)
    conflicting = replace(
        revision,
        market_input_contract=replace(
            revision.market_input_contract,
            aggregation_source=OnlyAggregationSource.INTERNAL,
        ),
    )
    monkeypatch.setattr(store, "load_verified", lambda fingerprint: conflicting)

    with pytest.raises(OnlyStrategyStoreError) as error:
        store.commit(revision)
    assert error.value.code == "DETERMINISTIC_STRATEGY_CONFLICT"


def test_strategy_store_failed_publication_leaves_no_target_or_staging_residue(tmp_path, monkeypatch) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    root = tmp_path / "semantic"
    store = OnlyStrategyRevisionStore(root)

    def fail_publication(source, target):
        del source, target
        raise OSError("injected publication failure")

    monkeypatch.setattr("onlyalpha.strategy.store.os.rename", fail_publication)
    with pytest.raises(OnlyStrategyStoreError) as error:
        store.commit(revision)
    assert error.value.code == "STRATEGY_COMMIT_FAILED"
    parent = root / "strategy" / "revisions" / "sha256" / str(revision.strategy_fingerprint)[:2]
    assert not (parent / str(revision.strategy_fingerprint)).exists()
    assert not tuple(parent.glob(".stage-*"))
