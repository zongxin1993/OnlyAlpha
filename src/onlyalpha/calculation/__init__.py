"""Public API; individual capabilities load only when explicitly requested."""

from importlib import import_module
from typing import TYPE_CHECKING

from onlyalpha.calculation.definition import *  # noqa: F403

if TYPE_CHECKING:
    from onlyalpha.calculation.artifact import (
        only_calculation_distribution_artifact_manifest as only_calculation_distribution_artifact_manifest,
    )
    from onlyalpha.calculation.capability import (
        OnlyCalculationSemanticCapability as OnlyCalculationSemanticCapability,
    )
    from onlyalpha.calculation.capability import (
        only_assert_calculation_capabilities_equivalent as only_assert_calculation_capabilities_equivalent,
    )
    from onlyalpha.calculation.capability import (
        only_calculation_capability_projection as only_calculation_capability_projection,
    )
    from onlyalpha.calculation.compatibility import (
        OnlyCalculationCompatibility as OnlyCalculationCompatibility,
    )
    from onlyalpha.calculation.compatibility import (
        only_calculation_output_compatibility as only_calculation_output_compatibility,
    )
    from onlyalpha.calculation.decimal_execution import (
        ONLY_DECIMAL_EXECUTION_POLICY_V1 as ONLY_DECIMAL_EXECUTION_POLICY_V1,
    )
    from onlyalpha.calculation.decimal_execution import (
        OnlyDecimalExecutionPolicy as OnlyDecimalExecutionPolicy,
    )
    from onlyalpha.calculation.decimal_execution import (
        only_decimal_context as only_decimal_context,
    )
    from onlyalpha.calculation.decimal_execution import (
        only_decimal_execution_semantic_dependency as only_decimal_execution_semantic_dependency,
    )
    from onlyalpha.calculation.decimal_execution import (
        only_quantize_decimal as only_quantize_decimal,
    )
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceCertificationProfile as OnlyCalculationEquivalenceCertificationProfile,
    )
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceError as OnlyCalculationEquivalenceError,
    )
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceEvidenceV2 as OnlyCalculationEquivalenceEvidenceV2,
    )
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceEvidenceV2Store as OnlyCalculationEquivalenceEvidenceV2Store,
    )
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceVerdict as OnlyCalculationEquivalenceVerdict,
    )
    from onlyalpha.calculation.equivalence import (
        only_calculation_equivalence_comparison_fingerprint as only_calculation_equivalence_comparison_fingerprint,
    )
    from onlyalpha.calculation.equivalence import (
        only_required_calculation_equivalence_profile as only_required_calculation_equivalence_profile,
    )
    from onlyalpha.calculation.graph import (
        OnlyCalculationGraphDefinition as OnlyCalculationGraphDefinition,
    )
    from onlyalpha.calculation.graph import (
        OnlyCalculationNodeDefinition as OnlyCalculationNodeDefinition,
    )
    from onlyalpha.calculation.implementation import (
        OnlyCalculationImplementationManifest as OnlyCalculationImplementationManifest,
    )
    from onlyalpha.calculation.implementation import (
        OnlyCalculationImplementationResource as OnlyCalculationImplementationResource,
    )
    from onlyalpha.calculation.implementation import (
        OnlyCalculationSemanticDependency as OnlyCalculationSemanticDependency,
    )
    from onlyalpha.calculation.implementation import (
        OnlyCalculationStateCapability as OnlyCalculationStateCapability,
    )
    from onlyalpha.calculation.implementation import (
        only_distribution_semantic_dependency as only_distribution_semantic_dependency,
    )
    from onlyalpha.calculation.implementation import (
        only_implementation_manifest_from_bytes as only_implementation_manifest_from_bytes,
    )
    from onlyalpha.calculation.implementation import (
        only_python_implementation_manifest as only_python_implementation_manifest,
    )
    from onlyalpha.calculation.implementation import (
        only_python_stdlib_semantic_dependency as only_python_stdlib_semantic_dependency,
    )
    from onlyalpha.calculation.registry import (
        OnlyCalculationBackendRegistration as OnlyCalculationBackendRegistration,
    )
    from onlyalpha.calculation.registry import (
        OnlyCalculationDefinitionResolver as OnlyCalculationDefinitionResolver,
    )
    from onlyalpha.calculation.registry import (
        OnlyCalculationRegistry as OnlyCalculationRegistry,
    )
    from onlyalpha.calculation.registry import (
        OnlyTradingCalculationBackend as OnlyTradingCalculationBackend,
    )
    from onlyalpha.calculation.registry import (
        OnlyTradingCalculationBackendResolver as OnlyTradingCalculationBackendResolver,
    )
    from onlyalpha.calculation.value_semantics import (
        OnlyCanonicalValueSemanticsV1 as OnlyCanonicalValueSemanticsV1,
    )

_EXPORTS = {
    "only_calculation_distribution_artifact_manifest": (
        "onlyalpha.calculation.artifact",
        "only_calculation_distribution_artifact_manifest",
    ),
    "OnlyCalculationSemanticCapability": ("onlyalpha.calculation.capability", "OnlyCalculationSemanticCapability"),
    "only_assert_calculation_capabilities_equivalent": (
        "onlyalpha.calculation.capability",
        "only_assert_calculation_capabilities_equivalent",
    ),
    "only_calculation_capability_projection": (
        "onlyalpha.calculation.capability",
        "only_calculation_capability_projection",
    ),
    "OnlyCalculationCompatibility": ("onlyalpha.calculation.compatibility", "OnlyCalculationCompatibility"),
    "only_calculation_output_compatibility": (
        "onlyalpha.calculation.compatibility",
        "only_calculation_output_compatibility",
    ),
    "ONLY_DECIMAL_EXECUTION_POLICY_V1": ("onlyalpha.calculation.decimal_execution", "ONLY_DECIMAL_EXECUTION_POLICY_V1"),
    "OnlyDecimalExecutionPolicy": ("onlyalpha.calculation.decimal_execution", "OnlyDecimalExecutionPolicy"),
    "only_decimal_context": ("onlyalpha.calculation.decimal_execution", "only_decimal_context"),
    "only_decimal_execution_semantic_dependency": (
        "onlyalpha.calculation.decimal_execution",
        "only_decimal_execution_semantic_dependency",
    ),
    "only_quantize_decimal": ("onlyalpha.calculation.decimal_execution", "only_quantize_decimal"),
    "OnlyCalculationEquivalenceCertificationProfile": (
        "onlyalpha.calculation.equivalence",
        "OnlyCalculationEquivalenceCertificationProfile",
    ),
    "OnlyCalculationEquivalenceError": ("onlyalpha.calculation.equivalence", "OnlyCalculationEquivalenceError"),
    "OnlyCalculationEquivalenceEvidenceV2": (
        "onlyalpha.calculation.equivalence",
        "OnlyCalculationEquivalenceEvidenceV2",
    ),
    "OnlyCalculationEquivalenceEvidenceV2Store": (
        "onlyalpha.calculation.equivalence",
        "OnlyCalculationEquivalenceEvidenceV2Store",
    ),
    "OnlyCalculationEquivalenceVerdict": ("onlyalpha.calculation.equivalence", "OnlyCalculationEquivalenceVerdict"),
    "only_calculation_equivalence_comparison_fingerprint": (
        "onlyalpha.calculation.equivalence",
        "only_calculation_equivalence_comparison_fingerprint",
    ),
    "only_required_calculation_equivalence_profile": (
        "onlyalpha.calculation.equivalence",
        "only_required_calculation_equivalence_profile",
    ),
    "OnlyCalculationGraphDefinition": ("onlyalpha.calculation.graph", "OnlyCalculationGraphDefinition"),
    "OnlyCalculationNodeDefinition": ("onlyalpha.calculation.graph", "OnlyCalculationNodeDefinition"),
    "OnlyCalculationImplementationManifest": (
        "onlyalpha.calculation.implementation",
        "OnlyCalculationImplementationManifest",
    ),
    "OnlyCalculationImplementationResource": (
        "onlyalpha.calculation.implementation",
        "OnlyCalculationImplementationResource",
    ),
    "OnlyCalculationSemanticDependency": ("onlyalpha.calculation.implementation", "OnlyCalculationSemanticDependency"),
    "OnlyCalculationStateCapability": ("onlyalpha.calculation.implementation", "OnlyCalculationStateCapability"),
    "only_distribution_semantic_dependency": (
        "onlyalpha.calculation.implementation",
        "only_distribution_semantic_dependency",
    ),
    "only_implementation_manifest_from_bytes": (
        "onlyalpha.calculation.implementation",
        "only_implementation_manifest_from_bytes",
    ),
    "only_python_implementation_manifest": (
        "onlyalpha.calculation.implementation",
        "only_python_implementation_manifest",
    ),
    "only_python_stdlib_semantic_dependency": (
        "onlyalpha.calculation.implementation",
        "only_python_stdlib_semantic_dependency",
    ),
    "OnlyCalculationBackendRegistration": ("onlyalpha.calculation.registry", "OnlyCalculationBackendRegistration"),
    "OnlyCalculationDefinitionResolver": ("onlyalpha.calculation.registry", "OnlyCalculationDefinitionResolver"),
    "OnlyCalculationRegistry": ("onlyalpha.calculation.registry", "OnlyCalculationRegistry"),
    "OnlyTradingCalculationBackend": ("onlyalpha.calculation.registry", "OnlyTradingCalculationBackend"),
    "OnlyTradingCalculationBackendResolver": (
        "onlyalpha.calculation.registry",
        "OnlyTradingCalculationBackendResolver",
    ),
    "OnlyCanonicalValueSemanticsV1": ("onlyalpha.calculation.value_semantics", "OnlyCanonicalValueSemanticsV1"),
}


def __getattr__(name: str) -> object:
    try:
        module, member = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module), member)
    globals()[name] = value
    return value


__all__ = sorted(
    set(_EXPORTS)
    | {name for name in globals() if name.startswith(("Only", "only_", "FACTOR_", "PREDICATE_", "TARGET_"))}
)
