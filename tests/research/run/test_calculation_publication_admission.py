from __future__ import annotations

from unittest.mock import Mock

import pytest

from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.errors import OnlyResearchRunAdmissionError
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.test_calculation_publication import publication_registry, publication_specification


def test_generic_admission_rejects_publication_before_allocating_run_or_reading_dataset():
    store, clock, identities = Mock(), Mock(), Mock()
    service = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(publication_registry()),
        dataset_store=store,
        now_utc=clock,
        run_id_factory=identities,
    )
    with pytest.raises(OnlyResearchRunAdmissionError) as error:
        service.prepare(publication_specification())
    assert error.value.code == "RESEARCH_ADMISSION_SPECIFICATION_VERSION_UNSUPPORTED"
    identities.assert_not_called()
    clock.assert_not_called()
    store.load_verified_table.assert_not_called()
