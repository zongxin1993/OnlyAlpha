"""Executable versioned Conformance Packs built exclusively on Scenario Runner."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.market.registry import OnlyMarketCapabilitySet, OnlyMarketProfileStatus
from onlyalpha.result.fingerprint import only_result_fingerprint

if TYPE_CHECKING:
    from onlyalpha.scenario import OnlyMarketScenario, OnlyMarketScenarioRunResult


class OnlyMarketConformanceErrorCode(StrEnum):
    CONFORMANCE_PACK_NOT_FOUND = "CONFORMANCE_PACK_NOT_FOUND"
    CONFORMANCE_PACK_VERSION_NOT_FOUND = "CONFORMANCE_PACK_VERSION_NOT_FOUND"
    CONFORMANCE_PACK_INVALID = "CONFORMANCE_PACK_INVALID"
    CONFORMANCE_SCENARIO_MISSING = "CONFORMANCE_SCENARIO_MISSING"
    CONFORMANCE_SCENARIO_FAILED = "CONFORMANCE_SCENARIO_FAILED"
    CONFORMANCE_SCENARIO_ERROR = "CONFORMANCE_SCENARIO_ERROR"
    CONFORMANCE_CAPABILITY_INCOMPLETE = "CONFORMANCE_CAPABILITY_INCOMPLETE"
    CONFORMANCE_DETERMINISM_FAILED = "CONFORMANCE_DETERMINISM_FAILED"
    CONFORMANCE_ARTIFACT_FAILED = "CONFORMANCE_ARTIFACT_FAILED"
    CONFORMANCE_RELEASE_GATE_FAILED = "CONFORMANCE_RELEASE_GATE_FAILED"
    PROFILE_NOT_ELIGIBLE_FOR_STABLE = "PROFILE_NOT_ELIGIBLE_FOR_STABLE"
    PROFILE_CONFORMANCE_PACK_MISSING = "PROFILE_CONFORMANCE_PACK_MISSING"
    QUERY_RESOURCE_NOT_FOUND = "QUERY_RESOURCE_NOT_FOUND"
    CLI_INVALID_ARGUMENT = "CLI_INVALID_ARGUMENT"


class OnlyMarketConformanceError(ValueError):
    def __init__(self, code: OnlyMarketConformanceErrorCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketConformancePackId:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("pack id is required")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, order=True)
class OnlyMarketConformancePackVersion:
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("pack version is required")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyMarketConformanceScenarioBinding:
    scenario_id: str
    scenario_version: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class OnlyMarketCapabilityRequirement:
    capability: str
    required_scenario_ids: tuple[str, ...]
    minimum_pass_count: int = 1
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_scenario_ids", tuple(sorted(set(self.required_scenario_ids))))
        if not self.capability or not self.required_scenario_ids or self.minimum_pass_count <= 0:
            raise ValueError("capability requirement is incomplete")


@dataclass(frozen=True, slots=True)
class OnlyMarketConformancePack:
    pack_id: OnlyMarketConformancePackId
    version: OnlyMarketConformancePackVersion
    profile_id: OnlyMarketProfileId
    profile_versions: tuple[str, ...]
    scenarios: tuple[OnlyMarketConformanceScenarioBinding, ...]
    requirements: tuple[OnlyMarketCapabilityRequirement, ...]
    schema_version: str = "1"
    source: str = "builtin"

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.scenarios, key=lambda item: (item.scenario_id, item.scenario_version)))
        object.__setattr__(self, "scenarios", ordered)
        object.__setattr__(self, "requirements", tuple(sorted(self.requirements, key=lambda item: item.capability)))
        if not ordered or len({(item.scenario_id, item.scenario_version) for item in ordered}) != len(ordered):
            raise ValueError("pack requires unique Scenario bindings")
        if len({item.capability for item in self.requirements}) != len(self.requirements):
            raise ValueError("pack contains duplicate capability requirements")


class OnlyMarketConformancePackRegistry:
    def __init__(self) -> None:
        self._packs: dict[tuple[str, str], OnlyMarketConformancePack] = {}

    def register(self, pack: OnlyMarketConformancePack) -> None:
        key = (str(pack.pack_id), str(pack.version))
        if key in self._packs:
            raise OnlyMarketConformanceError(
                OnlyMarketConformanceErrorCode.CONFORMANCE_PACK_INVALID, f"duplicate {key}"
            )
        bound = {item.scenario_id for item in pack.scenarios}
        if any(not set(item.required_scenario_ids) <= bound for item in pack.requirements):
            raise OnlyMarketConformanceError(
                OnlyMarketConformanceErrorCode.CONFORMANCE_SCENARIO_MISSING,
                "requirement references an unbound Scenario",
            )
        self._packs[key] = pack

    def get(self, pack_id: str, version: str | None = None) -> OnlyMarketConformancePack:
        matches = [pack for (identity, _), pack in self._packs.items() if identity == pack_id]
        if not matches:
            raise OnlyMarketConformanceError(OnlyMarketConformanceErrorCode.CONFORMANCE_PACK_NOT_FOUND, pack_id)
        if version is None:
            return sorted(matches, key=lambda item: str(item.version))[-1]
        try:
            return self._packs[(pack_id, version)]
        except KeyError as exc:
            raise OnlyMarketConformanceError(
                OnlyMarketConformanceErrorCode.CONFORMANCE_PACK_VERSION_NOT_FOUND, f"{pack_id}@{version}"
            ) from exc

    def list(self) -> tuple[OnlyMarketConformancePack, ...]:
        return tuple(self._packs[key] for key in sorted(self._packs))

    def for_profile(
        self, profile_id: OnlyMarketProfileId, version: str | None = None
    ) -> tuple[OnlyMarketConformancePack, ...]:
        return tuple(
            pack
            for pack in self.list()
            if pack.profile_id == profile_id
            and (version is None or not pack.profile_versions or version in pack.profile_versions)
        )


class OnlyMarketConformanceStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    INCOMPLETE = "INCOMPLETE"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class OnlyMarketCapabilityCoverageResult:
    capability: str
    declared: bool
    required: bool
    covered: bool
    scenario_ids: tuple[str, ...]
    passed_scenario_ids: tuple[str, ...]
    failed_scenario_ids: tuple[str, ...]
    missing_scenario_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketConformanceRunRequest:
    pack_id: str
    output_root: Path
    pack_version: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketConformanceRunResult:
    pack: OnlyMarketConformancePack
    status: OnlyMarketConformanceStatus
    scenarios: tuple[OnlyMarketScenarioRunResult, ...]
    coverage: tuple[OnlyMarketCapabilityCoverageResult, ...]
    pack_fingerprint: str
    artifact_path: Path | None


class OnlyMarketConformanceRunner:
    def __init__(
        self,
        packs: OnlyMarketConformancePackRegistry,
        scenarios: Mapping[tuple[str, str], OnlyMarketScenario],
        scenario_runner: object,
    ) -> None:
        self._packs = packs
        self._scenarios = MappingProxyType(dict(scenarios))
        self._scenario_runner = scenario_runner

    def run(self, request: OnlyMarketConformanceRunRequest) -> OnlyMarketConformanceRunResult:
        pack = self._packs.get(request.pack_id, request.pack_version)
        results = []
        for binding in pack.scenarios:
            scenario = self._scenarios.get((binding.scenario_id, binding.scenario_version))
            if scenario is None:
                raise OnlyMarketConformanceError(
                    OnlyMarketConformanceErrorCode.CONFORMANCE_SCENARIO_MISSING, binding.scenario_id
                )
            run = getattr(self._scenario_runner, "run", None)
            if not callable(run):
                raise TypeError("Conformance Runner requires public Scenario Runner port")
            from onlyalpha.scenario import OnlyMarketScenarioRunRequest

            results.append(
                run(OnlyMarketScenarioRunRequest(scenario, request.output_root / "scenarios" / binding.scenario_id))
            )
        scenario_results = tuple(results)
        by_id = {item.scenario_id: item for item in scenario_results}
        coverage = tuple(self._coverage(item, by_id) for item in pack.requirements)
        if any(item.status == "ERROR" for item in scenario_results):
            status = OnlyMarketConformanceStatus.ERROR
        elif any(item.status == "FAILED" for item in scenario_results):
            status = OnlyMarketConformanceStatus.FAILED
        elif not all(item.covered for item in coverage):
            status = OnlyMarketConformanceStatus.INCOMPLETE
        else:
            status = OnlyMarketConformanceStatus.PASSED
        fingerprint = only_result_fingerprint(
            {
                "pack": pack,
                "scenario_inputs": tuple(item.input_fingerprint for item in scenario_results),
                "scenario_results": tuple(item.result_fingerprint for item in scenario_results),
                "coverage": coverage,
            }
        )
        artifact = request.output_root / "pack_artifacts" / f"{pack.pack_id}-{pack.version}"
        artifact.mkdir(parents=True, exist_ok=False)
        (artifact / "pack_summary.json").write_text(
            json.dumps(
                {
                    "status": status.value,
                    "pack_fingerprint": fingerprint,
                    "coverage": [
                        item.__dict__
                        if hasattr(item, "__dict__")
                        else {field: getattr(item, field) for field in item.__dataclass_fields__}
                        for item in coverage
                    ],
                },
                default=list,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return OnlyMarketConformanceRunResult(pack, status, scenario_results, coverage, fingerprint, artifact)

    @staticmethod
    def _coverage(
        requirement: OnlyMarketCapabilityRequirement, results: Mapping[str, OnlyMarketScenarioRunResult]
    ) -> OnlyMarketCapabilityCoverageResult:
        required = requirement.required_scenario_ids
        passed = tuple(item for item in required if item in results and results[item].status == "PASSED")
        failed = tuple(item for item in required if item in results and results[item].status in {"FAILED", "ERROR"})
        missing = tuple(item for item in required if item not in results)
        return OnlyMarketCapabilityCoverageResult(
            requirement.capability,
            True,
            True,
            len(passed) >= requirement.minimum_pass_count and not failed and not missing,
            required,
            passed,
            failed,
            missing,
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileStabilityResult:
    eligible: bool
    target_status: OnlyMarketProfileStatus
    reasons: tuple[str, ...]


class OnlyMarketProfileStabilityEvaluator:
    def evaluate(
        self,
        status: OnlyMarketProfileStatus,
        capabilities: OnlyMarketCapabilitySet,
        run: OnlyMarketConformanceRunResult | None,
        quality_gate_passed: bool,
    ) -> OnlyMarketProfileStabilityResult:
        reasons = []
        if run is None:
            reasons.append("PROFILE_CONFORMANCE_PACK_MISSING")
        elif run.status is not OnlyMarketConformanceStatus.PASSED:
            reasons.append(f"PACK_{run.status.value}")
        elif set(capabilities.enabled) - {item.capability for item in run.coverage if item.covered}:
            reasons.append("CONFORMANCE_CAPABILITY_INCOMPLETE")
        if not quality_gate_passed:
            reasons.append("QUALITY_GATE_FAILED")
        return OnlyMarketProfileStabilityResult(
            not reasons, OnlyMarketProfileStatus.STABLE if not reasons else status, tuple(reasons)
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketConformanceReleaseGateResult:
    passed: bool
    checks: Mapping[str, bool]


class OnlyMarketConformanceReleaseGate:
    def evaluate(
        self, run: OnlyMarketConformanceRunResult, **quality_checks: bool
    ) -> OnlyMarketConformanceReleaseGateResult:
        checks = {
            "pack_passed": run.status is OnlyMarketConformanceStatus.PASSED,
            "capability_complete": all(item.covered for item in run.coverage),
            **quality_checks,
        }
        return OnlyMarketConformanceReleaseGateResult(all(checks.values()), MappingProxyType(checks))
