# ADR 0115: Private Quant Asset Identity, Version, Admission and Release Contract

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0097, 0098, 0110, 0111, 0112, 0113, 0114

## Context

ADR 0110 places production L3 Factor and L4 Strategy authoring assets in independent private repositories. ADR 0111 defines
explicit source/editable and installed-distribution loading, while ADR 0112 defines versioned providers and immutable catalog
generations. Those decisions do not yet freeze the complete relationship between authoring provenance, experiments, semantic
identity, executable implementation, releases, catalog activation, Research Evidence and StrategyRevision.

Private repositories change quickly and an Agent may create many mutable experiments. Git branches, source paths, package versions
and a current catalog are therefore useful provenance or selection facts, but none may become Calculation semantics or runtime
Strategy authority. Release and admission tooling also needs deterministic rules that prevent content drift under an existing
identity and prevent historical artifacts from being overwritten or silently replaced by a newer version.

## Decision

The lifecycle has distinct, non-substitutable authorities:

| Identity | Authority | Meaning |
|---|---|---|
| Git commit SHA | Git | exact authoring-source provenance |
| Experiment identity | private authoring workflow | one isolated mutable candidate context |
| Asset semantic version | Calculation or L4 authoring contract | one immutable mathematical or strategy-authoring meaning |
| Implementation fingerprint | Calculation implementation contract | exact executable implementation |
| Provider version | quant-asset provider | exact admitted provider content generation |
| Distribution version | package/release system | immutable distribution provenance |
| Catalog generation fingerprint | quant-asset catalog | exact validated provider set available to new work |
| StrategyRevision fingerprint | verified Strategy Freeze | sole exact runtime Strategy identity |

Git HEAD, a branch, filename, module path, source path, package version, provider, catalog, or any `latest` alias cannot substitute
for another layer. Research outcomes remain authoritative OnlyAlpha Evidence. A private repository cannot mint StrategyRevision or
acquire LIVE authority.

Production private asset IDs use `private.factor.<name>` for L3 and `private.strategy.<name>` for L4. Asset semantic versions are
positive integer strings. The same asset ID and semantic version denotes the same canonical semantic payload forever. A formula,
parameter meaning, input/output meaning, missing/warmup policy, execution-shape meaning, hypothesis interpretation, referenced
Calculation identity, Strategy parameter, eligibility/selection, entry/exit, or canonical input-contract change requires a new
asset semantic version. A performance refactor, packaging change, checkpoint repair, or bug fix that restores already-declared
semantics may retain that version, but changes exact implementation and provenance identity.

The preferred provider identities are `private.onlyalpha.alpha` and `private.onlyalpha.strategies`. Provider versions are
monotonically increasing positive integer strings, not SemVer. Any admitted content or implementation change requires a provider
version change; semantic change additionally requires an asset semantic-version change. The same provider ID and version may never
identify different content. Deterministic admission gates reject unchanged versions with changed content as
`PROVIDER_VERSION_REQUIRED`, unchanged asset ID/version with changed semantic payload as `SEMANTIC_VERSION_REQUIRED`, and a provider
version change over identical content as `UNNECESSARY_PROVIDER_VERSION_CHANGE` unless a separately accepted exceptional policy
exists.

Private distributions use PEP 440 CalVer `YYYY.M.D.N`, derived from the UTC release date and immutable same-day release/tag state,
unless an existing published repository contract requires a documented compatible scheme. Distribution version is provenance and
need not equal provider version. Providers derive installed distribution identity from package metadata rather than keeping a
second hand-edited version. Repackaging byte-identical provider content changes distribution/catalog provenance but not semantic or
provider content identity.

An experiment is mutable authoring workflow, not an admitted asset. Its deterministic opaque identity derives from a canonical
manifest of stable authoring inputs, excluding wall-clock time, temporary paths, model-response formatting and Research results.
Every reproducible iteration binds an exact Git commit or candidate source-bundle fingerprint. Candidate providers are explicit,
content-exact, non-production objects and are never registered in normal installed production entry points. Formal registration on
the admitted branch, followed by the required semantic/provider version transitions, is a separate action.

L3 continues to execute only through `onlyalpha.calculations` and is managed through `onlyalpha.quant_assets`. L4 exposes only
canonical authoring resources through `onlyalpha.quant_assets`; it is not a Trading execution plugin. Strategy resources reference
exact Calculation type IDs and semantic versions, never private Python implementation paths. Documentation, notes, papers, UI text
and dynamic Research results are excluded from canonical L4 resource content unless they are required to define semantics.

Engineering admission proves contract, determinism, identity, provenance, package/discovery correctness and applicable
RESEARCH/TRADING/checkpoint equivalence. It is distinct from future evidence-backed Alpha qualification. Source repositories may
retain hypotheses and static explanation but do not store current IC, Sharpe, backtest status, qualification snapshots or a second
Factor/Strategy status database as operational truth.

Each immutable release records a derived artifact manifest containing repository identity, Git commit, distribution identity,
wheel filename/SHA-256, provider identity/version/content fingerprint, admitted asset inventory and the exact tested OnlyAlpha
distribution. Nondeterministic build time is excluded from the canonical manifest fingerprint. Previously released versions, tags
and artifact paths cannot be overwritten. Artifacts referenced by Evidence or StrategyRevision remain retrievable; missing exact
historical implementations fail closed and never fall forward to a newer version.

Hot plug means validating an immutable provider set and selecting its Catalog Generation for **new work**. It uses isolated
process/worker environment generations. It never means `importlib.reload`, global `sys.path` mutation, module replacement, or
rebinding an active Run or StrategyRevision. Rollback selects an older exact artifact set for a new worker generation; existing
work continues on its bound generation or is explicitly cancelled and restarted.

Git admission uses four deliberately separate enforcement layers. Repository-tracked local hooks provide fast feedback but are not
an authority because they can be bypassed. Pull-request CI independently runs the canonical semantic/provider transition validator,
contract tests and installed-wheel checks under one stable `private-asset-admission` status. Server policy requires that status and a
pull request for `master`, blocks deletion and force-push, requires linear history, and permits squash merge only. Release is a second
gate over clean admitted `master`; it repeats the canonical validation, builds and installs the wheel, and creates a new immutable
CalVer tag, artifact and release manifest. A repository without verified server protection is not fully enforced even when all
repository-side artifacts exist.

`master` therefore denotes admitted source, not current production activation. Experiment branches may contain incomplete iterations
without provider-version churn, but formal registration, semantic-version changes when required, provider-version changes, tests and
provenance must enter `master` atomically in the final squash commit. Commit messages and Git branch names classify workflow intent
only; content-derived identities remain authoritative. Neither `--no-verify` nor an Agent policy exception can bypass pull-request CI
and server-required checks. Agents may prepare experiment branches and pull requests, but may not push or merge `master`, publish from
an experiment branch, move release tags, activate a Catalog, or acquire LIVE authority.

Deprecation is authoring guidance and does not mutate identity. Retirement omits an asset from a new Provider generation while its
historical artifacts remain exact and addressable. No successor alias or `latest` resolution is introduced.

## Consequences

`OnlyAlpha-alpha` and `OnlyAlpha-strategies` can evolve independently without becoming dependencies of OnlyAlpha Core. Cheap,
isolated experiments remain outside formal Providers until explicit admission. Releases, catalog activation, Research Evidence and
Strategy Freeze remain separate observable transitions. Exact historical Research and runtime behavior can be reproduced from
immutable semantic, implementation, distribution and catalog evidence.

Release/admission tooling in each private repository must enforce semantic/provider drift, immutable artifacts, installed entry
point discovery and source-versus-wheel equivalence. Deployment owns process-generation activation and artifact storage topology;
private packages do not add another Catalog manager or runtime.

## Rejected alternatives

- Git HEAD, branch, path, module, filename or latest package as semantic or runtime authority.
- SemVer semantics for asset/provider meaning or equality between distribution and provider versions.
- Releasing every mutable Agent experiment as a formal Provider generation.
- Private Calculation/Strategy execution SPIs, a Factor/Strategy graph, Feature Store or status database.
- In-place module reload or rebinding active work during hot plug/rollback.
- Committing dynamic Research outcomes as private source truth.
- Falling forward to the nearest/newest implementation when exact historical artifacts are missing.
