from types import SimpleNamespace

from onlyalpha_plugin_tushare.sdk.adapter import OnlyTushareSdkClient
from onlyalpha_plugin_tushare.sdk.loader import OnlyTushareModules


class OnlyFakeTusharePackage:
    def __init__(self) -> None:
        self.token_set = False
        self.api = object()
        self.parameters: dict[str, object] = {}

    def set_token(self, token: str) -> None:
        assert token == "credential"
        self.token_set = True

    def pro_api(self) -> object:
        assert self.token_set
        return self.api

    def pro_bar(self, **parameters: object) -> object:
        self.parameters = parameters
        return SimpleNamespace(columns=())


def test_sdk_adapter_uses_created_api_and_official_pro_bar_parameters() -> None:
    package = OnlyFakeTusharePackage()
    client = OnlyTushareSdkClient(OnlyTushareModules(package), "credential")  # type: ignore[arg-type]
    client.pro_bar(
        ts_code="000001.SZ",
        start_date="20260101",
        end_date="20260107",
        asset="E",
        freq="D",
        adj=None,
    )
    assert package.parameters == {
        "ts_code": "000001.SZ",
        "start_date": "20260101",
        "end_date": "20260107",
        "asset": "E",
        "freq": "D",
        "adj": None,
    }
