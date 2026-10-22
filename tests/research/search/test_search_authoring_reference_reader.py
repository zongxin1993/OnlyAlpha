"""Exact historical authoring-reader claims retained without a serving adapter."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from onlyalpha.research.search.symbolic.errors import OnlySymbolicSearchStoreError
from tests.support.research_reference_composition import _SearchAuthoringInputReader

SHA = "a" * 64


@dataclass(frozen=True)
class _Input:
    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "search_space_fingerprint": SHA}


class _SymbolicInputs:
    def load_search_space_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_algorithm_implementation_manifest_intrinsic_verified(self, fingerprint: str) -> _Input:
        raise OnlySymbolicSearchStoreError("SEARCH_ALGORITHM_MANIFEST_NOT_FOUND", fingerprint)


class _ParameterInputs:
    def load_search_space_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_policy_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()

    def load_algorithm_manifest_intrinsic_verified(self, fingerprint: str) -> _Input:
        return _Input()


def test_production_search_authoring_reader_dispatches_only_existing_authorities() -> None:
    reader = _SearchAuthoringInputReader(_SymbolicInputs(), _ParameterInputs())  # type: ignore[arg-type]
    assert reader.load_search_authoring_input_verified("SYMBOLIC_SEARCH_SPACE", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("PARAMETER_SEARCH_SPACE", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("RESEARCH_EVALUATION", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("SEARCH_POLICY", SHA).to_dict()
    assert reader.load_search_authoring_input_verified("SEARCH_ALGORITHM", SHA).to_dict()
    with pytest.raises(LookupError, match="SEARCH_BUDGET"):
        reader.load_search_authoring_input_verified("SEARCH_BUDGET", SHA)
