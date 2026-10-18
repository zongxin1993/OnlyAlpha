# Independent Market Data State vectors

`operations-v1.jsonl` records explicit valid operations and hand-specified retained end minutes/counters. Time offsets use
2026-01-05T01:30:00Z. A type is [instrument, window]; an update Bar is [instrument, window, end minute]. Bars use UTC
alignment, RAW, CONTINUOUS, OHLC 10.00/10.10/9.90/10.05 (precision 2), volume 100 (precision 0), trade count 1.
`restore` replaces state through each implementation's own existing checkpoint format; `seed_version` supplies an exact
counter as controlled initial state. Neither consumer generates expected histories or counters from the other implementation.

`records-v2.jsonl` contains full explicit independent schema-2 expectations, including nanosecond logical init and a visible
but unmaterialized secondary series. Rust writers and readers must preserve these facts. Python has no schema-2/Engine-bound
cache reader: its common consumer checks only existing Domain Bars and available snapshot semantics, not wire equivalence.
The current Python Runtime participant remains `market-data.cache` schema 1.

Python's known coercive/non-atomic restore, weak nested validation, history-limit bypass, out-of-view query behavior and
indicator-bearing snapshots are reference deviations. Corrected Rust adversarial tests are separate; common vectors cannot
certify whole-module parity, Source/Construction/Generation proof, Runtime readiness, real restart/upgrade or latency.
