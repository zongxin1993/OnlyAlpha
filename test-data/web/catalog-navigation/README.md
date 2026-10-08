# Controlled Catalog navigation transport

`responses.json` is shared by Web client/component tests and Browser E2E. It is deliberately
controlled transport data with placeholder fingerprints, not a golden numeric result, a hosted
generation attestation, an installed plugin catalog or production admission evidence. It covers
distinct Runtime/Catalog identities and descriptor-driven SMA default previews. Consumers mutate
copies for wrong-owner, missing-proof, duplicate and stale-generation tests.

The separate `discovery` response covers current-process registered metadata when no Runtime is
active. It intentionally contains no exact generation, implementation or readiness proof. Discovery
selection tests may not promote these entries to exact Catalog availability or numeric readiness.

The real Product queries validate canonical projections separately in HTTP contract tests.
