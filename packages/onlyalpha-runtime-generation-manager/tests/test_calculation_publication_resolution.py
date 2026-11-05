from __future__ import annotations


def test_hosted_worker_advertises_separate_calculation_publication_resolution():
    from onlyalpha.application.search_generation_execution import OnlySearchGenerationOperationV1
    from onlyalpha_runtime_generation_manager.search_worker import _CAPABILITIES

    operation = OnlySearchGenerationOperationV1("RESOLVE_RESEARCH_CALCULATION_PUBLICATION")
    assert operation in _CAPABILITIES
