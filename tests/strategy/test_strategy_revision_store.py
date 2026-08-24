import json

import pytest

from onlyalpha.strategy import OnlyFrozenStrategyRevisionStore, OnlyStrategyStoreError
from tests.strategy.p9_support import p9_strategy_case, publish_frozen_strategy_for_execution_test


def test_frozen_strategy_store_is_read_only_and_loads_verified_freeze_fixture(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    root = tmp_path / "semantic"
    store = OnlyFrozenStrategyRevisionStore(root)

    assert not hasattr(store, "commit")
    assert not hasattr(store, "publish")
    with pytest.raises(OnlyStrategyStoreError) as missing:
        store.load_verified(revision.strategy_fingerprint)
    assert missing.value.code == "STRATEGY_NOT_FOUND"

    publish_frozen_strategy_for_execution_test(root, revision)
    assert store.exists(str(revision.strategy_fingerprint))
    assert store.load_verified(str(revision.strategy_fingerprint)) == revision


def test_legacy_raw_revision_namespace_is_not_runtime_readable(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    root = tmp_path / "semantic"
    fingerprint = str(revision.strategy_fingerprint)
    legacy = root / "strategy" / "revisions" / "sha256" / fingerprint[:2] / fingerprint
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategy_fingerprint": fingerprint,
                "revision": revision.to_dict(),
            }
        ),
        encoding="utf-8",
    )

    store = OnlyFrozenStrategyRevisionStore(root)
    assert not store.exists(fingerprint)
    with pytest.raises(OnlyStrategyStoreError) as error:
        store.load_verified(fingerprint)
    assert error.value.code == "STRATEGY_NOT_FOUND"


@pytest.mark.parametrize("corruption", ["manifest", "unexpected", "path", "symlink"])
def test_frozen_strategy_reader_fails_closed_on_corruption(tmp_path, corruption) -> None:
    revision = p9_strategy_case(tmp_path / "case").revision
    root = tmp_path / "semantic"
    publish_frozen_strategy_for_execution_test(root, revision)
    store = OnlyFrozenStrategyRevisionStore(root)
    fingerprint = str(revision.strategy_fingerprint)
    target = root / "strategy" / "frozen-revisions" / "sha256" / fingerprint[:2] / fingerprint
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
