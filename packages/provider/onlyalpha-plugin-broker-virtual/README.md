# OnlyAlpha Virtual Broker Plugin

Deterministic simulated Broker implementation for OnlyAlpha backtests. Install it alongside Core:

```bash
pip install onlyalpha onlyalpha-plugin-broker-virtual
```

The plugin is discovered through the `onlyalpha.brokers` entry-point group with plugin ID `virtual`.
Its account, position, order, and trade stores are external simulated Broker projections used for query and
reconciliation. They are not Runtime accounting truth. Runtime remains the authority for applied trades, fees,
positions, allocations, accounts, ledgers, settlement, margin, risk, results, and audit.

The plugin never calculates or reports authoritative Runtime fees. Generated fills use `reported_fee=None` and
`fee_reporting_mode=NONE`; Core resolves local fees after accepting the Broker update.
