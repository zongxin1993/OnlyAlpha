"""Shared-resource claim conflict and reference-count authority."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.runtime.environment import OnlyResourceClaim


class OnlyResourceConfigurationConflict(ValueError):
    pass


@dataclass(slots=True)
class _OnlyResourceRecord:
    fingerprint: str
    reference_count: int


class OnlyInfrastructureRegistry:
    """Claim/refcount registry; resource semantics are canonicalized upstream."""

    def __init__(self) -> None:
        self._records: dict[str, _OnlyResourceRecord] = {}
        self._cluster_resources: dict[str, tuple[str, ...]] = {}

    def validate(self, cluster_id: object, claims: tuple[OnlyResourceClaim, ...]) -> None:
        cluster_key = str(cluster_id)
        if cluster_key in self._cluster_resources:
            raise ValueError(f"resources already acquired for {cluster_key}")
        conflicts = [
            claim
            for claim in claims
            if claim.key in self._records and self._records[claim.key].fingerprint != claim.fingerprint
        ]
        if conflicts:
            details = ", ".join(
                f"{claim.key}[existing={self._records[claim.key].fingerprint},requested={claim.fingerprint}]"
                for claim in conflicts
            )
            raise OnlyResourceConfigurationConflict(f"RESOURCE_CONFIGURATION_CONFLICT: {details}")

    def acquire(self, cluster_id: object, claims: tuple[OnlyResourceClaim, ...]) -> tuple[str, ...]:
        self.validate(cluster_id, claims)
        records = {
            key: _OnlyResourceRecord(record.fingerprint, record.reference_count)
            for key, record in self._records.items()
        }
        keys = []
        for claim in claims:
            record = records.get(claim.key)
            if record is None:
                records[claim.key] = _OnlyResourceRecord(claim.fingerprint, 1)
            else:
                record.reference_count += 1
            keys.append(claim.key)
        cluster_resources = dict(self._cluster_resources)
        cluster_resources[str(cluster_id)] = tuple(keys)
        self._records = records
        self._cluster_resources = cluster_resources
        return tuple(keys)

    def release(self, cluster_id: object) -> tuple[str, ...]:
        keys = self._cluster_resources.pop(str(cluster_id), ())
        released = []
        for key in keys:
            record = self._records[key]
            record.reference_count -= 1
            if record.reference_count == 0:
                del self._records[key]
                released.append(key)
        return tuple(released)

    @property
    def reference_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple((key, self._records[key].reference_count) for key in sorted(self._records))

    def references_for(self, cluster_id: object) -> tuple[str, ...]:
        return self._cluster_resources.get(str(cluster_id), ())
