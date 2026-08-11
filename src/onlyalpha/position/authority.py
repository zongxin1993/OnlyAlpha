"""Field-level Position authority policy."""

from dataclasses import dataclass

from onlyalpha.position.enums import OnlyPositionAuthority


@dataclass(frozen=True, slots=True)
class OnlyPositionAuthorityPolicy:
    """Explicit economic authority policy independent from Runtime identity."""

    broker_authoritative_fields: frozenset[str] = frozenset()
    reconciled_fields: frozenset[str] = frozenset()

    @classmethod
    def local(cls) -> "OnlyPositionAuthorityPolicy":
        return cls()

    @classmethod
    def broker_reconciled(cls) -> "OnlyPositionAuthorityPolicy":
        return cls(
            frozenset({"total_quantity", "position_side", "broker_average_price"}),
            frozenset(
                {
                    "available_quantity",
                    "frozen_quantity",
                    "settled_quantity",
                    "unsettled_quantity",
                }
            ),
        )

    def authority_for(self, field_name: str) -> OnlyPositionAuthority:
        if field_name in {"allocation", "strategy_pnl", "local_average_price", "fees"}:
            return OnlyPositionAuthority.LOCAL
        if field_name in self.broker_authoritative_fields:
            return OnlyPositionAuthority.BROKER
        if field_name in self.reconciled_fields:
            return OnlyPositionAuthority.RECONCILED
        return OnlyPositionAuthority.LOCAL
