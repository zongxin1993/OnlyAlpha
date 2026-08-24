from dataclasses import replace
from inspect import signature

import pytest

from onlyalpha.application import OnlyCalculationEquivalenceCertificationApplicationService
from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationEquivalenceError,
    OnlyCalculationEquivalenceEvidenceV2Store,
    OnlyCalculationRegistry,
    only_required_calculation_equivalence_profile,
)
from onlyalpha.strategy.equivalence import OnlyLegacyCalculationEquivalenceEvidenceV1Reader
from tests.strategy.p9_support import p9_strategy_case


def test_actual_backends_must_match_before_evidence_v2_is_published(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    node = next(
        item
        for item in case.revision.decision_graph.ordered_nodes
        if item.definition.type_id.startswith("onlyalpha.factor.")
    )
    registry = OnlyCalculationRegistry()
    seen = set()
    for candidate in case.revision.decision_graph.nodes:
        key = (candidate.definition.kind, candidate.definition.type_id, candidate.definition.semantic_version)
        if key in seen:
            continue
        seen.add(key)
        for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
            registration = case.registry.resolve(*key, backend)
            if candidate.fingerprint == node.fingerprint and backend is OnlyCalculationBackendKind.TRADING:

                class _MismatchFactory:
                    def create(self, definition, request):
                        del definition, request

                        class _Mismatch:
                            def update(self, inputs):
                                del inputs
                                return {node.definition.outputs[0].name: None}

                        return _Mismatch()

                registration = replace(registration, provider=_MismatchFactory())
            registry.register(registration)
    store = OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "semantic")
    service = OnlyCalculationEquivalenceCertificationApplicationService(registry, store)

    with pytest.raises(OnlyCalculationEquivalenceError) as error:
        service.certify(node)
    assert error.value.code == "EQUIVALENCE_CERTIFICATION_FAILED"
    assert not (tmp_path / "semantic" / "calculation-equivalence" / "evidence-v2").exists()


def test_certification_api_accepts_no_runner_corpus_profile_or_output(tmp_path) -> None:
    store = OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "semantic")

    assert tuple(signature(OnlyCalculationEquivalenceCertificationApplicationService).parameters) == (
        "calculations",
        "evidence_store",
    )
    assert tuple(signature(OnlyCalculationEquivalenceCertificationApplicationService.certify).parameters) == (
        "self",
        "node",
    )
    assert not hasattr(store, "commit")
    assert not hasattr(store, "publish")


def test_evidence_v2_binds_exact_node_and_required_profile(tmp_path) -> None:
    case = p9_strategy_case(tmp_path / "case")
    first, second = tuple(
        item
        for item in case.revision.decision_graph.ordered_nodes
        if item.definition.type_id == "onlyalpha.indicator.rolling_return"
    )
    store = OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "semantic")
    service = OnlyCalculationEquivalenceCertificationApplicationService(case.registry, store)
    evidence = service.certify(first)
    profile = only_required_calculation_equivalence_profile(first.definition)
    research = case.registry.resolve(
        first.definition.kind,
        first.definition.type_id,
        first.definition.semantic_version,
        OnlyCalculationBackendKind.RESEARCH,
    ).implementation_manifest
    trading = case.registry.resolve(
        first.definition.kind,
        first.definition.type_id,
        first.definition.semantic_version,
        OnlyCalculationBackendKind.TRADING,
    ).implementation_manifest
    assert research is not None and trading is not None
    assert (
        store.require_verified(
            calculation_node_fingerprint=first.fingerprint,
            reference=research.calculation_type_reference,
            research_implementation_fingerprint=research.implementation_fingerprint,
            trading_implementation_fingerprint=trading.implementation_fingerprint,
            certification_profile_fingerprint=profile.profile_fingerprint,
        )
        == evidence
    )
    with pytest.raises(OnlyCalculationEquivalenceError) as wrong_node:
        store.require_verified(
            calculation_node_fingerprint=second.fingerprint,
            reference=research.calculation_type_reference,
            research_implementation_fingerprint=research.implementation_fingerprint,
            trading_implementation_fingerprint=trading.implementation_fingerprint,
            certification_profile_fingerprint=profile.profile_fingerprint,
        )
    assert wrong_node.value.code == "EQUIVALENCE_EVIDENCE_NOT_FOUND"
    changed_profile = replace(profile, cases=tuple(sorted((*profile.cases, "SYSTEM_PROFILE_V2_CASE"))))
    with pytest.raises(OnlyCalculationEquivalenceError) as wrong_profile:
        store.require_verified(
            calculation_node_fingerprint=first.fingerprint,
            reference=research.calculation_type_reference,
            research_implementation_fingerprint=research.implementation_fingerprint,
            trading_implementation_fingerprint=trading.implementation_fingerprint,
            certification_profile_fingerprint=changed_profile.profile_fingerprint,
        )
    assert wrong_profile.value.code == "EQUIVALENCE_EVIDENCE_NOT_FOUND"


def test_legacy_v1_is_load_only_and_cannot_satisfy_admission(tmp_path) -> None:
    reader = OnlyLegacyCalculationEquivalenceEvidenceV1Reader(tmp_path / "semantic")
    assert not hasattr(reader, "require_verified")
    assert not hasattr(reader, "commit")
    assert not hasattr(reader, "publish")
