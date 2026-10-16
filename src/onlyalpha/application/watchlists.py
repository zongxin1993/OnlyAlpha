"""Owner-managed presentation configuration; never market-data or trading Authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from onlyalpha.application.market_data_product import OnlyMarketDataProductService, OnlyMarketDataSourceReferenceV1
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.source_read_access import OnlySourceReadSession
from onlyalpha.domain.errors import OnlyValidationError
from onlyalpha.domain.identifiers import OnlyInstrumentId

MAX_WATCHLISTS = 20
MAX_WATCHLIST_MEMBERS = 100
MAX_TOTAL_WATCHLIST_MEMBERS = 200


class OnlyWatchlistError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OnlyWatchlistMember:
    source: OnlyMarketDataSourceReferenceV1
    instrument_id: str

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.source, OnlyMarketDataSourceReferenceV1) or self.source.expected_type_id is None:
                raise ValueError
            if (
                not isinstance(self.instrument_id, str)
                or str(OnlyInstrumentId.parse(self.instrument_id)) != self.instrument_id
            ):
                raise ValueError
        except (TypeError, ValueError, OnlyValidationError) as error:
            raise OnlyWatchlistError("WATCHLIST_INVALID") from error


@dataclass(frozen=True, slots=True)
class OnlyWatchlist:
    list_id: str
    name: str
    members: tuple[OnlyWatchlistMember, ...]

    def __post_init__(self) -> None:
        try:
            identifier = UUID(self.list_id)
            if identifier.version != 4 or str(identifier) != self.list_id:
                raise ValueError
            if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 64:
                raise ValueError
            if self.name != self.name.strip() or any(ord(char) < 32 for char in self.name):
                raise ValueError
            if not isinstance(self.members, tuple) or len(self.members) > MAX_WATCHLIST_MEMBERS:
                raise ValueError
            if any(not isinstance(member, OnlyWatchlistMember) for member in self.members):
                raise ValueError
            if len(set(self.members)) != len(self.members):
                raise ValueError
        except (TypeError, ValueError, OnlyValidationError) as error:
            raise OnlyWatchlistError("WATCHLIST_INVALID") from error


@dataclass(frozen=True, slots=True)
class OnlyWatchlistBook:
    version: int
    lists: tuple[OnlyWatchlist, ...]

    def __post_init__(self) -> None:
        if (
            type(self.version) is not int
            or self.version < 0
            or not isinstance(self.lists, tuple)
            or len(self.lists) > MAX_WATCHLISTS
            or any(not isinstance(item, OnlyWatchlist) for item in self.lists)
            or len({item.list_id for item in self.lists}) != len(self.lists)
            or len({item.name for item in self.lists}) != len(self.lists)
            or sum(len(item.members) for item in self.lists) > MAX_TOTAL_WATCHLIST_MEMBERS
        ):
            raise OnlyWatchlistError("WATCHLIST_INVALID")


class OnlyWatchlistStore(Protocol):
    """Atomic owning store: configuration revision and global Command receipt commit together."""

    def read(self) -> OnlyWatchlistBook: ...
    def save(self, command_id: str, expected_version: int, lists: tuple[OnlyWatchlist, ...]) -> OnlyWatchlistBook: ...
    def command(self, command_id: str) -> OnlyWatchlistBook | None: ...


class OnlyWatchlistService:
    def __init__(self, store: OnlyWatchlistStore, market_data: OnlyMarketDataProductService) -> None:
        self._store = store
        self._market_data = market_data

    def read(self) -> OnlyWatchlistBook:
        return self._store.read()

    def command(self, command_id: str) -> OnlyWatchlistBook | None:
        return self._store.command(command_id)

    def save(
        self,
        command_id: str,
        expected_version: int,
        lists: tuple[OnlyWatchlist, ...],
        session: OnlySourceReadSession,
    ) -> OnlyWatchlistBook:
        OnlyProductCommandId(command_id)
        OnlyWatchlistBook(expected_version, lists)
        try:
            replay = self._store.command(command_id)
        except OnlyWatchlistError as error:
            if error.code != "WATCHLIST_COMMAND_UNKNOWN":
                raise
            # An immutable admission already exists. The owning store must compare
            # its intent before preserving UNKNOWN; this cannot create a second effect.
            return self._store.save(command_id, expected_version, lists)
        if replay is not None:
            return self._store.save(command_id, expected_version, lists)
        current = self._store.read()
        previous = {item.list_id: item for item in current.lists}
        for item in lists:
            old = previous.get(item.list_id)
            # Existing unavailable exact references remain editable/removable.
            previous_members = () if old is None else old.members
            added_by_source: dict[OnlyMarketDataSourceReferenceV1, list[str]] = {}
            for member in item.members:
                if member not in previous_members:
                    added_by_source.setdefault(member.source, []).append(member.instrument_id)
            for source, instruments in added_by_source.items():
                self._market_data.list_instruments(
                    source, instrument_ids=tuple(instruments), limit=len(instruments), read_session=session
                )
        session.check_active()
        return self._store.save(command_id, expected_version, lists)
