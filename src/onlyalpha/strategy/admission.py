"""Fail-closed Trading admission for exact Research candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
    OnlyFactorKind,
    OnlyTimestampSemantic,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.strategy.errors import OnlyStrategyAdmissionError
from onlyalpha.strategy.revision import (
    OnlyStrategyImplementationBinding,
    OnlyStrategySignalSemantics,
)


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationEquivalenceAdmission:
    calculation_type_reference: OnlyCalculationTypeReference
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    evidence_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("Research implementation", self.research_implementation_fingerprint),
            ("Trading implementation", self.trading_implementation_fingerprint),
            ("equivalence evidence", self.evidence_fingerprint),
        ):
            _sha(value, name)


class OnlyCalculationEquivalenceAdmissionRegistry:
    """Explicit evidence authority; evidence never enters Strategy identity."""

    def __init__(self) -> None:
        self._admissions: dict[tuple[OnlyCalculationTypeReference, str, str], OnlyCalculationEquivalenceAdmission] = {}

    def register(self, admission: OnlyCalculationEquivalenceAdmission) -> None:
        key = (
            admission.calculation_type_reference,
            admission.research_implementation_fingerprint,
            admission.trading_implementation_fingerprint,
        )
        existing = self._admissions.get(key)
        if existing is not None and existing != admission:
            raise ValueError("Calculation equivalence evidence conflicts")
        self._admissions[key] = admission

    def require(
        self,
        reference: OnlyCalculationTypeReference,
        research_implementation_fingerprint: str,
        trading_implementation_fingerprint: str,
    ) -> OnlyCalculationEquivalenceAdmission:
        try:
            return self._admissions[
                (reference, research_implementation_fingerprint, trading_implementation_fingerprint)
            ]
        except KeyError as exc:
            raise OnlyStrategyAdmissionError(
                "STRATEGY_NOT_TRADING_ADMISSIBLE",
                f"semantic equivalence evidence is unavailable for {reference.type_id}@{reference.semantic_version}",
            ) from exc


@dataclass(frozen=True, slots=True)
class OnlyStrategyAdmission:
    implementation_bindings: tuple[OnlyStrategyImplementationBinding, ...]
    admission_evidence_fingerprint: str


class OnlyStrategyTradingAdmissionService:
    def __init__(
        self,
        calculations: OnlyCalculationRegistry,
        equivalence: OnlyCalculationEquivalenceAdmissionRegistry,
    ) -> None:
        self._calculations = calculations
        self._equivalence = equivalence

    def admit(
        self,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
    ) -> OnlyStrategyAdmission:
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
            research = self._registration(reference, OnlyCalculationBackendKind.RESEARCH)
            trading = self._registration(reference, OnlyCalculationBackendKind.TRADING)
            if research.implementation_manifest is None or trading.implementation_manifest is None:
                self._fail(
                    "IMPLEMENTATION_IDENTITY_UNRESOLVED",
                    f"exact implementation identity is unavailable for {definition.type_id}@{definition.semantic_version}",
                )
            research_fingerprint = research.implementation_manifest.implementation_fingerprint
            trading_fingerprint = trading.implementation_manifest.implementation_fingerprint
            admitted = self._equivalence.require(reference, research_fingerprint, trading_fingerprint)
            bindings.append(
                OnlyStrategyImplementationBinding(node.fingerprint, research_fingerprint, trading_fingerprint)
            )
            evidence.append(admitted.evidence_fingerprint)
        self._validate_signals(graph, signals)
        canonical = tuple(sorted(bindings))
        return OnlyStrategyAdmission(
            canonical,
            only_canonical_fingerprint(
                {
                    "domain": "onlyalpha.strategy.trading-admission-evidence",
                    "schema_version": 1,
                    "evidence_fingerprints": sorted(evidence),
                }
            ),
        )

    def verify_revision_bindings(
        self,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        expected: tuple[OnlyStrategyImplementationBinding, ...],
    ) -> None:
        actual = self.admit(graph, signals).implementation_bindings
        if actual != expected:
            self._fail("IMPLEMENTATION_IDENTITY_MISMATCH", "current Calculation implementation differs from Revision")

    def _registration(
        self, reference: OnlyCalculationTypeReference, backend: OnlyCalculationBackendKind
    ) -> OnlyCalculationBackendRegistration:
        try:
            return self._calculations.resolve(
                reference.kind,
                reference.type_id,
                reference.semantic_version,
                backend,
            )
        except ValueError as exc:
            code = (
                "TRADING_BACKEND_UNAVAILABLE"
                if backend is OnlyCalculationBackendKind.TRADING
                else "RESEARCH_BACKEND_UNAVAILABLE"
            )
            self._fail(code, str(exc), exc)

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


def _sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


__all__ = [name for name in globals() if name.startswith("Only")]
