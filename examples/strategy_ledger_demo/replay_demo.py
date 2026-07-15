from decimal import Decimal

from _support import CNY, create

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.strategy_ledger.enums import OnlyStrategyLedgerReplayOperation
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerLifecycleCommand, OnlyStrategyLedgerReplayEntry
from onlyalpha.strategy_ledger.replay import OnlyStrategyLedgerReplayService

_, key = create()
command = OnlyStrategyLedgerLifecycleCommand(key, OnlyTimestamp(0), OnlyMoney(Decimal("100000.00"), CNY))
entries = (
    OnlyStrategyLedgerReplayEntry(1, OnlyStrategyLedgerReplayOperation.CREATE, command.to_json()),
    OnlyStrategyLedgerReplayEntry(2, OnlyStrategyLedgerReplayOperation.ACTIVATE, command.to_json()),
)
manager = OnlyStrategyLedgerManager(key.runtime_id)
OnlyStrategyLedgerReplayService().replay(manager, entries)
print(manager.require_snapshot(key).to_json())
