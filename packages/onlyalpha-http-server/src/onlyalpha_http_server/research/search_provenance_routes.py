"""Exact read-only Product projection over Search Experiment provenance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict

from onlyalpha.research.experiment.errors import OnlySearchProvenanceStoreError

SEARCH_PROVENANCE_ROUTE_TAG = "search-provenance"


class OnlySearchIterationResultReader(Protocol):
    def load_iteration_result_verified(self, iteration_result_fingerprint: str) -> object: ...


class OnlySearchTerminalProjectionReader(Protocol):
    def load_terminal_projection_verified(self, terminal_projection_fingerprint: str) -> object: ...


class ExactSearchIterationResultDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = 1
    iteration_result_fingerprint: str
    payload: dict[str, object]


class ExactSearchTerminalProjectionDto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: int = 1
    terminal_projection_fingerprint: str
    payload: dict[str, object]


ShaPath = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


def create_search_provenance_router(
    reader: OnlySearchIterationResultReader,
    terminal_reader: OnlySearchTerminalProjectionReader | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/search/iteration-results", tags=[SEARCH_PROVENANCE_ROUTE_TAG])

    @router.get(
        "/{iteration_result_fingerprint}",
        operation_id="get_exact_search_iteration_result_v2",
        response_model=ExactSearchIterationResultDto,
    )
    def get_iteration_result(iteration_result_fingerprint: ShaPath) -> ExactSearchIterationResultDto:
        try:
            value = reader.load_iteration_result_verified(iteration_result_fingerprint)
            serializer = getattr(value, "to_dict", None)
            if not callable(serializer):
                raise TypeError("SEARCH_ITERATION_RESULT_PROJECTION_INVALID")
            raw = serializer()
            if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
                raise TypeError("SEARCH_ITERATION_RESULT_PROJECTION_INVALID")
            payload = dict(cast(Mapping[str, object], raw))
            if payload.get("iteration_result_fingerprint") != iteration_result_fingerprint:
                raise ValueError("SEARCH_ITERATION_RESULT_IDENTITY_MISMATCH")
        except OnlySearchProvenanceStoreError as error:
            if error.code.endswith("_NOT_FOUND"):
                raise HTTPException(status_code=404, detail="SEARCH_ITERATION_RESULT_NOT_FOUND") from error
            raise HTTPException(status_code=500, detail="SEARCH_ITERATION_RESULT_CORRUPT") from error
        except Exception as error:
            raise HTTPException(status_code=500, detail="SEARCH_ITERATION_RESULT_CORRUPT") from error
        return ExactSearchIterationResultDto(
            iteration_result_fingerprint=iteration_result_fingerprint,
            payload=payload,
        )

    if terminal_reader is not None:

        @router.get(
            "/terminal-projections/{terminal_projection_fingerprint}",
            operation_id="get_exact_search_terminal_projection_v2",
            response_model=ExactSearchTerminalProjectionDto,
        )
        def get_terminal_projection(
            terminal_projection_fingerprint: ShaPath,
        ) -> ExactSearchTerminalProjectionDto:
            try:
                value = terminal_reader.load_terminal_projection_verified(terminal_projection_fingerprint)
                serializer = getattr(value, "to_dict", None)
                if not callable(serializer):
                    raise TypeError("SEARCH_TERMINAL_PROJECTION_INVALID")
                raw = serializer()
                if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
                    raise TypeError("SEARCH_TERMINAL_PROJECTION_INVALID")
                payload = dict(cast(Mapping[str, object], raw))
                identities = {
                    payload.get("enumeration_result_fingerprint"),
                    payload.get("feedback_decision_fingerprint"),
                    payload.get("iteration_result_fingerprint"),
                    payload.get("terminal_fingerprint"),
                }
                if terminal_projection_fingerprint not in identities:
                    raise ValueError("SEARCH_TERMINAL_PROJECTION_IDENTITY_MISMATCH")
            except Exception as error:
                code = getattr(error, "code", "")
                status = 404 if isinstance(code, str) and code.endswith("_NOT_FOUND") else 500
                detail = (
                    "SEARCH_TERMINAL_PROJECTION_NOT_FOUND" if status == 404 else "SEARCH_TERMINAL_PROJECTION_CORRUPT"
                )
                raise HTTPException(status_code=status, detail=detail) from error
            return ExactSearchTerminalProjectionDto(
                terminal_projection_fingerprint=terminal_projection_fingerprint,
                payload=payload,
            )

    return router


__all__ = [name for name in globals() if name.startswith(("Exact", "Only", "SEARCH", "create_"))]
