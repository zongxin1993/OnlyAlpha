"""Read-only Account query and Cluster Context views."""

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId


class OnlyAccountQueryService:
    def __init__(self, manager: OnlyAccountManager) -> None:
        self._manager = manager

    def get(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot | None:
        return self._manager.get_snapshot(account_id)

    def require(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot:
        return self._manager.require_snapshot(account_id)

    def list_accounts(self) -> tuple[OnlyAccountSnapshot, ...]:
        return self._manager.list_accounts()


class OnlyAccountQueryView:
    """Cluster-scoped immutable Account view."""

    def __init__(self, account_id: OnlyAccountId, query: OnlyAccountQueryService) -> None:
        self.__account_id = account_id
        self.__query = query

    def current(self) -> OnlyAccountSnapshot:
        return self.__query.require(self.__account_id)

    def get(self, account_id: OnlyAccountId) -> OnlyAccountSnapshot | None:
        if account_id != self.__account_id:
            raise PermissionError("Cluster cannot read an unauthorized Account")
        return self.__query.get(account_id)
