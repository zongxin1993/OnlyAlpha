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
    OnlyPrivateL3Asset,
    OnlyPrivateL3Draft,
    OnlyPrivateL3Revision,
    OnlyPrivateL4Asset,
    OnlyPrivateL4Draft,
    OnlyPrivateL4Revision,
)


class _Revisions:
    def __init__(self, l3: OnlyPrivateL3Revision, l4: OnlyPrivateL4Revision) -> None:
        self.l3 = l3
        self.l4 = l4

    def load_l3_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateL3Revision:
        if (factor_id, revision_fingerprint) != (self.l3.factor_id, self.l3.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.l3

    def load_l4_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateL4Revision:
        if (strategy_id, revision_fingerprint) != (self.l4.strategy_id, self.l4.revision_fingerprint):
            raise OnlyPrivateAssetNotFoundError()
        return self.l4


def _l3_draft(**changes: object) -> OnlyPrivateL3Draft:
    values: dict[str, object] = {
        "factor_id": "private.factor.momentum",
        "semantic_version": "1",
        "source_text": "def calculate(api, inputs, parameters):\n    return inputs\n",
        "l3_api_version": 1,
        "l3_api_contract_fingerprint": "a" * 64,
        "input_contract": {"close": {"type": "DECIMAL"}},
        "parameter_contract": {"window": {"type": "INTEGER"}},
        "output_contract": {"value": {"type": "DECIMAL"}},
        "description": "Momentum",
        "economic_rationale": "Trend persistence",
        "category": "momentum",
        "tags": ("daily", "trend"),
    }
    values.update(changes)
    return OnlyPrivateL3Draft(**values)  # type: ignore[arg-type]


def _l4_draft(**changes: object) -> OnlyPrivateL4Draft:
    values: dict[str, object] = {
        "strategy_id": "private.strategy.simple_momentum",
        "semantic_version": "1",
        "definition": {
            "schema_version": 1,
            "eligibility": {"calculation": "onlyalpha.indicator.liquidity@1"},
            "entry": {"factor": "private.factor.momentum@1"},
            "exit": {"operator": "<="},
        },
        "description": "Simple momentum",
        "tags": ("long_only",),
    }
    values.update(changes)
    return OnlyPrivateL4Draft(**values)  # type: ignore[arg-type]


def test_private_asset_identity_families_are_strict() -> None:
    assert OnlyPrivateL3Asset("private.factor.momentum").factor_id == "private.factor.momentum"
    assert OnlyPrivateL4Asset("private.strategy.momentum").strategy_id == "private.strategy.momentum"
    for invalid in ("factor.momentum", "private.strategy.momentum", "private.factor.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateL3Asset(invalid)
    for invalid in ("strategy.momentum", "private.factor.momentum", "private.strategy.Momentum"):
        with pytest.raises(OnlyPrivateAssetInvalidError):
            OnlyPrivateL4Asset(invalid)


def test_l3_revision_identity_separates_source_revision_semantics_and_api() -> None:
    draft = _l3_draft()
    revision = OnlyPrivateL3Revision.from_draft(draft)
    assert revision.source_sha256 != revision.revision_fingerprint
    assert revision.semantic_version != revision.revision_fingerprint
    assert "l3_api_version" != "semantic_version"
    assert OnlyPrivateL3Revision.from_draft(_l3_draft()) == revision

    changed_source = OnlyPrivateL3Revision.from_draft(_l3_draft(source_text=draft.source_text + "\n"))
    changed_semantics = OnlyPrivateL3Revision.from_draft(_l3_draft(semantic_version="2"))
    changed_api = OnlyPrivateL3Revision.from_draft(_l3_draft(l3_api_contract_fingerprint="b" * 64))
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


def test_l4_definition_and_revision_identity_are_deterministic_and_distinct() -> None:
    revision = OnlyPrivateL4Revision.from_draft(_l4_draft())
    reordered = OnlyPrivateL4Revision.from_draft(
        _l4_draft(
            definition={
                "exit": {"operator": "<="},
                "entry": {"factor": "private.factor.momentum@1"},
                "eligibility": {"calculation": "onlyalpha.indicator.liquidity@1"},
                "schema_version": 1,
            }
        )
    )
    changed = OnlyPrivateL4Revision.from_draft(
        _l4_draft(definition={"schema_version": 1, "entry": {"factor": "private.factor.reversal@1"}})
    )
    assert revision == reordered
    assert revision.definition_fingerprint != revision.revision_fingerprint
    assert changed.definition_fingerprint != revision.definition_fingerprint
    assert changed.revision_fingerprint != revision.revision_fingerprint


def test_drafts_are_mutable_but_revisions_are_deeply_immutable() -> None:
    draft = _l3_draft()
    draft.description = "Edited"
    revision = OnlyPrivateL3Revision.from_draft(draft)
    assert revision.description == "Edited"
    with pytest.raises(FrozenInstanceError):
        revision.description = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        revision.input_contract["other"] = {}  # type: ignore[index]


def test_revision_load_detects_source_definition_and_revision_tampering() -> None:
    l3 = OnlyPrivateL3Revision.from_draft(_l3_draft())
    source_changed = l3.to_dict()
    source_changed["source_text"] = l3.source_text + "# tampered\n"
    with pytest.raises(OnlyPrivateAssetCorruptError, match="SOURCE_HASH"):
        OnlyPrivateL3Revision.from_dict(source_changed)
    identity_changed = l3.to_dict()
    identity_changed["revision_fingerprint"] = "f" * 64
    with pytest.raises(OnlyPrivateAssetCorruptError, match="REVISION_FINGERPRINT"):
        OnlyPrivateL3Revision.from_dict(identity_changed)

    l4 = OnlyPrivateL4Revision.from_draft(_l4_draft())
    definition_changed = l4.to_dict()
    definition_changed["definition"] = {"schema_version": 1, "entry": "tampered"}
    with pytest.raises(OnlyPrivateAssetCorruptError, match="DEFINITION_FINGERPRINT"):
        OnlyPrivateL4Revision.from_dict(definition_changed)


def test_draft_cannot_be_loaded_where_revision_is_required() -> None:
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateL3Revision.from_dict(_l3_draft().to_dict())
    with pytest.raises(OnlyPrivateAssetInvalidError):
        OnlyPrivateL4Revision.from_dict(_l4_draft().to_dict())


def test_exact_revision_reference_resolves_authority_derived_binding_without_content_input() -> None:
    l3 = OnlyPrivateL3Revision.from_draft(_l3_draft())
    l4 = OnlyPrivateL4Revision.from_draft(_l4_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(_Revisions(l3, l4))

    l3_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.L3_FACTOR, l3.factor_id, l3.revision_fingerprint)
    )
    assert l3_binding.private_asset_content_fingerprint == l3.source_sha256
    assert l3_binding.semantic_version == l3.semantic_version
    assert l3_binding.l3_api_contract_fingerprint == l3.l3_api_contract_fingerprint

    l4_binding = resolver.resolve(
        OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.L4_STRATEGY, l4.strategy_id, l4.revision_fingerprint)
    )
    assert l4_binding.private_asset_content_fingerprint == l4.definition_fingerprint
    assert l4_binding.l3_api_version is None


def test_exact_revision_reference_never_falls_forward_or_crosses_asset_owner() -> None:
    l3 = OnlyPrivateL3Revision.from_draft(_l3_draft())
    resolver = OnlyPrivateAssetRevisionBindingResolver(_Revisions(l3, OnlyPrivateL4Revision.from_draft(_l4_draft())))
    for asset_id, revision in (
        (l3.factor_id, "f" * 64),
        ("private.factor.other", l3.revision_fingerprint),
    ):
        with pytest.raises(OnlyPrivateAssetRevisionNotFoundError):
            resolver.resolve(OnlyPrivateAssetRevisionReferenceV1(OnlyPrivateAssetKind.L3_FACTOR, asset_id, revision))

    class WrongOwner(_Revisions):
        def load_l3_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateL3Revision:
            del factor_id, revision_fingerprint
            return l3

    with pytest.raises(OnlyPrivateAssetReferenceMismatchError):
        OnlyPrivateAssetRevisionBindingResolver(WrongOwner(l3, OnlyPrivateL4Revision.from_draft(_l4_draft()))).resolve(
            OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.L3_FACTOR,
                "private.factor.other",
                "f" * 64,
            )
        )
