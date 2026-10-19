# Rust Settlement implementation plan

Execute inline under the approved scope in ../specs/2026-10-19-rust-settlement-design.md; this is construction order, not a status ledger.

1. Witness missing Settlement ownership in real Execution. Add failing library tests for six-axis T0/T1/TN/calendar identity, immutable economics, due ordering and atomic recovery. Implement Domain-only compile/Authority/Maturity with admitted Decimal/JSON/SHA dependencies.
2. Evolve normalized settlement proofs atomically. Register exact post-Fill lifecycle, derive initial bucket/withdrawal from the owner, and add SETTLEMENT_MATURITY to the existing coordinator. Test every projection cut, source/cycle mutations, cash/quantity conservation and duplicate prevention.
3. Add actual Python/native common vectors and fresh-process restart proof. Wire exact dependency/source guards, isolated closure, canonical lane, impact selection and synchronized patch version.
4. Complete targeted formal baseline, bounded simplicity and independent state-space/relation/predicate/mutation review. Fix blocking findings with witnessed regressions. Run final affected canonical/debug/release/build checks on one frozen source, then commit, ff-only merge, push and fetch/tree prove.

Review focus: booking vs trading/withdrawal truth, unknown calendar coverage, lifecycle reuse, cross-portfolio maturity, completed-history recovery and per-trade cash release identity. No test relaxation, implicit schema conversion or second Store.
