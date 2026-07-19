"""Versioned market-profile registry and auditable resolution models."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.market.models import (
    OnlyLiquidityModel,
    OnlyMarketProfile,
    OnlyMarketProfileId,
    OnlyMatchingModel,
    OnlySlippageModel,
)


class OnlyMarketProfileStatus(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    STABLE = "STABLE"
    DEPRECATED = "DEPRECATED"
    REMOVED = "REMOVED"


class OnlyMarketProfileResolutionMode(StrEnum):
    AUTO_EFFECTIVE_DATE = "AUTO_EFFECTIVE_DATE"
    PINNED_VERSION = "PINNED_VERSION"


@dataclass(frozen=True, slots=True)
class OnlyMarketCapabilitySet:
    supports_intraday_resale: bool = False
    supports_t_plus_n: bool = False
    supports_short_selling: bool = False
    supports_borrow: bool = False
    supports_margin: bool = False
    supports_netting: bool = False
    supports_hedging: bool = False
    supports_fractional_quantity: bool = False
    supports_board_lot: bool = False
    supports_odd_lot: bool = False
    supports_minimum_notional: bool = False
    supports_multi_session: bool = False
    supports_cross_midnight_session: bool = False
    supports_24x7: bool = False
    supports_daily_price_limit: bool = False
    supports_dynamic_tick_table: bool = False
    supports_circuit_breaker: bool = False
    supports_partial_fill: bool = False
    supports_maker_taker: bool = False
    supports_contract_multiplier: bool = False
    supports_close_today: bool = False
    supports_funding: bool = False
    supports_liquidation: bool = False
    supports_multi_currency: bool = False

    @property
    def enabled(self) -> tuple[str, ...]:
        return tuple(name for name, value in asdict(self).items() if value)


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileOverridePolicy:
    allowed_paths: frozenset[str] = frozenset(
        {
            "liquidity.maximum_participation_rate",
            "slippage.model",
            "slippage.value",
            "slippage.ticks",
            "matching.model",
            "strict",
        }
    )

    def validate(self, overrides: Mapping[str, object]) -> None:
        rejected = sorted(path for path in _leaf_paths(overrides) if path not in self.allowed_paths)
        if rejected:
            raise ValueError(f"market profile override is not permitted: {', '.join(rejected)}")


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileFamily:
    profile_id: OnlyMarketProfileId
    display_name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileVersion:
    profile_id: OnlyMarketProfileId
    version: str
    status: OnlyMarketProfileStatus
    effective_from: date
    effective_to: date | None
    profile: OnlyMarketProfile
    capability_set: OnlyMarketCapabilitySet
    override_policy: OnlyMarketProfileOverridePolicy
    source: str
    schema_version: str = "1"
    content_fingerprint: str = ""
    conformance_pack_id: str | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("market profile version cannot be empty")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("profile effective_to must be later than effective_from")
        if self.profile.profile_id is not self.profile_id or self.profile.version != self.version:
            raise ValueError("profile identity does not match version registration")
        expected = self.profile.content_fingerprint
        if self.content_fingerprint and self.content_fingerprint != expected:
            raise ValueError("market profile content fingerprint mismatch")
        object.__setattr__(self, "content_fingerprint", expected)
        if self.status is OnlyMarketProfileStatus.STABLE:
            if not self.conformance_pack_id:
                raise ValueError("stable market profile requires a conformance pack")
            if not self.capability_set.enabled:
                raise ValueError("stable market profile requires declared capabilities")


@dataclass(frozen=True, slots=True)
class OnlyMarketProfileRequest:
    profile_id: OnlyMarketProfileId
    version: str | None = None
    overrides: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", MappingProxyType(dict(self.overrides)))

    @property
    def resolution_mode(self) -> OnlyMarketProfileResolutionMode:
        if self.version is None:
            return OnlyMarketProfileResolutionMode.AUTO_EFFECTIVE_DATE
        return OnlyMarketProfileResolutionMode.PINNED_VERSION


@dataclass(frozen=True, slots=True)
class OnlyResolvedMarketRuleManifest:
    profile_id: str
    profile_version: str
    schema_version: str
    rules: Mapping[str, object]
    resolved_rules_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", MappingProxyType(dict(self.rules)))


@dataclass(frozen=True, slots=True)
class OnlyResolvedMarketProfile:
    requested_profile_id: OnlyMarketProfileId
    requested_version: str | None
    resolution_mode: OnlyMarketProfileResolutionMode
    resolved_profile_id: OnlyMarketProfileId
    resolved_version: str
    status: OnlyMarketProfileStatus
    effective_from: date
    effective_to: date | None
    capabilities: OnlyMarketCapabilitySet
    reference_source: str | None
    reference_version: str | None
    reference_fingerprint: str | None
    override_fingerprint: str
    resolved_rules_fingerprint: str
    schema_version: str
    profile: OnlyMarketProfile
    manifest: OnlyResolvedMarketRuleManifest


class OnlyMarketProfileRegistry:
    """Immutable-identity registry with non-overlapping effective intervals."""

    def __init__(self, versions: Iterable[OnlyMarketProfileVersion] = ()) -> None:
        self._families: dict[OnlyMarketProfileId, OnlyMarketProfileFamily] = {}
        self._versions: dict[tuple[OnlyMarketProfileId, str], OnlyMarketProfileVersion] = {}
        for item in versions:
            self.register(item)

    def register_family(self, family: OnlyMarketProfileFamily) -> None:
        current = self._families.get(family.profile_id)
        if current is not None and current != family:
            raise ValueError(f"market profile family already registered: {family.profile_id}")
        self._families[family.profile_id] = family

    def register(self, item: OnlyMarketProfileVersion) -> None:
        key = (item.profile_id, item.version)
        if key in self._versions:
            raise ValueError(f"market profile version already registered: {item.profile_id}@{item.version}")
        for current in self.versions(item.profile_id):
            if _overlaps(current.effective_from, current.effective_to, item.effective_from, item.effective_to):
                raise ValueError(f"market profile effective intervals overlap: {item.profile_id}")
        self._versions[key] = item
        self._families.setdefault(item.profile_id, OnlyMarketProfileFamily(item.profile_id, item.profile_id.value))

    def families(self) -> tuple[OnlyMarketProfileFamily, ...]:
        return tuple(self._families[key] for key in sorted(self._families, key=lambda value: value.value))

    def versions(self, profile_id: OnlyMarketProfileId) -> tuple[OnlyMarketProfileVersion, ...]:
        return tuple(
            sorted(
                (item for (family, _), item in self._versions.items() if family is profile_id),
                key=lambda item: (item.effective_from, item.version),
            )
        )

    def resolve(
        self,
        request: OnlyMarketProfileRequest,
        effective_on: date,
        *,
        reference_source: str | None = None,
        reference_version: str | None = None,
        reference_fingerprint: str | None = None,
    ) -> OnlyResolvedMarketProfile:
        if request.version is None:
            matches = tuple(
                item
                for item in self.versions(request.profile_id)
                if item.effective_from <= effective_on
                and (item.effective_to is None or effective_on < item.effective_to)
                and item.status is not OnlyMarketProfileStatus.REMOVED
            )
        else:
            item = self._versions.get((request.profile_id, request.version))
            matches = () if item is None or item.status is OnlyMarketProfileStatus.REMOVED else (item,)
        if len(matches) != 1:
            identity = request.profile_id.value + ("" if request.version is None else f"@{request.version}")
            raise ValueError(f"expected one resolvable market profile: {identity} on {effective_on}")
        selected = matches[0]
        selected.override_policy.validate(request.overrides)
        profile = _apply_overrides(selected.profile, request.overrides)
        override_fingerprint = _fingerprint(request.overrides)
        rules = _profile_rules(profile)
        resolved_fingerprint = _fingerprint(
            {
                "profile": profile.content_fingerprint,
                "capabilities": asdict(selected.capability_set),
                "reference": reference_fingerprint,
                "overrides": override_fingerprint,
            }
        )
        manifest = OnlyResolvedMarketRuleManifest(
            selected.profile_id.value,
            selected.version,
            selected.schema_version,
            rules,
            resolved_fingerprint,
        )
        return OnlyResolvedMarketProfile(
            request.profile_id,
            request.version,
            request.resolution_mode,
            selected.profile_id,
            selected.version,
            selected.status,
            selected.effective_from,
            selected.effective_to,
            selected.capability_set,
            reference_source,
            reference_version,
            reference_fingerprint,
            override_fingerprint,
            resolved_fingerprint,
            selected.schema_version,
            profile,
            manifest,
        )


def _leaf_paths(value: Mapping[str, object], prefix: str = "") -> tuple[str, ...]:
    paths: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping):
            paths.extend(_leaf_paths(item, path))
        else:
            paths.append(path)
    return tuple(paths)


def _overlaps(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    return (a_to is None or b_from < a_to) and (b_to is None or a_from < b_to)


def _normalize(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, StrEnum)):
        return value.isoformat() if isinstance(value, date) else value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, frozenset)):
        return [_normalize(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    payload = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _profile_rules(profile: OnlyMarketProfile) -> Mapping[str, object]:
    return {
        "session": asdict(profile.session_model),
        "settlement": asdict(profile.settlement_model),
        "position": asdict(profile.position_model),
        "short_selling": asdict(profile.short_selling_rule),
        "margin": None if profile.margin_model is None else asdict(profile.margin_model),
        "price": asdict(profile.price_rule),
        "quantity": asdict(profile.quantity_rule),
        "fee": asdict(profile.fee_model),
        "liquidity": asdict(profile.liquidity_model),
        "slippage": asdict(profile.slippage_model),
        "matching": asdict(profile.matching_model),
    }


def _apply_overrides(profile: OnlyMarketProfile, overrides: Mapping[str, object]) -> OnlyMarketProfile:
    liquidity = overrides.get("liquidity")
    if isinstance(liquidity, Mapping) and "maximum_participation_rate" in liquidity:
        profile = replace(
            profile,
            liquidity_model=OnlyLiquidityModel(
                profile.liquidity_model.model_type, Decimal(str(liquidity["maximum_participation_rate"]))
            ),
        )
    slippage = overrides.get("slippage")
    if isinstance(slippage, Mapping):
        model = slippage.get("model", profile.slippage_model.model_type)
        value = slippage.get("ticks", slippage.get("value", profile.slippage_model.value))
        profile = replace(
            profile,
            slippage_model=OnlySlippageModel(type(profile.slippage_model.model_type)(model), Decimal(str(value))),
        )
    matching = overrides.get("matching")
    if isinstance(matching, Mapping) and "model" in matching:
        profile = replace(
            profile, matching_model=OnlyMatchingModel(type(profile.matching_model.model_type)(matching["model"]))
        )
    if "strict" in overrides:
        profile = replace(profile, strict=bool(overrides["strict"]))
    return profile
