"""Retained Definition semantics at their reference owner, without HTTP DTO authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.research.definition import (
    OnlyResearchDefinition,
    OnlyResearchDefinitionError,
    OnlyResearchDefinitionResolver,
    OnlyResearchRegisteredUniverse,
    OnlyResearchUniverseKind,
    OnlyResearchUniverseSelection,
)
from onlyalpha.research.specification import OnlyResearchSpecification
from tests.research.definition.support import definition
from tests.research.definition.test_resolution import _case, _Datasets


class _Universes:
    def list_registered_universes(self) -> tuple[OnlyResearchRegisteredUniverse, ...]:
        return (
            OnlyResearchRegisteredUniverse("z.pool", OnlyResearchUniverseKind.REGISTERED_POOL, {"title": "Z"}),
            OnlyResearchRegisteredUniverse("a.universe", OnlyResearchUniverseKind.REGISTERED_UNIVERSE),
        )

    def resolve(self, selection: OnlyResearchUniverseSelection) -> tuple[str, ...]:
        return {
            "z.pool": ("B.XNAS", "A.XNAS"),
            "a.universe": ("A.XNAS", "B.XNAS"),
        }[selection.registered_id or ""]


def test_reference_definition_roundtrip_preserves_authoring_expression_order(tmp_path) -> None:
    committed, _, _, _ = _case(tmp_path)
    source = definition(committed.definition)
    transported = OnlyResearchDefinition.from_dict(dict(source.to_dict()))
    assert transported == source
    assert transported.schema_version == source.schema_version
    assert [item.left.to_dict() for item in transported.signals.entry.operands] == [  # type: ignore[union-attr]
        item.left.to_dict()
        for item in source.signals.entry.operands  # type: ignore[union-attr]
    ]


def test_reference_registered_universe_resolution_keeps_exact_authority_and_canonical_members(tmp_path) -> None:
    committed, store, registry, _ = _case(tmp_path)
    authority = _Universes()
    resolver = OnlyResearchDefinitionResolver(
        registry, _Datasets(store, committed.snapshot_fingerprint), universe_resolver=authority
    )
    source = definition(committed.definition)
    registered = OnlyResearchUniverseSelection(OnlyResearchUniverseKind.REGISTERED_POOL, registered_id="z.pool")
    source = replace(source, dataset=replace(source.dataset, universe=registered))
    resolved = resolver.resolve(OnlyResearchDefinition.from_dict(dict(source.to_dict())))
    assert resolver.universe_resolver is authority
    assert list(resolved.dataset_definition.instruments) == [
        OnlyInstrumentId.parse("A.XNAS"),
        OnlyInstrumentId.parse("B.XNAS"),
    ]


def test_reference_resolution_keeps_all_exact_identities_and_specification_input(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    source = definition(committed.definition)
    expected = resolver.resolve(source)
    actual = resolver.resolve(OnlyResearchDefinition.from_dict(dict(source.to_dict())))
    assert actual.authoring_definition_fingerprint == expected.authoring_definition_fingerprint
    assert actual.resolved_definition_fingerprint == expected.resolved_definition_fingerprint
    assert actual.dataset_snapshot_fingerprint == expected.dataset_snapshot_fingerprint
    assert actual.specification_fingerprint == expected.specification_fingerprint
    assert len(actual.candidates) == len(expected.candidates) == 4
    assert [item.candidate_fingerprint for item in actual.candidates] == [
        item.candidate_fingerprint for item in expected.candidates
    ]
    assert [(item.variable.instance_key, item.variable.output_name) for item in actual.published_variables] == [
        (item.variable.instance_key, item.variable.output_name) for item in expected.published_variables
    ]
    exact = actual.specification.to_dict()
    assert OnlyResearchSpecification.from_dict(exact) == expected.specification
    assert "PREDICATE" in str(exact)
    assert "workload" not in exact and "node_fingerprints" not in str(exact)


def test_reference_definition_domain_error_preserves_original_authoring_path(tmp_path) -> None:
    committed, _, _, resolver = _case(tmp_path)
    payload = deepcopy(dict(definition(committed.definition).to_dict()))
    payload["signals"]["entry"]["operands"][1]["right"] = {
        "kind": "LITERAL",
        "data_type": "STRING",
        "value": {"type": "STRING", "value": "bad"},
    }
    request = OnlyResearchDefinition.from_dict(payload)
    with pytest.raises(OnlyResearchDefinitionError) as caught:
        resolver.resolve(request)
    error = caught.value
    assert {"phase": error.phase.value, "code": error.code, "path": error.path, "detail": error.detail} == {
        "phase": "EXPRESSION",
        "code": "RESEARCH_DEFINITION_COMPARISON_TYPE_INVALID",
        "path": "signals.entry.operands[1].right",
        "detail": "DECIMAL cannot compare with STRING",
    }
