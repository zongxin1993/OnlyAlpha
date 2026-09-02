# OnlyAlpha Binance Provider

Credential-free Binance Spot public reference capture plus the bounded P9.2 historical/realtime DataSource. The DataSource normalizes closed 1m Bars, raw Trades, and Binance's declared `/api/v3/referencePrice` / `@referencePrice` fact. Average-price payloads are not market-reference facts.

Realtime continuity is in-process and serializes every state, buffer, dedup, sequence, recovery, and READY-proof mutation through one coordinator authority. Durable cursors, WAL, database revisions, private APIs, and Broker behavior remain outside P9.2.
