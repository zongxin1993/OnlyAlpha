"""Fail-closed service readiness without startup migration or deep semantic scans."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .deployment import OnlyResearchDeploymentError


class OnlyResearchReadinessStatus(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class OnlyResearchReadinessCheck:
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class OnlyResearchReadiness:
    status: OnlyResearchReadinessStatus
    checks: tuple[OnlyResearchReadinessCheck, ...]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyResearchRequiredRoot:
    name: str
    path: Path
    writable: bool


class OnlyResearchServiceReadinessProbe:
    def __init__(
        self,
        *,
        schema_status: Callable[[], object],
        deployment_check: Callable[[], object],
        required_roots: tuple[OnlyResearchRequiredRoot, ...],
        registry_check: Callable[[], None],
    ) -> None:
        self._schema_status = schema_status
        self._deployment_check = deployment_check
        self._required_roots = tuple(sorted(required_roots, key=lambda item: item.name))
        self._registry_check = registry_check

    def inspect(self) -> OnlyResearchReadiness:
        checks: list[OnlyResearchReadinessCheck] = []
        try:
            schema = self._schema_status()
        except Exception:
            return OnlyResearchReadiness(
                OnlyResearchReadinessStatus.NOT_READY,
                (OnlyResearchReadinessCheck("postgres", "UNAVAILABLE"),),
                "POSTGRES_UNAVAILABLE",
            )
        verdict = getattr(schema, "verdict", None)
        compatible = getattr(schema, "compatible", False)
        checks.append(OnlyResearchReadinessCheck("postgres", "READY"))
        checks.append(OnlyResearchReadinessCheck("schema", "COMPATIBLE" if compatible else str(verdict)))
        if not compatible:
            return OnlyResearchReadiness(OnlyResearchReadinessStatus.NOT_READY, tuple(checks), "SCHEMA_INCOMPATIBLE")
        try:
            self._deployment_check()
        except OnlyResearchDeploymentError as exc:
            checks.append(OnlyResearchReadinessCheck("deployment_binding", exc.code.value))
            return OnlyResearchReadiness(
                OnlyResearchReadinessStatus.NOT_READY,
                tuple(checks),
                exc.code.value,
            )
        except Exception:
            checks.append(OnlyResearchReadinessCheck("deployment_binding", "UNAVAILABLE"))
            return OnlyResearchReadiness(
                OnlyResearchReadinessStatus.NOT_READY,
                tuple(checks),
                "POSTGRES_UNAVAILABLE",
            )
        checks.append(OnlyResearchReadinessCheck("deployment_binding", "COMPATIBLE"))
        for root in self._required_roots:
            usable = root.path.is_dir() and os.access(root.path, os.R_OK)
            if root.writable:
                usable = usable and os.access(root.path, os.W_OK)
            checks.append(OnlyResearchReadinessCheck(root.name, "READY" if usable else "UNUSABLE"))
            if not usable:
                return OnlyResearchReadiness(
                    OnlyResearchReadinessStatus.NOT_READY,
                    tuple(checks),
                    "REQUIRED_ROOT_UNUSABLE",
                )
        try:
            self._registry_check()
        except Exception:
            checks.append(OnlyResearchReadinessCheck("registry", "INVALID"))
            return OnlyResearchReadiness(OnlyResearchReadinessStatus.NOT_READY, tuple(checks), "REGISTRY_INVALID")
        checks.append(OnlyResearchReadinessCheck("registry", "READY"))
        return OnlyResearchReadiness(OnlyResearchReadinessStatus.READY, tuple(checks))

    def assert_ready(self) -> None:
        readiness = self.inspect()
        if readiness.status is not OnlyResearchReadinessStatus.READY:
            raise RuntimeError(readiness.reason or "RESEARCH_SERVICE_NOT_READY")


__all__ = [name for name in globals() if name.startswith("Only")]
