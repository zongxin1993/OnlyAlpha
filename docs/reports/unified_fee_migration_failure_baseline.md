# Unified Fee Migration Failure Baseline

Baseline commit: `f18eab37c7229acb544941cc410b96985813542b` (`master`).

Environment: uv 0.9.18; Python 3.12.12 through `uv run`.

`uv run pytest -q` could not be used as the product baseline because it mixes
the Core and both plugin top-level `tests` packages in one interpreter and
fails collection with 34 `ModuleNotFoundError` errors. This is contrary to the
repository test-package rule. The Core baseline was therefore executed as
`uv run pytest tests -q`: **366 passed, 37 failed**.

Root causes:

1. Fee estimation constructed an `OnlyMoney` from unquantized fractional
   notional, causing `value exceeds declared precision` before an order could
   be reserved.
2. Integration, product golden data and resource fixtures still asserted the
   removed fixed-commission semantics.
3. The Virtual Broker reports no local fee; its account snapshot is external
   simulation evidence and is not the Runtime's local fee-inclusive truth.

No failure was resolved by adding a legacy commission branch, skip, xfail, or
relaxed numeric precision.
