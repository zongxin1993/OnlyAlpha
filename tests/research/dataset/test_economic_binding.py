import json

import pytest

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.research.dataset import (
    OnlyDatasetEconomicBindingStore,
    OnlyDatasetEconomicBindingStoreError,
    OnlyEconomicFactManifest,
    OnlyResearchDatasetEconomicBinding,
)


def test_economic_binding_is_order_independent_and_identity_complete() -> None:
    mark = OnlyEconomicFactManifest(OnlyMarketDataType.REFERENCE_PRICE, "a" * 64, 2, "v1", OnlyReferencePriceKind.MARK)
    funding = OnlyEconomicFactManifest(OnlyMarketDataType.FUNDING_RATE, "b" * 64, 1, "v1")
    first = OnlyResearchDatasetEconomicBinding("c" * 64, "d" * 64, (funding, mark))
    second = OnlyResearchDatasetEconomicBinding("c" * 64, "d" * 64, (mark, funding))

    assert first.fingerprint == second.fingerprint
    assert first.economic_facts == (funding, mark)


def test_economic_content_or_market_product_changes_identity() -> None:
    mark = OnlyEconomicFactManifest(OnlyMarketDataType.REFERENCE_PRICE, "a" * 64, 2, "v1", OnlyReferencePriceKind.MARK)
    baseline = OnlyResearchDatasetEconomicBinding("c" * 64, "d" * 64, (mark,))
    changed_content = OnlyResearchDatasetEconomicBinding(
        "c" * 64,
        "d" * 64,
        (OnlyEconomicFactManifest(OnlyMarketDataType.REFERENCE_PRICE, "e" * 64, 2, "v1", OnlyReferencePriceKind.MARK),),
    )
    changed_product = OnlyResearchDatasetEconomicBinding("c" * 64, "f" * 64, (mark,))

    assert len({baseline.fingerprint, changed_content.fingerprint, changed_product.fingerprint}) == 3


def test_funding_manifest_cannot_create_parallel_reference_kind_authority() -> None:
    with pytest.raises(ValueError, match="REFERENCE_KIND_NOT_APPLICABLE"):
        OnlyEconomicFactManifest(
            OnlyMarketDataType.FUNDING_RATE,
            "a" * 64,
            1,
            "v1",
            OnlyReferencePriceKind.MARK,
        )


def test_economic_binding_store_round_trip_and_corruption_fail_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    mark = OnlyEconomicFactManifest(
        OnlyMarketDataType.REFERENCE_PRICE,
        "a" * 64,
        2,
        "mark-v1",
        OnlyReferencePriceKind.MARK,
    )
    binding = OnlyResearchDatasetEconomicBinding("c" * 64, "d" * 64, (mark,))
    store = OnlyDatasetEconomicBindingStore(tmp_path)

    assert store.publish_verified(binding) == binding
    assert store.publish_verified(binding) == binding
    assert store.load_verified(binding.fingerprint) == binding

    target = (
        tmp_path
        / "research"
        / "dataset-economic-bindings"
        / "sha256"
        / binding.fingerprint[:2]
        / binding.fingerprint
        / "manifest.json"
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["binding"]["base_dataset_snapshot_fingerprint"] = "e" * 64
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OnlyDatasetEconomicBindingStoreError) as raised:
        store.load_verified(binding.fingerprint)
    assert raised.value.code == "DATASET_BINDING_CORRUPT"
