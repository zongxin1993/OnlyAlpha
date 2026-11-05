"""Restricted authored Factor execution host and its numerical interface protocols."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
from onlyalpha.calculation.definition import OnlyCalculationDefinition

from onlyalpha_backend_algorithms.sdk.private_factor_execution import (
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorSourceArtifactManifestV1,
    only_execute_private_factor_program,
)


class ManagedProgramHost(OnlyPrivateFactorIsolatedProgramHost):
    """The owning process installs seccomp/rlimits before calling this host."""

    def execute(
        self,
        manifest: OnlyPrivateFactorSourceArtifactManifestV1,
        source: bytes,
        inputs: Mapping[str, object],
        parameters: Mapping[str, object],
    ) -> object:
        return only_execute_private_factor_program(manifest, source, inputs, parameters)


class ResearchBackend(Protocol):
    def execute(
        self, definition: OnlyCalculationDefinition, inputs: Mapping[str, pa.Array]
    ) -> Mapping[str, pa.Array]: ...


class TradingBackend(Protocol):
    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]: ...
