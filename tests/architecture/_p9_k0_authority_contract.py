"""Architecture-only loader for the single P9.K.0 authority contract."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any


class AuthorityContractError(ValueError):
    """The machine-readable authority contract is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    name: str
    identity_authority: str
    mutation_capability: str
    read_capability: str | None
    recovery_capability: str | None
    semantic_persistence_relation: str


@dataclass(frozen=True, slots=True)
class Capability:
    id: str
    name: str
    kind: str
    privileged: bool
    reserved: bool


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    name: str
    production: bool
    allowed_capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class ActorPath:
    pattern: str
    actor: str


@dataclass(frozen=True, slots=True)
class Binding:
    capability: str
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class Ownership:
    capability: str
    approved_production_holders: frozenset[str]


@dataclass(frozen=True, slots=True)
class ConstructorOwnership:
    id: str
    capability: str
    symbol: str
    approved_paths: frozenset[str]


@dataclass(frozen=True, slots=True)
class LegacyDebt:
    id: str
    description: str
    paths: frozenset[str]
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class AuthorityContract:
    version: int
    name: str
    facts: Mapping[str, Fact]
    capabilities: Mapping[str, Capability]
    actors: Mapping[str, Actor]
    actor_paths: tuple[ActorPath, ...]
    sensitive_path_patterns: tuple[str, ...]
    bindings: Mapping[str, Binding]
    ownership: Mapping[str, Ownership]
    constructors: Mapping[str, ConstructorOwnership]
    legacy_debts: Mapping[str, LegacyDebt]
    reserved_future_capabilities: frozenset[str]

    def classify_path(self, path: str) -> Actor:
        matches = tuple(rule for rule in self.actor_paths if path_matches(path, rule.pattern))
        if len(matches) != 1:
            raise AuthorityContractError(f"{path} matches {len(matches)} actor classifications")
        return self.actors[matches[0].actor]

    def is_sensitive_path(self, path: str) -> bool:
        return any(path_matches(path, pattern) for pattern in self.sensitive_path_patterns)

    @property
    def symbol_capabilities(self) -> Mapping[str, frozenset[str]]:
        values: dict[str, set[str]] = {}
        for binding in self.bindings.values():
            for symbol in binding.symbols:
                values.setdefault(symbol, set()).add(binding.capability)
        return MappingProxyType({key: frozenset(value) for key, value in values.items()})


def path_matches(path: str, pattern: str) -> bool:
    return PurePosixPath(path).match(pattern)


def load_authority_contract(path: Path) -> AuthorityContract:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuthorityContractError(f"authority contract cannot be parsed: {exc}") from exc
    return authority_contract_from_document(document)


def load_authority_contract_text(source: str) -> AuthorityContract:
    try:
        document = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise AuthorityContractError(f"authority contract cannot be parsed: {exc}") from exc
    return authority_contract_from_document(document)


def authority_contract_from_document(document: Mapping[str, Any]) -> AuthorityContract:
    version = _integer(document, "contract_version")
    if version != 1:
        raise AuthorityContractError(f"unsupported authority contract version: {version}")
    name = _string(document, "name")
    facts = _indexed(
        document,
        "facts",
        lambda item: Fact(
            _string(item, "id"),
            _string(item, "name"),
            _string(item, "identity_authority"),
            _string(item, "mutation_capability"),
            _optional_string(item, "read_capability"),
            _optional_string(item, "recovery_capability"),
            _string(item, "semantic_persistence_relation"),
        ),
    )
    capabilities = _indexed(
        document,
        "capabilities",
        lambda item: Capability(
            _string(item, "id"),
            _string(item, "name"),
            _string(item, "kind"),
            _boolean(item, "privileged"),
            _boolean(item, "reserved", default=False),
        ),
    )
    actors = _indexed(
        document,
        "actors",
        lambda item: Actor(
            _string(item, "id"),
            _string(item, "name"),
            _boolean(item, "production"),
            frozenset(_string_list(item, "allowed_capabilities")),
        ),
    )
    actor_paths = tuple(
        ActorPath(_string(item, "pattern"), _string(item, "actor")) for item in _table_list(document, "actor_paths")
    )
    bindings = _indexed_by(
        document,
        "bindings",
        "capability",
        lambda item: Binding(_string(item, "capability"), frozenset(_string_list(item, "symbols"))),
    )
    ownership = _indexed_by(
        document,
        "ownership",
        "capability",
        lambda item: Ownership(
            _string(item, "capability"), frozenset(_string_list(item, "approved_production_holders"))
        ),
    )
    constructors = _indexed(
        document,
        "constructors",
        lambda item: ConstructorOwnership(
            _string(item, "id"),
            _string(item, "capability"),
            _string(item, "symbol"),
            frozenset(_string_list(item, "approved_paths")),
        ),
    )
    debts = _indexed(
        document,
        "legacy_debts",
        lambda item: LegacyDebt(
            _string(item, "id"),
            _string(item, "description"),
            frozenset(_string_list(item, "paths")),
            frozenset(_string_list(item, "capabilities")),
        ),
    )
    reserved = frozenset(_string_list(document, "reserved_future_capabilities"))
    sensitive = tuple(_string_list(document, "sensitive_path_patterns"))
    contract = AuthorityContract(
        version,
        name,
        MappingProxyType(facts),
        MappingProxyType(capabilities),
        MappingProxyType(actors),
        actor_paths,
        sensitive,
        MappingProxyType(bindings),
        MappingProxyType(ownership),
        MappingProxyType(constructors),
        MappingProxyType(debts),
        reserved,
    )
    _validate(contract)
    return contract


def _validate(contract: AuthorityContract) -> None:
    capability_ids = set(contract.capabilities)
    actor_ids = set(contract.actors)
    if not contract.facts or not capability_ids or not actor_ids:
        raise AuthorityContractError("facts, capabilities and actors must be non-empty")
    valid_kinds = {
        "READ",
        "VERIFY",
        "CREATE",
        "TRANSITION",
        "PUBLISH",
        "RECONCILE",
        "RECOVER",
        "MIGRATE",
        "CONSTRUCT",
        "EXECUTE",
    }
    invalid_kinds = {item.kind for item in contract.capabilities.values()} - valid_kinds
    if invalid_kinds:
        raise AuthorityContractError(f"unknown capability kinds: {sorted(invalid_kinds)}")
    for fact in contract.facts.values():
        references = {fact.mutation_capability}
        references.update(value for value in (fact.read_capability, fact.recovery_capability) if value is not None)
        _require_subset(references, capability_ids, f"fact {fact.id} capability")
    for actor in contract.actors.values():
        _require_subset(actor.allowed_capabilities, capability_ids, f"actor {actor.id} capability")
    for rule in contract.actor_paths:
        if rule.actor not in actor_ids:
            raise AuthorityContractError(f"actor path references unknown actor: {rule.actor}")
    if not contract.actor_paths or not contract.sensitive_path_patterns:
        raise AuthorityContractError("actor classification and sensitive path rules must be non-empty")
    if set(contract.bindings) != capability_ids:
        raise AuthorityContractError("every capability must have exactly one binding entry")
    privileged = {item.id for item in contract.capabilities.values() if item.privileged}
    if set(contract.ownership) != privileged:
        raise AuthorityContractError("every privileged capability must have exactly one ownership rule")
    for rule in contract.ownership.values():
        _require_subset(rule.approved_production_holders, actor_ids, f"ownership {rule.capability} actor")
        non_production = {actor for actor in rule.approved_production_holders if not contract.actors[actor].production}
        if non_production:
            raise AuthorityContractError(
                f"production ownership contains non-production actors: {sorted(non_production)}"
            )
    for constructor in contract.constructors.values():
        if constructor.capability not in privileged:
            raise AuthorityContractError(f"constructor {constructor.id} references non-privileged capability")
    for debt in contract.legacy_debts.values():
        _require_subset(debt.capabilities, capability_ids, f"legacy debt {debt.id} capability")
    _require_subset(contract.reserved_future_capabilities, capability_ids, "reserved capability")
    declared_reserved = {item.id for item in contract.capabilities.values() if item.reserved}
    if contract.reserved_future_capabilities != declared_reserved:
        raise AuthorityContractError("reserved capability declarations differ")
    for capability in contract.reserved_future_capabilities:
        if contract.ownership[capability].approved_production_holders:
            raise AuthorityContractError(f"reserved capability has production holders: {capability}")


def _indexed(document: Mapping[str, Any], key: str, factory: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw in _table_list(document, key):
        value = factory(raw)
        identifier = value.id
        if identifier in result:
            raise AuthorityContractError(f"duplicate {key} ID: {identifier}")
        result[identifier] = value
    return result


def _indexed_by(document: Mapping[str, Any], key: str, identifier_key: str, factory: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw in _table_list(document, key):
        identifier = _string(raw, identifier_key)
        if identifier in result:
            raise AuthorityContractError(f"duplicate {key} ID: {identifier}")
        result[identifier] = factory(raw)
    return result


def _table_list(document: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AuthorityContractError(f"{key} must be an array of tables")
    return tuple(value)


def _string(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise AuthorityContractError(f"{key} must be a non-empty string")
    return value


def _optional_string(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AuthorityContractError(f"{key} must be a non-empty string when present")
    return value


def _string_list(document: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise AuthorityContractError(f"{key} must be a string array")
    if len(value) != len(set(value)):
        raise AuthorityContractError(f"{key} contains duplicates")
    return tuple(value)


def _integer(document: Mapping[str, Any], key: str) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuthorityContractError(f"{key} must be an integer")
    return value


def _boolean(document: Mapping[str, Any], key: str, *, default: bool | None = None) -> bool:
    value = document.get(key, default)
    if not isinstance(value, bool):
        raise AuthorityContractError(f"{key} must be a boolean")
    return value


def _require_subset(values: set[str] | frozenset[str], allowed: set[str], label: str) -> None:
    unknown = set(values) - allowed
    if unknown:
        raise AuthorityContractError(f"{label} references unknown IDs: {sorted(unknown)}")


__all__ = [
    "Actor",
    "AuthorityContract",
    "AuthorityContractError",
    "Capability",
    "ConstructorOwnership",
    "Fact",
    "authority_contract_from_document",
    "load_authority_contract",
    "load_authority_contract_text",
    "path_matches",
]
