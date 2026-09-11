"""Lazy public Search Experiment provenance contract."""

from importlib import import_module

_PUBLIC_EXPORTS = {
    "onlyalpha.research.experiment.errors": (
        "OnlySearchProvenanceError",
        "OnlySearchProvenanceStoreError",
    ),
    "onlyalpha.research.experiment.model": (
        "SEARCH_EXPERIMENT_CONTEXT_SCHEMA_VERSION",
        "SEARCH_EXPERIMENT_POLICY_SCHEMA_VERSION",
        "SEARCH_EXPERIMENT_SCHEMA_VERSION",
        "SEARCH_HYPOTHESIS_SCHEMA_VERSION",
        "SEARCH_ITERATION_PLAN_SCHEMA_VERSION",
        "SEARCH_ITERATION_RESULT_SCHEMA_VERSION",
        "OnlySearchAlgorithmBindingV1",
        "OnlySearchBudgetV1",
        "OnlySearchCommitDisposition",
        "OnlySearchCommitOutcome",
        "OnlySearchDecisionEngineBindingV1",
        "OnlySearchDecisionMode",
        "OnlySearchEvaluationContextReferenceV1",
        "OnlySearchExperimentManifestV1",
        "OnlySearchExperimentManifestV2",
        "OnlySearchExperimentManifestV3",
        "OnlySearchFailureCode",
        "OnlySearchHypothesisSourceKind",
        "OnlySearchHypothesisSourceReferenceV1",
        "OnlySearchHypothesisV1",
        "OnlySearchIterationDisposition",
        "OnlySearchIterationPlanV1",
        "OnlySearchIterationResultV1",
        "OnlySearchPolicyReferenceV1",
        "OnlySearchRandomnessMode",
        "OnlySearchResearchResultReferenceV1",
        "OnlySearchSpaceReferenceV1",
        "OnlySearchWorkflowBindingV1",
    ),
    "onlyalpha.research.experiment.store": ("OnlyJsonSearchProvenanceStore",),
    "onlyalpha.research.experiment.verification": (
        "OnlySearchCandidateReader",
        "OnlySearchCandidateValue",
        "OnlySearchCatalogGenerationReader",
        "OnlySearchCatalogGenerationValue",
        "OnlySearchContextReader",
        "OnlySearchDatasetReader",
        "OnlySearchExperimentReader",
        "OnlySearchFreezeRelationReader",
        "OnlySearchFreezeRelationValue",
        "OnlySearchIterationPlanReader",
        "OnlySearchIterationResultReader",
        "OnlySearchProposalReader",
        "OnlySearchProposalValue",
        "OnlySearchQualificationDecisionReader",
        "OnlySearchResearchResultReader",
        "OnlySearchSpaceReader",
        "OnlySearchSpaceValue",
        "verify_search_experiment_references",
        "verify_search_iteration_lineage",
        "verify_search_iteration_proposal_reference",
        "verify_search_iteration_result_references",
    ),
}
_exports_loaded = False


def _load_public_exports() -> None:
    global _exports_loaded
    if _exports_loaded:
        return
    for module_name, exported in _PUBLIC_EXPORTS.items():
        module = import_module(module_name)
        for name in exported:
            globals()[name] = getattr(module, name)
    names = [
        name for name in globals() if name.startswith(("OnlySearch", "OnlyJsonSearch", "SEARCH_", "verify_search"))
    ]
    list.clear(__all__)
    list.extend(__all__, names)
    _exports_loaded = True


class _LazyPublicNames(list[str]):
    def __iter__(self):  # type: ignore[no-untyped-def]
        _load_public_exports()
        return list.__iter__(self)

    def __len__(self) -> int:
        _load_public_exports()
        return list.__len__(self)

    def __getitem__(self, key):  # type: ignore[no-untyped-def]
        _load_public_exports()
        return list.__getitem__(self, key)


__all__: list[str] = _LazyPublicNames()


def __getattr__(name: str) -> object:
    _load_public_exports()
    try:
        return globals()[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
