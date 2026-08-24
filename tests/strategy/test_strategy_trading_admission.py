from dataclasses import replace

import pytest

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationEquivalenceEvidenceV2Store,
    OnlyCalculationRegistry,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.research import OnlyResearchCalculationImplementationBinding
from onlyalpha.strategy import OnlyStrategyAdmissionError, OnlyStrategyTradingAdmissionService
from tests.strategy.p9_support import p9_strategy_case


def _registry_without(case, *, backend=None, manifest=True, state=True):
    result = OnlyCalculationRegistry()
    seen = set()
    for node in case.revision.decision_graph.nodes:
        definition = node.definition
        for current in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
            key = (definition.kind, definition.type_id, definition.semantic_version, current)
            if key in seen or current is backend:
                continue
            seen.add(key)
            registration = case.registry.resolve(*key)
            if not manifest:
                registration = replace(registration, implementation_manifest=None)
            if not state and current is OnlyCalculationBackendKind.TRADING:
                registration = replace(registration, state_capability=None, checkpoint_schema_version=None)
            result.register(registration)
    return result


def test_admission_requires_exact_trading_backend(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    service = OnlyStrategyTradingAdmissionService(
        _registry_without(case, backend=OnlyCalculationBackendKind.TRADING),
        case.equivalence,
    )

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        service.admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            case.revision.market_input_contract,
            case.execution_evidence[0],
        )
    assert error.value.code == "TRADING_BACKEND_UNAVAILABLE"


def test_admission_requires_resolved_implementation_identity(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    service = OnlyStrategyTradingAdmissionService(
        _registry_without(case, manifest=False),
        case.equivalence,
    )

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        service.admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            case.revision.market_input_contract,
            case.execution_evidence[0],
        )
    assert error.value.code == "IMPLEMENTATION_IDENTITY_UNRESOLVED"


def test_admission_rejects_unknown_calculation_state_capability(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    service = OnlyStrategyTradingAdmissionService(
        _registry_without(case, state=False),
        case.equivalence,
    )

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        service.admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            case.revision.market_input_contract,
            case.execution_evidence[0],
        )
    assert error.value.code == "CALCULATION_STATE_CAPABILITY_UNRESOLVED"


def test_admission_requires_explicit_equivalence_evidence(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    service = OnlyStrategyTradingAdmissionService(
        case.registry,
        OnlyCalculationEquivalenceEvidenceV2Store(tmp_path / "empty"),
    )

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        service.admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            case.revision.market_input_contract,
            case.execution_evidence[0],
        )
    assert error.value.code == "STRATEGY_NOT_TRADING_ADMISSIBLE"


@pytest.mark.parametrize("adjustment_type", (OnlyAdjustmentType.FORWARD, OnlyAdjustmentType.BACKWARD))
def test_admission_rejects_non_raw_market_input(tmp_path, adjustment_type) -> None:
    case = p9_strategy_case(tmp_path)
    adjusted = replace(
        case.revision.market_input_contract,
        adjustment_type=adjustment_type,
        adjustment_reference="2026-08-24",
    )

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        OnlyStrategyTradingAdmissionService(case.registry, case.equivalence).admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            adjusted,
            case.execution_evidence[0],
        )
    assert error.value.code == "STRATEGY_NOT_TRADING_ADMISSIBLE"


@pytest.mark.parametrize("role", ("eligibility", "entry", "exit"))
def test_admission_rejects_missing_or_invalid_required_signal_role(tmp_path, role) -> None:
    case = p9_strategy_case(tmp_path)
    signals = case.revision.signal_semantics
    invalid = replace(signals, **{role: signals.entry if role != "entry" else signals.exit})

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        OnlyStrategyTradingAdmissionService(case.registry, case.equivalence).admit(
            case.revision.decision_graph,
            invalid,
            case.revision.market_input_contract,
            case.execution_evidence[0],
        )
    assert error.value.code == "STRATEGY_NOT_TRADING_ADMISSIBLE"


def test_admission_uses_historical_evidence_without_current_research_backend(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
    admitted = OnlyStrategyTradingAdmissionService(
        _registry_without(case, backend=OnlyCalculationBackendKind.RESEARCH),
        case.equivalence,
    ).admit(
        case.revision.decision_graph,
        case.revision.signal_semantics,
        case.revision.market_input_contract,
        case.execution_evidence[0],
    )

    assert admitted.implementation_bindings == case.revision.implementation_bindings


@pytest.mark.parametrize("changed_backend", ("RESEARCH", "TRADING"))
def test_implementation_change_invalidates_existing_equivalence_v2(tmp_path, changed_backend) -> None:
    case = p9_strategy_case(tmp_path)
    registry = case.registry
    provenance = case.execution_evidence[0]
    if changed_backend == "RESEARCH":
        first = provenance.research_implementation_bindings[0]
        provenance = replace(
            provenance,
            research_implementation_bindings=(
                OnlyResearchCalculationImplementationBinding(first.node_fingerprint, "f" * 64),
                *provenance.research_implementation_bindings[1:],
            ),
        )
    else:
        registry = OnlyCalculationRegistry()
        changed_node = case.revision.decision_graph.ordered_nodes[0]
        seen = set()
        for node in case.revision.decision_graph.nodes:
            key = (node.definition.kind, node.definition.type_id, node.definition.semantic_version)
            if key in seen:
                continue
            seen.add(key)
            for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
                registration = case.registry.resolve(*key, backend)
                if (
                    key
                    == (
                        changed_node.definition.kind,
                        changed_node.definition.type_id,
                        changed_node.definition.semantic_version,
                    )
                    and backend is OnlyCalculationBackendKind.TRADING
                ):
                    assert registration.implementation_manifest is not None
                    registration = replace(
                        registration,
                        implementation_manifest=only_implementation_manifest_from_bytes(
                            calculation_type_reference=(
                                registration.implementation_manifest.calculation_type_reference
                            ),
                            backend_kind=backend,
                            entrypoint_identity=registration.implementation_manifest.entrypoint_identity,
                            resources={"changed.py": b"trading-v2"},
                        ),
                    )
                registry.register(registration)

    with pytest.raises(OnlyStrategyAdmissionError) as error:
        OnlyStrategyTradingAdmissionService(registry, case.equivalence).admit(
            case.revision.decision_graph,
            case.revision.signal_semantics,
            case.revision.market_input_contract,
            provenance,
        )
    assert error.value.code == "STRATEGY_NOT_TRADING_ADMISSIBLE"
