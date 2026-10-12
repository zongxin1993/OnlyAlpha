# Chart Study Query mutation vector

`query.json` is a synthetic owning-history/installed-SMA vector for Python contract
and browser adapter mutation tests. It is neither real venue data nor scientific evidence.
UUID and observation time inputs are deterministic. The server DTO owns its shape.

Regenerate with `python scripts/chart_study_query_fixture.py write`; validate exact
producer parity with `python scripts/chart_study_query_fixture.py check` through
the canonical Compose test runner. Never serve this vector from the Shipping API.
