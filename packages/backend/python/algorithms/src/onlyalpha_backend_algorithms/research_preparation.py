"""Pure executable ABI observations; Rust owns publication, Runtime and consent."""

from decimal import Decimal
from importlib.metadata import version
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha.calculation.definition import OnlyCalculationDefinition
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
    }


STRATEGY_CONTRACT = "ONLYALPHA_STRATEGY_EXECUTABLE_PREPARATION_V1"


def prepare(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    if type(payload) is not dict:
        raise ValueError("RESEARCH_PREPARATION_INPUT_INVALID")
    if payload.get("contract") == STRATEGY_CONTRACT:
        return prepare_strategy(payload, artifact)
    return _prepare_factor(payload, artifact)


def prepare_strategy(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    """Observe the actual installed Target library before entering confinement."""
    from onlyalpha_backend_algorithms.research_resolution import private_calculation_records
    from onlyalpha_backend_algorithms.targets.registration import registrations as target_registrations

    if (
        set(payload) != {"schema_version", "contract", "source", "graph", "core_artifact", "target_artifact"}
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["contract"] != STRATEGY_CONTRACT
        or payload["target_artifact"]["distribution_version"] != version("onlyalpha-backend-algorithms")
    ):
        raise ValueError("RESEARCH_STRATEGY_PREPARATION_INPUT_INVALID")
    target = verify_distribution(
        payload["target_artifact"], "onlyalpha_backend_algorithms", "onlyalpha-backend-algorithms"
    )
    registrations = target_registrations()
    if not registrations or any(
        row.type_definition.kind.value != "TARGET"
        or row.backend.value != "RESEARCH"
        or row.implementation_manifest is None
        for row in registrations
    ):
        raise ValueError("RESEARCH_TARGET_IMPLEMENTATION_UNAVAILABLE")
    targets = private_calculation_records(registrations)
    # The Factor certification below installs seccomp. All actual Target package
    # resource reads and implementation observations must already be complete.
    factor = _prepare_factor(
        {key: value for key, value in payload.items() if key not in {"contract", "target_artifact"}}, artifact
    )
    return {
        **factor,
        "contract": STRATEGY_CONTRACT,
        "target_artifact_sha256": target["artifact_sha256"],
        "target_resources_fingerprint": target["resources_fingerprint"],
        "target_calculations": targets,
    }


def _prepare_factor(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    if set(payload) != {"schema_version", "source", "graph", "core_artifact"}:
        raise ValueError("RESEARCH_PREPARATION_INPUT_INVALID")
    resolved = resolve(payload, artifact)
    observation = certify({"source": payload["source"], "graph": payload["graph"]})
    return {
        **resolved,
        **observation,
        "contract": "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1",
    }
