"""Source-owned private Factor registrations for the bounded authoring interface."""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
)
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

MAX_WORK = 8 * 1024 * 1024

# Installed resources/metadata and Arrow shared-library initialization precede
# confinement. Per-source resolution below is in memory; authored math stays
# inside the owning process's OS sandbox.
pa.array([Decimal("1")], type=pa.decimal128(38, 18))


def private_calculation_records(registrations: Iterable[OnlyCalculationBackendRegistration]) -> list[dict[str, Any]]:
    """Actual source-owned capabilities, shared by Factor and complete graph resolution."""
    return cast(
        list[dict[str, Any]],
        json.loads(
            only_canonical_json(
                sorted(
                    [
                        {
                            "type": row.type_definition.descriptor(),
                            "backend": row.backend.value,
                            "implementation_fingerprint": row.implementation_manifest.implementation_fingerprint,
                            "state_capability": None if row.state_capability is None else row.state_capability.value,
                            "checkpoint_schema_version": row.checkpoint_schema_version,
                        }
                        for row in registrations
                        if row.implementation_manifest is not None
                    ],
                    key=only_canonical_fingerprint,
                )
            )
        ),
    )


def registry_for_sources(
    sources: list[dict[str, Any]],
    host: OnlyPrivateFactorIsolatedProgramHost | None = None,
) -> tuple[OnlyCalculationRegistry, list[dict[str, object]]]:
    """Load exact authored sources without builtin Operator or Target registration."""
    if type(sources) is not list or len(sources) > 128 or len(json.dumps(sources).encode()) > MAX_WORK:
        raise ValueError("RESEARCH_CALCULATION_RESOLUTION_BUDGET")
    registry = OnlyCalculationRegistry()
    artifacts: dict[str, dict[str, object]] = {}
    for raw in sources:
        source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(raw)
        if source.factor_id in artifacts:
            raise ValueError("RESEARCH_CALCULATION_SOURCE_CONFLICT")
        validation = only_validate_private_factor_revision(source)
        manifest, code = OnlyPrivateFactorSourceArtifactManifestV1.materialize(source, validation)
        private = only_private_factor_backend_registrations(
            source,
            manifest,
            code,
            OnlyPrivateFactorAdapterV1(
                "RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], host or OnlyPrivateFactorIsolatedProgramHost()
            ),
            OnlyPrivateFactorAdapterV1(
                "TRADING", _ADAPTER_FINGERPRINTS["TRADING"], host or OnlyPrivateFactorIsolatedProgramHost()
            ),
        )
        for registration in private:
            registry.register(registration)
        artifacts[source.factor_id] = {
            "private_calculations": private_calculation_records(private),
            "source_artifact": manifest.to_dict(),
            "validation_evidence": {
                **validation.to_dict(),
                "validation_evidence_fingerprint": validation.validation_evidence_fingerprint,
            },
        }
    return registry, [artifacts[key] for key in sorted(artifacts)]
