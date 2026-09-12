"""Identity-only projections for exact Research Brief references."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from onlyalpha.research.agent.model import OnlyAgentEvaluationContextReferenceV1


class OnlyDatasetSnapshotIdentity(Protocol):
    @property
    def snapshot_fingerprint(self) -> str: ...


class OnlyDatasetSnapshotIdentityReader(Protocol):
    def load(self, snapshot_fingerprint: str) -> OnlyDatasetSnapshotIdentity: ...


class OnlyEvaluationContextIdentity(Protocol):
    @property
    def evaluation_contract_fingerprint(self) -> str: ...

    @property
    def schema_version(self) -> int: ...


class OnlyEvaluationContextIdentityReader(Protocol):
    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> OnlyEvaluationContextIdentity: ...


class ExactDatasetSnapshotDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    snapshot_fingerprint: str

    @classmethod
    def from_model(cls, value: OnlyDatasetSnapshotIdentity) -> ExactDatasetSnapshotDto:
        return cls(snapshot_fingerprint=value.snapshot_fingerprint)


class ExactEvaluationContextDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    evaluation_kind: str
    evaluation_schema_version: int
    evaluation_fingerprint: str

    @classmethod
    def from_model(
        cls,
        reference: OnlyAgentEvaluationContextReferenceV1,
        value: OnlyEvaluationContextIdentity,
    ) -> ExactEvaluationContextDto:
        fingerprint = value.evaluation_contract_fingerprint
        if (
            value.schema_version != reference.evaluation_schema_version
            or fingerprint != reference.evaluation_fingerprint
        ):
            raise ValueError("RESEARCH_EVALUATION_REFERENCE_INVALID")
        return cls(
            evaluation_kind=reference.evaluation_kind,
            evaluation_schema_version=value.schema_version,
            evaluation_fingerprint=fingerprint,
        )


__all__ = [name for name in globals() if name.startswith(("Exact", "Only"))]
