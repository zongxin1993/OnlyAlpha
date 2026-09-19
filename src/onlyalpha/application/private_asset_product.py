"""Product discovery projections over DB-native Private Asset authorities."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetCorruptError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetNotFoundError,
    OnlyPrivateFactorRevision,
    OnlyPrivateStrategyRevision,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlyPrivateAssetProductError(RuntimeError):
    code = "PRIVATE_ASSET_PRODUCT_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyPrivateAssetExactReadMismatch(OnlyPrivateAssetProductError):
    code = "PRIVATE_ASSET_EXACT_READ_MISMATCH"


class OnlyPrivateAssetExactRevisionUnavailable(OnlyPrivateAssetProductError):
    code = "PRIVATE_ASSET_EXACT_REVISION_UNAVAILABLE"


class OnlyPrivateAssetExactReadFailure(OnlyPrivateAssetProductError):
    code = "PRIVATE_ASSET_EXACT_READ_FAILURE"


class OnlyProductAssetSearchProjectionCorrupt(OnlyPrivateAssetProductError):
    code = "PRIVATE_ASSET_SEARCH_PROJECTION_CORRUPT"


class OnlyProductAssetSearchProjectionUnavailable(OnlyPrivateAssetProductError):
    code = "PRIVATE_ASSET_SEARCH_PROJECTION_UNAVAILABLE"


class OnlyProductAssetProjectionCompleteness(StrEnum):
    CERTIFIED_COMPLETE = "CERTIFIED_COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class OnlyProductAssetSearchStatus(StrEnum):
    MATCH = "MATCH"
    NO_MATCH_ON_CERTIFIED_COMPLETE_PROJECTION = "NO_MATCH_ON_CERTIFIED_COMPLETE_PROJECTION"
    PROJECTION_INCOMPLETE = "PROJECTION_INCOMPLETE"
    PROJECTION_UNAVAILABLE = "PROJECTION_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class OnlyProductAssetLocatorV1:
    private_asset_kind: OnlyPrivateAssetKind
    private_asset_id: str
    revision_fingerprint: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.private_asset_kind, OnlyPrivateAssetKind):
            raise ValueError("PRIVATE_ASSET_LOCATOR_KIND_INVALID")
        if not self.private_asset_id:
            raise ValueError("PRIVATE_ASSET_LOCATOR_ID_INVALID")
        _require_sha(self.revision_fingerprint, "revision_fingerprint")
        _require_sha(self.content_fingerprint, "content_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return {
            "private_asset_kind": self.private_asset_kind.value,
            "private_asset_id": self.private_asset_id,
            "revision_fingerprint": self.revision_fingerprint,
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyProductAssetLocatorV1:
        _exact(value, {"private_asset_kind", "private_asset_id", "revision_fingerprint", "content_fingerprint"})
        return cls(
            OnlyPrivateAssetKind(_string(value["private_asset_kind"])),
            _string(value["private_asset_id"]),
            _string(value["revision_fingerprint"]),
            _string(value["content_fingerprint"]),
        )


@dataclass(frozen=True, slots=True)
class OnlyProductAssetRegistryEntryV1:
    locator: OnlyProductAssetLocatorV1
    semantic_version: str
    description: str
    category: str | None
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.semantic_version:
            raise ValueError("PRIVATE_ASSET_SEMANTIC_VERSION_INVALID")
        if self.category is not None and not self.category:
            raise ValueError("PRIVATE_ASSET_CATEGORY_INVALID")
        if self.tags != tuple(sorted(set(self.tags))):
            raise ValueError("PRIVATE_ASSET_TAGS_INVALID")

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.locator.private_asset_kind.value, self.locator.private_asset_id

    def to_dict(self) -> dict[str, object]:
        return {
            "locator": self.locator.to_dict(),
            "semantic_version": self.semantic_version,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyProductAssetRegistryEntryV1:
        _exact(value, {"locator", "semantic_version", "description", "category", "tags"})
        locator = value["locator"]
        tags = value["tags"]
        if (
            not isinstance(locator, Mapping)
            or not isinstance(tags, list)
            or any(not isinstance(item, str) for item in tags)
        ):
            raise OnlyProductAssetSearchProjectionCorrupt("entry shape")
        category = value["category"]
        if category is not None and not isinstance(category, str):
            raise OnlyProductAssetSearchProjectionCorrupt("entry category")
        return cls(
            OnlyProductAssetLocatorV1.from_dict(cast(Mapping[str, object], locator)),
            _string(value["semantic_version"]),
            _string(value["description"]),
            category,
            tuple(cast(list[str], tags)),
        )


@dataclass(frozen=True, slots=True)
class OnlyProductAssetRegistrySnapshotV1:
    entries: tuple[OnlyProductAssetRegistryEntryV1, ...]
    registry_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.entries != tuple(sorted(self.entries, key=lambda item: item.sort_key)):
            raise ValueError("PRIVATE_ASSET_REGISTRY_INVALID")
        if len({item.sort_key for item in self.entries}) != len(self.entries):
            raise ValueError("PRIVATE_ASSET_REGISTRY_DUPLICATE")
        if self.registry_fingerprint != _registry_fingerprint(self.entries):
            raise ValueError("PRIVATE_ASSET_REGISTRY_FINGERPRINT_MISMATCH")

    @classmethod
    def create(cls, entries: tuple[OnlyProductAssetRegistryEntryV1, ...]) -> OnlyProductAssetRegistrySnapshotV1:
        ordered = tuple(sorted(entries, key=lambda item: item.sort_key))
        return cls(ordered, _registry_fingerprint(ordered))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "registry_fingerprint": self.registry_fingerprint,
            "entries": [item.to_dict() for item in self.entries],
        }


class OnlyPrivateAssetProductAuthority(Protocol):
    def list_current_factor_revisions(self) -> tuple[OnlyPrivateFactorRevision, ...]: ...

    def list_current_strategy_revisions(self) -> tuple[OnlyPrivateStrategyRevision, ...]: ...

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision: ...

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision: ...


class OnlyPrivateAssetProductService:
    def __init__(self, authority: OnlyPrivateAssetProductAuthority) -> None:
        self._authority = authority

    def current_registry(self) -> OnlyProductAssetRegistrySnapshotV1:
        entries = tuple(_factor_entry(item) for item in self._authority.list_current_factor_revisions()) + tuple(
            _strategy_entry(item) for item in self._authority.list_current_strategy_revisions()
        )
        return OnlyProductAssetRegistrySnapshotV1.create(entries)

    def read_exact(self, locator: OnlyProductAssetLocatorV1) -> OnlyPrivateFactorRevision | OnlyPrivateStrategyRevision:
        revision: OnlyPrivateFactorRevision | OnlyPrivateStrategyRevision
        try:
            if locator.private_asset_kind is OnlyPrivateAssetKind.FACTOR:
                revision = self._authority.load_factor_revision(locator.private_asset_id, locator.revision_fingerprint)
                content_fingerprint = revision.source_sha256
                asset_id = revision.factor_id
            else:
                revision = self._authority.load_strategy_revision(
                    locator.private_asset_id, locator.revision_fingerprint
                )
                content_fingerprint = revision.definition_fingerprint
                asset_id = revision.strategy_id
        except (OnlyPrivateAssetAuthorityUnavailableError, OnlyPrivateAssetCorruptError):
            raise
        except OnlyPrivateAssetNotFoundError as exc:
            raise OnlyPrivateAssetExactRevisionUnavailable(locator.revision_fingerprint) from exc
        except Exception as exc:
            raise OnlyPrivateAssetExactReadFailure(locator.revision_fingerprint) from exc
        if (
            asset_id != locator.private_asset_id
            or revision.revision_fingerprint != locator.revision_fingerprint
            or content_fingerprint != locator.content_fingerprint
        ):
            raise OnlyPrivateAssetExactReadMismatch(locator.revision_fingerprint)
        return revision


@dataclass(frozen=True, slots=True)
class OnlyProductAssetSearchProjectionV1:
    entries: tuple[OnlyProductAssetRegistryEntryV1, ...]
    registry_fingerprint: str
    completeness: OnlyProductAssetProjectionCompleteness
    projection_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        try:
            if (
                self.schema_version != 1
                or self.entries != tuple(sorted(self.entries, key=lambda item: item.sort_key))
                or self.projection_fingerprint
                != _projection_fingerprint(self.entries, self.registry_fingerprint, self.completeness)
            ):
                raise ValueError
            _require_sha(self.registry_fingerprint, "registry_fingerprint")
        except (TypeError, ValueError) as exc:
            raise OnlyProductAssetSearchProjectionCorrupt("projection verification") from exc

    @classmethod
    def from_registry(
        cls,
        registry: OnlyProductAssetRegistrySnapshotV1,
        completeness: OnlyProductAssetProjectionCompleteness = OnlyProductAssetProjectionCompleteness.CERTIFIED_COMPLETE,
    ) -> OnlyProductAssetSearchProjectionV1:
        return cls(
            registry.entries,
            registry.registry_fingerprint,
            completeness,
            _projection_fingerprint(registry.entries, registry.registry_fingerprint, completeness),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "registry_fingerprint": self.registry_fingerprint,
            "completeness": self.completeness.value,
            "projection_fingerprint": self.projection_fingerprint,
            "entries": [item.to_dict() for item in self.entries],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyProductAssetSearchProjectionV1:
        try:
            _exact(
                value,
                {"schema_version", "registry_fingerprint", "completeness", "projection_fingerprint", "entries"},
            )
            entries = value["entries"]
            if not isinstance(entries, list) or any(not isinstance(item, Mapping) for item in entries):
                raise ValueError
            return cls(
                tuple(OnlyProductAssetRegistryEntryV1.from_dict(cast(Mapping[str, object], item)) for item in entries),
                _string(value["registry_fingerprint"]),
                OnlyProductAssetProjectionCompleteness(_string(value["completeness"])),
                _string(value["projection_fingerprint"]),
                _integer(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyProductAssetSearchProjectionCorrupt("projection payload") from exc


@dataclass(frozen=True, slots=True)
class OnlyProductAssetSearchQueryV1:
    text: str | None = None
    kind: OnlyPrivateAssetKind | None = None
    category: str | None = None
    tag: str | None = None

    def __post_init__(self) -> None:
        for value in (self.text, self.category, self.tag):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("PRIVATE_ASSET_SEARCH_QUERY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyProductAssetSearchResultV1:
    status: OnlyProductAssetSearchStatus
    results: tuple[OnlyProductAssetRegistryEntryV1, ...]
    projection_fingerprint: str | None
    registry_fingerprint: str | None
    completeness: OnlyProductAssetProjectionCompleteness | None
    built_at: datetime | None
    projection_stale: bool = False


class OnlyProductAssetSearchProjectionStore(Protocol):
    def publish(self, projection: OnlyProductAssetSearchProjectionV1, built_at: datetime) -> None: ...

    def load_current(self) -> tuple[OnlyProductAssetSearchProjectionV1, datetime] | None: ...


class OnlyProductAssetSearchProjectionService:
    def __init__(
        self,
        registry: OnlyPrivateAssetProductService,
        store: OnlyProductAssetSearchProjectionStore,
        now_utc: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._store = store
        self._now_utc = now_utc

    def rebuild(self) -> OnlyProductAssetSearchProjectionV1:
        projection = OnlyProductAssetSearchProjectionV1.from_registry(self._registry.current_registry())
        self._store.publish(projection, self._now_utc())
        loaded = self._store.load_current()
        if loaded is None or loaded[0] != projection:
            raise OnlyProductAssetSearchProjectionCorrupt("publish verification")
        return projection

    def search(self, query: OnlyProductAssetSearchQueryV1) -> OnlyProductAssetSearchResultV1:
        try:
            loaded = self._store.load_current()
        except OnlyProductAssetSearchProjectionCorrupt:
            raise
        except OnlyProductAssetSearchProjectionUnavailable:
            loaded = None
        except Exception:
            loaded = None
        if loaded is None:
            return OnlyProductAssetSearchResultV1(
                OnlyProductAssetSearchStatus.PROJECTION_UNAVAILABLE, (), None, None, None, None
            )
        projection, built_at = loaded
        try:
            current = self._registry.current_registry()
        except Exception:
            return OnlyProductAssetSearchResultV1(
                OnlyProductAssetSearchStatus.PROJECTION_UNAVAILABLE,
                (),
                projection.projection_fingerprint,
                projection.registry_fingerprint,
                projection.completeness,
                built_at,
            )
        results = tuple(item for item in projection.entries if _matches(item, query))
        stale = current.registry_fingerprint != projection.registry_fingerprint
        if stale or projection.completeness is OnlyProductAssetProjectionCompleteness.INCOMPLETE:
            status = OnlyProductAssetSearchStatus.PROJECTION_INCOMPLETE
        elif results:
            status = OnlyProductAssetSearchStatus.MATCH
        else:
            status = OnlyProductAssetSearchStatus.NO_MATCH_ON_CERTIFIED_COMPLETE_PROJECTION
        return OnlyProductAssetSearchResultV1(
            status,
            results,
            projection.projection_fingerprint,
            projection.registry_fingerprint,
            projection.completeness,
            built_at,
            stale,
        )


def _factor_entry(revision: OnlyPrivateFactorRevision) -> OnlyProductAssetRegistryEntryV1:
    return OnlyProductAssetRegistryEntryV1(
        OnlyProductAssetLocatorV1(
            OnlyPrivateAssetKind.FACTOR,
            revision.factor_id,
            revision.revision_fingerprint,
            revision.source_sha256,
        ),
        revision.semantic_version,
        revision.description,
        revision.category,
        revision.tags,
    )


def _strategy_entry(revision: OnlyPrivateStrategyRevision) -> OnlyProductAssetRegistryEntryV1:
    return OnlyProductAssetRegistryEntryV1(
        OnlyProductAssetLocatorV1(
            OnlyPrivateAssetKind.STRATEGY,
            revision.strategy_id,
            revision.revision_fingerprint,
            revision.definition_fingerprint,
        ),
        revision.semantic_version,
        revision.description,
        None,
        revision.tags,
    )


def _matches(entry: OnlyProductAssetRegistryEntryV1, query: OnlyProductAssetSearchQueryV1) -> bool:
    if query.kind is not None and entry.locator.private_asset_kind is not query.kind:
        return False
    if query.category is not None and (entry.category or "").casefold() != query.category.strip().casefold():
        return False
    if query.tag is not None and query.tag.strip().casefold() not in {item.casefold() for item in entry.tags}:
        return False
    if query.text is None:
        return True
    needle = query.text.strip().casefold()
    haystack = " ".join(
        (entry.locator.private_asset_id, entry.description, entry.category or "", *entry.tags)
    ).casefold()
    return needle in haystack


def _registry_fingerprint(entries: tuple[OnlyProductAssetRegistryEntryV1, ...]) -> str:
    return only_canonical_fingerprint(
        {"contract": "ONLYALPHA_PRODUCT_ASSET_REGISTRY_V1", "entries": [item.to_dict() for item in entries]}
    )


def _projection_fingerprint(
    entries: tuple[OnlyProductAssetRegistryEntryV1, ...],
    registry_fingerprint: str,
    completeness: OnlyProductAssetProjectionCompleteness,
) -> str:
    return only_canonical_fingerprint(
        {
            "contract": "ONLYALPHA_PRODUCT_ASSET_SEARCH_PROJECTION_V1",
            "registry_fingerprint": registry_fingerprint,
            "completeness": completeness.value,
            "entries": [item.to_dict() for item in entries],
        }
    )


def _require_sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lower-case SHA-256")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be an integer")
    return value


def _exact(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise ValueError("fields are invalid")


__all__ = [name for name in globals() if name.startswith("Only")]
