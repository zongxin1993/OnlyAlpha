from _support import create

from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.strategy_ledger.views import OnlyStrategyLedgerContextView

manager, key = create()
view = OnlyStrategyLedgerContextView(key, OnlyStrategyLedgerQueryService(manager))
print(view.equity, hasattr(view, "apply_trade"))
