"""Deterministic conformance score and report models."""

from dataclasses import dataclass

ONLY_SCORE_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("domain_boundary", 10),
    ("value_types", 15),
    ("instruments", 15),
    ("precision_increment", 10),
    ("market_rules", 10),
    ("bar_time", 15),
    ("order_trade_position", 8),
    ("serialization", 5),
    ("historical_versions", 4),
    ("extensibility", 3),
    ("determinism", 5),
)


@dataclass(frozen=True, slots=True)
class OnlyDomainConformanceScore:
    dimensions: tuple[tuple[str, int], ...]
    vetoes: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return sum(score for _, score in self.dimensions)

    @property
    def status(self) -> str:
        if self.vetoes or self.total < 70:
            return "REJECTED"
        if self.total < 90:
            return "CONDITIONALLY_ACCEPTED"
        return "ACCEPTED"

    @property
    def recommend_runtime(self) -> bool:
        return self.total >= 90 and not self.vetoes

    @property
    def recommend_backtest(self) -> bool:
        return self.recommend_runtime

    @classmethod
    def full_pass(cls) -> "OnlyDomainConformanceScore":
        return cls(ONLY_SCORE_WEIGHTS)

    @classmethod
    def current_assessment(cls) -> "OnlyDomainConformanceScore":
        """Audited score: market rules 9/10 and Bar/time semantics 13/15."""
        dimensions = tuple(
            (name, 9 if name == "market_rules" else 13 if name == "bar_time" else weight)
            for name, weight in ONLY_SCORE_WEIGHTS
        )
        return cls(dimensions)


@dataclass(frozen=True, slots=True)
class OnlyDomainConformanceReport:
    score: OnlyDomainConformanceScore
    test_total: int
    passed: int
    failed: int
    skipped: int
    unsupported: tuple[str, ...]
