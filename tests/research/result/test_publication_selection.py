from __future__ import annotations

import pytest


def test_publication_selection_round_trip_and_execution_contract():
    from onlyalpha.research.calculation.publication import (
        OnlyResearchCalculationPublicationContract,
        OnlyResearchCalculationPublicationSelectionV1,
    )

    selection = OnlyResearchCalculationPublicationSelectionV1()
    assert selection.execution_contract == OnlyResearchCalculationPublicationContract()
    assert OnlyResearchCalculationPublicationSelectionV1.from_dict(selection.to_dict()) == selection


@pytest.mark.parametrize(
    "key,value",
    (
        ("artifact_profile", "RESEARCH_CALCULATION_V1"),
        ("calculation_result_schema_version", 1),
        ("execution_evidence_schema_version", 1),
        ("readiness_contract_version", 0),
        ("readiness_contract_version", True),
        ("extra", 1),
    ),
)
def test_publication_selection_rejects_wrong_versions_and_extra_fields(key, value):
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1

    raw = OnlyResearchCalculationPublicationSelectionV1().to_dict()
    raw[key] = value
    with pytest.raises(ValueError):
        OnlyResearchCalculationPublicationSelectionV1.from_dict(raw)


def test_publication_selection_rejects_every_missing_field():
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1

    raw = OnlyResearchCalculationPublicationSelectionV1().to_dict()
    for key in raw:
        with pytest.raises(ValueError):
            OnlyResearchCalculationPublicationSelectionV1.from_dict(
                {name: value for name, value in raw.items() if name != key}
            )
