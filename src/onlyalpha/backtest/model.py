"""Strict portable Backtest intent and durable Run state authority."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .errors import OnlyBacktestIntegrityError, OnlyBacktestStateConflictError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_PROFILE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


@dataclass(frozen=True, order=True, slots=True)
class OnlyBacktestRunId:
    value: str

    def __post_init__(self) -> None:
        _uuid4(self.value, "Backtest Run ID")

    @classmethod
    def new(cls) -> OnlyBacktestRunId:
        return cls(str(uuid.uuid4()))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True, slots=True)
class OnlyBacktestProfileReference:
    profile_id: str
    version: str

    def __post_init__(self) -> None:
        if _PROFILE_ID.fullmatch(self.profile_id) is None or _PROFILE_VERSION.fullmatch(self.version) is None:
            raise ValueError("BACKTEST_PROFILE_REFERENCE_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {"profile_id": self.profile_id, "version": self.version}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyBacktestProfileReference:
        _exact(payload, {"profile_id", "version"}, "Backtest Profile reference")
        return cls(_string(payload, "profile_id"), _string(payload, "version"))


@dataclass(frozen=True, slots=True)
class OnlyBacktestSpecification:
    """Exact user semantic intent; deliberately excludes assembly and operational detail."""

    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    market_product_configuration_fingerprint: str
    portfolio_profile: OnlyBacktestProfileReference
    risk_profile: OnlyBacktestProfileReference
    execution_profile: OnlyBacktestProfileReference
    base_currency: str
    initial_capital: str
    ordered_fact_policy: str = "ORDERED_FACTS_V1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in (
            "strategy_fingerprint",
            "dataset_binding_fingerprint",
            "market_product_configuration_fingerprint",
        ):
            _sha(getattr(self, name), name)
        for value in (self.portfolio_profile, self.risk_profile, self.execution_profile):
            if not isinstance(value, OnlyBacktestProfileReference):
                raise ValueError("BACKTEST_PROFILE_REFERENCE_INVALID")
        if (
            not self.base_currency.isascii()
            or not self.base_currency.isalpha()
            or self.base_currency != self.base_currency.upper()
        ):
            raise ValueError("BACKTEST_BASE_CURRENCY_INVALID")
        try:
            capital = Decimal(self.initial_capital)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("BACKTEST_INITIAL_CAPITAL_INVALID") from exc
        if not capital.is_finite() or capital <= 0 or self.initial_capital != format(capital, "f"):
            raise ValueError("BACKTEST_INITIAL_CAPITAL_INVALID")
        if self.ordered_fact_policy != "ORDERED_FACTS_V1" or self.schema_version != 1:
            raise ValueError("BACKTEST_SPECIFICATION_VERSION_UNSUPPORTED")

    @property
    def specification_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "dataset_binding_fingerprint": self.dataset_binding_fingerprint,
            "market_product_configuration_fingerprint": self.market_product_configuration_fingerprint,
            "portfolio_profile": self.portfolio_profile.to_dict(),
            "risk_profile": self.risk_profile.to_dict(),
            "execution_profile": self.execution_profile.to_dict(),
            "initial_account": {
                "base_currency": self.base_currency,
                "capital": self.initial_capital,
            },
            "runtime_options": {"ordered_fact_policy": self.ordered_fact_policy},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyBacktestSpecification:
        _exact(
            payload,
            {
                "schema_version",
                "strategy_fingerprint",
                "dataset_binding_fingerprint",
                "market_product_configuration_fingerprint",
                "portfolio_profile",
                "risk_profile",
                "execution_profile",
                "initial_account",
                "runtime_options",
            },
            "Backtest Specification",
        )
        account = _mapping(payload, "initial_account")
        runtime = _mapping(payload, "runtime_options")
        _exact(account, {"base_currency", "capital"}, "Backtest initial account")
        _exact(runtime, {"ordered_fact_policy"}, "Backtest runtime options")
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("BACKTEST_SPECIFICATION_INVALID")
        return cls(
            strategy_fingerprint=_string(payload, "strategy_fingerprint"),
            dataset_binding_fingerprint=_string(payload, "dataset_binding_fingerprint"),
            market_product_configuration_fingerprint=_string(payload, "market_product_configuration_fingerprint"),
            portfolio_profile=OnlyBacktestProfileReference.from_dict(_mapping(payload, "portfolio_profile")),
            risk_profile=OnlyBacktestProfileReference.from_dict(_mapping(payload, "risk_profile")),
            execution_profile=OnlyBacktestProfileReference.from_dict(_mapping(payload, "execution_profile")),
            base_currency=_string(account, "base_currency"),
            initial_capital=_string(account, "capital"),
            ordered_fact_policy=_string(runtime, "ordered_fact_policy"),
            schema_version=schema_version,
        )


@dataclass(frozen=True, slots=True)
class OnlyBacktestAdmissionResolution:
    strategy_revision_schema_version: int
    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    base_dataset_snapshot_fingerprint: str
    market_product_composition_fingerprint: str
    portfolio_profile_fingerprint: str
    risk_profile_fingerprint: str
    execution_profile_fingerprint: str
    kernel_semantics_version: str
    implementation_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.strategy_revision_schema_version < 1 or not self.kernel_semantics_version.strip():
            raise ValueError("BACKTEST_ADMISSION_RESOLUTION_INVALID")
        for name in (
            "strategy_fingerprint",
            "dataset_binding_fingerprint",
            "base_dataset_snapshot_fingerprint",
            "market_product_composition_fingerprint",
            "portfolio_profile_fingerprint",
            "risk_profile_fingerprint",
            "execution_profile_fingerprint",
        ):
            _sha(getattr(self, name), name)
        canonical = tuple(sorted(self.implementation_fingerprints))
        if canonical != self.implementation_fingerprints or len(canonical) != len(set(canonical)):
            raise ValueError("BACKTEST_IMPLEMENTATION_IDENTITIES_INVALID")
        for value in canonical:
            _sha(value, "implementation_fingerprint")

    @property
    def admission_resolution_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "schema_version": 1,
                "strategy_revision_schema_version": self.strategy_revision_schema_version,
                "strategy_fingerprint": self.strategy_fingerprint,
                "dataset_binding_fingerprint": self.dataset_binding_fingerprint,
                "base_dataset_snapshot_fingerprint": self.base_dataset_snapshot_fingerprint,
                "market_product_composition_fingerprint": self.market_product_composition_fingerprint,
                "portfolio_profile_fingerprint": self.portfolio_profile_fingerprint,
                "risk_profile_fingerprint": self.risk_profile_fingerprint,
                "execution_profile_fingerprint": self.execution_profile_fingerprint,
                "kernel_semantics_version": self.kernel_semantics_version,
                "implementation_fingerprints": list(self.implementation_fingerprints),
            }
        )


class OnlyBacktestRunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class OnlyBacktestRunFailurePhase(StrEnum):
    ADMISSION = "ADMISSION"
    EXECUTION = "EXECUTION"
    EVIDENCE_COMMIT = "EVIDENCE_COMMIT"
    OPERATIONAL = "OPERATIONAL"


@dataclass(frozen=True, slots=True)
class OnlyBacktestRunFailure:
    phase: OnlyBacktestRunFailurePhase
    code: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.phase, OnlyBacktestRunFailurePhase):
            raise ValueError("BACKTEST_FAILURE_PHASE_INVALID")
        if not self.code or self.code != self.code.upper() or not self.code.replace("_", "").isalnum():
            raise ValueError("BACKTEST_FAILURE_CODE_INVALID")
        if not self.detail:
            raise ValueError("BACKTEST_FAILURE_DETAIL_REQUIRED")


_TRANSITIONS: dict[OnlyBacktestRunState, frozenset[OnlyBacktestRunState]] = {
    OnlyBacktestRunState.QUEUED: frozenset({OnlyBacktestRunState.RUNNING, OnlyBacktestRunState.CANCELLED}),
    OnlyBacktestRunState.RUNNING: frozenset(
        {OnlyBacktestRunState.COMPLETED, OnlyBacktestRunState.FAILED, OnlyBacktestRunState.CANCEL_REQUESTED}
    ),
    OnlyBacktestRunState.CANCEL_REQUESTED: frozenset(
        {OnlyBacktestRunState.CANCELLED, OnlyBacktestRunState.COMPLETED, OnlyBacktestRunState.FAILED}
    ),
    OnlyBacktestRunState.COMPLETED: frozenset(),
    OnlyBacktestRunState.FAILED: frozenset(),
    OnlyBacktestRunState.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class OnlyBacktestRun:
    run_id: OnlyBacktestRunId
    revision: int
    state: OnlyBacktestRunState
    specification: OnlyBacktestSpecification
    canonical_specification_payload: str
    admission_resolution_fingerprint: str
    queued_at: datetime
    started_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    finished_at: datetime | None = None
    evidence_fingerprint: str | None = None
    result_fingerprint: str | None = None
    determinism_fingerprint: str | None = None
    failure: OnlyBacktestRunFailure | None = None

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.run_id, OnlyBacktestRunId) or self.revision < 0:
                raise ValueError("Backtest Run identity/revision is invalid")
            if not isinstance(self.state, OnlyBacktestRunState):
                raise ValueError("Backtest Run state is invalid")
            if self.canonical_specification_payload != only_canonical_json(self.specification.to_dict()):
                raise ValueError("Backtest Specification payload is not canonical")
            _sha(self.admission_resolution_fingerprint, "admission_resolution_fingerprint")
            for name in ("evidence_fingerprint", "result_fingerprint", "determinism_fingerprint"):
                value = getattr(self, name)
                if value is not None:
                    _sha(value, name)
            for name in ("queued_at", "started_at", "cancel_requested_at", "finished_at"):
                value = getattr(self, name)
                if value is not None:
                    _utc(value, name)
            if self.state is self.state.QUEUED and any(
                value is not None
                for value in (
                    self.started_at,
                    self.cancel_requested_at,
                    self.finished_at,
                    self.evidence_fingerprint,
                    self.result_fingerprint,
                    self.determinism_fingerprint,
                    self.failure,
                )
            ):
                raise ValueError("QUEUED Backtest contains later lifecycle facts")
            if self.state in {self.state.RUNNING, self.state.CANCEL_REQUESTED} and self.started_at is None:
                raise ValueError("active Backtest requires started_at")
            if self.state is self.state.RUNNING and self.cancel_requested_at is not None:
                raise ValueError("RUNNING Backtest cannot contain cancellation")
            if self.state is self.state.CANCEL_REQUESTED and self.cancel_requested_at is None:
                raise ValueError("CANCEL_REQUESTED Backtest requires timestamp")
            if self.state.terminal != (self.finished_at is not None):
                raise ValueError("terminal Backtest and finished_at differ")
            if self.state is self.state.COMPLETED and any(
                value is None
                for value in (
                    self.started_at,
                    self.evidence_fingerprint,
                    self.result_fingerprint,
                    self.determinism_fingerprint,
                )
            ):
                raise ValueError("COMPLETED Backtest requires verified Evidence and result identities")
            if self.state is self.state.FAILED and (self.started_at is None or self.failure is None):
                raise ValueError("FAILED Backtest requires execution and structured failure")
            if self.state is not self.state.FAILED and self.failure is not None:
                raise ValueError("failure is valid only for FAILED Backtest")
        except (TypeError, ValueError) as exc:
            raise OnlyBacktestIntegrityError("BACKTEST_RUN_CORRUPT", str(exc)) from exc

    @property
    def specification_fingerprint(self) -> str:
        return self.specification.specification_fingerprint

    @classmethod
    def queued(
        cls,
        *,
        run_id: OnlyBacktestRunId,
        specification: OnlyBacktestSpecification,
        admission_resolution_fingerprint: str,
        queued_at: datetime,
    ) -> OnlyBacktestRun:
        return cls(
            run_id=run_id,
            revision=0,
            state=OnlyBacktestRunState.QUEUED,
            specification=specification,
            canonical_specification_payload=only_canonical_json(specification.to_dict()),
            admission_resolution_fingerprint=admission_resolution_fingerprint,
            queued_at=queued_at,
        )

    def transition(
        self,
        target: OnlyBacktestRunState,
        *,
        at: datetime,
        evidence_fingerprint: str | None = None,
        result_fingerprint: str | None = None,
        determinism_fingerprint: str | None = None,
        failure: OnlyBacktestRunFailure | None = None,
    ) -> OnlyBacktestRun:
        _utc(at, "transition timestamp")
        if target not in _TRANSITIONS[self.state]:
            raise OnlyBacktestStateConflictError(f"illegal Backtest transition: {self.state} -> {target}")
        started = self.started_at
        cancelled = self.cancel_requested_at
        finished = self.finished_at
        if target is target.RUNNING:
            started = at
        elif target is target.CANCEL_REQUESTED:
            cancelled = at
        else:
            finished = at
        if target is not target.FAILED and failure is not None:
            raise OnlyBacktestStateConflictError("failure is valid only for FAILED transition")
        return OnlyBacktestRun(
            run_id=self.run_id,
            revision=self.revision + 1,
            state=target,
            specification=self.specification,
            canonical_specification_payload=self.canonical_specification_payload,
            admission_resolution_fingerprint=self.admission_resolution_fingerprint,
            queued_at=self.queued_at,
            started_at=started,
            cancel_requested_at=cancelled,
            finished_at=finished,
            evidence_fingerprint=evidence_fingerprint or self.evidence_fingerprint,
            result_fingerprint=result_fingerprint or self.result_fingerprint,
            determinism_fingerprint=determinism_fingerprint or self.determinism_fingerprint,
            failure=failure if target is target.FAILED else None,
        )


def _exact(payload: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{name} fields are invalid")


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    return value


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lower-case SHA256")
    return value


def _uuid4(value: object, name: str) -> None:
    try:
        parsed = uuid.UUID(value)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a canonical UUID4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(f"{name} must be a canonical UUID4")


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be timezone-aware UTC")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
