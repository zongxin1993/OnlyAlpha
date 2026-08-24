from dataclasses import replace

import pytest

from onlyalpha.domain.enums import OnlyAggregationSource
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSpecification
from onlyalpha.strategy import (
    OnlyStrategyImplementationBinding,
    OnlyStrategyMarketInputContract,
    OnlyStrategyRevision,
    OnlyStrategyUniverse,
)
from tests.strategy.p9_support import p9_strategy_case


def test_strategy_fingerprint_is_canonical_and_excludes_external_evidence(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    revision = case.revision
    reordered = replace(revision, universe=OnlyStrategyUniverse(tuple(reversed(revision.universe.instruments))))

    assert reordered.strategy_fingerprint == revision.strategy_fingerprint
    assert not {
        "dataset_snapshot_fingerprint",
        "research_run_id",
        "capital",
        "account",
        "broker",
        "fee",
        "execution",
        "created_at",
        "created_by",
        "display_name",
        "comment",
    } & set(revision.semantic_payload())

    reconstructed = OnlyStrategyRevision.from_dict(
        {key: revision.to_dict()[key] for key in reversed(tuple(revision.to_dict()))}
    )
    assert reconstructed == revision
    assert reconstructed.strategy_fingerprint == revision.strategy_fingerprint


def test_every_strategy_semantic_boundary_changes_the_single_fingerprint(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    revision = case.revision
    original = revision.strategy_fingerprint
    contract = revision.market_input_contract
    variants = (
        replace(revision, universe=OnlyStrategyUniverse((OnlyInstrumentId.parse("C.XNAS"),))),
        replace(
            revision,
            market_input_contract=replace(
                contract,
                bar_specification=OnlyBarSpecification(
                    contract.bar_specification.step + 1,
                    contract.bar_specification.aggregation,
                    contract.bar_specification.price_type,
                ),
            ),
        ),
        replace(
            revision,
            market_input_contract=OnlyStrategyMarketInputContract(
                contract.bar_specification,
                OnlyAggregationSource.INTERNAL,
                contract.adjustment_type,
            ),
        ),
        case.revision_variants[1],
        replace(
            revision,
            implementation_bindings=(
                replace(
                    revision.implementation_bindings[0],
                    trading_implementation_fingerprint="f" * 64,
                ),
                *revision.implementation_bindings[1:],
            ),
        ),
        replace(
            revision,
            implementation_bindings=(
                replace(
                    revision.implementation_bindings[0],
                    research_implementation_fingerprint="e" * 64,
                ),
                *revision.implementation_bindings[1:],
            ),
        ),
    )

    assert all(item.strategy_fingerprint != original for item in variants)


def test_revision_requires_exact_graph_implementation_and_signal_role_coverage(tmp_path) -> None:
    revision = p9_strategy_case(tmp_path).revision
    with pytest.raises(ValueError, match="exactly cover"):
        OnlyStrategyRevision(
            revision.universe,
            revision.market_input_contract,
            revision.decision_graph,
            revision.implementation_bindings[1:],
            revision.signal_semantics,
        )
    with pytest.raises(ValueError, match="canonical"):
        replace(revision, implementation_bindings=tuple(reversed(revision.implementation_bindings)))
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyStrategyImplementationBinding("not-a-sha", "a" * 64, "b" * 64)
