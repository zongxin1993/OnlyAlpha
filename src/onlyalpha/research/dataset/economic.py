"""Immutable economic-fact evidence bound to a Research/Backtest Dataset."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.domain.trading import OnlyReferencePriceKind

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyEconomicFactManifest:
    fact_family: OnlyMarketDataType
    content_fingerprint: str
    record_count: int
    data_version: str
    reference_price_kind: OnlyReferencePriceKind | None = None

    def __post_init__(self) -> None:
        if (
            self.fact_family
            not in {
                OnlyMarketDataType.REFERENCE_PRICE,
                OnlyMarketDataType.FUNDING_RATE,
                OnlyMarketDataType.SETTLEMENT,
            }
            or not _SHA256.fullmatch(self.content_fingerprint)
            or self.record_count < 0
            or not self.data_version.strip()
        ):
            raise ValueError("ECONOMIC_FACT_MANIFEST_INVALID")
        if self.fact_family is OnlyMarketDataType.REFERENCE_PRICE and self.reference_price_kind is None:
            raise ValueError("ECONOMIC_FACT_REFERENCE_KIND_REQUIRED")
        if self.fact_family is OnlyMarketDataType.SETTLEMENT:
            object.__setattr__(self, "reference_price_kind", OnlyReferencePriceKind.SETTLEMENT)
        if self.fact_family is OnlyMarketDataType.FUNDING_RATE and self.reference_price_kind is not None:
            raise ValueError("ECONOMIC_FACT_REFERENCE_KIND_NOT_APPLICABLE")

    def semantic_payload(self) -> dict[str, object]:
        return {
            "content_fingerprint": self.content_fingerprint,
            "data_version": self.data_version,
            "fact_family": self.fact_family.value,
            "record_count": self.record_count,
            "reference_price_kind": (None if self.reference_price_kind is None else self.reference_price_kind.value),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyEconomicFactManifest:
        if set(payload) != {
            "content_fingerprint",
            "data_version",
            "fact_family",
            "record_count",
            "reference_price_kind",
        }:
            raise ValueError("ECONOMIC_FACT_MANIFEST_INVALID")
        reference = payload["reference_price_kind"]
        count = payload["record_count"]
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("ECONOMIC_FACT_MANIFEST_INVALID")
        return cls(
            fact_family=OnlyMarketDataType(str(payload["fact_family"])),
            content_fingerprint=str(payload["content_fingerprint"]),
            record_count=count,
            data_version=str(payload["data_version"]),
            reference_price_kind=None if reference is None else OnlyReferencePriceKind(str(reference)),
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchDatasetEconomicBinding:
    """Versioned identity joining strategy data and Kernel-only economic facts."""

    base_dataset_snapshot_fingerprint: str
    market_product_composition_fingerprint: str
    economic_facts: tuple[OnlyEconomicFactManifest, ...]
    canonical_ordering_version: str = "1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.canonical_ordering_version != "1"
            or not _SHA256.fullmatch(self.base_dataset_snapshot_fingerprint)
            or not _SHA256.fullmatch(self.market_product_composition_fingerprint)
        ):
            raise ValueError("DATASET_ECONOMIC_BINDING_INVALID")
        ordered = tuple(
            sorted(
                self.economic_facts,
                key=lambda item: (
                    item.fact_family.value,
                    "" if item.reference_price_kind is None else item.reference_price_kind.value,
                    item.content_fingerprint,
                ),
            )
        )
        keys = tuple((item.fact_family, item.reference_price_kind) for item in ordered)
        if len(keys) != len(set(keys)):
            raise ValueError("DATASET_ECONOMIC_FACT_AUTHORITY_DUPLICATE")
        object.__setattr__(self, "economic_facts", ordered)

    def semantic_payload(self) -> dict[str, object]:
        return {
            "base_dataset_snapshot_fingerprint": self.base_dataset_snapshot_fingerprint,
            "canonical_ordering_version": self.canonical_ordering_version,
            "economic_facts": [item.semantic_payload() for item in self.economic_facts],
            "market_product_composition_fingerprint": self.market_product_composition_fingerprint,
            "schema_version": self.schema_version,
        }

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.semantic_payload())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchDatasetEconomicBinding:
        if set(payload) != {
            "base_dataset_snapshot_fingerprint",
            "canonical_ordering_version",
            "economic_facts",
            "market_product_composition_fingerprint",
            "schema_version",
        } or not isinstance(payload["economic_facts"], list):
            raise ValueError("DATASET_ECONOMIC_BINDING_INVALID")
        facts: list[OnlyEconomicFactManifest] = []
        for item in payload["economic_facts"]:
            if not isinstance(item, Mapping):
                raise ValueError("DATASET_ECONOMIC_BINDING_INVALID")
            facts.append(OnlyEconomicFactManifest.from_dict(item))
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("DATASET_ECONOMIC_BINDING_INVALID")
        return cls(
            base_dataset_snapshot_fingerprint=str(payload["base_dataset_snapshot_fingerprint"]),
            market_product_composition_fingerprint=str(payload["market_product_composition_fingerprint"]),
            economic_facts=tuple(facts),
            canonical_ordering_version=str(payload["canonical_ordering_version"]),
            schema_version=schema_version,
        )


__all__ = ["OnlyEconomicFactManifest", "OnlyResearchDatasetEconomicBinding"]
