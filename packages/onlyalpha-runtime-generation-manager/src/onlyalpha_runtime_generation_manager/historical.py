"""Fail-closed historical manifest resolution through exact executable artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onlyalpha.strategy.revision import OnlyStrategyRevision

from .builder import OnlyRuntimeGenerationBuilder, OnlyValidatedRuntimeGeneration
from .registry import OnlyHistoricalRuntimeGenerationResolver


@dataclass(frozen=True, slots=True)
class OnlyHistoricalExecutableRuntimeGenerationResolver:
    manifests: OnlyHistoricalRuntimeGenerationResolver
    builder: OnlyRuntimeGenerationBuilder

    def resolve(
        self,
        revision: OnlyStrategyRevision,
        *,
        environment_root: Path,
        exact_generation_fingerprint: str | None = None,
    ) -> OnlyValidatedRuntimeGeneration:
        manifest = self.manifests.resolve(
            revision,
            exact_generation_fingerprint=exact_generation_fingerprint,
        )
        try:
            return self.builder.rebuild_validated(
                expected_manifest=manifest,
                environment_root=environment_root,
            )
        except Exception as exc:
            raise ValueError("HISTORICAL_IMPLEMENTATION_UNAVAILABLE") from exc


__all__ = ["OnlyHistoricalExecutableRuntimeGenerationResolver"]
