from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.quant_assets import (
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetInvalidError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetReferenceMismatchError,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionNotFoundError,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorAsset,
    OnlyPrivateFactorDraft,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
)


class _Revisions:
    def __init__(self, factor: OnlyPrivateFactorRevision, strategy: OnlyPrivateStrategyRevision) -> None:
        self.factor = factor
        self.strategy = strategy

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision:
        if (factor_id, revision_fingerprint) != (self.factor.factor_id, self.factor.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.factor

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision:
        if (strategy_id, revision_fingerprint) != (self.strategy.strategy_id, self.strategy.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.strategy


def _factor_draft(**changes: object) -> OnlyPrivateFactorDraft:
    values: dict[str, object] = {
        "factor_id": "private.factor.momentum",
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return inputs\n",
        "factor_api_version": 1,
        "factor_api_contract_fingerprint": "a" * 64,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("daily", "trend"),
    }
    values.update(changes)
    return OnlyPrivateFactorDraft(**values)  # type: ignore[arg-type]


def _strategy_definition(instruments: tuple[str, ...] = ("TEST.XSHG",)) -> dict[str, object]:
    return {
        "schema_version": 1,
        "universe": {"kind": "SINGLE_INSTRUMENT", "instruments": list(instruments)},
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
            "right": {
                "kind": "LITERAL",
                "data_type": "DECIMAL",
                "value": {"type": "DECIMAL", "value": "0"},
            },
        },
        "signals": {
            "entry": {
                "kind": "COMPARISON",
                "operator": ">",
                "left": {"kind": "VARIABLE", "instance_key": "signal", "output_name": "value"},
                "right": {
                    "kind": "LITERAL",
                    "data_type": "DECIMAL",
                    "value": {"type": "DECIMAL", "value": "0"},
                },
            },
            "exit": {
                "kind": "COMPARISON",
                "operator": "<=",
                "left": {"kind": "VARIABLE", "instance_key": "signal", "output_name": "value"},
                "right": {
                    "kind": "LITERAL",
                    "data_type": "DECIMAL",
                    "value": {"type": "DECIMAL", "value": "0"},
                },
            },
        },
    }


def _strategy_draft(**changes: object) -> OnlyPrivateStrategyDraft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.simple_momentum",
        "semantic_version": "1",
        "definition": {
            **_strategy_definition(),
        },
        "description": "Simple momentum",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateStrategyDraft(**values)  # type: ignore[arg-type]


def test_private_asset_identity_families_are_strict() -> None:
    assert OnlyPrivateFactorAsset("private.factor.momentum").factor_id == "private.factor.momentum"
    assert OnlyPrivateStrategyAsset("private.strategy.momentum").strategy_id == "private.strategy.momentum"
    for invalid in ("factor.momentum", "private.strategy.momentum", "private.factor.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateFactorAsset(invalid)
    for invalid in ("strategy.momentum", "private.factor.momentum", "private.strategy.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateStrategyAsset(invalid)


def test_factor_revision_identity_separates_source_revision_semantics_and_api() -> None:
    draft = _factor_draft()
    revision = OnlyPrivateFactorRevision.from_draft(draft)
    assert revision.source_sha256 != revision.revision_fingerprint
    assert revision.semantic_version != revision.revision_fingerprint
    assert "factor_api_version" != "semantic_version"
    assert OnlyPrivateFactorRevision.from_draft(_factor_draft()) == revision

    changed_source = OnlyPrivateFactorRevision.from_draft(_factor_draft(source_text=draft.source_text + "\n"))
    changed_semantics = OnlyPrivateFactorRevision.from_draft(_factor_draft(semantic_version="2"))
    changed_api = OnlyPrivateFactorRevision.from_draft(_factor_draft(factor_api_contract_fingerprint="b" * 64))
    assert (
        len(
            {
                revision.revision_fingerprint,
                changed_source.revision_fingerprint,
                changed_semantics.revision_fingerprint,
                changed_api.revision_fingerprint,
            }
        )
        == 4
    )


def test_strategy_definition_and_revision_identity_are_deterministic_and_distinct() -> None:
    revision = OnlyPrivateStrategyRevision.from_draft(_strategy_draft())
    reordered = OnlyPrivateStrategyRevision.from_draft(
        _strategy_draft(
            definition=_strategy_definition(),
        )
    )
    changed = OnlyPrivateStrategyRevision.from_draft(_strategy_draft(definition=_strategy_definition(("OTHER.XSHG",))))
    assert revision == reordered
    assert revision.definition_fingerprint != revision.revision_fingerprint
    assert changed.definition_fingerprint != revision.definition_fingerprint
    assert changed.revision_fingerprint != revision.revision_fingerprint


def test_drafts_are_mutable_but_revisions_are_deeply_immutable() -> None:
    draft = _factor_draft()
    draft.description = "Edited"
    revision = OnlyPrivateFactorRevision.from_draft(draft)
    assert revision.description == "Edited"
    with pytest.raises(FrozenInstanceError):
        revision.description = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        revision.input_contract["other"] = {}  # type: ignore[index]


def test_revision_load_detects_source_definition_and_revision_tampering() -> None:
    factor = OnlyPrivateFactorRevision.from_draft(_factor_draft())
    source_changed = factor.to_dict()
    source_changed["source_text"] = factor.source_text + "# tampered\n"
    with pytest.raises(OnlyPrivateAssetCorruptError, match="SOURCE_HASH"):
        OnlyPrivateFactorRevision.from_dict(source_changed)
    identity_changed = factor.to_dict()
    identity_changed["revision_fingerprint"] = "f" * 64
    with pytest.raises(OnlyPrivateAssetCorruptError, match="REVISION_FINGERPRINT"):
        OnlyPrivateFactorRevision.from_dict(identity_changed)

    strategy = OnlyPrivateStrategyRevision.from_draft(_strategy_draft())
    definition_changed = strategy.to_dict()
    definition_changed["definition"] = _strategy_definition(("OTHER.XSHG",))
    with pytest.raises(OnlyPrivateAssetCorruptError, match="DEFINITION_FINGERPRINT"):
        OnlyPrivateStrategyRevision.from_dict(definition_changed)


def test_draft_cannot_be_loaded_where_revision_is_required() -> None:
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateFactorRevision.from_dict(_factor_draft().to_dict())
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateStrategyRevision.from_dict(_strategy_draft().to_dict())


def test_exact_revision_reference_resolves_authority_derived_binding_without_content_input() -> None:
    factor = OnlyPrivateFactorRevision.from_draft(_factor_draft())
    strategy = OnlyPrivateStrategyRevision.from_draft(_strategy_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(_Revisions(factor, strategy))

    factor_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.FACTOR, factor.factor_id, factor.revision_fingerprint)
    )
    assert factor_binding.private_asset_content_fingerprint == factor.source_sha256
    assert factor_binding.semantic_version == factor.semantic_version
    assert factor_binding.factor_api_contract_fingerprint == factor.factor_api_contract_fingerprint

    strategy_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.STRATEGY, strategy.strategy_id, strategy.revision_fingerprint
        )
    )
    assert strategy_binding.private_asset_content_fingerprint == strategy.definition_fingerprint
    assert strategy_binding.factor_api_version is None


def test_exact_revision_reference_never_falls_forward_or_crosses_asset_owner() -> None:
    factor = OnlyPrivateFactorRevision.from_draft(_factor_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(
        _Revisions(factor, OnlyPrivateStrategyRevision.from_draft(_strategy_draft()))
    )
    for asset_id, revision in (
        (factor.factor_id, "f" * 64),
        ("private.factor.other", factor.revision_fingerprint),
    ):
        with pytest.raises(OnlyPrivateAssetRevisionNotFoundError):
            resolver.resolve(OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.FACTOR, asset_id, revision))

    class WrongOwner(_Revisions):
        def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision:
            del factor_id, revision_fingerprint
            return factor

    with pytest.raises(OnlyPrivateAssetReferenceMismatchError):
        OnlyPrivateAssetRevisionBindingResolver(
            WrongOwner(factor, OnlyPrivateStrategyRevision.from_draft(_strategy_draft()))
        ).resolve(
            OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.FACTOR,
                "private.factor.other",
                "f" * 64,
            )
        )
