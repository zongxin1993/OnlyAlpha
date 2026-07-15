"""Strategy Ledger failures."""


class OnlyStrategyLedgerError(Exception):
    pass


class OnlyStrategyLedgerInsufficientCashError(OnlyStrategyLedgerError):
    pass


class OnlyStrategyLedgerCurrencyError(OnlyStrategyLedgerError):
    pass


class OnlyStrategyLedgerScopeError(OnlyStrategyLedgerError):
    pass


class OnlyStrategyLedgerReconciliationError(OnlyStrategyLedgerError):
    pass
