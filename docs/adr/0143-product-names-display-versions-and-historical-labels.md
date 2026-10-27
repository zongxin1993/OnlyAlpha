# ADR 0143: Product names, display versions and historical labels

- Status: Accepted
- Date: 2026-10-27
- Decision maker: repository owner, explicitly accepting the naming/history rules and requesting their documentation; active-development cutover without historical compatibility work.
- Related: PROJECT_CONSTITUTION.md; ADRs 0092, 0104, 0117, 0124, 0129, 0130, 0135, 0141, 0142.
- Owning architecture: [Product display identity](../product-display-identity.md).
- Construction sequence: [Repository migration work program](../repository-migration-work-program.md#product-display-migration).

## Decision

Use meaningful system-generated names and editable usage summaries as the primary human presentation of Indicators, Factors,
Strategies, workspace instances, Research and Backtest tasks. Users can rename them through the formal API. The existing
owning Rust business module maintains current display metadata and concurrency/audit behavior; Web is not its durable
Authority. Plugin declarations supply public type defaults, with Product-owned user overrides. No separate alias service or
global name-identity registry is introduced. Names need not be unique and cannot select execution or authorize access.

Private objects expose "Version N" as a backend projection of the complete verified publication chain. Reuse existing
Revision identity and retain `semantic_version`; do not establish a second version ledger or number filtered browser rows.
Draft saves and renames do not publish content. Public algorithms retain their declared algorithm versions and separate
parameters. These versions are distinct from product/library release and API versions.

Historical Research/Backtest inputs primarily display immutable submission-time name/version snapshots bound to their exact
accepted references. Current names are optional, separately labelled associations through stable identity. Task titles remain
editable without changing input snapshots or scientific/trading results. Submission and recovery must preserve a coherent
snapshot; a retry cannot consult current metadata and relabel an already accepted task. Published report bytes are immutable.

Current Factor `description` participates in Revision fingerprints. Preserve that contract and original bytes. Add explicit
object-level display metadata instead of changing the old field's meaning or hash participation. Version-bound descriptions
remain content; an editable usage summary cannot redefine a calculation, research hypothesis or trading rule. Presentation
commands/audits and immutable reports may hash their own labels without making those hashes execution identities.

## Development scope and consequences

No old-development-data compatibility, old-description seeding, submission-snapshot backfill, dual schemas, legacy readers,
identity conversion or automatic fallback is required or authorized. Implement the new current contract directly; if old
disposable dev resources prevent adoption, use an explicit coordinated rebuild under AGENTS.md. This ADR does not authorize
one now. Source initialization and runtime startup do not silently repair or rewrite old records.

New-model history, exact identities, append-only facts and recovery remain mandatory. This choice does not waive unrelated
bound-work artifact obligations or permit semantic reinterpretation of any retained fingerprint. Normal human operations
remain Web → versioned API → owning Authority. Documentation acceptance is not code completion, execution admission,
Research/Backtest implementation, release or deployment authorization.

Using fingerprints as primary names was rejected because it obscures meaning. Using current names for historical inputs was
rejected because it rewrites the apparent research context. Renaming by publishing a new algorithm Revision was rejected
because it confuses presentation with computation; silently removing old description fields from hashes was rejected because
it changes existing identity semantics. Per-object ownership and derived display ordinals avoid unnecessary infrastructure.
