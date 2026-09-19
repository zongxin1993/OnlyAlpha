"""Fail-closed Trading admission for exact Research candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from onlyalpha.calculation.registry import OnlyCalculationRegistry
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


@dataclass(frozen=True, order=True, slots=True)
class OnlyRuntimeStrategyTradingNodeBindingV1:
    node_fingerprint: str
    kind: str
    type_id: str
    semantic_version: str
    research_implementation_fingerprint: str
    trading_implementation_fingerprint: str
    state_capability: OnlyCalculationStateCapability
    checkpoint_schema_version: int | None

    def __post_init__(self) -> None:
        for value in (
            self.node_fingerprint,
            self.research_implementation_fingerprint,
            self.trading_implementation_fingerprint,
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        if not self.kind or not self.type_id or not self.semantic_version:
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        if (
            self.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE
            and self.checkpoint_schema_version is None
        ) or (
            self.state_capability is OnlyCalculationStateCapability.STATELESS
            and self.checkpoint_schema_version is not None
        ):
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "node_fingerprint": self.node_fingerprint,
            "kind": self.kind,
            "type_id": self.type_id,
            "semantic_version": self.semantic_version,
            "research_implementation_fingerprint": self.research_implementation_fingerprint,
            "trading_implementation_fingerprint": self.trading_implementation_fingerprint,
            "state_capability": self.state_capability.value,
            "checkpoint_schema_version": self.checkpoint_schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRuntimeStrategyTradingNodeBindingV1:
        expected = {
            "node_fingerprint",
            "kind",
            "type_id",
            "semantic_version",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "state_capability",
            "checkpoint_schema_version",
        }
        if set(payload) != expected:
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        checkpoint = payload["checkpoint_schema_version"]
        if checkpoint is not None and (isinstance(checkpoint, bool) or not isinstance(checkpoint, int)):
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        try:
            return cls(
                _string(payload, "node_fingerprint"),
                _string(payload, "kind"),
                _string(payload, "type_id"),
                _string(payload, "semantic_version"),
                _string(payload, "research_implementation_fingerprint"),
                _string(payload, "trading_implementation_fingerprint"),
                OnlyCalculationStateCapability(_string(payload, "state_capability")),
                checkpoint,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID") from exc


@dataclass(frozen=True, slots=True)
class OnlyRuntimeStrategyTradingResolutionV1:
    runtime_generation_fingerprint: str
    calculation_graph_fingerprint: str
    node_bindings: tuple[OnlyRuntimeStrategyTradingNodeBindingV1, ...]

    def __post_init__(self) -> None:
        for value in (self.runtime_generation_fingerprint, self.calculation_graph_fingerprint):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        canonical = tuple(sorted(self.node_bindings))
        if canonical != self.node_bindings or len({item.node_fingerprint for item in canonical}) != len(canonical):
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "calculation_graph_fingerprint": self.calculation_graph_fingerprint,
            "node_bindings": [item.to_dict() for item in self.node_bindings],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRuntimeStrategyTradingResolutionV1:
        if set(payload) != {"runtime_generation_fingerprint", "calculation_graph_fingerprint", "node_bindings"}:
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        bindings = payload["node_bindings"]
        if not isinstance(bindings, list) or any(not isinstance(item, Mapping) for item in bindings):
            raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
        return cls(
            _string(payload, "runtime_generation_fingerprint"),
            _string(payload, "calculation_graph_fingerprint"),
            tuple(OnlyRuntimeStrategyTradingNodeBindingV1.from_dict(item) for item in bindings),
        )


def only_resolve_runtime_strategy_trading(
    *,
    runtime_generation_fingerprint: str,
    calculations: OnlyCalculationRegistry,
    graph: OnlyCalculationGraphDefinition,
    signals: OnlyStrategySignalSemantics,
    market_input_contract: OnlyStrategyMarketInputContract,
    research_implementation_bindings: Sequence[_ResearchImplementationBinding],
) -> OnlyRuntimeStrategyTradingResolutionV1:
    OnlyStrategyTradingAdmissionService._validate_strategy_semantics(graph, signals, market_input_contract)
    historical = {
        item.node_fingerprint: item.research_implementation_fingerprint for item in research_implementation_bindings
    }
    if set(historical) != {item.fingerprint for item in graph.nodes}:
        raise OnlyStrategyAdmissionError(
            "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
            "historical Research implementation bindings differ from exact Calculation Graph",
        )
    bindings: list[OnlyRuntimeStrategyTradingNodeBindingV1] = []
    for node in graph.ordered_nodes:
        reference = OnlyCalculationTypeReference(
            node.definition.kind,
            node.definition.type_id,
            node.definition.semantic_version,
        )
        try:
            trading = calculations.resolve(
                reference.kind,
                reference.type_id,
                reference.semantic_version,
                OnlyCalculationBackendKind.TRADING,
            )
        except ValueError as exc:
            raise OnlyStrategyAdmissionError("TRADING_BACKEND_UNAVAILABLE", str(exc)) from exc
        if trading.implementation_manifest is None:
            raise OnlyStrategyAdmissionError(
                "IMPLEMENTATION_IDENTITY_UNRESOLVED",
                f"exact implementation identity is unavailable for {reference.type_id}@{reference.semantic_version}",
            )
        if trading.state_capability is None or (
            trading.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE
            and trading.checkpoint_schema_version is None
        ):
            raise OnlyStrategyAdmissionError(
                "CALCULATION_STATE_CAPABILITY_UNRESOLVED",
                f"{reference.type_id}@{reference.semantic_version}",
            )
        bindings.append(
            OnlyRuntimeStrategyTradingNodeBindingV1(
                node.fingerprint,
                reference.kind.value,
                reference.type_id,
                reference.semantic_version,
                historical[node.fingerprint],
                trading.implementation_manifest.implementation_fingerprint,
                trading.state_capability,
                trading.checkpoint_schema_version,
            )
        )
    return OnlyRuntimeStrategyTradingResolutionV1(
        runtime_generation_fingerprint,
        graph.fingerprint,
        tuple(sorted(bindings)),
    )


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
        resolution = only_resolve_runtime_strategy_trading(
            runtime_generation_fingerprint="0" * 64,
            calculations=self._calculations,
            graph=graph,
            signals=signals,
            market_input_contract=market_input_contract,
            research_implementation_bindings=research_execution_evidence.research_implementation_bindings,
        )
        return self.admit_resolved(
            graph,
            signals,
            market_input_contract,
            research_execution_evidence,
            resolution,
        )

    def admit_resolved(
        self,
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        market_input_contract: OnlyStrategyMarketInputContract,
        research_execution_evidence: _ResearchCalculationExecutionEvidence,
        resolution: OnlyRuntimeStrategyTradingResolutionV1,
    ) -> OnlyStrategyAdmission:
        self._validate_strategy_semantics(graph, signals, market_input_contract)
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
        if resolution.calculation_graph_fingerprint != graph.fingerprint:
            self._fail("IMPLEMENTATION_IDENTITY_MISMATCH", "Runtime Trading resolution names another graph")
        resolved = {item.node_fingerprint: item for item in resolution.node_bindings}
        if set(resolved) != set(historical):
            self._fail("IMPLEMENTATION_IDENTITY_MISMATCH", "Runtime Trading resolution node closure differs")
        bindings: list[OnlyStrategyImplementationBinding] = []
        evidence: list[str] = []
        for node in graph.ordered_nodes:
            definition = node.definition
            reference = OnlyCalculationTypeReference(definition.kind, definition.type_id, definition.semantic_version)
            research_fingerprint = historical[node.fingerprint]
            binding = resolved[node.fingerprint]
            if (
                binding.kind != definition.kind.value
                or binding.type_id != definition.type_id
                or binding.semantic_version != definition.semantic_version
                or binding.research_implementation_fingerprint != research_fingerprint
            ):
                self._fail("IMPLEMENTATION_IDENTITY_MISMATCH", "Runtime Trading resolution semantics differ")
            trading_fingerprint = binding.trading_implementation_fingerprint
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

    @staticmethod
    def _validate_strategy_semantics(
        graph: OnlyCalculationGraphDefinition,
        signals: OnlyStrategySignalSemantics,
        market_input_contract: OnlyStrategyMarketInputContract,
    ) -> None:
        if (
            market_input_contract.adjustment_type is not OnlyAdjustmentType.RAW
            or market_input_contract.adjustment_reference is not None
        ):
            raise OnlyStrategyAdmissionError(
                "STRATEGY_NOT_TRADING_ADMISSIBLE",
                "P9.0 Trading Strategy input must be RAW without an adjustment reference",
            )
        for node in graph.ordered_nodes:
            definition = node.definition
            if definition.kind is OnlyCalculationKind.TARGET:
                raise OnlyStrategyAdmissionError(
                    "STRATEGY_NOT_TRADING_ADMISSIBLE", "TARGET/future semantics cannot enter Strategy"
                )
            if definition.timestamp is not OnlyTimestampSemantic.EVENT_TIME:
                raise OnlyStrategyAdmissionError(
                    "STRATEGY_NOT_TRADING_ADMISSIBLE", "Strategy calculations must use causal event time"
                )
            if definition.factor_kind is OnlyFactorKind.CROSS_SECTION:
                raise OnlyStrategyAdmissionError(
                    "STRATEGY_NOT_TRADING_ADMISSIBLE", "P9.0 does not admit cross-section Trading execution"
                )
            unsupported = sorted(
                {
                    reference.source
                    for reference in definition.input_bindings.values()
                    if reference.source is not None and reference.source not in _BAR_SOURCES
                }
            )
            if unsupported:
                raise OnlyStrategyAdmissionError(
                    "STRATEGY_NOT_TRADING_ADMISSIBLE", f"unsupported market input: {unsupported[0]}"
                )
        by_node = {node.fingerprint: node.definition for node in graph.nodes}
        for role, binding, semantic_type in (
            ("ELIGIBILITY", signals.eligibility, "ELIGIBILITY"),
            ("ENTRY", signals.entry, "ENTRY_SIGNAL"),
            ("EXIT", signals.exit, "EXIT_SIGNAL"),
        ):
            signal_definition = by_node.get(binding.node_fingerprint)
            output = (
                None
                if signal_definition is None
                else next((item for item in signal_definition.outputs if item.name == binding.output_name), None)
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


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError("RUNTIME_STRATEGY_TRADING_RESOLUTION_INVALID")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
