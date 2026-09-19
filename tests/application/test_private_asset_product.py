from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.application.private_asset_product import (
    OnlyPrivateAssetExactReadFailure,
    OnlyPrivateAssetExactReadMismatch,
    OnlyPrivateAssetProductService,
    OnlyProductAssetLocatorV1,
    OnlyProductAssetProjectionCompleteness,
    OnlyProductAssetSearchProjectionCorrupt,
    OnlyProductAssetSearchProjectionService,
    OnlyProductAssetSearchProjectionUnavailable,
    OnlyProductAssetSearchProjectionV1,
    OnlyProductAssetSearchQueryV1,
    OnlyProductAssetSearchStatus,
)
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetKind,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
)
from onlyalpha.quant_assets.private_factor_execution import ONLY_PRIVATE_FACTOR_API_V1

NOW = datetime(2026, 9, 19, tzinfo=UTC)


def _factor(
    factor_id: str = "private.factor.momentum",
    *,
    description: str = "Momentum over close prices",
    tags: tuple[str, ...] = ("momentum", "price"),
    base: str | None = None,
) -> OnlyPrivateFactorRevision:
    return OnlyPrivateFactorRevision.from_draft(
        OnlyPrivateFactorDraft(
            factor_id=factor_id,
            semantic_version="1",
            source_text="def calculate(api, inputs, parameters):\n    return inputs['close']\n",
            factor_api_version=1,
            factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
            input_contract={"close": "DECIMAL"},
            parameter_contract={},
            output_contract={"score": "DECIMAL"},
            description=description,
            economic_rationale="Price persistence",
            category="MOMENTUM",
            tags=tags,
            base_revision_fingerprint=base,
        )
    )


def _strategy(
    strategy_id: str = "private.strategy.momentum",
    *,
    description: str = "Momentum strategy",
    tags: tuple[str, ...] = ("momentum",),
    factor: OnlyPrivateFactorRevision | None = None,
    base: str | None = None,
) -> OnlyPrivateStrategyRevision:
    del factor
    definition = {
        "schema_version": 1,
        "universe": {"kind": "SINGLE_INSTRUMENT", "instruments": ["TEST.XSHG"]},
        "market_input": {
            "schema_version": 1,
            "data_kind": "BAR",
            "bar_specification": {"step": 1, "aggregation": "TIME", "price_type": "LAST"},
            "aggregation_source": "EXTERNAL",
            "adjustment_type": "RAW",
            "adjustment_reference": None,
            "observation_admission": "FINAL_ONLY",
        },
        "calculations": [
            {
                "instance_key": "signal",
                "type_reference": {
                    "kind": "INDICATOR",
                    "type_id": "onlyalpha.indicator.liquidity",
                    "semantic_version": "1",
                },
                "parameters": {},
                "published_outputs": ["value"],
                "input_bindings": [{"input_name": "close", "source": "bar.close"}],
                "primary_output": "value",
            }
        ],
        "factor_revision_dependencies": [],
        "eligibility": {
            "kind": "COMPARISON",
            "operator": ">",
            "left": {"kind": "DATASET_FIELD", "field_name": "close"},
            "right": {"kind": "LITERAL", "data_type": "DECIMAL", "value": {"type": "DECIMAL", "value": "0"}},
        },
        "signals": {
            "entry": {
                "kind": "COMPARISON",
                "operator": ">",
                "left": {"kind": "VARIABLE", "instance_key": "signal", "output_name": "value"},
                "right": {"kind": "LITERAL", "data_type": "DECIMAL", "value": {"type": "DECIMAL", "value": "0"}},
            },
            "exit": {
                "kind": "COMPARISON",
                "operator": "<=",
                "left": {"kind": "VARIABLE", "instance_key": "signal", "output_name": "value"},
                "right": {"kind": "LITERAL", "data_type": "DECIMAL", "value": {"type": "DECIMAL", "value": "0"}},
            },
        },
    }
    return OnlyPrivateStrategyRevision.from_draft(
        OnlyPrivateStrategyDraft(
            strategy_id=strategy_id,
            semantic_version="1",
            definition=definition,
            description=description,
            tags=tags,
            base_revision_fingerprint=base,
        )
    )


class _Authority:
    def __init__(
        self,
        factors: tuple[OnlyPrivateFactorRevision, ...],
        strategies: tuple[OnlyPrivateStrategyRevision, ...],
    ) -> None:
        self.factors = factors
        self.strategies = strategies

    def list_current_factor_revisions(self) -> tuple[OnlyPrivateFactorRevision, ...]:
        return self.factors

    def list_current_strategy_revisions(self) -> tuple[OnlyPrivateStrategyRevision, ...]:
        return self.strategies

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision:
        return next(
            item
            for item in self.factors
            if item.factor_id == factor_id and item.revision_fingerprint == revision_fingerprint
        )

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision:
        return next(
            item
            for item in self.strategies
            if item.strategy_id == strategy_id and item.revision_fingerprint == revision_fingerprint
        )


class _ProjectionStore:
    def __init__(self) -> None:
        self.current: OnlyProductAssetSearchProjectionV1 | None = None
        self.built_at: datetime | None = None
        self.unavailable = False

    def publish(self, projection: OnlyProductAssetSearchProjectionV1, built_at: datetime) -> None:
        self.current = projection
        self.built_at = built_at

    def load_current(self) -> tuple[OnlyProductAssetSearchProjectionV1, datetime] | None:
        if self.unavailable:
            raise OnlyProductAssetSearchProjectionUnavailable("database")
        if self.current is None or self.built_at is None:
            return None
        return self.current, self.built_at


def test_registry_is_deterministic_and_contains_only_published_exact_revisions() -> None:
    factor = _factor()
    strategy = _strategy(factor=factor)
    first = OnlyPrivateAssetProductService(_Authority((factor,), (strategy,))).current_registry()
    second = OnlyPrivateAssetProductService(_Authority((factor,), (strategy,))).current_registry()

    assert first == second
    assert [item.locator.private_asset_id for item in first.entries] == [factor.factor_id, strategy.strategy_id]
    assert first.entries[0].locator == OnlyProductAssetLocatorV1(
        OnlyPrivateAssetKind.FACTOR,
        factor.factor_id,
        factor.revision_fingerprint,
        factor.source_sha256,
    )
    assert "source_text" not in first.entries[0].to_dict()
    assert "definition" not in first.entries[1].to_dict()


def test_exact_read_never_falls_forward_after_current_revision_changes() -> None:
    old = _factor()
    new = _factor(description="New description", base=old.revision_fingerprint)
    authority = _Authority((old,), ())
    service = OnlyPrivateAssetProductService(authority)
    locator = service.current_registry().entries[0].locator
    authority.factors = (new, old)

    assert service.read_exact(locator) == old
    with pytest.raises(OnlyPrivateAssetExactReadMismatch, match="PRIVATE_ASSET_EXACT_READ_MISMATCH"):
        service.read_exact(replace(locator, content_fingerprint="0" * 64))


@pytest.mark.parametrize(
    "failure",
    (
        OnlyPrivateAssetAuthorityUnavailableError("database"),
        OnlyPrivateAssetCorruptError("revision"),
    ),
)
def test_exact_read_preserves_authority_unavailable_and_corrupt_failures(failure: Exception) -> None:
    factor = _factor()
    authority = _Authority((factor,), ())
    locator = OnlyPrivateAssetProductService(authority).current_registry().entries[0].locator

    def fail(_factor_id: str, _revision_fingerprint: str) -> OnlyPrivateFactorRevision:
        raise failure

    authority.load_factor_revision = fail  # type: ignore[method-assign]
    with pytest.raises(type(failure)):
        OnlyPrivateAssetProductService(authority).read_exact(locator)


def test_exact_read_never_turns_unknown_failure_into_missing_revision() -> None:
    factor = _factor()
    authority = _Authority((factor,), ())
    locator = OnlyPrivateAssetProductService(authority).current_registry().entries[0].locator

    def fail(_factor_id: str, _revision_fingerprint: str) -> OnlyPrivateFactorRevision:
        raise RuntimeError("backend defect")

    authority.load_factor_revision = fail  # type: ignore[method-assign]
    with pytest.raises(OnlyPrivateAssetExactReadFailure, match="PRIVATE_ASSET_EXACT_READ_FAILURE"):
        OnlyPrivateAssetProductService(authority).read_exact(locator)


def test_search_distinguishes_match_certified_absence_incomplete_and_unavailable() -> None:
    factor = _factor()
    registry = OnlyPrivateAssetProductService(_Authority((factor,), ()))
    store = _ProjectionStore()
    search = OnlyProductAssetSearchProjectionService(registry, store, lambda: NOW)

    assert (
        search.search(OnlyProductAssetSearchQueryV1(text="momentum")).status
        is OnlyProductAssetSearchStatus.PROJECTION_UNAVAILABLE
    )

    store.unavailable = True
    assert (
        search.search(OnlyProductAssetSearchQueryV1(text="momentum")).status
        is OnlyProductAssetSearchStatus.PROJECTION_UNAVAILABLE
    )
    store.unavailable = False

    built = search.rebuild()
    match = search.search(OnlyProductAssetSearchQueryV1(text="momentum", tag="price"))
    absent = search.search(OnlyProductAssetSearchQueryV1(text="value"))
    assert match.status is OnlyProductAssetSearchStatus.MATCH
    assert match.results[0].locator.private_asset_id == factor.factor_id
    assert absent.status is OnlyProductAssetSearchStatus.NO_MATCH_ON_CERTIFIED_COMPLETE_PROJECTION
    assert built.projection_fingerprint == search.rebuild().projection_fingerprint

    store.current = OnlyProductAssetSearchProjectionV1.from_registry(
        registry.current_registry(), OnlyProductAssetProjectionCompleteness.INCOMPLETE
    )
    assert (
        search.search(OnlyProductAssetSearchQueryV1(text="value")).status
        is OnlyProductAssetSearchStatus.PROJECTION_INCOMPLETE
    )


def test_stale_projection_cannot_certify_absence() -> None:
    first = _factor()
    authority = _Authority((first,), ())
    registry = OnlyPrivateAssetProductService(authority)
    store = _ProjectionStore()
    search = OnlyProductAssetSearchProjectionService(registry, store, lambda: NOW)
    search.rebuild()
    authority.factors = (_factor("private.factor.value", description="Value", tags=("value",)),)

    outcome = search.search(OnlyProductAssetSearchQueryV1(text="missing"))

    assert outcome.status is OnlyProductAssetSearchStatus.PROJECTION_INCOMPLETE
    assert outcome.projection_stale is True


def test_projection_corruption_is_rejected() -> None:
    factor = _factor()
    registry = OnlyPrivateAssetProductService(_Authority((factor,), ())).current_registry()
    projection = OnlyProductAssetSearchProjectionV1.from_registry(registry)

    with pytest.raises(OnlyProductAssetSearchProjectionCorrupt, match="PRIVATE_ASSET_SEARCH_PROJECTION_CORRUPT"):
        replace(projection, projection_fingerprint="0" * 64)


def test_search_structured_filters_are_canonical_and_do_not_rank_quality() -> None:
    factor = _factor()
    strategy = _strategy(factor=factor)
    registry = OnlyPrivateAssetProductService(_Authority((factor,), (strategy,)))
    store = _ProjectionStore()
    search = OnlyProductAssetSearchProjectionService(registry, store, lambda: NOW)
    search.rebuild()

    result = search.search(
        OnlyProductAssetSearchQueryV1(
            kind=OnlyPrivateAssetKind.FACTOR,
            category="MOMENTUM",
            tag="momentum",
        )
    )

    assert result.status is OnlyProductAssetSearchStatus.MATCH
    assert result.results == (registry.current_registry().entries[0],)
    assert not ({"score", "qualified", "novel", "recommendation"} & set(result.results[0].to_dict()))
