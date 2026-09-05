# ADR 0117: Immutable Distribution Runtime Generation and New-Work Activation

- Status: Accepted
- Date: 2026-09-05
- Decision maker: repository owner through the B2.4 implementation authorization
- Related: ADR 0064, 0069, 0097, 0111, 0112, 0115, 0116

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
