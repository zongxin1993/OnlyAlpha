from math import inf, nan

import pytest
from onlyalpha_plugin_tushare.data_source.validation import only_validate_response
from onlyalpha_plugin_tushare.errors import OnlyTushareError

from .support import OnlyFakeFrame, row


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"open": nan}, "TUSHARE_PRICE_INVALID"),
        ({"high": inf}, "TUSHARE_PRICE_INVALID"),
        ({"vol": -1}, "TUSHARE_VOLUME_INVALID"),
        ({"amount": -1}, "TUSHARE_AMOUNT_INVALID"),
        ({"ts_code": "000001.SZ"}, "TUSHARE_SYMBOL_MISMATCH"),
    ],
)
def test_invalid_rows_fail_structurally(changes, code) -> None:
    with pytest.raises(OnlyTushareError) as caught:
        only_validate_response(OnlyFakeFrame([row(**changes)]), "600000.SH")
    assert caught.value.code == code


def test_identical_duplicate_warns_but_conflict_fails() -> None:
    values = row()
    rows, issues = only_validate_response(OnlyFakeFrame([values, dict(values)]), "600000.SH")
    assert len(rows) == len(issues) == 1
    with pytest.raises(OnlyTushareError) as caught:
        only_validate_response(OnlyFakeFrame([values, row(close=10.36)]), "600000.SH")
    assert caught.value.code == "TUSHARE_DUPLICATE_BAR"


def test_missing_column_fails() -> None:
    with pytest.raises(OnlyTushareError) as caught:
        only_validate_response(OnlyFakeFrame([row()], columns=("ts_code",)), "600000.SH")
    assert caught.value.code == "TUSHARE_REQUIRED_COLUMN_MISSING"
