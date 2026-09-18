"""Portable example seeds imported through the Private Asset Authority."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint

from .private import (
    OnlyPrivateAssetAuthoringAuthority,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionReferenceV1,
    OnlyPrivateFactorAsset,
    OnlyPrivateFactorDraft,
    OnlyPrivateStrategyAsset,
    OnlyPrivateStrategyDraft,
)
from .private_factor_execution import ONLY_PRIVATE_FACTOR_API_V1

_EXAMPLE_ID = re.compile(r"^(?:factor|strategy)\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class OnlyPrivateAssetExampleBundleV1:
    example_id: str
    display_name: str
    description: str
    asset_kind: OnlyPrivateAssetKind
    dependencies: tuple[str, ...]
    payload: Mapping[str, object]
    source_text: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or self.schema_version != 1
            or not isinstance(self.example_id, str)
            or _EXAMPLE_ID.fullmatch(self.example_id) is None
        ):
            raise ValueError("PRIVATE_ASSET_EXAMPLE_ID_INVALID")
        if (
            not isinstance(self.display_name, str)
            or not self.display_name
            or not isinstance(self.description, str)
            or not isinstance(self.asset_kind, OnlyPrivateAssetKind)
            or not isinstance(self.payload, Mapping)
        ):
            raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID")
        if (
            any(not isinstance(item, str) for item in self.dependencies)
            or tuple(sorted(set(self.dependencies))) != self.dependencies
        ):
            raise ValueError("PRIVATE_ASSET_EXAMPLE_DEPENDENCIES_INVALID")
        if self.asset_kind is OnlyPrivateAssetKind.FACTOR:
            if self.dependencies or not isinstance(self.source_text, str):
                raise ValueError("PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID")
        elif self.asset_kind is OnlyPrivateAssetKind.STRATEGY:
            if self.source_text is not None:
                raise ValueError("PRIVATE_STRATEGY_EXAMPLE_BUNDLE_INVALID")
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise ValueError("PRIVATE_ASSET_EXAMPLE_KIND_INVALID")

    @property
    def bundle_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "schema_version": self.schema_version,
                "example_id": self.example_id,
                "display_name": self.display_name,
                "description": self.description,
                "asset_kind": self.asset_kind.value,
                "dependencies": list(self.dependencies),
                "payload": self.payload,
                "source_text": self.source_text,
            }
        )


def only_load_private_asset_example_bundle(root: Path) -> OnlyPrivateAssetExampleBundleV1:
    metadata_path = root / ("asset.json" if root.parent.name == "factor" else "strategy.json")
    try:
        raw = metadata_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID")
    common = {"schema_version", "example_id", "display_name", "description", "asset_kind", "dependencies"}
    asset_kind = payload.get("asset_kind")
    if not isinstance(asset_kind, str):
        raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID")
    kind = OnlyPrivateAssetKind(asset_kind)
    body_name = "factor" if kind is OnlyPrivateAssetKind.FACTOR else "strategy"
    if set(payload) != common | {body_name} or not isinstance(payload[body_name], dict):
        raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID")
    dependencies = payload["dependencies"]
    if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
        raise ValueError("PRIVATE_ASSET_EXAMPLE_DEPENDENCIES_INVALID")
    source_text = None
    if kind is OnlyPrivateAssetKind.FACTOR:
        try:
            source_text = (root / "source.py").read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("PRIVATE_FACTOR_EXAMPLE_SOURCE_INVALID") from exc
    return OnlyPrivateAssetExampleBundleV1(
        example_id=_string(payload["example_id"], "PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID"),
        display_name=_string(payload["display_name"], "PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID"),
        description=_string(payload["description"], "PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID", nonempty=False),
        asset_kind=kind,
        dependencies=tuple(cast(list[str], dependencies)),
        payload=cast(dict[str, object], payload[body_name]),
        source_text=source_text,
        schema_version=_schema_version(payload["schema_version"]),
    )


@dataclass(frozen=True, slots=True)
class OnlyPrivateAssetExampleImporterV1:
    authority: OnlyPrivateAssetAuthoringAuthority

    def import_bundles(
        self, bundles: Iterable[OnlyPrivateAssetExampleBundleV1]
    ) -> dict[str, OnlyPrivateAssetRevisionReferenceV1]:
        ordered = sorted(bundles, key=lambda item: (item.asset_kind is OnlyPrivateAssetKind.STRATEGY, item.example_id))
        imported: dict[str, OnlyPrivateAssetRevisionReferenceV1] = {}
        for bundle in ordered:
            if bundle.example_id in imported:
                raise ValueError("PRIVATE_ASSET_EXAMPLE_DUPLICATE")
            imported[bundle.example_id] = self._import(bundle, imported)
        return imported

    def _import(
        self,
        bundle: OnlyPrivateAssetExampleBundleV1,
        imported: Mapping[str, OnlyPrivateAssetRevisionReferenceV1],
    ) -> OnlyPrivateAssetRevisionReferenceV1:
        payload = dict(bundle.payload)
        if bundle.asset_kind is OnlyPrivateAssetKind.FACTOR:
            if set(payload) != {
                "factor_id",
                "semantic_version",
                "input_contract",
                "parameter_contract",
                "output_contract",
                "economic_rationale",
                "category",
                "tags",
            }:
                raise ValueError("PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID")
            factor_id = _string(payload.pop("factor_id"), "PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID")
            self.authority.put_factor_asset(OnlyPrivateFactorAsset(factor_id))
            factor_draft = OnlyPrivateFactorDraft(
                factor_id=factor_id,
                source_text=cast(str, bundle.source_text),
                description=bundle.description,
                factor_api_version=1,
                factor_api_contract_fingerprint=ONLY_PRIVATE_FACTOR_API_V1.api_contract_fingerprint,
                semantic_version=_string(payload["semantic_version"], "PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID"),
                input_contract=cast(Mapping[str, object], payload["input_contract"]),
                parameter_contract=cast(Mapping[str, object], payload["parameter_contract"]),
                output_contract=cast(Mapping[str, object], payload["output_contract"]),
                economic_rationale=_string(
                    payload["economic_rationale"], "PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID", nonempty=False
                ),
                category=_string(payload["category"], "PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID"),
                tags=_tags(payload["tags"], "PRIVATE_FACTOR_EXAMPLE_BUNDLE_INVALID"),
            )
            self.authority.save_factor_draft(factor_draft)
            _, factor_revision = self.authority.publish_factor_revision(factor_id)
            return OnlyPrivateAssetRevisionReferenceV1(
                OnlyPrivateAssetKind.FACTOR, factor_revision.factor_id, factor_revision.revision_fingerprint
            )

        if set(payload) != {"strategy_id", "semantic_version", "definition", "tags"}:
            raise ValueError("PRIVATE_STRATEGY_EXAMPLE_BUNDLE_INVALID")
        missing = set(bundle.dependencies) - set(imported)
        if missing or any(
            imported[item].private_asset_kind is not OnlyPrivateAssetKind.FACTOR for item in bundle.dependencies
        ):
            raise ValueError("PRIVATE_STRATEGY_EXAMPLE_DEPENDENCY_UNRESOLVED")
        strategy_id = _string(payload.pop("strategy_id"), "PRIVATE_STRATEGY_EXAMPLE_BUNDLE_INVALID")
        raw_definition = payload.pop("definition")
        if not isinstance(raw_definition, dict) or "factor_revision_dependencies" in raw_definition:
            raise ValueError("PRIVATE_STRATEGY_EXAMPLE_DEFINITION_INVALID")
        definition = dict(raw_definition)
        definition["factor_revision_dependencies"] = [
            {
                "example_id": item,
                "factor_id": imported[item].private_asset_id,
                "revision_fingerprint": imported[item].private_asset_revision_fingerprint,
            }
            for item in bundle.dependencies
        ]
        self.authority.put_strategy_asset(OnlyPrivateStrategyAsset(strategy_id))
        strategy_draft = OnlyPrivateStrategyDraft(
            strategy_id=strategy_id,
            definition=definition,
            description=bundle.description,
            semantic_version=_string(payload["semantic_version"], "PRIVATE_STRATEGY_EXAMPLE_BUNDLE_INVALID"),
            tags=_tags(payload["tags"], "PRIVATE_STRATEGY_EXAMPLE_BUNDLE_INVALID"),
        )
        self.authority.save_strategy_draft(strategy_draft)
        _, strategy_revision = self.authority.publish_strategy_revision(strategy_id)
        return OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind.STRATEGY, strategy_revision.strategy_id, strategy_revision.revision_fingerprint
        )


def _schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise ValueError("PRIVATE_ASSET_EXAMPLE_BUNDLE_INVALID")
    return value


def _string(value: object, error: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ValueError(error)
    return value


def _tags(value: object, error: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(error)
    return tuple(value)
