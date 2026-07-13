from datetime import datetime
from pathlib import Path

import pytest

from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.time import OnlyTimestamp


def test_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(OnlyValidationError, match="naive"):
        OnlyTimestamp.from_datetime(datetime(2026, 7, 13, 9, 30))


def test_production_code_has_no_implicit_local_clock_calls() -> None:
    source_root = Path(__file__).parents[2] / "src" / "onlyalpha"
    source = "\n".join(path.read_text() for path in source_root.rglob("*.py"))
    assert "datetime.utcnow(" not in source
    assert "datetime.now()" not in source
    assert "datetime.fromtimestamp(value)" not in source
