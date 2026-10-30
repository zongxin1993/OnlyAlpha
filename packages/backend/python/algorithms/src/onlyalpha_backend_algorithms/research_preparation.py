"""Pure executable ABI observations; Rust owns publication, Runtime and consent."""

from decimal import Decimal
from importlib.metadata import version
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha_plugin_operators.metadata import provider_manifest
from onlyalpha_plugin_operators.registration import registrations

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.private_factor_provider_snapshot import (
    OnlyPrivateFactorProviderSnapshotEntryV1,
    OnlyPrivateFactorProviderSnapshotV1,
)
from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.research_evaluation import ManagedProgramHost
from onlyalpha_backend_algorithms.research_worker import resolve, verify_distribution
from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
)
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1


def certify(payload: dict[str, Any]) -> dict[str, Any]:
    source = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(payload["source"])
    validation = only_validate_private_factor_revision(source)
    manifest, code = OnlyPrivateFactorSourceArtifactManifestV1.materialize(source, validation)
    private = only_private_factor_backend_registrations(
        source,
        manifest,
        code,
        OnlyPrivateFactorAdapterV1("RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], ManagedProgramHost()),
        OnlyPrivateFactorAdapterV1("TRADING", _ADAPTER_FINGERPRINTS["TRADING"], ManagedProgramHost()),
    )
    roots = [
        OnlyCalculationDefinition.from_dict(n["definition"])
        for n in payload["graph"]["nodes"]
        if n["definition"]["type_id"] == source.factor_id
    ]
    if len(roots) != 1:
        raise ValueError("RESEARCH_PREPARATION_ROOT_MISMATCH")
    parameters = roots[0].parameters
    # Frozen deterministic synthetic vectors, never market observations or Research Evidence.
    vectors = tuple(
        {name: Decimal(2 + index * 7 + column) for column, name in enumerate(sorted(source.input_contract))}
        for index in range(8)
    )
    operators = [
        {
            "type": r.type_definition.descriptor(),
            "backend": r.backend.value,
            "implementation_fingerprint": r.implementation_manifest.implementation_fingerprint,
            "state_capability": None if r.state_capability is None else r.state_capability.value,
            "checkpoint_schema_version": r.checkpoint_schema_version,
        }
        for r in registrations()
        if r.implementation_manifest is not None
    ]
    # Arrow initialization may load its declared shared libraries before seccomp.
    pa.array([Decimal("1")], type=pa.decimal128(38, 18))
    isolation = restrict()
    equivalence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.certify(
        manifest, code, private, vectors, parameters
    )
    snapshot = OnlyPrivateFactorProviderSnapshotV1(
        (OnlyPrivateFactorProviderSnapshotEntryV1.derive(manifest, equivalence),)
    )
    return {
        "isolation": isolation,
        "equivalence_evidence": equivalence.to_dict(),
        "provider_snapshot": snapshot.to_dict(),
        "certification_policy": "ONLYALPHA_PRIVATE_FACTOR_ABI_VECTORS_V1",
        "certification_vectors": {"vectors": list(vectors), "parameters": parameters},
        "operator_provider_manifest": provider_manifest(),
        "operator_calculations": sorted(operators, key=only_canonical_fingerprint),
    }


def prepare(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    if set(payload) != {"schema_version", "source", "graph", "core_artifact", "operator_artifact"}:
        raise ValueError("RESEARCH_PREPARATION_INPUT_INVALID")
    declared = provider_manifest()["source"]
    if (
        not isinstance(declared, dict)
        or version(str(declared["distribution_name"])) != declared["distribution_version"]
    ):
        raise ValueError("RESEARCH_PREPARATION_DISTRIBUTION_MISMATCH")
    if payload["operator_artifact"]["distribution_version"] != declared["distribution_version"]:
        raise ValueError("RESEARCH_PREPARATION_DISTRIBUTION_MISMATCH")
    operator = verify_distribution(
        payload["operator_artifact"], "onlyalpha_plugin_operators", "onlyalpha-plugin-operators"
    )
    resolved = resolve({key: value for key, value in payload.items() if key != "operator_artifact"}, artifact)
    observation = certify({"source": payload["source"], "graph": payload["graph"]})
    return {
        **resolved,
        **observation,
        "contract": "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1",
        "operator_artifact_sha256": operator["artifact_sha256"],
        "operator_resources_fingerprint": operator["resources_fingerprint"],
    }
