"""Strict Backtest Product HTTP DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class BacktestProfileReferenceDto(_Dto):
    profile_id: str
    version: str


class BacktestInitialAccountDto(_Dto):
    base_currency: str
    capital: str


class BacktestRuntimeOptionsDto(_Dto):
    ordered_fact_policy: Literal["ORDERED_FACTS_V1"] = "ORDERED_FACTS_V1"


class BacktestRunCreateRequest(_Dto):
    schema_version: Literal[1] = 1
    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    market_product_configuration_fingerprint: str
    portfolio_profile: BacktestProfileReferenceDto
    risk_profile: BacktestProfileReferenceDto
    execution_profile: BacktestProfileReferenceDto
    initial_account: BacktestInitialAccountDto
    runtime_options: BacktestRuntimeOptionsDto = BacktestRuntimeOptionsDto()


class BacktestRunCreateResponse(_Dto):
    schema_version: Literal[1] = 1
    backtest_run_id: str
    state: str
    disposition: str


class BacktestFailureDto(_Dto):
    phase: str
    code: str
    detail: str


class BacktestRunDto(_Dto):
    schema_version: Literal[1] = 1
    run_id: str
    state: str
    revision: int
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    queued_at: str
    started_at: str | None
    cancel_requested_at: str | None
    finished_at: str | None
    result_fingerprint: str | None
    evidence_fingerprint: str | None
    determinism_fingerprint: str | None
    failure: BacktestFailureDto | None


class BacktestCancellationResponse(_Dto):
    schema_version: Literal[1] = 1
    run_id: str
    state: str
    revision: int


class BacktestEvidenceArtifactDto(_Dto):
    name: str
    sha256: str
    size: int
    media_type: str


class BacktestEvidenceManifestDto(_Dto):
    schema_version: Literal[1] = 1
    backtest_run_id: str
    specification_fingerprint: str
    admission_resolution_fingerprint: str
    strategy_fingerprint: str
    dataset_binding_fingerprint: str
    base_dataset_snapshot_fingerprint: str
    market_product_composition_fingerprint: str
    portfolio_profile_fingerprint: str
    risk_profile_fingerprint: str
    execution_profile_fingerprint: str
    kernel_semantics_version: str
    implementation_fingerprints: tuple[str, ...]
    result_fingerprint: str
    determinism_fingerprint: str
    artifacts: tuple[BacktestEvidenceArtifactDto, ...]
    evidence_fingerprint: str


class BacktestEvidenceDto(_Dto):
    schema_version: Literal[1] = 1
    manifest: BacktestEvidenceManifestDto


class ProductErrorDto(_Dto):
    phase: str
    code: str
    detail: str


class ProductErrorEnvelopeDto(_Dto):
    schema_version: Literal[1] = 1
    error: ProductErrorDto


PRODUCT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ProductErrorEnvelopeDto} for status in (400, 404, 409, 500, 503)
}


__all__ = [name for name in globals() if name.endswith("Dto") or name.startswith(("Backtest", "PRODUCT_"))]
