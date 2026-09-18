"""Database-native Private Factor/Strategy authoring contracts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import NoReturn, Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint

PRIVATE_ASSET_SCHEMA_VERSION = 1

_FACTOR_ID = re.compile(r"^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_STRATEGY_ID = re.compile(r"^private\.strategy\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMANTIC_VERSION = re.compile(r"^[1-9][0-9]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OnlyPrivateAssetError(RuntimeError):
    code = "PRIVATE_ASSET_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyPrivateAssetInvalidError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_INVALID"


class OnlyPrivateAssetSchemaUnsupportedError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_SCHEMA_UNSUPPORTED"


class OnlyPrivateAssetNotFoundError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_NOT_FOUND"


class OnlyPrivateAssetConflictError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_CONFLICT"


class OnlyPrivateAssetCorruptError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_CORRUPT"


class OnlyPrivateAssetStaleBaseError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_STALE_BASE"


class OnlyPrivateAssetParentMismatchError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_PARENT_MISMATCH"


class OnlyPrivateAssetAuthorityUnavailableError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"


class OnlyPrivateAssetRevisionNotFoundError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_REVISION_NOT_FOUND"


class OnlyPrivateAssetRevisionCorruptError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_REVISION_CORRUPT"


class OnlyPrivateAssetReferenceMismatchError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_REFERENCE_MISMATCH"


class OnlyPrivateAssetKindUnsupportedError(OnlyPrivateAssetError):
    code = "PRIVATE_ASSET_KIND_UNSUPPORTED"


class OnlyPrivateAssetPutDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"


class OnlyPrivateAssetKind(StrEnum):
    FACTOR = "FACTOR"
    STRATEGY = "STRATEGY"


@dataclass(frozen=True, slots=True)
class OnlyPrivateAssetRevisionReferenceV1:
    """Caller-owned exact reference; contains no authority-derived facts."""

    private_asset_kind: OnlyPrivateAssetKind
    private_asset_id: str
    private_asset_revision_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.private_asset_kind, OnlyPrivateAssetKind):
            raise OnlyPrivateAssetKindUnsupportedError(str(self.private_asset_kind))
        if self.private_asset_kind is OnlyPrivateAssetKind.FACTOR:
            _factor_id(self.private_asset_id)
        elif self.private_asset_kind is OnlyPrivateAssetKind.STRATEGY:
            _strategy_id(self.private_asset_id)
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise OnlyPrivateAssetKindUnsupportedError(str(self.private_asset_kind))
        _fingerprint(self.private_asset_revision_fingerprint, "private_asset_revision_fingerprint")


@dataclass(frozen=True, slots=True)
class OnlyVerifiedPrivateAssetRevisionBindingV1:
    """Facts derived by resolving one exact immutable Revision."""

    private_asset_kind: OnlyPrivateAssetKind
    private_asset_id: str
    private_asset_revision_fingerprint: str
    private_asset_content_fingerprint: str
    semantic_version: str
    factor_api_version: int | None = None
    factor_api_contract_fingerprint: str | None = None

    def __post_init__(self) -> None:
        OnlyPrivateAssetRevisionReferenceV1(
            self.private_asset_kind,
            self.private_asset_id,
            self.private_asset_revision_fingerprint,
        )
        _fingerprint(self.private_asset_content_fingerprint, "private_asset_content_fingerprint")
        _semantic_version(self.semantic_version)
        if self.private_asset_kind is OnlyPrivateAssetKind.FACTOR:
            if self.factor_api_version != 1 or self.factor_api_contract_fingerprint is None:
                raise OnlyPrivateAssetReferenceMismatchError("Factor API binding is incomplete")
            _fingerprint(self.factor_api_contract_fingerprint, "factor_api_contract_fingerprint")
        elif self.factor_api_version is not None or self.factor_api_contract_fingerprint is not None:
            raise OnlyPrivateAssetReferenceMismatchError("Strategy Revision cannot carry an Factor API binding")


def _invalid(detail: str) -> NoReturn:
    raise OnlyPrivateAssetInvalidError(detail)


def _schema(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid("schema_version must be an integer")
    if value != PRIVATE_ASSET_SCHEMA_VERSION:
        raise OnlyPrivateAssetSchemaUnsupportedError(str(value))
    return value


def _string(value: object, name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        _invalid(f"{name} must be a string")
    return value


def _fingerprint(value: object, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _invalid(f"{name} must be a lower-case SHA-256")
    return cast(str | None, value)


def _factor_id(value: object) -> str:
    value = _string(value, "factor_id")
    if _FACTOR_ID.fullmatch(value) is None:
        _invalid("factor_id must use private.factor.<name>")
    return value


def _strategy_id(value: object) -> str:
    value = _string(value, "strategy_id")
    if _STRATEGY_ID.fullmatch(value) is None:
        _invalid("strategy_id must use private.strategy.<name>")
    return value


def _semantic_version(value: object) -> str:
    value = _string(value, "semantic_version")
    if _SEMANTIC_VERSION.fullmatch(value) is None:
        _invalid("semantic_version must be a positive integer string")
    return value


def _source(value: object) -> str:
    value = _string(value, "source_text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise OnlyPrivateAssetInvalidError("source_text must be valid UTF-8") from exc
    return value


def _tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item for item in value):
        _invalid("tags must be non-empty strings")
    canonical = tuple(sorted(cast(tuple[str, ...] | list[str], value)))
    if len(canonical) != len(set(canonical)):
        _invalid("tags must be unique")
    return canonical


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _invalid(f"{name} object keys must be strings")
        return MappingProxyType({key: _freeze_json(item, name) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, name) for item in value)
    _invalid(f"{name} must contain canonical JSON values")


def _object(value: object, name: str, *, nonempty: bool = False) -> Mapping[str, object]:
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping) or (nonempty and not frozen):
        _invalid(f"{name} must be an object")
    return cast(Mapping[str, object], frozen)


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        _invalid(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _exact(payload: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(payload) != expected:
        _invalid(f"{name} fields are invalid")


def only_private_factor_source_sha256(source_text: str) -> str:
    return hashlib.sha256(_source(source_text).encode("utf-8")).hexdigest()


def only_private_strategy_definition_fingerprint(definition: Mapping[str, object]) -> str:
    return only_canonical_fingerprint(
        {
            "contract": "ONLYALPHA_PRIVATE_STRATEGY_DEFINITION_V1",
            "definition": _object(definition, "definition", nonempty=True),
        }
    )


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorAsset:
    factor_id: str
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "factor_id", _factor_id(self.factor_id))
        _schema(self.schema_version)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "factor_id": self.factor_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorAsset:
        _exact(payload, {"schema_version", "factor_id"}, "Private Factor Asset")
        return cls(_factor_id(payload["factor_id"]), _schema(payload["schema_version"]))


@dataclass(slots=True)
class OnlyPrivateFactorDraft:
    factor_id: str
    semantic_version: str
    source_text: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    input_contract: Mapping[str, object]
    parameter_contract: Mapping[str, object]
    output_contract: Mapping[str, object]
    description: str
    economic_rationale: str
    category: str
    tags: tuple[str, ...] = ()
    base_revision_fingerprint: str | None = None
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.factor_id = _factor_id(self.factor_id)
        self.semantic_version = _semantic_version(self.semantic_version)
        self.source_text = _source(self.source_text)
        if isinstance(self.factor_api_version, bool) or self.factor_api_version != 1:
            _invalid("factor_api_version must equal 1")
        self.factor_api_contract_fingerprint = cast(
            str, _fingerprint(self.factor_api_contract_fingerprint, "factor_api_contract_fingerprint")
        )
        self.input_contract = _object(self.input_contract, "input_contract")
        self.parameter_contract = _object(self.parameter_contract, "parameter_contract")
        self.output_contract = _object(self.output_contract, "output_contract")
        self.description = _string(self.description, "description", nonempty=False)
        self.economic_rationale = _string(self.economic_rationale, "economic_rationale", nonempty=False)
        self.category = _string(self.category, "category")
        self.tags = _tags(self.tags)
        self.base_revision_fingerprint = _fingerprint(
            self.base_revision_fingerprint, "base_revision_fingerprint", optional=True
        )
        _schema(self.schema_version)

    @property
    def source_sha256(self) -> str:
        return only_private_factor_source_sha256(self.source_text)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "factor_id": self.factor_id,
            "base_revision_fingerprint": self.base_revision_fingerprint,
            "semantic_version": self.semantic_version,
            "source_text": self.source_text,
            "factor_api_version": self.factor_api_version,
            "factor_api_contract_fingerprint": self.factor_api_contract_fingerprint,
            "input_contract": _thaw_json(self.input_contract),
            "parameter_contract": _thaw_json(self.parameter_contract),
            "output_contract": _thaw_json(self.output_contract),
            "description": self.description,
            "economic_rationale": self.economic_rationale,
            "category": self.category,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorDraft:
        _exact(payload, _FACTOR_DRAFT_FIELDS, "Private Factor Draft")
        return cls(
            factor_id=_factor_id(payload["factor_id"]),
            semantic_version=_semantic_version(payload["semantic_version"]),
            source_text=_source(payload["source_text"]),
            factor_api_version=cast(int, payload["factor_api_version"]),
            factor_api_contract_fingerprint=cast(
                str, _fingerprint(payload["factor_api_contract_fingerprint"], "factor_api_contract_fingerprint")
            ),
            input_contract=_mapping(payload["input_contract"], "input_contract"),
            parameter_contract=_mapping(payload["parameter_contract"], "parameter_contract"),
            output_contract=_mapping(payload["output_contract"], "output_contract"),
            description=_string(payload["description"], "description", nonempty=False),
            economic_rationale=_string(payload["economic_rationale"], "economic_rationale", nonempty=False),
            category=_string(payload["category"], "category"),
            tags=_tags(payload["tags"]),
            base_revision_fingerprint=_fingerprint(
                payload["base_revision_fingerprint"], "base_revision_fingerprint", optional=True
            ),
            schema_version=_schema(payload["schema_version"]),
        )


_FACTOR_DRAFT_FIELDS = {
    "schema_version",
    "factor_id",
    "base_revision_fingerprint",
    "semantic_version",
    "source_text",
    "factor_api_version",
    "factor_api_contract_fingerprint",
    "input_contract",
    "parameter_contract",
    "output_contract",
    "description",
    "economic_rationale",
    "category",
    "tags",
}


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorRevision:
    factor_id: str
    semantic_version: str
    revision_fingerprint: str
    parent_revision_fingerprint: str | None
    source_text: str
    source_sha256: str
    factor_api_version: int
    factor_api_contract_fingerprint: str
    input_contract: Mapping[str, object]
    parameter_contract: Mapping[str, object]
    output_contract: Mapping[str, object]
    description: str
    economic_rationale: str
    category: str
    tags: tuple[str, ...] = ()
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "factor_id", _factor_id(self.factor_id))
        object.__setattr__(self, "semantic_version", _semantic_version(self.semantic_version))
        object.__setattr__(
            self, "parent_revision_fingerprint", _fingerprint(self.parent_revision_fingerprint, "parent", optional=True)
        )
        object.__setattr__(self, "source_text", _source(self.source_text))
        object.__setattr__(self, "input_contract", _object(self.input_contract, "input_contract"))
        object.__setattr__(self, "parameter_contract", _object(self.parameter_contract, "parameter_contract"))
        object.__setattr__(self, "output_contract", _object(self.output_contract, "output_contract"))
        object.__setattr__(self, "description", _string(self.description, "description", nonempty=False))
        object.__setattr__(
            self, "economic_rationale", _string(self.economic_rationale, "economic_rationale", nonempty=False)
        )
        object.__setattr__(self, "category", _string(self.category, "category"))
        object.__setattr__(self, "tags", _tags(self.tags))
        _schema(self.schema_version)
        if isinstance(self.factor_api_version, bool) or self.factor_api_version != 1:
            _invalid("factor_api_version must equal 1")
        _fingerprint(self.factor_api_contract_fingerprint, "factor_api_contract_fingerprint")
        _fingerprint(self.source_sha256, "source_sha256")
        _fingerprint(self.revision_fingerprint, "revision_fingerprint")
        if self.source_sha256 != only_private_factor_source_sha256(self.source_text):
            raise OnlyPrivateAssetCorruptError("PRIVATE_FACTOR_SOURCE_HASH_MISMATCH")
        if self.revision_fingerprint != only_private_factor_revision_fingerprint(self):
            raise OnlyPrivateAssetCorruptError("PRIVATE_FACTOR_REVISION_FINGERPRINT_MISMATCH")

    @classmethod
    def from_draft(cls, draft: OnlyPrivateFactorDraft) -> OnlyPrivateFactorRevision:
        clean = OnlyPrivateFactorDraft.from_dict(draft.to_dict())
        values: dict[str, object] = {
            "factor_id": clean.factor_id,
            "semantic_version": clean.semantic_version,
            "parent_revision_fingerprint": clean.base_revision_fingerprint,
            "source_text": clean.source_text,
            "source_sha256": clean.source_sha256,
            "factor_api_version": clean.factor_api_version,
            "factor_api_contract_fingerprint": clean.factor_api_contract_fingerprint,
            "input_contract": clean.input_contract,
            "parameter_contract": clean.parameter_contract,
            "output_contract": clean.output_contract,
            "description": clean.description,
            "economic_rationale": clean.economic_rationale,
            "category": clean.category,
            "tags": clean.tags,
            "schema_version": clean.schema_version,
        }
        return cls(
            factor_id=clean.factor_id,
            semantic_version=clean.semantic_version,
            revision_fingerprint=only_private_factor_revision_fingerprint(values),
            parent_revision_fingerprint=clean.base_revision_fingerprint,
            source_text=clean.source_text,
            source_sha256=clean.source_sha256,
            factor_api_version=clean.factor_api_version,
            factor_api_contract_fingerprint=clean.factor_api_contract_fingerprint,
            input_contract=clean.input_contract,
            parameter_contract=clean.parameter_contract,
            output_contract=clean.output_contract,
            description=clean.description,
            economic_rationale=clean.economic_rationale,
            category=clean.category,
            tags=clean.tags,
            schema_version=clean.schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return _factor_revision_payload(self)

    def to_dict(self) -> dict[str, object]:
        return {"revision_fingerprint": self.revision_fingerprint, **self.identity_payload()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorRevision:
        expected = (_FACTOR_DRAFT_FIELDS | {"revision_fingerprint", "parent_revision_fingerprint", "source_sha256"}) - {
            "base_revision_fingerprint"
        }
        _exact(payload, expected, "Private Factor Revision")
        return cls(
            factor_id=_factor_id(payload["factor_id"]),
            semantic_version=_semantic_version(payload["semantic_version"]),
            revision_fingerprint=cast(str, payload["revision_fingerprint"]),
            parent_revision_fingerprint=cast(str | None, payload["parent_revision_fingerprint"]),
            source_text=_source(payload["source_text"]),
            source_sha256=cast(str, payload["source_sha256"]),
            factor_api_version=cast(int, payload["factor_api_version"]),
            factor_api_contract_fingerprint=cast(str, payload["factor_api_contract_fingerprint"]),
            input_contract=_mapping(payload["input_contract"], "input_contract"),
            parameter_contract=_mapping(payload["parameter_contract"], "parameter_contract"),
            output_contract=_mapping(payload["output_contract"], "output_contract"),
            description=_string(payload["description"], "description", nonempty=False),
            economic_rationale=_string(payload["economic_rationale"], "economic_rationale", nonempty=False),
            category=_string(payload["category"], "category"),
            tags=_tags(payload["tags"]),
            schema_version=_schema(payload["schema_version"]),
        )


def _factor_revision_payload(value: OnlyPrivateFactorRevision | Mapping[str, object]) -> dict[str, object]:
    get = value.__getitem__ if isinstance(value, Mapping) else lambda name: getattr(value, name)
    return {
        "schema_version": get("schema_version"),
        "factor_id": get("factor_id"),
        "semantic_version": get("semantic_version"),
        "parent_revision_fingerprint": get("parent_revision_fingerprint"),
        "source_text": get("source_text"),
        "source_sha256": get("source_sha256"),
        "factor_api_version": get("factor_api_version"),
        "factor_api_contract_fingerprint": get("factor_api_contract_fingerprint"),
        "input_contract": _thaw_json(get("input_contract")),
        "parameter_contract": _thaw_json(get("parameter_contract")),
        "output_contract": _thaw_json(get("output_contract")),
        "description": get("description"),
        "economic_rationale": get("economic_rationale"),
        "category": get("category"),
        "tags": list(cast(tuple[str, ...], get("tags"))),
    }


def only_private_factor_revision_fingerprint(value: OnlyPrivateFactorRevision | Mapping[str, object]) -> str:
    return only_canonical_fingerprint(
        {"contract": "ONLYALPHA_PRIVATE_FACTOR_REVISION_V1", **_factor_revision_payload(value)}
    )


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyAsset:
    strategy_id: str
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _strategy_id(self.strategy_id))
        _schema(self.schema_version)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "strategy_id": self.strategy_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyAsset:
        _exact(payload, {"schema_version", "strategy_id"}, "Private Strategy Asset")
        return cls(_strategy_id(payload["strategy_id"]), _schema(payload["schema_version"]))


@dataclass(slots=True)
class OnlyPrivateStrategyDraft:
    strategy_id: str
    semantic_version: str
    definition: Mapping[str, object]
    description: str = ""
    tags: tuple[str, ...] = ()
    base_revision_fingerprint: str | None = None
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.strategy_id = _strategy_id(self.strategy_id)
        self.semantic_version = _semantic_version(self.semantic_version)
        self.definition = _object(self.definition, "definition", nonempty=True)
        self.description = _string(self.description, "description", nonempty=False)
        self.tags = _tags(self.tags)
        self.base_revision_fingerprint = _fingerprint(
            self.base_revision_fingerprint, "base_revision_fingerprint", optional=True
        )
        _schema(self.schema_version)

    @property
    def definition_fingerprint(self) -> str:
        return only_private_strategy_definition_fingerprint(self.definition)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "base_revision_fingerprint": self.base_revision_fingerprint,
            "semantic_version": self.semantic_version,
            "definition": _thaw_json(self.definition),
            "description": self.description,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyDraft:
        _exact(payload, _STRATEGY_DRAFT_FIELDS, "Private Strategy Draft")
        return cls(
            strategy_id=_strategy_id(payload["strategy_id"]),
            semantic_version=_semantic_version(payload["semantic_version"]),
            definition=_mapping(payload["definition"], "definition"),
            description=_string(payload["description"], "description", nonempty=False),
            tags=_tags(payload["tags"]),
            base_revision_fingerprint=_fingerprint(
                payload["base_revision_fingerprint"], "base_revision_fingerprint", optional=True
            ),
            schema_version=_schema(payload["schema_version"]),
        )


_STRATEGY_DRAFT_FIELDS = {
    "schema_version",
    "strategy_id",
    "base_revision_fingerprint",
    "semantic_version",
    "definition",
    "description",
    "tags",
}


@dataclass(frozen=True, slots=True)
class OnlyPrivateStrategyRevision:
    strategy_id: str
    semantic_version: str
    revision_fingerprint: str
    parent_revision_fingerprint: str | None
    definition: Mapping[str, object]
    definition_fingerprint: str
    description: str = ""
    tags: tuple[str, ...] = ()
    schema_version: int = PRIVATE_ASSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _strategy_id(self.strategy_id))
        object.__setattr__(self, "semantic_version", _semantic_version(self.semantic_version))
        object.__setattr__(
            self, "parent_revision_fingerprint", _fingerprint(self.parent_revision_fingerprint, "parent", optional=True)
        )
        object.__setattr__(self, "definition", _object(self.definition, "definition", nonempty=True))
        object.__setattr__(self, "description", _string(self.description, "description", nonempty=False))
        object.__setattr__(self, "tags", _tags(self.tags))
        _schema(self.schema_version)
        _fingerprint(self.definition_fingerprint, "definition_fingerprint")
        _fingerprint(self.revision_fingerprint, "revision_fingerprint")
        if self.definition_fingerprint != only_private_strategy_definition_fingerprint(self.definition):
            raise OnlyPrivateAssetCorruptError("PRIVATE_STRATEGY_DEFINITION_FINGERPRINT_MISMATCH")
        if self.revision_fingerprint != only_private_strategy_revision_fingerprint(self):
            raise OnlyPrivateAssetCorruptError("PRIVATE_STRATEGY_REVISION_FINGERPRINT_MISMATCH")

    @classmethod
    def from_draft(cls, draft: OnlyPrivateStrategyDraft) -> OnlyPrivateStrategyRevision:
        clean = OnlyPrivateStrategyDraft.from_dict(draft.to_dict())
        values: dict[str, object] = {
            "strategy_id": clean.strategy_id,
            "semantic_version": clean.semantic_version,
            "parent_revision_fingerprint": clean.base_revision_fingerprint,
            "definition": clean.definition,
            "definition_fingerprint": clean.definition_fingerprint,
            "description": clean.description,
            "tags": clean.tags,
            "schema_version": clean.schema_version,
        }
        return cls(
            strategy_id=clean.strategy_id,
            semantic_version=clean.semantic_version,
            revision_fingerprint=only_private_strategy_revision_fingerprint(values),
            parent_revision_fingerprint=clean.base_revision_fingerprint,
            definition=clean.definition,
            definition_fingerprint=clean.definition_fingerprint,
            description=clean.description,
            tags=clean.tags,
            schema_version=clean.schema_version,
        )

    def identity_payload(self) -> dict[str, object]:
        return _strategy_revision_payload(self)

    def to_dict(self) -> dict[str, object]:
        return {"revision_fingerprint": self.revision_fingerprint, **self.identity_payload()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateStrategyRevision:
        expected = (
            _STRATEGY_DRAFT_FIELDS
            | {
                "revision_fingerprint",
                "parent_revision_fingerprint",
                "definition_fingerprint",
            }
        ) - {"base_revision_fingerprint"}
        _exact(payload, expected, "Private Strategy Revision")
        return cls(
            strategy_id=_strategy_id(payload["strategy_id"]),
            semantic_version=_semantic_version(payload["semantic_version"]),
            revision_fingerprint=cast(str, payload["revision_fingerprint"]),
            parent_revision_fingerprint=cast(str | None, payload["parent_revision_fingerprint"]),
            definition=_mapping(payload["definition"], "definition"),
            definition_fingerprint=cast(str, payload["definition_fingerprint"]),
            description=_string(payload["description"], "description", nonempty=False),
            tags=_tags(payload["tags"]),
            schema_version=_schema(payload["schema_version"]),
        )


def _strategy_revision_payload(value: OnlyPrivateStrategyRevision | Mapping[str, object]) -> dict[str, object]:
    get = value.__getitem__ if isinstance(value, Mapping) else lambda name: getattr(value, name)
    return {
        "schema_version": get("schema_version"),
        "strategy_id": get("strategy_id"),
        "semantic_version": get("semantic_version"),
        "parent_revision_fingerprint": get("parent_revision_fingerprint"),
        "definition": _thaw_json(get("definition")),
        "definition_fingerprint": get("definition_fingerprint"),
        "description": get("description"),
        "tags": list(cast(tuple[str, ...], get("tags"))),
    }


def only_private_strategy_revision_fingerprint(value: OnlyPrivateStrategyRevision | Mapping[str, object]) -> str:
    return only_canonical_fingerprint(
        {"contract": "ONLYALPHA_PRIVATE_STRATEGY_REVISION_V1", **_strategy_revision_payload(value)}
    )


class OnlyPrivateAssetAuthoringAuthority(Protocol):
    def put_factor_asset(self, asset: OnlyPrivateFactorAsset) -> OnlyPrivateAssetPutDisposition: ...

    def load_factor_asset(self, factor_id: str) -> OnlyPrivateFactorAsset: ...

    def save_factor_draft(self, draft: OnlyPrivateFactorDraft) -> None: ...

    def load_factor_draft(self, factor_id: str) -> OnlyPrivateFactorDraft | None: ...

    def clear_factor_draft(self, factor_id: str) -> bool: ...

    def publish_factor_revision(
        self, factor_id: str
    ) -> tuple[OnlyPrivateAssetPutDisposition, OnlyPrivateFactorRevision]: ...

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision: ...

    def list_factor_revision_history(self, factor_id: str) -> tuple[OnlyPrivateFactorRevision, ...]: ...

    def put_strategy_asset(self, asset: OnlyPrivateStrategyAsset) -> OnlyPrivateAssetPutDisposition: ...

    def load_strategy_asset(self, strategy_id: str) -> OnlyPrivateStrategyAsset: ...

    def save_strategy_draft(self, draft: OnlyPrivateStrategyDraft) -> None: ...

    def load_strategy_draft(self, strategy_id: str) -> OnlyPrivateStrategyDraft | None: ...

    def clear_strategy_draft(self, strategy_id: str) -> bool: ...

    def publish_strategy_revision(
        self, strategy_id: str
    ) -> tuple[OnlyPrivateAssetPutDisposition, OnlyPrivateStrategyRevision]: ...

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision: ...

    def list_strategy_revision_history(self, strategy_id: str) -> tuple[OnlyPrivateStrategyRevision, ...]: ...


class OnlyPrivateAssetExactRevisionAuthority(Protocol):
    """Minimum owning-authority surface needed to bind exact Revisions."""

    def load_factor_revision(self, factor_id: str, revision_fingerprint: str) -> OnlyPrivateFactorRevision: ...

    def load_strategy_revision(self, strategy_id: str, revision_fingerprint: str) -> OnlyPrivateStrategyRevision: ...


class OnlyPrivateAssetRevisionBindingResolver:
    def __init__(self, authority: OnlyPrivateAssetExactRevisionAuthority) -> None:
        self._authority = authority

    def resolve_factor_revision(self, reference: OnlyPrivateAssetRevisionReferenceV1) -> OnlyPrivateFactorRevision:
        if not isinstance(reference, OnlyPrivateAssetRevisionReferenceV1):
            raise OnlyPrivateAssetInvalidError("exact Private Asset Revision reference is required")
        if reference.private_asset_kind is not OnlyPrivateAssetKind.FACTOR:
            raise OnlyPrivateAssetKindUnsupportedError(str(reference.private_asset_kind))
        try:
            revision = self._authority.load_factor_revision(
                reference.private_asset_id, reference.private_asset_revision_fingerprint
            )
            if (
                revision.factor_id != reference.private_asset_id
                or revision.revision_fingerprint != reference.private_asset_revision_fingerprint
            ):
                raise OnlyPrivateAssetReferenceMismatchError(reference.private_asset_id)
            return revision
        except OnlyPrivateAssetNotFoundError as exc:
            raise OnlyPrivateAssetRevisionNotFoundError(reference.private_asset_revision_fingerprint) from exc
        except OnlyPrivateAssetCorruptError as exc:
            raise OnlyPrivateAssetRevisionCorruptError(reference.private_asset_revision_fingerprint) from exc

    def resolve(self, reference: OnlyPrivateAssetRevisionReferenceV1) -> OnlyVerifiedPrivateAssetRevisionBindingV1:
        if not isinstance(reference, OnlyPrivateAssetRevisionReferenceV1):
            raise OnlyPrivateAssetInvalidError("exact Private Asset Revision reference is required")
        try:
            if reference.private_asset_kind is OnlyPrivateAssetKind.FACTOR:
                factor_revision = self.resolve_factor_revision(reference)
                return OnlyVerifiedPrivateAssetRevisionBindingV1(
                    private_asset_kind=reference.private_asset_kind,
                    private_asset_id=factor_revision.factor_id,
                    private_asset_revision_fingerprint=factor_revision.revision_fingerprint,
                    private_asset_content_fingerprint=factor_revision.source_sha256,
                    semantic_version=factor_revision.semantic_version,
                    factor_api_version=factor_revision.factor_api_version,
                    factor_api_contract_fingerprint=factor_revision.factor_api_contract_fingerprint,
                )
            if reference.private_asset_kind is OnlyPrivateAssetKind.STRATEGY:
                strategy_revision = self._authority.load_strategy_revision(
                    reference.private_asset_id, reference.private_asset_revision_fingerprint
                )
                if (
                    strategy_revision.strategy_id != reference.private_asset_id
                    or strategy_revision.revision_fingerprint != reference.private_asset_revision_fingerprint
                ):
                    raise OnlyPrivateAssetReferenceMismatchError(reference.private_asset_id)
                return OnlyVerifiedPrivateAssetRevisionBindingV1(
                    private_asset_kind=reference.private_asset_kind,
                    private_asset_id=strategy_revision.strategy_id,
                    private_asset_revision_fingerprint=strategy_revision.revision_fingerprint,
                    private_asset_content_fingerprint=strategy_revision.definition_fingerprint,
                    semantic_version=strategy_revision.semantic_version,
                )
            raise OnlyPrivateAssetKindUnsupportedError(str(reference.private_asset_kind))
        except OnlyPrivateAssetNotFoundError as exc:
            raise OnlyPrivateAssetRevisionNotFoundError(reference.private_asset_revision_fingerprint) from exc
        except OnlyPrivateAssetCorruptError as exc:
            raise OnlyPrivateAssetRevisionCorruptError(reference.private_asset_revision_fingerprint) from exc


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "PRIVATE_"))]
