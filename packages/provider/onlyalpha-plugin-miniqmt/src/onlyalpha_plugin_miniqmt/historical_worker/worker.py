"""One-request worker entry point. XtQuant is deliberately imported late."""

from __future__ import annotations

import argparse
import traceback
from importlib import import_module
from pathlib import Path

from . import exit_codes
from .models import OnlyMiniQmtProtocolVersionMismatch, OnlyMiniQmtWorkerRequest
from .protocol import (
    PROTOCOL_VERSION,
    atomic_write_bytes,
    atomic_write_json,
    bars_payload,
    bytes_fingerprint,
    fingerprint,
    read_json,
)


def _failure(
    workdir: Path,
    request: OnlyMiniQmtWorkerRequest | None,
    *,
    status: str,
    code: str,
    exc: BaseException,
    provider_version: str | None = None,
) -> None:
    trace = "".join(traceback.format_exception(exc))[-16_384:]
    atomic_write_json(
        workdir / "failure.json",
        {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": None if request is None else request.request_id,
            "status": status,
            "code": code,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": trace,
            "request_fingerprint": None if request is None else request.request_fingerprint,
            "provider_version": provider_version,
            "compatibility_profile_id": None if request is None else request.compatibility_profile_id,
        },
    )


def run(request_path: Path) -> int:
    workdir = request_path.parent
    request: OnlyMiniQmtWorkerRequest | None = None
    try:
        request = OnlyMiniQmtWorkerRequest.parse(read_json(request_path))
    except OnlyMiniQmtProtocolVersionMismatch as exc:
        _failure(workdir, request, status="PROTOCOL_ERROR", code="PROTOCOL_VERSION_MISMATCH", exc=exc)
        return exit_codes.PROTOCOL_VERSION_MISMATCH
    except Exception as exc:
        _failure(workdir, request, status="INVALID_REQUEST", code="MINIQMT_HISTORICAL_INVALID_REQUEST", exc=exc)
        return exit_codes.INVALID_REQUEST
    try:
        package = import_module("xtquant")
        xtdata = import_module("xtquant.xtdata")
        provider_version = str(getattr(package, "__version__", "unknown"))
    except Exception as exc:
        _failure(workdir, request, status="IMPORT_FAILED", code="MINIQMT_HISTORICAL_IMPORT_FAILED", exc=exc)
        return exit_codes.SDK_IMPORT_FAILED
    try:
        from .query import OnlyMiniQmtDownloadError, OnlyMiniQmtQueryError, query_history, rows

        raw_rows = rows(query_history(xtdata, request))
    except OnlyMiniQmtDownloadError as exc:
        _failure(
            workdir,
            request,
            status="DOWNLOAD_FAILED",
            code="MINIQMT_HISTORICAL_DOWNLOAD_FAILED",
            exc=exc,
            provider_version=provider_version,
        )
        return exit_codes.DOWNLOAD_FAILED
    except OnlyMiniQmtQueryError as exc:
        _failure(
            workdir,
            request,
            status="QUERY_FAILED",
            code="MINIQMT_HISTORICAL_QUERY_FAILED",
            exc=exc,
            provider_version=provider_version,
        )
        return exit_codes.QUERY_FAILED
    except Exception as exc:
        _failure(
            workdir,
            request,
            status="QUERY_FAILED",
            code="MINIQMT_HISTORICAL_QUERY_FAILED",
            exc=exc,
            provider_version=provider_version,
        )
        return exit_codes.QUERY_FAILED
    if not raw_rows:
        empty_error = ValueError("XtQuant historical query returned no rows")
        _failure(
            workdir,
            request,
            status="EMPTY_RESULT",
            code="MINIQMT_HISTORICAL_EMPTY_RESULT",
            exc=empty_error,
            provider_version=provider_version,
        )
        return exit_codes.EMPTY_RESULT
    try:
        from .validation import normalize_rows

        records = normalize_rows(raw_rows, request)
    except Exception as exc:
        _failure(
            workdir,
            request,
            status="INVALID_DATA",
            code="MINIQMT_HISTORICAL_INVALID_DATA",
            exc=exc,
            provider_version=provider_version,
        )
        return exit_codes.DATA_VALIDATION_FAILED
    try:
        encoded = bars_payload(records)
        content_fingerprint = fingerprint(records)
        bars_file_fingerprint = bytes_fingerprint(encoded)
        atomic_write_bytes(workdir / "bars.jsonl", encoded)
        atomic_write_json(
            workdir / "result.json",
            {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.request_id,
                "status": "SUCCESS",
                "provider": "miniqmt",
                "provider_version": provider_version,
                "compatibility_profile_id": request.compatibility_profile_id,
                "instrument_id": request.instrument_id,
                "period": request.period,
                "requested_bars": request.required_bars,
                "row_count": len(records),
                "first_bar_end_ns": records[0]["bar_end_ns"],
                "last_bar_end_ns": records[-1]["bar_end_ns"],
                "request_fingerprint": request.request_fingerprint,
                "content_fingerprint": content_fingerprint,
                "bars_file_fingerprint": bars_file_fingerprint,
            },
        )
    except Exception as exc:
        _failure(
            workdir,
            request,
            status="PROTOCOL_ERROR",
            code="MINIQMT_HISTORICAL_SERIALIZATION_FAILED",
            exc=exc,
            provider_version=provider_version,
        )
        return exit_codes.RESULT_SERIALIZATION_FAILED
    return exit_codes.SUCCESS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    return run(args.request)


if __name__ == "__main__":
    raise SystemExit(main())
