"""Installed infrastructure SPI implementation for formal work generation binding."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.calculation.registry import OnlyCalculationRegistry

from .registry import OnlyRuntimeGenerationRegistry


def runtime_generation_work_authority(root: Path) -> OnlyRuntimeGenerationRegistry:
    return OnlyRuntimeGenerationRegistry(root)


__all__ = ["runtime_generation_work_authority"]


def calculation_generation_context(generation: str) -> OnlyCalculationRegistry:
    """Expose this exact verified installed registry; never resolve an ambient generation."""
    import json
    import sys

    from onlyalpha.calculation.definition import OnlyCalculationBackendKind
    from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
    from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

    from .builder import _HOSTED_GENERATION_SEAL
    from .hosted import only_load_hosted_quant_asset_catalog, only_verify_hosted_runtime_generation

    evidence = OnlyRuntimeGenerationValidationEvidence.from_dict(
        json.loads((Path(sys.prefix) / _HOSTED_GENERATION_SEAL).read_text())
    )
    if evidence.runtime_generation_fingerprint != generation:
        raise RuntimeError("CALCULATION_GENERATION_CONTEXT_MISMATCH")
    only_verify_hosted_runtime_generation(evidence)
    catalog = only_load_hosted_quant_asset_catalog(evidence)
    registry = OnlyCalculationRegistry()
    for provider in catalog.providers:
        for registration in provider.calculation_registrations:
            if registration.backend is OnlyCalculationBackendKind.TRADING:
                registry.register(registration)
    only_register_trading_predicate_primitives(registry)
    return registry
