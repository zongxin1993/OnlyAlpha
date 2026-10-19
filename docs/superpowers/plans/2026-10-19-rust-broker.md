# Rust Broker implementation plan

Use the approved common-protocol design; no provider implementation or Runtime activation. This is a design sequence, not a progress ledger.

1. Add adversarial command/recovery and reconciliation tests, witness RED at the new library boundary.
2. Implement immutable validated models, declared ports, bounded ingress and Execution v2 fact identity.
3. Implement opaque journal admission, durable dispatch, conservative restart and exact reconciliation receipts.
4. Add the minimal owning Execution read adapter required by the real consumer; run deterministic Virtual Broker and native comparisons.
5. Wire the dependency/source isolation guards, impact selector, version synchronization and canonical Rust lane. Run affected baseline checks through the single dev environment.
6. Perform bounded simplicity and independent correctness review; fix blocking findings and rerun affected checks. Run the full canonical Rust lane against the frozen final source.
7. Verify source receipts, release transition and remote base; commit and fast-forward master, push, fetch and compare the resulting commit/tree.

Constitution impact: NO. Formal business/product acceptance remains the shipping Web path; this library's controlled technical comparisons do not claim that acceptance.
