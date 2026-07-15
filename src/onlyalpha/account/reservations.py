"""Runtime-scoped Account cash Reservation collection."""

from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.models import OnlyAccountReservation
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId


class OnlyAccountReservationManager:
    """Owns Reservation identity/indexing; AccountManager owns cash mutations."""

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self.runtime_id = runtime_id
        self._reservations: dict[OnlyAccountReservationId, OnlyAccountReservation] = {}

    def add(self, reservation: OnlyAccountReservation) -> None:
        if reservation.runtime_id != self.runtime_id:
            raise ValueError("Account Reservation belongs to another Runtime")
        existing = self._reservations.get(reservation.reservation_id)
        if existing is not None and existing != reservation:
            raise ValueError("Account Reservation ID reused with different content")
        self._reservations.setdefault(reservation.reservation_id, reservation)

    def update(self, reservation: OnlyAccountReservation) -> None:
        if reservation.reservation_id not in self._reservations:
            raise KeyError(f"Account Reservation not found: {reservation.reservation_id}")
        if reservation.runtime_id != self.runtime_id:
            raise ValueError("Account Reservation belongs to another Runtime")
        self._reservations[reservation.reservation_id] = reservation

    def get(self, reservation_id: OnlyAccountReservationId) -> OnlyAccountReservation | None:
        return self._reservations.get(reservation_id)

    def require(self, reservation_id: OnlyAccountReservationId) -> OnlyAccountReservation:
        reservation = self.get(reservation_id)
        if reservation is None:
            raise KeyError(f"Account Reservation not found: {reservation_id}")
        return reservation

    def list_by_account(self, account_id: OnlyAccountId) -> tuple[OnlyAccountReservation, ...]:
        return tuple(
            sorted(
                (item for item in self._reservations.values() if item.account_id == account_id),
                key=lambda item: str(item.reservation_id),
            )
        )
