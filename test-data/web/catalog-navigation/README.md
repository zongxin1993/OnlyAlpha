# Controlled Catalog navigation transport

`responses.json` is shared by Web client/component tests and Browser E2E. It is deliberately
controlled transport data with placeholder fingerprints, not a golden numeric result, a hosted
generation attestation, an installed plugin catalog or production admission evidence. It covers
distinct Runtime/Catalog identities and descriptor-driven SMA default previews. Consumers mutate
copies for wrong-owner, missing-proof, duplicate and stale-generation tests.

The real Product queries validate canonical projections separately in HTTP contract tests.
