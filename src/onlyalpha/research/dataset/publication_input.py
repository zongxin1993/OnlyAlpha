"""Internal reader-issued input capability, distinct from portable evidence parsing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from weakref import WeakValueDictionary, finalize

from .sealed_input_evidence import OnlyRetainedSealedChartInputEvidenceV1


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _OnlyVerifiedSealedChartPublicationInput:
    retained: OnlyRetainedSealedChartInputEvidenceV1
    result_plan_fingerprint: str
    graph_fingerprint: str
    runtime_generation_fingerprint: str


_INPUTS: WeakValueDictionary[int, _OnlyVerifiedSealedChartPublicationInput] = WeakValueDictionary()
_ISSUANCE: dict[int, tuple[tuple[object, ...], Callable[[], OnlyRetainedSealedChartInputEvidenceV1]]] = {}


def _payload(value: _OnlyVerifiedSealedChartPublicationInput) -> tuple[object, ...]:
    return (
        value.retained.canonical_json,
        value.result_plan_fingerprint,
        value.graph_fingerprint,
        value.runtime_generation_fingerprint,
    )


def _only_issue_verified_sealed_chart_publication_input(
    retained: OnlyRetainedSealedChartInputEvidenceV1,
    result_plan_fingerprint: str,
    graph_fingerprint: str,
    runtime_generation_fingerprint: str,
    reverify: Callable[[], OnlyRetainedSealedChartInputEvidenceV1],
) -> _OnlyVerifiedSealedChartPublicationInput:
    """Only the owning Application export composes this hook after complete reads."""
    value = _OnlyVerifiedSealedChartPublicationInput(
        retained, result_plan_fingerprint, graph_fingerprint, runtime_generation_fingerprint
    )
    _INPUTS[id(value)] = value
    _ISSUANCE[id(value)] = (_payload(value), reverify)
    finalize(value, _ISSUANCE.pop, id(value), None)
    return value


def _only_require_verified_sealed_chart_publication_input(
    value: object,
    result_plan_fingerprint: str,
    graph_fingerprint: str,
    runtime_generation_fingerprint: str,
) -> OnlyRetainedSealedChartInputEvidenceV1:
    if type(value) is not _OnlyVerifiedSealedChartPublicationInput or _INPUTS.get(id(value)) is not value:
        raise ValueError("reader-issued sealed input required")
    issued = _ISSUANCE.get(id(value))
    if (
        issued is None
        or issued[0] != _payload(value)
        or value.result_plan_fingerprint != result_plan_fingerprint
        or value.graph_fingerprint != graph_fingerprint
        or value.runtime_generation_fingerprint != runtime_generation_fingerprint
    ):
        raise ValueError("issued sealed input context differs")
    if issued[1]().canonical_json != value.retained.canonical_json:
        raise ValueError("owning sealed input changed after export")
    return value.retained
