# Market-data WAL reference bytes

`market_wal_history.json` contains deterministic OAMD v1 frames and metadata
written and read by the canonical Python WAL implementation. The controlled
observation is storage test input, not evidence of a real provider request.
The Rust filesystem tests read the historical bytes without rewriting them and
compare native output byte-for-byte with the reference writer output.

The fixture keeps isolated Rust Product/HTTP tests independent of Python and
application imports. Its generator is a separate repository-level reference
check; it never runs in the Product or calculation worker.

Run the current-source check through the frozen dev verification entrypoint:

```sh
python scripts/dev_verification.py run -- env PYTHONPATH=/workspace/src:/workspace python packages/onlyalpha-product-runtime/tests/support/market_wal_history.py check packages/onlyalpha-product-runtime/tests/fixtures/market_wal_history.json
```

For an intentional reference change, regenerate in the working tree with the
repository Python environment, inspect the semantic and byte changes, and then
run the formal check above and affected Rust tests:

```sh
PYTHONPATH=src:. python packages/onlyalpha-product-runtime/tests/support/market_wal_history.py write packages/onlyalpha-product-runtime/tests/fixtures/market_wal_history.json
```

`legacy_metadata_json` exercises the existing schema-1 missing recovery-field
reader semantics. It does not authorize identity translation, alternate readers,
or a Python business fallback. Filesystem interoperability alone does not prove
service restart, deployment upgrade, or Shipping Web UI acceptance.
