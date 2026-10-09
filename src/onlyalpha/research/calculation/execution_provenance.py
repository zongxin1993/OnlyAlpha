"""Structural Runtime provenance and native, process-local execution context issuance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from weakref import WeakValueDictionary, finalize

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.dataset.strict import require_int, require_sha256, require_str

from .errors import OnlyResearchCalculationError

_CONTEXT = "Runtime execution provenance"


@dataclass(frozen=True, slots=True)
class OnlyResearchRuntimeExecutionProvenanceV1:
    runtime_generation_fingerprint: str
    validation_evidence_fingerprint: str
    core_execution_fingerprint: str
    catalog_generation_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Runtime execution provenance schema")
        for name in (
            "runtime_generation_fingerprint",
            "validation_evidence_fingerprint",
            "core_execution_fingerprint",
            "catalog_generation_fingerprint",
        ):
            require_sha256({name: getattr(self, name)}, name, _CONTEXT)

    def to_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchRuntimeExecutionProvenanceV1:
        if not isinstance(payload, Mapping) or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("Runtime execution provenance fields differ")
        return cls(
            require_str(payload, "runtime_generation_fingerprint", _CONTEXT),
            require_str(payload, "validation_evidence_fingerprint", _CONTEXT),
            require_str(payload, "core_execution_fingerprint", _CONTEXT),
            require_str(payload, "catalog_generation_fingerprint", _CONTEXT),
            require_int(payload, "schema_version", _CONTEXT),
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _OnlyResearchRuntimeExecutionContext:
    provenance: OnlyResearchRuntimeExecutionProvenanceV1
    graph_fingerprint: str
    implementation_bindings: tuple[tuple[str, str], ...]


_CONTEXTS: WeakValueDictionary[int, _OnlyResearchRuntimeExecutionContext] = WeakValueDictionary()
_ISSUANCE: dict[int, tuple[OnlyResearchRuntimeExecutionProvenanceV1, tuple[tuple[str, str], ...], str]] = {}


def _context_payload(context: _OnlyResearchRuntimeExecutionContext) -> str:
    return only_canonical_json(
        {
            "provenance": context.provenance.to_dict(),
            "graph_fingerprint": context.graph_fingerprint,
            "implementation_bindings": context.implementation_bindings,
        }
    )


def _only_issue_research_runtime_execution_context(
    provenance: OnlyResearchRuntimeExecutionProvenanceV1,
    graph_fingerprint: str,
    implementation_bindings: tuple[tuple[str, str], ...],
) -> _OnlyResearchRuntimeExecutionContext:
    """Internal trusted-composition hook; never a public DTO-to-capability API."""
    if type(provenance) is not OnlyResearchRuntimeExecutionProvenanceV1:
        raise ValueError("exact Runtime provenance contract required")
    provenance = OnlyResearchRuntimeExecutionProvenanceV1.from_dict(provenance.to_dict())
    require_sha256({"graph": graph_fingerprint}, "graph", _CONTEXT)
    if (
        type(implementation_bindings) is not tuple
        or not implementation_bindings
        or any(type(item) is not tuple or len(item) != 2 for item in implementation_bindings)
        or implementation_bindings != tuple(sorted(implementation_bindings))
        or len({item[0] for item in implementation_bindings}) != len(implementation_bindings)
    ):
        raise ValueError("canonical unique implementation bindings required")
    for node, implementation in implementation_bindings:
        require_sha256({"node": node}, "node", _CONTEXT)
        require_sha256({"implementation": implementation}, "implementation", _CONTEXT)
    context = _OnlyResearchRuntimeExecutionContext(provenance, graph_fingerprint, implementation_bindings)
    _CONTEXTS[id(context)] = context
    _ISSUANCE[id(context)] = (context.provenance, context.implementation_bindings, _context_payload(context))
    finalize(context, _ISSUANCE.pop, id(context), None)
    return context


def _only_require_research_runtime_execution_context(
    value: object,
    graph_fingerprint: str,
) -> _OnlyResearchRuntimeExecutionContext:
    if type(value) is not _OnlyResearchRuntimeExecutionContext or _CONTEXTS.get(id(value)) is not value:
        raise OnlyResearchCalculationError(
            "RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED", "issued Runtime context required"
        )
    try:
        issued = _ISSUANCE.get(id(value))
        valid = (
            issued is not None
            and value.graph_fingerprint == graph_fingerprint
            and value.provenance is issued[0]
            and value.implementation_bindings is issued[1]
            and issued[2] == _context_payload(value)
        )
    except (AttributeError, TypeError, ValueError):
        valid = False
    if not valid:
        raise OnlyResearchCalculationError("RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED", "Runtime context changed")
    return value
