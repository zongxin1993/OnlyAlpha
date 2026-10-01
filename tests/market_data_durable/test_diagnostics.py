from __future__ import annotations

import pytest

from onlyalpha.market_data.durable.diagnostics import only_market_data_diagnostic_error


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        "RuntimeError: https://user:private-value@host/path failed",
        "OperationalError: password=private-value database unavailable",
        'RuntimeError: {"token": "private-value"}',
        "RuntimeError: Authorization: Bearer private-value",
        "RuntimeError: Authorization: Basic private-value",
        "RuntimeError: https://host/path?api_key=private-value&request=1",
    ],
)
def test_durable_diagnostics_redact_credentials_without_changing_authoritative_error(error: str) -> None:
    diagnostic = only_market_data_diagnostic_error(error)
    assert diagnostic is not None
    assert "private-value" not in diagnostic
    assert "<redacted>" in diagnostic
    assert "private-value" in error


@pytest.mark.unit
def test_durable_diagnostics_preserve_benign_exact_errors() -> None:
    assert only_market_data_diagnostic_error(None) is None
    error = "RuntimeError:MARKET_DATA_PHYSICAL_ROWS_UNVERIFIABLE"
    assert only_market_data_diagnostic_error(error) == error
