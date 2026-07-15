from decimal import Decimal

from _support import ACCOUNT, CNY, RUNTIME, A, B, create

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey

manager, key_a = create(A)
key_b = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, B, CNY)
manager.create_ledger(key_b, OnlyMoney(Decimal("50000.00"), CNY), OnlyTimestamp(0))
manager.activate_ledger(key_b, OnlyTimestamp(0))
print(key_a.cluster_id, manager.require_snapshot(key_a).cash.cash_balance)
print(key_b.cluster_id, manager.require_snapshot(key_b).cash.cash_balance)
