from dataclasses import replace
from decimal import Decimal
from inspect import signature

import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.application import OnlyCalculationEquivalenceCertificationApplicationService
from onlyalpha.application.calculation_equivalence import _required_certification_horizon
from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationEquivalenceError,
    OnlyCalculationEquivalenceEvidenceV2Store,
    OnlyCalculationNodeDefinition,
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
        if item.definition.type_id.startswith("example.factor.")
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


def _registry_with_late_trading_divergence(type_id: str, fail_at: int) -> OnlyCalculationRegistry:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        if (
            registration.backend is OnlyCalculationBackendKind.TRADING
            and registration.type_definition.type_id == type_id
        ):

            class _LateDivergenceFactory:
                def create(self, definition, request):
                    del request

                    class _LateDivergence:
                        def __init__(self):
                            self.values = []
                            self.ema = None

                        def update(self, inputs):
                            value = Decimal(str(inputs["value"]))
                            self.values.append(value)
                            if definition.type_id.endswith(".ema"):
                                alpha = Decimal(2) / Decimal(int(str(definition.parameters["period"])) + 1)
                                self.ema = value if self.ema is None else self.ema + alpha * (value - self.ema)
                                output = self.ema.quantize(Decimal("0.000000000001"))
                            else:
                                period = int(str(definition.parameters["period"]))
                                output = (
                                    None
                                    if len(self.values) <= period or self.values[-period - 1] == 0
                                    else (self.values[-1] / self.values[-period - 1] - 1).quantize(
                                        Decimal("0.000000000001")
                                    )
                                )
                            if len(self.values) == fail_at and output is not None:
                                output += Decimal("0.000000000001")
                            return {"value": output}

                    return _LateDivergence()

            registration = replace(registration, provider=_LateDivergenceFactory())
        registry.register(registration)
    return registry


@pytest.mark.parametrize("fail_offset", (0, 1))
def test_rolling_first_ready_and_eviction_late_divergence_fail_certification(tmp_path, fail_offset) -> None:
    period = 20
    definition = resolve_definition(
        next(item for item in TYPES if item.type_id.endswith(".rolling_return")), {"period": period}
    )
    node = OnlyCalculationNodeDefinition(definition)
    service = OnlyCalculationEquivalenceCertificationApplicationService(
        _registry_with_late_trading_divergence(definition.type_id, period + 1 + fail_offset),
        OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / f"semantic-{fail_offset}"),
    )
    with pytest.raises(OnlyCalculationEquivalenceError) as error:
        service.certify(node)
    assert error.value.code == "EQUIVALENCE_CERTIFICATION_FAILED"


def test_recursive_late_divergence_after_warmup_fails_certification(tmp_path) -> None:
    period = 20
    definition = resolve_definition(next(item for item in TYPES if item.type_id.endswith(".ema")), {"period": period})
    node = OnlyCalculationNodeDefinition(definition)
    service = OnlyCalculationEquivalenceCertificationApplicationService(
        _registry_with_late_trading_divergence(definition.type_id, period + 3),
        OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "semantic"),
    )
    with pytest.raises(OnlyCalculationEquivalenceError) as error:
        service.certify(node)
    assert error.value.code == "EQUIVALENCE_CERTIFICATION_FAILED"


def test_exact_parameters_change_state_horizon_corpus_and_evidence(tmp_path) -> None:
    rolling = next(item for item in TYPES if item.type_id.endswith(".rolling_return"))
    short = OnlyCalculationNodeDefinition(resolve_definition(rolling, {"period": 2}))
    long = OnlyCalculationNodeDefinition(resolve_definition(rolling, {"period": 20}))
    assert short.fingerprint != long.fingerprint
    assert _required_certification_horizon(short.definition).observation_count == 5
    assert _required_certification_horizon(long.definition).observation_count == 23
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    service = OnlyCalculationEquivalenceCertificationApplicationService(
        registry, OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "semantic")
    )
    short_evidence = service.certify(short)
    long_evidence = service.certify(long)
    assert short_evidence.corpus_fingerprint != long_evidence.corpus_fingerprint
    assert short_evidence.evidence_fingerprint != long_evidence.evidence_fingerprint
