# ADR 0117: Immutable Distribution Runtime Generation and New-Work Activation

> Component-placement supersession: [ADR 0142](0142-library-product-boundaries-and-independent-releases.md) places the Generation manager in backend modules and the minimal Python base environment in backend release artifacts. The existing sole ledger/binding Authority, exact artifacts, activation/draining and historical-resolution rules below remain unchanged. The old package path is not the final layout.

- Status: Accepted
- Date: 2026-09-05
- Decision maker: repository owner through the B2.4 implementation authorization
- Related: ADR 0064, 0069, 0097, 0111, 0112, 0115, 0116

> Compatibility note: ADR 0129 makes database Revision the intended Private L3/L4 authoring Authority. This ADR remains the exact
> executable materialization and Runtime Generation contract after an admitted Revision is converted into runtime artifacts; it does
> not make Git, a wheel or a package the required production authoring Authority.

## Context

ADR 0115 freezes private source, semantic, implementation, Provider, distribution, Catalog and StrategyRevision identities. ADR
0116 binds controlled authoring Research to one exact process composition. Production release bytes, executable process
generations and the durable selection used by new formal work remain unspecified. An installed package, mutable path or in-process
Catalog pointer cannot prove which exact bytes execute, cannot survive restart as activation Authority, and cannot resolve the
implementation fingerprints of a historical StrategyRevision without a forbidden latest-version fallback.

## Decision

OnlyAlpha defines a locator-independent immutable Distribution Artifact manifest. Artifact byte identity is its SHA-256 and size;
the manifest additionally binds exact distribution identity, source repository/revision, Provider identity/version/content,
admitted asset inventory, Calculation implementation fingerprints and the exact tested Core execution identity. Storage paths,
registry URLs and credentials are operational locators and never identity. A content-addressed Artifact Store implements put-once
and exact fetch/verification; same declared artifact identity with different bytes or manifest fails closed.

OnlyAlpha also defines one immutable Runtime Generation manifest. It binds the exact Core execution artifact identity, complete
artifact set, exact Provider identities and contents, Catalog generation fingerprint and exact Calculation implementation
fingerprints. Its fingerprint excludes host, PID, process start time, environment/cache path, container ID, registry URL, clock
and random identifiers. A candidate is built in a clean isolated environment, from exact verified artifacts, and becomes READY
only after installed entry-point discovery recomputes and matches its Provider, Catalog and implementation closure.

The independently buildable `packages/onlyalpha-runtime-generation-manager/` component owns artifact transport, isolated
construction and the durable operational generation ledger. Core owns only the stable market-agnostic DTOs and validation
semantics. Core does not install packages, create environments, scan private paths, know Gitea or activate a deployment.

The generation ledger is append-only and hash chained. Its deterministic projection is the sole Authority for READY state,
`ACTIVE_FOR_NEW_WORK`, DRAINING/RETIRED state and immutable work bindings. Activation is an expected-current compare-and-set under
one durable commit boundary. A validation failure or crash before commit leaves the old pointer unchanged; restart after commit
replays the committed activation. Retrying the exact committed transition is idempotent. Competing transitions from the same
expected current generation yield one winner and one `GENERATION_ACTIVATION_CONFLICT`.

New formal work reads the active pointer exactly once and records an immutable `work_id -> runtime_generation_fingerprint`
binding. Later activation or rollback affects new work only. An old generation drains while bound work remains; process stop and
artifact retirement/deletion are separate. Rollback is another guarded new-work activation and never rebinds existing work.

Historical resolution matches every Research and TRADING implementation fingerprint in the verified StrategyRevision against
immutable Runtime Generation manifests. It never selects by semantic version, package version, availability order or latest. A
missing exact closure fails as `HISTORICAL_IMPLEMENTATION_UNAVAILABLE`; an ambiguous closure must be disambiguated by an explicit
exact generation identity rather than guessed.

The identity and Authority boundaries are permanent:

```text
CatalogGeneration != RuntimeGeneration
StrategyRevision != RuntimeGeneration
Artifact identity != artifact locator
active Run binding != current active generation pointer
Git admitted source != released artifact != deployment activation
```

Agent may author, research, inspect Evidence and prepare release metadata. Artifact publication and Runtime Generation activation
remain explicitly authorized release/operator actions; neither grants Agent or deployment infrastructure LIVE trading Authority.

## Consequences

Exact executable bytes can be validated, activated, rolled back and reconstructed without mutating Strategy identity or active
work. Immutable manifests provide a rebuildable implementation-to-generation index rather than a second semantic Authority.
Artifacts needed by historical Evidence or StrategyRevision remain retrievable even after their process generation drains.

Public L3/L4 examples and private repositories consume the same artifact and generation contracts. A private-only installation,
Catalog or runtime path is forbidden. Runtime construction costs an isolated environment/process per candidate, which is accepted
to preserve exactness and fail-closed behavior.

## Rejected alternatives

- Package `latest`, newest mtime, highest version or ambient installed packages as execution selection.
- Extending StrategyRevision with wheel, process, host, registry or environment details.
- Replacing CatalogGeneration with RuntimeGeneration or maintaining a second Provider registry.
- Mutable status files/databases that are not derived from durable generation facts.
- In-place `sys.path` mutation, directory watching, `importlib.reload` or active Run rebinding.
- Blindly choosing one of multiple historical generations with an incomplete exact binding.

## Native Research input runtime composition

The native backend may be retained as a `RESEARCH_RUNTIME` artifact in the same immutable artifact
set, independently of `BACKTEST_RUNTIME`. At most one of each role belongs to a Generation. This is
an auxiliary backend artifact with the backend's version, not another package or release line.
Its native logical name is `onlyalpha_backend-<version>-<target>.elf`, distribution `onlyalpha-backend`,
OnlyAlpha Git provenance, and mandatory `tested_core_execution_fingerprint` equal to this exact
Generation's Core identity. It is not installed as a Python wheel. The existing clean builder checks
its actual `--describe-research-runtime` response against protocol `onlyalpha.research.executor/1`,
actual artifact SHA, declared target and version before retaining it as an executable runtime.

Native input admission re-verifies the selected runtime's physical bytes and its original manifest
relation. Its managed algorithm process verifies that every used pure SDK semantic resource matches
that selected Core wheel's actual bytes, without importing Core business modules. The minimal SDK
package bootstrap remains separately pinned in its installation artifact; bootstrap differences do
not assert whole-Core execution equivalence. The precise supported contract is native Factor
Definition/source/input preparation with the declared algorithm ABI and ADR 0147 statistics, not
Python Trading Kernel equivalence or an unrestricted executor capability.

READY and matching package versions alone are insufficient. Missing runtime/Core resources,
substituted native bytes, different tested Core or unavailable original resources refuse admission.
This composition does not grant Human Research permission, create a Run, activate a Generation,
certify scientific quality, or authorize publication/SIM/LIVE. Actual Run execution still binds this
same selected artifact and must preserve the existing Command, lease, cancellation and recovery gates.

## Native backend Calculation capability binding

Distribution Artifact Manifest2 adds the `BACKEND_RUNTIME` role for the single statically linked
`onlyalpha-backend` ELF. It retains Manifest1's source, byte, distribution and tested-Core bindings,
and adds the strict `execution_capabilities` array of exact `kind` and versioned `contract` pairs.
Calculation implementations use the existing complete ImplementationManifest1 and Artifact summary
format. A Calculation capability is not an execution, work-admission or publication grant.

Each native Predicate implementation binds its actual logical Rust entrypoint and the SHA-256 of
the complete linked backend ELF as an implementation resource. Parameters and input edges remain
in the Calculation Definition. Rebuilding the backend may conservatively change implementation
identity even when a Calculation's semantic identity is unchanged. A metadata or source digest
cannot substitute for this actual executable resource.

One artifact SHA continues to have one immutable manifest. When the same backend image supports
more than one execution capability, those capabilities belong to that one `BACKEND_RUNTIME`
manifest; the bytes must not be republished under a second runtime role or as a synthetic wheel.
Each requested execution capability must resolve to exactly one artifact in the exact work-bound
Generation. An advertised capability must be actually implemented by that image. TRADING
Calculation registrations do not themselves imply a Backtest execution capability.

The backend's versioned native descriptor derives from the actual loaded Linux executable inode
and the finite adapters compiled into that image. The existing Research descriptor retains its
four-field wire. Native admission verifies the selected sealed release, stored Artifact2,
complete native implementation summaries and actual loaded-image SHA/target/version before
consuming native capabilities. New Generation preparation retains that actual observation in
Installed Research Environment V2 proof and checks its complete artifact/private-Factor
implementation closure. The unchanged RuntimeGeneration1 wire binds these new exact values.

Manifest1 and its existing `RESEARCH_RUNTIME` and `BACKTEST_RUNTIME` facts retain their original
semantics and bytes; they are not translated or amended into native Calculation grants.
Historical reads remain distinct from current executable admission. Missing exact Artifact2
capability or a different running image refuses native admission, without current/latest
substitution. Existing installed SDK resource checks remain necessary for the Python mathematical
nodes and grant no native Kernel equivalence. Complete graph execution and equivalence evidence,
Research permission, Run ownership, Freeze, Qualification and Promotion retain their own gates.
