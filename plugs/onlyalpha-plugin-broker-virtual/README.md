# OnlyAlpha Virtual Broker Plugin

Deterministic simulated Broker implementation for OnlyAlpha backtests. Install it alongside Core:

```bash
pip install onlyalpha onlyalpha-plugin-broker-virtual
```

The plugin is discovered through the `onlyalpha.brokers` entry-point group with plugin ID `virtual`.
Its account, position, order, and trade stores are external simulated Broker projections used for query and
reconciliation. They are not Runtime accounting truth. Runtime remains the authority for committed executions, fees,
positions, allocations, accounts, ledgers, settlement, margin, risk, results, and audit.

The plugin never calculates or reports authoritative Runtime fees. Broker fills carry no fee authority; Core resolves
local fees after accepting the update.

Deterministic lifecycle scenarios can select a non-default outcome by positive, one-based submission index:

```yaml
extensions:
  simulation:
    submissions:
      - submission_index: 1
        action: REJECT_BEFORE_ACCEPTED
        rejection_code: SCENARIO_REJECTED
        reason: deterministic rejection
      - submission_index: 2
        action: ACCEPT_THEN_EXPIRE
        reason: deterministic expiry
```

Unlisted submissions follow the ordinary Accept path. The controls never inspect a market, venue, instrument, or
Runtime Manager: they only publish normalized Broker lifecycle updates. Checkpoint schema v3 binds a canonical
SHA-256 fingerprint of the complete simulation plan and validates every frozen pending submission action. v1/v2,
configuration drift, and scheduled-action conflicts fail closed.
