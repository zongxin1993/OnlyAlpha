"""Independent schema-selected provenance dispatch reference regression."""

from __future__ import annotations

from typing import cast

import pytest

from onlyalpha.research.experiment import (
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
)
from onlyalpha.research.search.parameter.context import (
    OnlyParameterSearchContextResolver,
)
from onlyalpha.research.search.symbolic.context import OnlySymbolicSearchContextResolver
from tests.support.research_reference_composition import _SearchContextReader


@pytest.mark.parametrize(
    ("manifest_type", "expected_resolver"),
    (
        (OnlySearchExperimentManifestV2, "symbolic"),
        (OnlySearchExperimentManifestV3, "parameter"),
    ),
)
def test_shared_search_provenance_dispatches_every_context_read_by_experiment_schema(
    manifest_type: type[OnlySearchExperimentManifestV2] | type[OnlySearchExperimentManifestV3],
    expected_resolver: str,
) -> None:
    calls: list[tuple[str, str, object, tuple[object, ...]]] = []

    class Resolver:
        def __init__(self, name: str) -> None:
            self._name = name

        def __getattr__(self, method: str):  # type: ignore[no-untyped-def]
            def invoke(experiment: object, *args: object) -> object:
                calls.append((self._name, method, experiment, args))
                return method

            return invoke

    contexts = _SearchContextReader(
        cast(OnlySymbolicSearchContextResolver, Resolver("symbolic")),
        cast(OnlyParameterSearchContextResolver, Resolver("parameter")),
    )
    experiment = object.__new__(manifest_type)
    operations = (
        ("resolve_verified_context", ()),
        ("resolve_historical_facts", (("proposal",),)),
        ("load_proposal_contextual_verified", ("plan",)),
        ("load_proposal_occurrence_contextual_verified", ("plan",)),
        ("load_proposal_historical_verified", ("plan",)),
        ("verify_iteration_plan_ledger", ("plan", ())),
        ("verify_iteration_plan_historical_ledger", ("plan", ())),
        ("next_iteration_ordinal", ()),
        ("next_historical_iteration_ordinal", ((),)),
    )

    for method, args in operations:
        assert getattr(contexts, method)(experiment, *args) == method

    assert len(calls) == len(operations)
    assert {call[0] for call in calls} == {expected_resolver}
    assert all(call[2] is experiment for call in calls)
