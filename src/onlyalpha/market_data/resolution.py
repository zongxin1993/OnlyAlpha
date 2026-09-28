"""Canonical Bar construction recipes, resolution, lineage, and runtime dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyPriceType
from onlyalpha.domain.market import (
    OnlyBarAlignment,
    OnlyBarSemantic,
    OnlyBarType,
    OnlyFixedDurationBarFormation,
)


class OnlyBarConstructionKind(StrEnum):
    PROVIDER_NATIVE = "PROVIDER_NATIVE"
    DERIVED = "DERIVED"


class OnlyBarResolutionMode(StrEnum):
    PROVIDER_NATIVE = "PROVIDER_NATIVE"
    DERIVED = "DERIVED"


class OnlyBarResolutionPolicy(StrEnum):
    PREFER_EXACT_NATIVE = "PREFER_EXACT_NATIVE"


class OnlyBarConstructionRequirementKind(StrEnum):
    POLICY = "POLICY"
    EXACT_RECIPE = "EXACT_RECIPE"


class OnlyBarMissingPolicy(StrEnum):
    REJECT = "REJECT"
    SKIP_WINDOW = "SKIP_WINDOW"


class OnlyBarIncompletePolicy(StrEnum):
    DROP = "DROP"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class OnlyBarConstructionRecipe:
    target_semantic: OnlyBarSemantic
    kind: OnlyBarConstructionKind
    base_semantic: OnlyBarSemantic | None = None
    algorithm_id: str | None = None
    algorithm_version: int | None = None
    missing_policy: OnlyBarMissingPolicy | None = None
    incomplete_policy: OnlyBarIncompletePolicy | None = None
    alignment_requirement: OnlyBarAlignment | None = None

    def __post_init__(self) -> None:
        native = self.kind is OnlyBarConstructionKind.PROVIDER_NATIVE
        derived = (
            self.base_semantic,
            self.algorithm_id,
            self.algorithm_version,
            self.missing_policy,
            self.incomplete_policy,
            self.alignment_requirement,
        )
        if (native and any(value is not None for value in derived)) or (
            not native and any(value is None for value in derived)
        ):
            raise ValueError("BAR_CONSTRUCTION_RECIPE_INVALID")
        if not native:
            assert self.base_semantic is not None
            if (
                self.algorithm_version is None
                or self.algorithm_version < 1
                or self.target_semantic.price_type is not self.base_semantic.price_type
                or self.target_semantic.adjustment_policy is not self.base_semantic.adjustment_policy
            ):
                raise ValueError("BAR_CONSTRUCTION_RECIPE_INVALID")

    @classmethod
    def provider_native(cls, target: OnlyBarSemantic) -> OnlyBarConstructionRecipe:
        return cls(target, OnlyBarConstructionKind.PROVIDER_NATIVE)

    @classmethod
    def derived(
        cls,
        target: OnlyBarSemantic,
        base: OnlyBarSemantic,
        *,
        algorithm_id: str,
        algorithm_version: int = 1,
        missing_policy: OnlyBarMissingPolicy = OnlyBarMissingPolicy.REJECT,
        incomplete_policy: OnlyBarIncompletePolicy = OnlyBarIncompletePolicy.DROP,
    ) -> OnlyBarConstructionRecipe:
        if not base.is_fixed_duration:
            raise ValueError("BAR_CONSTRUCTION_RECIPE_BASE_UNSUPPORTED")
        assert isinstance(base.formation, OnlyFixedDurationBarFormation)
        return cls(
            target,
            OnlyBarConstructionKind.DERIVED,
            base,
            algorithm_id,
            algorithm_version,
            missing_policy,
            incomplete_policy,
            base.formation.alignment,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target_semantic": self.target_semantic.to_dict(),
            "kind": self.kind.value,
            "base_semantic": None if self.base_semantic is None else self.base_semantic.to_dict(),
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "missing_policy": None if self.missing_policy is None else self.missing_policy.value,
            "incomplete_policy": None if self.incomplete_policy is None else self.incomplete_policy.value,
            "alignment_requirement": None if self.alignment_requirement is None else self.alignment_requirement.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarConstructionRecipe:
        if value.get("schema_version") != 1 or not isinstance(value.get("target_semantic"), Mapping):
            raise ValueError("BAR_CONSTRUCTION_RECIPE_REBUILD_REQUIRED")
        base = value.get("base_semantic")
        if base is not None and not isinstance(base, Mapping):
            raise ValueError("BAR_CONSTRUCTION_RECIPE_INVALID")
        target = value["target_semantic"]
        assert isinstance(target, Mapping)
        recipe = cls(
            OnlyBarSemantic.from_dict(target),
            OnlyBarConstructionKind(str(value["kind"])),
            None if base is None else OnlyBarSemantic.from_dict(base),
            None if value.get("algorithm_id") is None else str(value["algorithm_id"]),
            None if value.get("algorithm_version") is None else int(str(value["algorithm_version"])),
            None if value.get("missing_policy") is None else OnlyBarMissingPolicy(str(value["missing_policy"])),
            None
            if value.get("incomplete_policy") is None
            else OnlyBarIncompletePolicy(str(value["incomplete_policy"])),
            None
            if value.get("alignment_requirement") is None
            else OnlyBarAlignment(str(value["alignment_requirement"])),
        )
        if recipe.to_dict() != dict(value):
            raise ValueError("BAR_CONSTRUCTION_RECIPE_INVALID")
        return recipe

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())


@dataclass(frozen=True, slots=True)
class OnlyBarConstructionRequirement:
    kind: OnlyBarConstructionRequirementKind
    policy: OnlyBarResolutionPolicy | None = None
    recipe: OnlyBarConstructionRecipe | None = None

    def __post_init__(self) -> None:
        valid = (
            self.kind is OnlyBarConstructionRequirementKind.POLICY and self.policy is not None and self.recipe is None
        ) or (
            self.kind is OnlyBarConstructionRequirementKind.EXACT_RECIPE
            and self.policy is None
            and self.recipe is not None
        )
        if not valid:
            raise ValueError("BAR_CONSTRUCTION_REQUIREMENT_INVALID")

    @classmethod
    def prefer_exact_native(cls) -> OnlyBarConstructionRequirement:
        return cls(OnlyBarConstructionRequirementKind.POLICY, OnlyBarResolutionPolicy.PREFER_EXACT_NATIVE)

    @classmethod
    def exact(cls, recipe: OnlyBarConstructionRecipe) -> OnlyBarConstructionRequirement:
        return cls(OnlyBarConstructionRequirementKind.EXACT_RECIPE, recipe=recipe)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind.value,
            "policy": None if self.policy is None else self.policy.value,
            "recipe": None if self.recipe is None else self.recipe.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarConstructionRequirement:
        if value.get("schema_version") != 1:
            raise ValueError("BAR_CONSTRUCTION_REQUIREMENT_REBUILD_REQUIRED")
        recipe = value.get("recipe")
        if recipe is not None and not isinstance(recipe, Mapping):
            raise ValueError("BAR_CONSTRUCTION_REQUIREMENT_INVALID")
        requirement = cls(
            OnlyBarConstructionRequirementKind(str(value["kind"])),
            None if value.get("policy") is None else OnlyBarResolutionPolicy(str(value["policy"])),
            None if recipe is None else OnlyBarConstructionRecipe.from_dict(recipe),
        )
        if requirement.to_dict() != dict(value):
            raise ValueError("BAR_CONSTRUCTION_REQUIREMENT_INVALID")
        return requirement


@dataclass(frozen=True, slots=True)
class OnlyBarCapability:
    semantic: OnlyBarSemantic
    historical_supported: bool
    realtime_supported: bool
    calendar_fingerprint: str
    grid_origin_ns: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.calendar_fingerprint
            or (self.grid_origin_ns is not None and type(self.grid_origin_ns) is not int)
            or self.semantic.adjustment_policy is not OnlyAdjustmentType.RAW
        ):
            raise ValueError("BAR_CAPABILITY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBarResolutionPlan:
    target_semantic: OnlyBarSemantic
    requirement: OnlyBarConstructionRequirement
    resolved_recipe: OnlyBarConstructionRecipe
    source_id: str
    instrument_id: str
    integration_revision_fingerprint: str
    calendar_fingerprint: str
    grid_origin_ns: int
    fingerprint: str

    @property
    def mode(self) -> OnlyBarResolutionMode:
        return OnlyBarResolutionMode(self.resolved_recipe.kind.value)

    @property
    def provider_semantic(self) -> OnlyBarSemantic | None:
        return self.target_semantic if self.mode is OnlyBarResolutionMode.PROVIDER_NATIVE else None

    @property
    def base_semantic(self) -> OnlyBarSemantic | None:
        return self.resolved_recipe.base_semantic

    @property
    def aggregation_semantics_version(self) -> str | None:
        if self.resolved_recipe.algorithm_id is None:
            return None
        return f"{self.resolved_recipe.algorithm_id}_V{self.resolved_recipe.algorithm_version}"

    @property
    def recipe_fingerprint(self) -> str:
        return self.resolved_recipe.fingerprint

    @property
    def alignment_id(self) -> str:
        return self.calendar_fingerprint

    def to_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 3,
            "target_semantic": self.target_semantic.to_dict(),
            "requirement": self.requirement.to_dict(),
            "resolved_recipe": self.resolved_recipe.to_dict(),
            "source_id": self.source_id,
            "instrument_id": self.instrument_id,
            "integration_revision_fingerprint": self.integration_revision_fingerprint,
            "calendar_fingerprint": self.calendar_fingerprint,
            "grid_origin_ns": self.grid_origin_ns,
        }
        return {**payload, "fingerprint": only_canonical_fingerprint(payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarResolutionPlan:
        if value.get("schema_version") != 3:
            raise ValueError("BAR_RESOLUTION_PLAN_REBUILD_REQUIRED")
        if any(
            not isinstance(value.get(key), Mapping) for key in ("target_semantic", "requirement", "resolved_recipe")
        ):
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        plan = cls(
            OnlyBarSemantic.from_dict(value["target_semantic"]),  # type: ignore[arg-type]
            OnlyBarConstructionRequirement.from_dict(value["requirement"]),  # type: ignore[arg-type]
            OnlyBarConstructionRecipe.from_dict(value["resolved_recipe"]),  # type: ignore[arg-type]
            str(value["source_id"]),
            str(value["instrument_id"]),
            str(value["integration_revision_fingerprint"]),
            str(value["calendar_fingerprint"]),
            int(str(value["grid_origin_ns"])),
            str(value["fingerprint"]),
        )
        if plan.to_dict() != dict(value) or plan.target_semantic != plan.resolved_recipe.target_semantic:
            raise ValueError("BAR_RESOLUTION_PLAN_INVALID")
        return plan

    @classmethod
    def from_canonical_payload(cls, value: Mapping[str, object]) -> OnlyBarResolutionPlan:
        if "resolved_recipe" not in value:
            raise ValueError("BAR_RESOLUTION_PLAN_REBUILD_REQUIRED")
        return cls.from_dict(value)


@dataclass(frozen=True, slots=True)
class OnlyBarConstructionIdentity:
    plan: OnlyBarResolutionPlan
    data_version: str
    provider_semantic: str | None
    base_revision_id: str | None
    base_revision_fingerprint: str | None
    base_seal_id: str | None
    adjustment_evidence: str | None
    fingerprint: str

    @classmethod
    def build(
        cls,
        plan: OnlyBarResolutionPlan,
        *,
        data_version: str,
        provider_semantic: str | None = None,
        base_revision_id: str | None = None,
        base_revision_fingerprint: str | None = None,
        base_seal_id: str | None = None,
        adjustment_evidence: str | None = None,
    ) -> OnlyBarConstructionIdentity:
        if not data_version or plan.to_dict()["fingerprint"] != plan.fingerprint:
            raise ValueError("BAR_CONSTRUCTION_INVALID")
        base = (base_revision_id, base_revision_fingerprint, base_seal_id)
        native = plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE
        if (native and any(base)) or (not native and not all(base)):
            raise ValueError("BAR_CONSTRUCTION_BASE_REVISION_REQUIRED")
        if plan.target_semantic.adjustment_policy is not OnlyAdjustmentType.RAW and not adjustment_evidence:
            raise ValueError("BAR_CONSTRUCTION_ADJUSTMENT_EVIDENCE_REQUIRED")
        payload = {
            "schema_version": 2,
            "plan": plan.to_dict(),
            "data_version": data_version,
            "provider_semantic": provider_semantic,
            "base_revision_id": base_revision_id,
            "base_revision_fingerprint": base_revision_fingerprint,
            "base_seal_id": base_seal_id,
            "adjustment_evidence": adjustment_evidence,
        }
        return cls(
            plan, data_version, provider_semantic, *base, adjustment_evidence, only_canonical_fingerprint(payload)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "plan": self.plan.to_dict(),
            "data_version": self.data_version,
            "provider_semantic": self.provider_semantic,
            "base_revision_id": self.base_revision_id,
            "base_revision_fingerprint": self.base_revision_fingerprint,
            "base_seal_id": self.base_seal_id,
            "adjustment_evidence": self.adjustment_evidence,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> OnlyBarConstructionIdentity:
        if value.get("schema_version") != 2 or not isinstance(value.get("plan"), Mapping):
            raise ValueError("BAR_CONSTRUCTION_REBUILD_REQUIRED")

        def optional(key: str) -> str | None:
            item = value.get(key)
            if item is not None and not isinstance(item, str):
                raise ValueError("BAR_CONSTRUCTION_INVALID")
            return item

        identity = cls.build(
            OnlyBarResolutionPlan.from_dict(value["plan"]),  # type: ignore[arg-type]
            data_version=str(value["data_version"]),
            provider_semantic=optional("provider_semantic"),
            base_revision_id=optional("base_revision_id"),
            base_revision_fingerprint=optional("base_revision_fingerprint"),
            base_seal_id=optional("base_seal_id"),
            adjustment_evidence=optional("adjustment_evidence"),
        )
        if identity.to_dict() != dict(value):
            raise ValueError("BAR_CONSTRUCTION_INVALID")
        return identity

    @classmethod
    def from_canonical_payload(cls, value: Mapping[str, object]) -> OnlyBarConstructionIdentity:
        if "schema_version" not in value:
            raise ValueError("BAR_CONSTRUCTION_REBUILD_REQUIRED")
        return cls.from_dict(value)


@dataclass(frozen=True, slots=True)
class OnlyBarDerivedDependency:
    source: OnlyBarType
    target: OnlyBarType
    recipe: OnlyBarConstructionRecipe

    def __post_init__(self) -> None:
        if (
            self.source.instrument_id != self.target.instrument_id
            or self.source.semantic != self.recipe.base_semantic
            or self.target.semantic != self.recipe.target_semantic
            or self.recipe.kind is not OnlyBarConstructionKind.DERIVED
        ):
            raise ValueError("BAR_DEPENDENCY_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBarDependencyGraph:
    provider_inputs: tuple[OnlyBarType, ...]
    derived_dependencies: tuple[OnlyBarDerivedDependency, ...]

    def __post_init__(self) -> None:
        if len(set(self.provider_inputs)) != len(self.provider_inputs):
            raise ValueError("BAR_DEPENDENCY_GRAPH_INVALID")
        targets = {item.target for item in self.derived_dependencies}
        if len(targets) != len(self.derived_dependencies) or targets.intersection(self.provider_inputs):
            raise ValueError("BAR_DEPENDENCY_GRAPH_INVALID")
        available_sources = set(self.provider_inputs) | targets
        if any(item.source not in available_sources for item in self.derived_dependencies):
            raise ValueError("BAR_DEPENDENCY_GRAPH_INVALID")
        adjacency: dict[OnlyBarType, tuple[OnlyBarType, ...]] = {}
        for edge in self.derived_dependencies:
            adjacency[edge.source] = (*adjacency.get(edge.source, ()), edge.target)
        visiting: set[OnlyBarType] = set()
        visited: set[OnlyBarType] = set()

        def visit(node: OnlyBarType) -> None:
            if node in visiting:
                raise ValueError("BAR_DEPENDENCY_GRAPH_CYCLE")
            if node in visited:
                return
            visiting.add(node)
            for target in adjacency.get(node, ()):
                visit(target)
            visiting.remove(node)
            visited.add(node)

        for node in adjacency:
            visit(node)


class OnlyBarConstructionAlgorithmRegistry:
    def __init__(self) -> None:
        self._available = frozenset({("TIME_BAR", 1)})

    def require(self, recipe: OnlyBarConstructionRecipe) -> None:
        if (
            recipe.kind is OnlyBarConstructionKind.DERIVED
            and (
                recipe.algorithm_id,
                recipe.algorithm_version,
            )
            not in self._available
        ):
            raise ValueError("CONSTRUCTION_ALGORITHM_UNAVAILABLE")


def only_plan_bar_resolution(
    target: OnlyBarSemantic,
    capabilities: tuple[OnlyBarCapability, ...],
    *,
    calendar_fingerprint: str,
    source_id: str,
    instrument_id: str,
    integration_revision_fingerprint: str,
    requirement: OnlyBarConstructionRequirement | None = None,
) -> OnlyBarResolutionPlan:
    """Resolve interactive policy or an exact frozen recipe without substitution."""

    requirement = requirement or OnlyBarConstructionRequirement.prefer_exact_native()
    if (
        target.price_type is not OnlyPriceType.LAST
        or target.adjustment_policy is not OnlyAdjustmentType.RAW
        or not target.is_fixed_duration
        or not calendar_fingerprint
        or not source_id
        or not instrument_id
        or len(integration_revision_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in integration_revision_fingerprint)
    ):
        raise ValueError("BAR_RESOLUTION_UNSUPPORTED")
    assert isinstance(target.formation, OnlyFixedDurationBarFormation)
    native = tuple(
        item
        for item in capabilities
        if item.semantic == target
        and item.calendar_fingerprint == calendar_fingerprint
        and item.historical_supported
        and item.realtime_supported
        and item.grid_origin_ns is not None
    )
    if len(native) > 1:
        raise ValueError("BAR_RESOLUTION_AMBIGUOUS")
    if requirement.kind is OnlyBarConstructionRequirementKind.EXACT_RECIPE:
        assert requirement.recipe is not None
        recipe = requirement.recipe
        if recipe.target_semantic != target:
            raise ValueError("BAR_RESOLUTION_REQUIREMENT_MISMATCH")
        candidates = (
            native
            if recipe.kind is OnlyBarConstructionKind.PROVIDER_NATIVE
            else tuple(
                item
                for item in capabilities
                if item.semantic == recipe.base_semantic
                and item.calendar_fingerprint == calendar_fingerprint
                and item.historical_supported
                and item.realtime_supported
                and item.grid_origin_ns is not None
            )
        )
        if len(candidates) != 1:
            raise ValueError("BAR_RESOLUTION_EXACT_RECIPE_UNAVAILABLE")
        capability = candidates[0]
    elif native:
        recipe = OnlyBarConstructionRecipe.provider_native(target)
        capability = native[0]
    else:
        base = OnlyBarSemantic.fixed_duration(
            1,
            alignment=target.formation.alignment,
            price_type=target.price_type,
            adjustment_policy=target.adjustment_policy,
        )
        bases = tuple(
            item
            for item in capabilities
            if item.semantic == base
            and item.calendar_fingerprint == calendar_fingerprint
            and item.historical_supported
            and item.realtime_supported
            and item.grid_origin_ns is not None
        )
        if len(bases) != 1:
            raise ValueError("BAR_RESOLUTION_BASE_UNAVAILABLE")
        recipe = OnlyBarConstructionRecipe.derived(
            target,
            base,
            algorithm_id="TIME_BAR" if target.is_aligned else "ROLLING_TIME_BAR",
        )
        capability = bases[0]
    assert capability.grid_origin_ns is not None
    origin = capability.grid_origin_ns % (capability.semantic.stride_minutes * 60_000_000_000)
    payload = {
        "schema_version": 3,
        "target_semantic": target.to_dict(),
        "requirement": requirement.to_dict(),
        "resolved_recipe": recipe.to_dict(),
        "source_id": source_id,
        "instrument_id": instrument_id,
        "integration_revision_fingerprint": integration_revision_fingerprint,
        "calendar_fingerprint": calendar_fingerprint,
        "grid_origin_ns": origin,
    }
    return OnlyBarResolutionPlan(
        target,
        requirement,
        recipe,
        source_id,
        instrument_id,
        integration_revision_fingerprint,
        calendar_fingerprint,
        origin,
        only_canonical_fingerprint(payload),
    )


def only_expected_fixed_duration_bar_ends(
    semantic: OnlyBarSemantic,
    *,
    start_ns: int,
    end_ns: int,
    grid_origin_ns: int,
) -> tuple[int, ...]:
    if not semantic.is_fixed_duration:
        raise ValueError("BAR_RESOLUTION_UNSUPPORTED")
    stride_ns = semantic.stride_minutes * 60_000_000_000
    window_ns = semantic.window_minutes * 60_000_000_000
    if start_ns >= end_ns or (start_ns - grid_origin_ns) % stride_ns or (end_ns - grid_origin_ns) % stride_ns:
        return ()
    return tuple(range(start_ns + window_ns, end_ns + 1, stride_ns))
