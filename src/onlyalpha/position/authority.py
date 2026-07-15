"""Field-level Position authority policy."""

from dataclasses import dataclass

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.position.enums import OnlyPositionAuthority


@dataclass(frozen=True, slots=True)
class OnlyPositionAuthorityPolicy:
    runtime_mode: OnlyRuntimeMode

    def authority_for(self, field_name: str) -> OnlyPositionAuthority:
        if field_name in {"allocation", "strategy_pnl", "local_average_price", "fees"}:
            return OnlyPositionAuthority.LOCAL
        if self.runtime_mode is OnlyRuntimeMode.LIVE:
            if field_name in {"total_quantity", "position_side", "broker_average_price"}:
                return OnlyPositionAuthority.BROKER
            if field_name in {
                "available_quantity",
                "frozen_quantity",
                "settled_quantity",
                "unsettled_quantity",
            }:
                return OnlyPositionAuthority.RECONCILED
        return OnlyPositionAuthority.LOCAL
