import pytest

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.research.dataset import OnlyEconomicFactManifest, OnlyResearchDatasetEconomicBinding


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
