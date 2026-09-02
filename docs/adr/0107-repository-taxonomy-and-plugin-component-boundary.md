# ADR 0107: Repository Taxonomy and Plugin/Component Boundary

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
