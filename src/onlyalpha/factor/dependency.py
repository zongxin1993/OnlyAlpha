"""Stable Factor dependency validation and topological plan."""

from dataclasses import dataclass

from onlyalpha.factor.base import OnlyFactor
from onlyalpha.factor.config import OnlyFactorType
from onlyalpha.factor.identifiers import OnlyFactorId


@dataclass(frozen=True, slots=True)
class OnlyFactorDependency:
    factor_id: OnlyFactorId
    depends_on: OnlyFactorId


@dataclass(frozen=True, slots=True)
class OnlyFactorExecutionPlan:
    ordered_factor_ids: tuple[OnlyFactorId, ...]


class OnlyFactorDependencyGraph:
    def build(self, factors: tuple[OnlyFactor, ...]) -> OnlyFactorExecutionPlan:
        by_id = {factor.factor_id: factor for factor in factors}
        if len(by_id) != len(factors):
            raise ValueError("Factor IDs must be unique within a Cluster")
        for factor in factors:
            for dependency in factor.config.dependencies:
                if dependency not in by_id:
                    raise ValueError(f"factor {factor.factor_id} depends on unknown factor {dependency}")
                if (
                    factor.factor_type is OnlyFactorType.TIME_SERIES
                    and by_id[dependency].factor_type is OnlyFactorType.CROSS_SECTION
                ):
                    raise ValueError("TimeSeries Factor cannot depend on CrossSection Factor at the same time point")
        state: dict[OnlyFactorId, int] = {}
        result: list[OnlyFactorId] = []

        def visit(factor_id: OnlyFactorId) -> None:
            marker = state.get(factor_id, 0)
            if marker == 1:
                raise ValueError(f"Factor dependency cycle detected at {factor_id}")
            if marker == 2:
                return
            state[factor_id] = 1
            for dependency in sorted(by_id[factor_id].config.dependencies):
                visit(dependency)
            state[factor_id] = 2
            result.append(factor_id)

        for factor_id in sorted(by_id):
            visit(factor_id)
        return OnlyFactorExecutionPlan(tuple(result))
