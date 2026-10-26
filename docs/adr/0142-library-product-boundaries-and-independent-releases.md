# ADR 0142: Library/product boundaries and independent releases

- Status: Accepted
- Date: 2026-10-26
- Decision maker: repository owner, through explicit GrillMe decisions and authorization to persist the design and migration plan.
- Related: PROJECT_CONSTITUTION.md; ADRs 0107, 0115–0117, 0129, 0130, 0139–0141.
- Owning architecture: [Repository and product boundaries](../repository-product-architecture.md).
- Construction sequence: [Repository migration work program](../repository-migration-work-program.md).

## Decision and rationale

Keep one repository and one root Cargo workspace. `crates/` contains reusable Rust libraries; `packages/backend/` and
`packages/frontend/` are the two product packages; concrete plugins remain in `plugs/`, formal protocols in `contracts/`.
Retain the twenty selected Kernel crate boundaries and their independent dependency/source-closure checks. Rename the current
Predicate-only `core/` directory and `onlyalpha-kernel` package to `predicates/` and `onlyalpha-predicates`, atomically with
consumers and build/provenance inputs. Do not add a facade crate, per-worker package or service per module.

The Rust library set has one SemVer release line. Backend and frontend each have their own SemVer line and named immutable
tags (`libs-vX.Y.Z`, `backend-vX.Y.Z`, `frontend-vX.Y.Z`). Plugins have their own distribution versions and unambiguous named
tags; private asset/Provider semantic identities retain their owning contracts. Only selected changed release units advance;
an unrelated change or documentation-only change does not force all product/library versions to advance. Version starting
numbers are not assigned by this decision. Keep one metadata authority per release unit, not a second version ledger.

Backend owns product business modules, API/security, product storage, Generation lifecycle, Agent coordination and worker
assembly. Its default is one Rust executable with `serve` and `worker` roles, sharing ordinary internal modules, with multiple
processes only for actual lifecycle/resource/fault/permission/Generation needs. These are operator startup interfaces, not a
new Product CLI. Agent still uses the formal Product API. Protocols, reusable backtest execution, algorithm bridge and Trading
persistence are libraries outside the Kernel. Python process management remains backend-owned; bridge ports keep reusable
libraries independent of backend.

Rust plugins initially remain statically linked: a plugin release does not replace a running backend; adopting changed plugin
code requires a new backend artifact/release. No dynamic Rust ABI or hot reload is introduced. Backend ships its target-specific
minimal Python interpreter/runtime, algorithm executor/SDK and protocol resources as constituent artifacts under its version.
Algorithm plugins/private executable Revisions use the existing exact artifact and Generation admission flow; they are not all
baked into every backend release. Current backend business code cannot be relabeled an algorithm SDK.

Development uses local workspace paths. Formal releases verify that every selected library/plugin source closure equals its
immutable released source content, and bind locks, toolchain, target, features and build inputs. Path plus a version assertion
or Cargo.lock alone does not prove source identity. Start with immutable source artifacts and hashes, without a private Cargo
registry. Frontend/backend may have different versions only within explicitly verified API-compatible combinations; default
delivery uses a tested pair. No old-development-version shim or general rolling-upgrade promise is introduced.

## Migration and Python retirement

First migrate repository organization, release machinery and packaging while preserving actual admitted behavior. Continue
remaining Rust capability construction in the dependency order of ADRs 0139/0141. Each migrated library/capability includes an
explicit Python-retirement assessment and deletion of its obsolete Python implementation plus imports, exports, packaging,
entry points, deployment/build consumers and implementation-only comparison wiring once the affected replacement, caller,
product, failure and recovery gates pass. A Rust library's presence or vector pass alone does not permit deletion. An affected
still-running Python caller or required algorithm dependency must first migrate or receive its minimal legitimate SDK boundary.

This makes retirement part of each eligible migration delivery rather than optional later cleanup. R8 remains the aggregate
final Kernel retirement gate; it is not a reason to keep an already safely replaceable module indefinitely, nor permission to
remove a still-required one early. Keep independent semantic vectors, fault assertions, replay fixtures and exact archived
artifacts/readers required by existing work/history. No permanent dual Kernel, new compatibility shim, legacy loader, identity
translation, latest substitution or fallback. Python-authored Indicators/Factors, necessary mathematical helpers/SDK and
legitimate engineering tools remain; language-appropriate plugin exceptions retain their owning decisions.

## Supersession and limits

This supersedes ADR 0107's directory/component naming where inconsistent, ADR 0139's `core/` placement and worker package
placement, ADRs 0116/0117's independently packaged worker/manager placement, and the repository-wide synchronized release
policy. Their semantic, protocol, Authority, permission, exact-history and Generation obligations remain. It extends ADR 0141
with the selected organization and mandatory bounded Python deletion. It does not modify the Constitution, activate Rust
writers, certify current implementation, authorize LIVE, start code migration, publish releases or delete source/data.

One root-version release policy was rejected because unrelated layers change at different rates. Separate repositories,
per-worker distributions, dynamic Rust plugin loading and a Cargo registry were rejected as unnecessary current complexity.
The cost is explicit dependency provenance and tested release combinations rather than version-number equality.
