# ADR 0107: Repository Taxonomy and Plugin/Component Boundary

> Placement/naming supersession: [ADR 0142](0142-library-product-boundaries-and-independent-releases.md) selects reusable libraries under `crates/`, only backend/frontend product packages under `packages/`, and independently versioned plugins under `plugs/`. The decisions below record the earlier layout; their protocol and Authority boundaries remain. Target paths are not current-source claims.

- Status: Accepted
- Date: 2026-09-02

## Decision

1. `src/onlyalpha/` is the stable, market-agnostic OnlyAlpha core/application and Plugin SPI.
2. `plugs/` contains concrete implementations discovered and assembled through that SPI.
3. `packages/` contains independently buildable/versioned/deployable non-plugin components.
4. Plugin distributions use `onlyalpha-plugin-<NAME>`; components use `onlyalpha-<FUNC>-<NAME>`.
5. Category-first wrappers (`apps`, `packages/provider`, `market`, `api`, `protocol`, `factor`, `indicator`, `target`, `fake`) are abolished.
6. Web is a component, not a Plugin. The HTTP server is a replaceable transport component, not Kernel.
7. The OpenAPI Product Contract remains a first-class root contract under `contracts/`.
8. Plugin type and capability are expressed by descriptor/SPI semantics, not first-level repository taxonomy.

This decision supersedes only repository locations and package naming in older ADR examples; it does not change their authority, API semantics,
idempotency, Stateful Kernel, or Web boundary conclusions.
