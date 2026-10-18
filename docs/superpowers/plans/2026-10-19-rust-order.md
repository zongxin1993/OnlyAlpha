# Rust Order implementation plan

Owner authorized recommended implementation and direct master publication without further questions.
Spec: `docs/superpowers/specs/2026-10-19-rust-order-design.md`. Implement inline; one independent final review.

## Task 1: Pure Order lifecycle

Write shared independent lifecycle vectors and Rust tests first, demonstrate RED, implement Domain-based state, exact rounding,
scope/identity checks, submission-outcome graph, cancellation and immutable facts. Dependencies: Domain plus already-admitted
bigdecimal/num-bigint/serde_json/sha2 only. No new registry package or service. Reuse one Order crate with internal responsibility files.

## Task 2: Exact fresh recovery and comparison

Write bad checkpoint/continuation/identity tests first. Implement bounded canonical applied-command journal and full fresh replay,
exact expected digest/config/state comparison and atomic receiver replacement. Compare actual Python Manager on valid common inputs;
classify its defects instead of redefining expected behavior. No Python core cleanup or historical conversion.

## Task 3: Engineering integration and publication

Update Cargo/member/lock/version checks, affected impact selection, pure boundary guard and extracted module closure with tests.
Document owned Contract and source navigation. Run frozen sole-dev targeted and canonical checks, baseline static checks and bounded
simplicity review. Dispatch one independent whole-scope reviewer after initial validation; fix blockers with RED/GREEN regressions.
Finish required Rust debug/release and independent build validation on final source. Fetch master, commit, ff-only merge, push and
fetch/prove exact alignment. Version stays0.10.10; no Release.

## Review focus

Re-derive ownership and all success/failure/UNKNOWN/cancellation states. Test identity-with-different-payload, generated identity
collision after restore, external account/Venue relations, partial fill pending cancel, arithmetic failure before commit,
checkpoint splicing and atomic receiver preservation. No missing proof may imply duplicate or absence. No local state may imply
venue acceptance, broker dispatch permission or cross-authority economic success.
