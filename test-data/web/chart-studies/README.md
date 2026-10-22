# Chart Study Query mutation vectors

`query.json` is synthetic technical input for strict contract, precision, cursor,
renderer and Web mutation tests. Its producer executes the current Rust
`Application` capture/publish flow into the owning PostgreSQL/ClickHouse sealed
Storage, reads the original 2000-bar window, then invokes Rust `ChartQuery` with
the exact isolated algorithm installation. Capability and evaluation fingerprints
come from their owning native implementations. No output fields are relabelled
or manually rehashed. Fixed clock, IDs, technical source and build/install paths
make every identity input explicit.

The technical Rust support reuses the existing native consumer's controlled
loopback venue and owner setup helpers. Only `chart_vector::export_vector` runs;
no Shipping service or normal-user acceptance is represented by this harness.
`numeric-cases.json` retains zero-input readiness/nullability cases from the pure
`ChartFactory` in that same exact SDK installation, without Python Product or
HTTP imports. Neither vector is Research evidence or real venue data, and neither
may be served from the Shipping API.

Use the sole canonical frozen serial verification entry to run
`python scripts/chart_study_query_fixture.py write --output-dir <evidence-dir>`.
Apply the actual generated files after the operation finishes and the source
window reopens; `check` compares committed exact bytes with a fresh producer.
The producer requires the guarded canonical `ONLYALPHA_POSTGRES_DSN` ending in
`_test` and the dedicated `onlyalpha_test_chart_query_vector` ClickHouse namespace.
It resets only that serial test schema/database, never dev business state. It
retains compiler artifacts, ELF and SDK hashes, process cleanup receipts and raw
native outputs under `test-results/chart-query-vector-evidence/<operation-id>`.
