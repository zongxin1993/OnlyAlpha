from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import onlyalpha_http_server.main as server
import pytest

from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchExperimentManifestV3
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus
from onlyalpha.research.search.parameter.context import OnlyParameterSearchContextResolver
from onlyalpha.research.search.symbolic.context import OnlySymbolicSearchContextResolver


def test_servers_require_explicit_roots() -> None:
    with pytest.raises(SystemExit) as full:
        server.main([])
    assert full.value.code == 2


@pytest.mark.parametrize(
    ("evidence", "error"),
    (
        (OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, ()), None),
        (
            OnlyResearchReadiness(OnlyResearchReadinessStatus.NOT_READY, (), "SCHEMA_INCOMPATIBLE"),
            "SCHEMA_INCOMPATIBLE",
        ),
    ),
)
def test_product_verification_retains_exact_ready_or_failure_evidence(
    evidence: OnlyResearchReadiness,
    error: str | None,
) -> None:
    class Probe:
        def inspect(self) -> OnlyResearchReadiness:
            return evidence

    verification = server._ResearchProductVerification(Probe())  # type: ignore[arg-type]
    if error is None:
        verification.verify()
    else:
        with pytest.raises(RuntimeError, match=error):
            verification.verify()
    assert verification.evidence is evidence


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

    contexts = server._SearchContextReader(
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


def test_search_product_composition_shares_schema_dispatching_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbolic_store = object()
    parameter_store = object()
    symbolic_contexts = object()
    parameter_contexts = object()
    provenance = object()
    symbolic_adapter = object()
    parameter_adapter = object()
    commands = object()
    queries = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(server, "OnlyJsonSymbolicSearchStore", lambda _root: symbolic_store)
    monkeypatch.setattr(server, "OnlyJsonParameterSearchStore", lambda _root: parameter_store)
    monkeypatch.setattr(server, "OnlySymbolicSearchContextResolver", lambda **_kwargs: symbolic_contexts)
    monkeypatch.setattr(server, "OnlyParameterSearchContextResolver", lambda **_kwargs: parameter_contexts)

    def make_provenance(_root: Path, **kwargs: object) -> object:
        captured["search_contexts"] = kwargs["search_contexts"]
        return provenance

    def make_symbolic_adapter(**kwargs: object) -> object:
        captured["symbolic_provenance"] = kwargs["provenance"]
        captured["symbolic_contexts"] = kwargs["contexts"]
        return symbolic_adapter

    def make_parameter_adapter(**kwargs: object) -> object:
        captured["parameter_provenance"] = kwargs["provenance"]
        captured["parameter_contexts"] = kwargs["contexts"]
        return parameter_adapter

    def make_commands(**kwargs: object) -> object:
        captured["adapters"] = kwargs["adapters"]
        return commands

    monkeypatch.setattr(server, "OnlyJsonSearchProvenanceStore", make_provenance)
    monkeypatch.setattr(server, "OnlySymbolicSearchProductAdapterV1", make_symbolic_adapter)
    monkeypatch.setattr(server, "OnlyParameterSearchProductAdapterV1", make_parameter_adapter)
    monkeypatch.setattr(server, "OnlySearchProductCommandServiceV1", make_commands)
    monkeypatch.setattr(server, "OnlySearchProductQueryServiceV1", lambda adapters: queries)
    for helper in (
        "OnlyResearchSpecificationResolver",
        "OnlySymbolicResearchCommandGatewayV1",
        "OnlyHostedSymbolicGenerationExecutionV1",
        "OnlyParameterResearchEvidenceReader",
        "OnlyParameterResearchEvidenceFinalizerV1",
        "OnlyResearchEffectSummaryExecutor",
        "OnlyResearchResultAssembler",
        "OnlyParameterResearchCommandGatewayV1",
        "OnlyHostedParameterGenerationExecutionV1",
    ):
        monkeypatch.setattr(server, helper, lambda *_args, **_kwargs: object())

    composed = server._compose_search_product(
        layout=OnlyUserDataLayout(tmp_path),
        calculations=cast(Any, object()),
        datasets=cast(Any, object()),
        research_commands=cast(Any, object()),
        research_runs=cast(Any, object()),
        research_results=cast(Any, object()),
        statistics_results=cast(Any, object()),
        calculation_results=cast(Any, object()),
        legacy_statistics_results=cast(Any, object()),
        summary_statistics_results=cast(Any, object()),
        product_commands=cast(Any, object()),
        runtime_generations=cast(Any, object()),
        generation_host=cast(Any, object()),
    )

    assert composed == (commands, queries, provenance)
    shared_contexts = captured["search_contexts"]
    assert isinstance(shared_contexts, server._SearchContextReader)
    assert shared_contexts._symbolic is symbolic_contexts
    assert shared_contexts._parameter is parameter_contexts
    assert captured["symbolic_provenance"] is provenance
    assert captured["parameter_provenance"] is provenance
    assert captured["symbolic_contexts"] is symbolic_contexts
    assert captured["parameter_contexts"] is parameter_contexts
    assert captured["adapters"] == (symbolic_adapter, parameter_adapter)
