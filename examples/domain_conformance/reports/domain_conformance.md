# Domain Conformance Report

- Git commit: `6606e0c`
- Python: `3.12.0`
- Tests: 16 passed, 0 failed, 0 skipped
- Score: **97/100**
- Status: **ACCEPTED**

## Dimensions

- domain_boundary: 10
- value_types: 15
- instruments: 15
- precision_increment: 10
- market_rules: 9
- bar_time: 13
- order_trade_position: 8
- serialization: 5
- historical_versions: 4
- extensibility: 3
- determinism: 5

## Vetoes

- None

## Unsupported capabilities

- shared real-time/offline Bar aggregation algorithm
- quanto PnL conversion model
- full event-sourced order reconciliation

## Recommendation

Proceed to minimal Runtime and Backtest data-driving work; do not start Live trading.
