"""Single authority for execution Projection identity construction."""

from __future__ import annotations

from typing import Protocol, cast

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.transaction.codec import only_with_execution_projection_hash
from onlyalpha.transaction.projection import (
    OnlyRuntimeProjection,
    OnlyRuntimeProjectionComponent,
    OnlyRuntimeProjectionIdentity,
)
from onlyalpha.transaction.state_hash import only_execution_state_hash


class _OnlyVersionedState(Protocol):
    @property
    def version(self) -> int: ...


class OnlyRuntimeProjectionBuilder:
    """Build version/hash identity once and finalize the complete payload hash."""

    def identity(
        self,
        *,
        component: OnlyRuntimeProjectionComponent,
        entity_key: str,
        before: OnlyDomainModel | None,
        after: OnlyDomainModel,
        projection_sequence: int,
    ) -> OnlyRuntimeProjectionIdentity:
        before_state = None if before is None else cast(_OnlyVersionedState, before)
        after_state = cast(_OnlyVersionedState, after)
        expected_version = 0 if before_state is None else before_state.version
        return OnlyRuntimeProjectionIdentity(
            component,
            entity_key,
            expected_version,
            after_state.version,
            only_execution_state_hash(before),
            only_execution_state_hash(after),
            projection_sequence,
            "0" * 64,
        )

    def finalize[ProjectionT: OnlyRuntimeProjection](self, projection: ProjectionT) -> ProjectionT:
        return cast(ProjectionT, only_with_execution_projection_hash(projection))


__all__ = ["OnlyRuntimeProjectionBuilder"]
