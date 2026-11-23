"""Installed mathematical library qualification. Factor construction belongs to factor_build."""

from importlib.metadata import version
from typing import Any

from onlyalpha_backend_algorithms.chart_isolation import restrict
from onlyalpha_backend_algorithms.research_worker import verify_core, verify_distribution

ENVIRONMENT_CONTRACT = "ONLYALPHA_INSTALLED_CALCULATION_ENVIRONMENT_V1"


def prepare(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    if type(payload) is not dict or payload.get("contract") != ENVIRONMENT_CONTRACT:
        raise ValueError("RESEARCH_PREPARATION_INPUT_INVALID")
    return prepare_environment(payload, artifact)


def prepare_environment(payload: dict[str, Any], artifact: str) -> dict[str, Any]:
    """Observe installed libraries only; factor compilation/certification has its own owner."""
    if (
        set(payload)
        not in (
            {"schema_version", "contract", "core_artifact"},
            {"schema_version", "contract", "core_artifact", "target_artifact"},
        )
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["contract"] != ENVIRONMENT_CONTRACT
    ):
        raise ValueError("RESEARCH_ENVIRONMENT_PREPARATION_INPUT_INVALID")
    core = verify_core(payload["core_artifact"])
    target_observation: dict[str, Any] = {}
    if "target_artifact" in payload:
        from onlyalpha_backend_algorithms.research_resolution import private_calculation_records
        from onlyalpha_backend_algorithms.targets.registration import registrations as target_registrations

        if payload["target_artifact"]["distribution_version"] != version("onlyalpha-backend-algorithms"):
            raise ValueError("RESEARCH_TARGET_IMPLEMENTATION_UNAVAILABLE")
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
        calculations = private_calculation_records(registrations)
        target_observation = {
            "target_artifact_sha256": target["artifact_sha256"],
            "target_resources_fingerprint": target["resources_fingerprint"],
            "target_calculations": calculations,
        }
    isolation = restrict()
    return {
        **core,
        "schema_version": 1,
        "contract": ENVIRONMENT_CONTRACT,
        "algorithm_artifact": artifact,
        "isolation": isolation,
        "implementations": [],
        **target_observation,
    }
