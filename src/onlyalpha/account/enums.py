"""Account state, mutation and reconciliation enumerations."""

from enum import StrEnum


class OnlyAccountType(StrEnum):
    CASH = "CASH"
    MARGIN = "MARGIN"


class OnlyAccountStatus(StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    RECONCILING = "RECONCILING"
    SUSPENDED = "SUSPENDED"
    ERROR = "ERROR"
    CLOSED = "CLOSED"


class OnlyAccountMutationStatus(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    NO_CHANGE = "NO_CHANGE"
    STALE = "STALE"


class OnlyAccountCashChangeType(StrEnum):
    INITIAL_DEPOSIT = "INITIAL_DEPOSIT"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRADE_BUY = "TRADE_BUY"
    TRADE_SELL = "TRADE_SELL"
    FEE = "FEE"


class OnlyAccountReservationState(StrEnum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class OnlyAccountAuthority(StrEnum):
    LOCAL = "LOCAL"
    BROKER = "BROKER"
    DERIVED = "DERIVED"
    RECONCILED = "RECONCILED"


class OnlyAccountReconciliationSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK_ACCOUNT = "BLOCK_ACCOUNT"
    FAIL_RUNTIME = "FAIL_RUNTIME"


class OnlyAccountReconciliationAction(StrEnum):
    NONE = "NONE"
    REFRESH = "REFRESH"
    BLOCK_ACCOUNT = "BLOCK_ACCOUNT"
    FAIL_RUNTIME = "FAIL_RUNTIME"
