from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.quant_assets import (
    OnlyPrivateAlphaAsset,
    OnlyPrivateAlphaDraft,
    OnlyPrivateAlphaRevision,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetInvalidError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateAssetReferenceMismatchError,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionNotFoundError,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDraft,
    OnlyPrivateStrategyRevision,
)


class _Revisions:
    def __init__(self, alpha: OnlyPrivateAlphaRevision, strategy: OnlyPrivateStrategyRevision) -> None:
        self.alpha = alpha
        self.strategy = strategy

    def load_alpha_revision(self, alpha_id: str, revision_fingerprint: str) -> OnlyPrivateAlphaRevision:
        if (alpha_id, revision_fingerprint) != (self.alpha.alpha_id, self.alpha.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.alpha

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision:
        if (strategy_id, revision_fingerprint) != (self.strategy.strategy_id, self.strategy.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.strategy


def _alpha_draft(**changes: object) -> OnlyPrivateAlphaDraft:
    values: dict[str, object] = {
        "alpha_id": "private.alpha.momentum",
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return inputs\n",
        "alpha_api_version": 1,
        "alpha_api_contract_fingerprint": "a" * 64,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("daily", "trend"),
    }
    values.update(changes)
    return OnlyPrivateAlphaDraft(**values)  # type: ignore[arg-type]


def _strategy_draft(**changes: object) -> OnlyPrivateStrategyDraft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.simple_momentum",
        "semantic_version": "1",
        "definition": {
            "schema_version": 1,
            "eligibility": {"calculation": "onlyalpha.indicator.liquidity@1"},
            "entry": {"factor": "private.alpha.momentum@1"},
            "exit": {"operator": "<="},
        },
        "description": "Simple momentum",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateStrategyDraft(**values)  # type: ignore[arg-type]


def test_private_asset_identity_families_are_strict() -> None:
    assert OnlyPrivateAlphaAsset("private.alpha.momentum").alpha_id == "private.alpha.momentum"
    assert OnlyPrivateStrategyAsset("private.strategy.momentum").strategy_id == "private.strategy.momentum"
    for invalid in ("factor.momentum", "private.strategy.momentum", "private.alpha.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateAlphaAsset(invalid)
    for invalid in ("strategy.momentum", "private.alpha.momentum", "private.strategy.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateStrategyAsset(invalid)


def test_alpha_revision_identity_separates_source_revision_semantics_and_api() -> None:
    draft = _alpha_draft()
    revision = OnlyPrivateAlphaRevision.from_draft(draft)
    assert revision.source_sha256 != revision.revision_fingerprint
    assert revision.semantic_version != revision.revision_fingerprint
    assert "alpha_api_version" != "semantic_version"
    assert OnlyPrivateAlphaRevision.from_draft(_alpha_draft()) == revision

    changed_source = OnlyPrivateAlphaRevision.from_draft(_alpha_draft(source_text=draft.source_text + "\n"))
    changed_semantics = OnlyPrivateAlphaRevision.from_draft(_alpha_draft(semantic_version="2"))
    changed_api = OnlyPrivateAlphaRevision.from_draft(_alpha_draft(alpha_api_contract_fingerprint="b" * 64))
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
            definition={
                "exit": {"operator": "<="},
                "entry": {"factor": "private.alpha.momentum@1"},
                "eligibility": {"calculation": "onlyalpha.indicator.liquidity@1"},
                "schema_version": 1,
            }
        )
    )
    changed = OnlyPrivateStrategyRevision.from_draft(
        _strategy_draft(definition={"schema_version": 1, "entry": {"factor": "private.alpha.reversal@1"}})
    )
    assert revision == reordered
    assert revision.definition_fingerprint != revision.revision_fingerprint
    assert changed.definition_fingerprint != revision.definition_fingerprint
    assert changed.revision_fingerprint != revision.revision_fingerprint


def test_drafts_are_mutable_but_revisions_are_deeply_immutable() -> None:
    draft = _alpha_draft()
    draft.description = "Edited"
    revision = OnlyPrivateAlphaRevision.from_draft(draft)
    assert revision.description == "Edited"
    with pytest.raises(FrozenInstanceError):
        revision.description = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        revision.input_contract["other"] = {}  # type: ignore[index]


def test_revision_load_detects_source_definition_and_revision_tampering() -> None:
    alpha = OnlyPrivateAlphaRevision.from_draft(_alpha_draft())
    source_changed = alpha.to_dict()
    source_changed["source_text"] = alpha.source_text + "# tampered\n"
    with pytest.raises(OnlyPrivateAssetCorruptError, match="SOURCE_HASH"):
        OnlyPrivateAlphaRevision.from_dict(source_changed)
    identity_changed = alpha.to_dict()
    identity_changed["revision_fingerprint"] = "f" * 64
    with pytest.raises(OnlyPrivateAssetCorruptError, match="REVISION_FINGERPRINT"):
        OnlyPrivateAlphaRevision.from_dict(identity_changed)

    strategy = OnlyPrivateStrategyRevision.from_draft(_strategy_draft())
    definition_changed = strategy.to_dict()
    definition_changed["definition"] = {"schema_version": 1, "entry": "tampered"}
    with pytest.raises(OnlyPrivateAssetCorruptError, match="DEFINITION_FINGERPRINT"):
        OnlyPrivateStrategyRevision.from_dict(definition_changed)


def test_draft_cannot_be_loaded_where_revision_is_required() -> None:
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateAlphaRevision.from_dict(_alpha_draft().to_dict())
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateStrategyRevision.from_dict(_strategy_draft().to_dict())


def test_exact_revision_reference_resolves_authority_derived_binding_without_content_input() -> None:
    alpha = OnlyPrivateAlphaRevision.from_draft(_alpha_draft())
    strategy = OnlyPrivateStrategyRevision.from_draft(_strategy_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(_Revisions(alpha, strategy))

    alpha_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.ALPHA, alpha.alpha_id, alpha.revision_fingerprint)
    )
    assert alpha_binding.private_asset_content_fingerprint == alpha.source_sha256
    assert alpha_binding.semantic_version == alpha.semantic_version
    assert alpha_binding.alpha_api_contract_fingerprint == alpha.alpha_api_contract_fingerprint

    strategy_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.STRATEGY, strategy.strategy_id, strategy.revision_fingerprint
        )
    )
    assert strategy_binding.private_asset_content_fingerprint == strategy.definition_fingerprint
    assert strategy_binding.alpha_api_version is None


def test_exact_revision_reference_never_falls_forward_or_crosses_asset_owner() -> None:
    alpha = OnlyPrivateAlphaRevision.from_draft(_alpha_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(
        _Revisions(alpha, OnlyPrivateStrategyRevision.from_draft(_strategy_draft()))
    )
    for asset_id, revision in (
        (alpha.alpha_id, "f" * 64),
        ("private.alpha.other", alpha.revision_fingerprint),
    ):
        with pytest.raises(OnlyPrivateAssetRevisionNotFoundError):
            resolver.resolve(OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.ALPHA, asset_id, revision))

    class WrongOwner(_Revisions):
        def load_alpha_revision(self, alpha_id: str, revision_fingerprint: str) -> OnlyPrivateAlphaRevision:
            del alpha_id, revision_fingerprint
            return alpha

    with pytest.raises(OnlyPrivateAssetReferenceMismatchError):
        OnlyPrivateAssetRevisionBindingResolver(
            WrongOwner(alpha, OnlyPrivateStrategyRevision.from_draft(_strategy_draft()))
        ).resolve(
            OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.ALPHA,
                "private.alpha.other",
                "f" * 64,
            )
        )
