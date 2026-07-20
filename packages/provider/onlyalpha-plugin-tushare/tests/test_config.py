import pytest
from onlyalpha_plugin_tushare.config import OnlyTushareConfig
from onlyalpha_plugin_tushare.errors import OnlyTushareError

from onlyalpha.domain.enums import OnlyAdjustmentType


def test_token_environment_precedes_hidden_direct_config(monkeypatch) -> None:
    config = OnlyTushareConfig.parse(
        {"token_env": "TEST_TUSHARE_TOKEN", "token": "direct", "adjustment": "qfq"}
    )
    monkeypatch.setenv("TEST_TUSHARE_TOKEN", " environment ")
    assert config.resolve_token() == "environment"
    assert config.adjustment is OnlyAdjustmentType.FORWARD
    assert "direct" not in repr(config)


def test_missing_token_has_sanitized_error(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_TUSHARE_TOKEN", raising=False)
    with pytest.raises(OnlyTushareError) as caught:
        OnlyTushareConfig(token_env="MISSING_TUSHARE_TOKEN").resolve_token()
    assert caught.value.code == "TUSHARE_TOKEN_MISSING"
