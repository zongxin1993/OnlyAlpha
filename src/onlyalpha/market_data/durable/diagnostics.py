"""Credential-safe error text for non-authoritative durable diagnostics."""

from __future__ import annotations

import re


def only_market_data_diagnostic_error(error: str | None) -> str | None:
    if error is None:
        return None
    error = re.sub(r"(://)[^/@\s]+@", r"\1<redacted>@", error)
    error = re.sub(r"\b(Bearer|Basic)\s+[^\s,;]+", r"\1 <redacted>", error, flags=re.IGNORECASE)
    return re.sub(
        r"(\b(?:password|passwd|pwd|token|secret|api[_-]?key|authorization)[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s&,;]+)",
        r"\1<redacted>",
        error,
        flags=re.IGNORECASE,
    )
