from typing import Protocol

from .loader import OnlyTushareModules


class OnlyTushareClient(Protocol):
    def pro_bar(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
        asset: str,
        freq: str,
        adj: str | None,
    ) -> object: ...


class OnlyTushareSdkClient:
    def __init__(self, modules: OnlyTushareModules, token: str) -> None:
        self._package = modules.package
        self._package.set_token(token)
        self._pro = self._package.pro_api()

    def pro_bar(
        self,
        *,
        ts_code: str,
        start_date: str,
        end_date: str,
        asset: str,
        freq: str,
        adj: str | None,
    ) -> object:
        return self._package.pro_bar(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            asset=asset,
            freq=freq,
            adj=adj,
        )
