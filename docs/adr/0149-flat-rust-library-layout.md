# ADR 0149: Flat Rust library layout

- Status: Accepted
- Date: 2026-11-04
- Owning architecture: [Repository and product boundaries](../repository-product-architecture.md).

## Decision

Use one root Cargo workspace. Each reusable Rust library has a direct directory under `crates/`, named for its
responsibility. Cargo package names retain the `onlyalpha-` prefix. Kernel membership follows semantic ownership
and permitted dependencies. Rust sources in reusable crates and concrete Rust plugins use their package-local `src/` directories.

- `onlyalpha-runtime` owns the reusable durable Execution session, checkpointing and verified replay. It depends on
  `onlyalpha-execution`. Backtest remains an independent consumer of Runtime.
- `onlyalpha-market-data` owns pipeline composition and includes the state and delivery modules. Keep construction in
  `onlyalpha-market-data-construction` so Strategy and plugins can use it without importing the pipeline or Calculation.
- Calculation Bridge owns the generated Rust Gateway bindings and the optional `gateway-codegen` target. Canonical
  protocol definitions remain in `contracts/gateway/` and the Python projection keeps its existing package.
- Preserve the other library responsibilities and independent dependency and source closure checks.

This partially supersedes the directory placement and fixed twenty-crate Kernel layout in ADRs 0139
and 0142. The layout preserves canonical semantics, release ownership, Product and LIVE admission, and exact historical identity.
