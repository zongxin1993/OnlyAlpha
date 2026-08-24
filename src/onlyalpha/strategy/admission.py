"""Fail-closed Trading admission for exact Research candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn, Protocol

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.equivalence import (
    OnlyCalculationEquivalenceError,
    OnlyCalculationEquivalenceEvidenceV2,
    only_required_calculation_equivalence_profile,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.strategy.errors import OnlyStrategyAdmissionError
from onlyalpha.strategy.revision import (
    OnlyStrategyImplementationBinding,
    OnlyStrategyMarketInputContract,
    OnlyStrategySignalSemantics,
)


class OnlyCalculationEquivalenceEvidenceReader(Protocol):
    def require_verified(
        self,
        *,
        calculation_node_fingerprint: str,
        reference: OnlyCalculationTypeReference,
        research_implementation_fingerprint: str,
        trading_implementation_fingerprint: str,
        certification_profile_fingerprint: str,
    ) -> OnlyCalculationEquivalenceEvidenceV2: ...


class _ResearchImplementationBinding(Protocol):
    @property
    def node_fingerprint(self) -> str: ...

    @property
    def research_implementation_fingerprint(self) -> str: ...


class _ResearchCalculationExecutionEvidence(Protocol):
    @property
    def calculation_graph_fingerprint(self) -> str: ...

    @property
    def research_implementation_bindings(self) -> Sequence[_ResearchImplementationBinding]: ...


@dataclass(frozen=True, slots=True)
class OnlyStrategyAdmission:
    implementation_bindings: tuple[OnlyStrategyImplementationBinding, ...]
    equivalence_evidence_fingerprints: tuple[str, ...]
    admission_evidence_fingerprint: str


class OnlyStrategyTradingAdmissionService:
    def __init__(
        self,
        calculations: OnlyCalculationRegistry,
        equivalence: OnlyCalculationEquivalenceEvidenceReader,
    ) -> None:
        self._calculations = calculations
        self._equivalence = equivalence

    def admit(
        self,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        market_input_contract: OnlyStrategyMarketInputContract,
        research_execution_evidence: _ResearchCalculationExecutionEvidence,
    ) -> OnlyStrategyAdmission:
        if (
            market_input_contract.adjustment_type is not OnlyAdjustmentType.RAW
            or market_input_contract.adjustment_reference is not None
        ):
            self._fail(
                "STRATEGY_NOT_TRADING_ADMISSIBLE",
                "P9.0 Trading Strategy input must be RAW without an adjustment reference",
            )
        historical = {
            item.node_fingerprint: item.research_implementation_fingerprint
            for item in research_execution_evidence.research_implementation_bindings
        }
        if research_execution_evidence.calculation_graph_fingerprint != graph.fingerprint or set(historical) != {
            item.fingerprint for item in graph.nodes
        }:
            self._fail(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                "historical Research implementation bindings differ from exact Calculation Graph",
            )
        bindings: list[OnlyStrategyImplementationBinding] = []
        evidence: list[str] = []
        for node in graph.ordered_nodes:
            definition = node.definition
            if definition.kind is OnlyCalculationKind.TARGET:
                self._fail("STRATEGY_NOT_TRADING_ADMISSIBLE", "TARGET/future semantics cannot enter Strategy")
            if definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME:
                self._fail("STRATEGY_NOT_TRADING_ADMISSIBLE", "Strategy calculations must use causal event time")
            if definition.factor_kind is OnlyFactorKind.CROSS_SECTION:
                self._fail("STRATEGY_NOT_TRADING_ADMISSIBLE", "P9.0 does not admit cross-section Trading execution")
            unsupported = sorted(
                {
                    reference.source
                    for reference in definition.input_bindings.values()
                    if reference.source is not None and reference.source not in _BAR_SOURCES
                }
            )
            if unsupported:
                self._fail("STRATEGY_NOT_TRADING_ADMISSIBLE", f"unsupported market input: {unsupported[0]}")
            reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
            trading = self._trading_registration(reference)
            if trading.implementation_manifest is None:
                self._fail(
                    "IMPLEMENTATION_IDENTITY_UNRESOLVED",
                    f"exact implementation identity is unavailable for {definition.type_id}@{definition.semantic_version}",
                )
            if trading.state_capability is None:
                self._fail(
                    "CALCULATION_STATE_CAPABILITY_UNRESOLVED",
                    f"{definition.type_id}@{definition.semantic_version}",
                )
            if (
                trading.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE
                and trading.checkpoint_schema_version is None
            ):
                self._fail(
                    "CALCULATION_STATE_CAPABILITY_UNRESOLVED",
                    f"{definition.type_id}@{definition.semantic_version}",
                )
            research_fingerprint = historical[node.fingerprint]
            trading_fingerprint = trading.implementation_manifest.implementation_fingerprint
            try:
                profile = only_required_calculation_equivalence_profile(definition)
            except OnlyCalculationEquivalenceError as exc:
                self._fail(exc.code, exc.detail, exc)
            try:
                admitted = self._equivalence.require_verified(
                    calculation_node_fingerprint=node.fingerprint,
                    reference=reference,
                    research_implementation_fingerprint=research_fingerprint,
                    trading_implementation_fingerprint=trading_fingerprint,
                    certification_profile_fingerprint=profile.profile_fingerprint,
                )
            except OnlyCalculationEquivalenceError as exc:
                code = "STRATEGY_NOT_TRADING_ADMISSIBLE" if exc.code == "EQUIVALENCE_EVIDENCE_NOT_FOUND" else exc.code
                self._fail(code, exc.detail, exc)
            bindings.append(
                OnlyStrategyImplementationBinding(node.fingerprint, research_fingerprint, trading_fingerprint)
            )
            evidence.append(admitted.evidence_fingerprint)
        self._validate_signals(graph, signals)
        canonical = tuple(sorted(bindings))
        evidence_fingerprints = tuple(sorted(set(evidence)))
        return OnlyStrategyAdmission(
            canonical,
            evidence_fingerprints,
            only_canonical_fingerprint(
                {
                    "domain": "onlyalpha.strategy.trading-admission-evidence",
                    "schema_version": 1,
                    "evidence_fingerprints": evidence_fingerprints,
                }
            ),
        )

    def verify_revision_bindings(
        self,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        market_input_contract: OnlyStrategyMarketInputContract,
        expected: tuple[OnlyStrategyImplementationBinding, ...],
        research_execution_evidence: _ResearchCalculationExecutionEvidence,
    ) -> None:
        actual = self.admit(graph, signals, market_input_contract, research_execution_evidence).implementation_bindings
        if actual != expected:
            self._fail("IMPLEMENTATION_IDENTITY_MISMATCH", "current Calculation implementation differs from Revision")

    def _trading_registration(self, reference: OnlyCalculationTypeReference) -> OnlyCalculationBackendRegistration:
        try:
            return self._calculations.resolve(
                reference.kind,
                reference.type_id,
                reference.semantic_version,
                OnlyCalculationBackendKind.TRADING,
            )
        except ValueError as exc:
            self._fail("TRADING_BACKEND_UNAVAILABLE", str(exc), exc)

    @staticmethod
    def _validate_signals(graph: OnlyCalculationGraphDefinition, signals: OnlyStrategySignalSemantics) -> None:
        by_node = {node.fingerprint: node.definition for node in graph.nodes}
        for role, binding, semantic_type in (
            ("ELIGIBILITY", signals.eligibility, "ELIGIBILITY"),
            ("ENTRY", signals.entry, "ENTRY_SIGNAL"),
            ("EXIT", signals.exit, "EXIT_SIGNAL"),
        ):
            definition = by_node.get(binding.node_fingerprint)
            output = (
                None
                if definition is None
                else next((item for item in definition.outputs if item.name == binding.output_name), None)
            )
            if output is None or output.semantic_type != semantic_type or output.data_type.value != "BOOLEAN":
                raise OnlyStrategyAdmissionError(
                    "STRATEGY_NOT_TRADING_ADMISSIBLE",
                    f"missing or invalid {role} binding",
                )

    @staticmethod
    def _fail(code: str, detail: str, cause: Exception | None = None) -> NoReturn:
        error = OnlyStrategyAdmissionError(code, detail)
        if cause is None:
            raise error
        raise error from cause


_BAR_SOURCES = frozenset(
    {
        "bar.open",
        "bar.high",
        "bar.low",
        "bar.close",
        "bar.volume",
        "bar.quote_volume",
        "bar.turnover",
        "bar.trade_count",
        "bar.open_interest",
    }
)


__all__ = [name for name in globals() if name.startswith("Only")]
