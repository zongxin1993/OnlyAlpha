from __future__ import annotations

from copy import deepcopy

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.run import OnlyResearchRunAdmissionError
from onlyalpha.research.run.evidence import (
    OnlyResearchAdmissionResolutionEvidence,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
    OnlyResearchSpecificationResolver,
)
from tests.research.specification.support import registry, specification


def _resolution(version: int):  # type: ignore[no-untyped-def]
    spec = specification()
    if version == 2:
        spec = OnlyResearchSpecification(
            spec.dataset_snapshot_fingerprint,
            spec.calculations,
            spec.statistics,
            OnlyResearchScientificEvidenceSpec(
                "feature",
                (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
                OnlyResearchSignalEvidenceSpec(),
            ),
            2,
        )
    return OnlyResearchSpecificationResolver(registry()).resolve(spec)


@pytest.mark.parametrize(
    "version,pinned",
    [
        (1, "77323c359cc557260cd8aac70fd6313f31f1b49d93b9be2b8661470a7228eb15"),
        (2, "66f39fecb140bdda81249bfcb3e6b8283644002cd0abb607825552a1452a1e96"),
    ],
)
def test_projection_preserves_historical_admission_fingerprint_bytes(version: int, pinned: str) -> None:
    resolution = _resolution(version)
    # Independently retained pre-projection algorithm: persisted Runs must replay
    # the same bytes, including V1 omission versus V2 nullable candidate identity.
    payload: dict[str, object] = {
        "schema_version": version,
        "specification_fingerprint": resolution.specification_fingerprint,
        "candidates": [
            {
                "calculation_id": item.calculation_id,
                "assignment": item.assignment,
                "graph_fingerprint": item.graph_fingerprint,
                "calculation_fingerprint": item.calculation_fingerprint,
                "node_fingerprints": item.node_fingerprints,
                **({"candidate_fingerprint": item.candidate_fingerprint} if version == 2 else {}),
            }
            for item in resolution.candidates
        ],
        "statistics_fingerprints": [item.statistics_fingerprint for item in resolution.statistics],
        "research_result_plan_fingerprint": resolution.workload.result_plan.fingerprint,
    }
    if version == 2:
        payload["published_series"] = resolution.published_series
        payload["signals"] = resolution.signals
    evidence = OnlyResearchAdmissionResolutionEvidence.from_resolution(resolution)
    assert only_canonical_fingerprint(payload) == pinned
    assert evidence.fingerprint == pinned
    assert only_research_admission_resolution_fingerprint(resolution) == pinned
    assert OnlyResearchAdmissionResolutionEvidence.from_dict(evidence.to_dict()) == evidence


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p.update(schema_version=3),
        lambda p: p.update(unexpected=True),
        lambda p: p.update(specification_fingerprint="INVALID"),
        lambda p: p["candidates"][0].update(graph=object()),
        lambda p: p["candidates"][0].update(graph_fingerprint="A" * 64),
        lambda p: p["candidates"][0].update(assignment={"x": object()}),
        lambda p: p["published_series"][0].update(output_name=1),
        lambda p: p.update(signals=[{"role": "OTHER"}]),
    ],
)
def test_projection_rejects_noncanonical_or_executable_payload(change) -> None:  # type: ignore[no-untyped-def]
    payload = OnlyResearchAdmissionResolutionEvidence.from_resolution(_resolution(2)).to_dict()
    change(payload)
    with pytest.raises(OnlyResearchRunAdmissionError) as error:
        OnlyResearchAdmissionResolutionEvidence.from_dict(payload)
    assert error.value.code == "RESEARCH_ADMISSION_EVIDENCE_INVALID"


def test_projection_cannot_be_mutated_through_nested_input_or_output() -> None:
    original = OnlyResearchAdmissionResolutionEvidence.from_resolution(_resolution(2))
    payload = original.to_dict()
    evidence = OnlyResearchAdmissionResolutionEvidence.from_dict(payload)
    modified = deepcopy(payload)
    modified["specification_fingerprint"] = "f" * 64
    payload.clear()
    evidence.to_dict().clear()
    assert evidence == original
    assert OnlyResearchAdmissionResolutionEvidence.from_dict(modified).fingerprint != evidence.fingerprint
