"""The unique mutable authority root for one Trading Runtime."""

from __future__ import annotations

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.account.performance import OnlyAccountValuationSource
from onlyalpha.runtime.trading.config import OnlyTradingKernelConfig
from onlyalpha.runtime.trading.services import OnlyTradingAuthorities, OnlyTradingKernelServices


class OnlyTradingKernel:
    """Own shared trading state independently from the external-world driver."""

    def __init__(self, config: OnlyTradingKernelConfig, authorities: OnlyTradingAuthorities) -> None:
        self.config = config
        self.authorities = authorities
        self._services: OnlyTradingKernelServices | None = None
        authorities.account_manager.bind_performance_observer(self._project_account_performance)

    @property
    def services(self) -> OnlyTradingKernelServices:
        services = self._services
        if services is None:
            raise RuntimeError("Trading Kernel processing services are not installed")
        return services

    def install_services(self, services: OnlyTradingKernelServices) -> None:
        if self._services is not None:
            raise RuntimeError("Trading Kernel processing services can only be installed once")
        authorities = self.authorities
        if (
            services.position_manager is not authorities.position_manager
            or services.allocation_manager is not authorities.allocation_manager
            or services.position_reservation_manager is not authorities.position_reservation_manager
            or services.strategy_ledger_manager is not authorities.strategy_ledger_manager
            or services.account_manager is not authorities.account_manager
            or services.settlement_authority is not authorities.settlement_authority
            or services.margin_manager is not authorities.margin_manager
            or services.fee_application_ledger is not authorities.fee_application_ledger
        ):
            raise ValueError("Trading Kernel service graph contains foreign mutable authorities")
        self._services = services

    def _project_account_performance(
        self,
        snapshot: OnlyAccountSnapshot,
        source: OnlyAccountValuationSource,
        previous: OnlyAccountSnapshot | None,
    ) -> None:
        self.authorities.account_performance_projector.record(snapshot, source, previous=previous)
