"""Construction of the Runtime-neutral Trading Kernel authority graph."""

from onlyalpha.account.manager import OnlyAccountManager
from onlyalpha.account.performance import OnlyAccountPerformanceProjector
from onlyalpha.account.reservations import OnlyAccountReservationManager
from onlyalpha.account.views import OnlyAccountQueryService
from onlyalpha.fee.ledger import OnlyFeeApplicationLedger
from onlyalpha.fee.reconciliation_authority import OnlyFeeReconciliationAuthority
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.margin.manager import OnlyMarginManager
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.queries import OnlyPositionQueryService
from onlyalpha.position.reservations import OnlyPositionReservationManager
from onlyalpha.runtime.trading.config import OnlyTradingKernelConfig
from onlyalpha.runtime.trading.kernel import OnlyTradingKernel
from onlyalpha.runtime.trading.services import OnlyTradingAuthorities
from onlyalpha.settlement.authority import OnlySettlementAuthority
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService


class OnlyTradingKernelBuilder:
    """Create shared authorities without selecting a Runtime driver or plugin."""

    def build(self, config: OnlyTradingKernelConfig) -> OnlyTradingKernel:
        position = OnlyPositionManager(config.runtime_id)
        allocation = OnlyPositionAllocationManager(config.runtime_id)
        position_query = OnlyPositionQueryService(position, allocation)
        position_reservation = OnlyPositionReservationManager(config.runtime_id, position, allocation)
        ledger = OnlyStrategyLedgerManager(config.runtime_id)
        ledger_query = OnlyStrategyLedgerQueryService(ledger)
        account_reservation = OnlyAccountReservationManager(config.runtime_id)
        account = OnlyAccountManager(config.runtime_id, reservation_manager=account_reservation)
        authorities = OnlyTradingAuthorities(
            position,
            allocation,
            position_reservation,
            position_query,
            ledger,
            ledger_query,
            OnlyStrategyLedgerLocator(ledger),
            account_reservation,
            account,
            OnlyAccountPerformanceProjector(config.runtime_id),
            OnlyAccountQueryService(account),
            OnlySettlementAuthority(),
            OnlyMarginManager(config.runtime_id),
            OnlyFeeApplicationLedger(),
            OnlyFeeReconciliationAuthority(),
            OnlyFeeReconciliationRiskGate(),
        )
        return OnlyTradingKernel(config, authorities)
