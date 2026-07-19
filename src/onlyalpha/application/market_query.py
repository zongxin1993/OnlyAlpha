"""JSON-ready read-only Market Profile query boundary."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.market.registry import OnlyMarketProfileRegistry


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileSummary:
    profile_id: str
    display_name: str
    versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileDetail:
    profile_id: str
    version: str
    status: str
    effective_from: str
    effective_to: str | None
    enabled_capabilities: tuple[str, ...]
    conformance_pack_id: str | None
    content_fingerprint: str


class OnlyMarketProfileQueryService:
    def __init__(self, registry: OnlyMarketProfileRegistry) -> None:
        self._registry = registry

    def list_profiles(self) -> tuple[OnlyMarketProfileSummary, ...]:
        return tuple(
            OnlyMarketProfileSummary(
                family.profile_id.value,
                family.display_name,
                tuple(item.version for item in self._registry.versions(family.profile_id)),
            )
            for family in self._registry.families()
        )

    def profile(self, profile_id: str, version: str | None = None) -> OnlyMarketProfileDetail:
        identity = OnlyMarketProfileId(profile_id)
        versions = self._registry.versions(identity)
        selected = (
            next((item for item in versions if item.version == version), None)
            if version
            else versions[-1]
            if versions
            else None
        )
        if selected is None:
            raise ValueError(f"QUERY_RESOURCE_NOT_FOUND: {profile_id}{'' if version is None else '@' + version}")
        return OnlyMarketProfileDetail(
            selected.profile_id.value,
            selected.version,
            selected.status.value,
            selected.effective_from.isoformat(),
            None if selected.effective_to is None else selected.effective_to.isoformat(),
            selected.capability_set.enabled,
            selected.conformance_pack_id,
            selected.content_fingerprint,
        )
