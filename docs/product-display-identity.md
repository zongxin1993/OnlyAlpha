# Product names, display versions and historical labels

This target architecture derives from the Constitution and [ADR 0143](adr/0143-product-names-display-versions-and-historical-labels.md).
It governs Indicator, Factor, Strategy, workspace calculation, Research and Backtest presentation. It is not a claim that their
Rust Product flows or metadata contracts are implemented. Construction follows the existing [migration work program](repository-migration-work-program.md).

## Terms and identity boundaries

| Term | Meaning and owner | Change rule |
|---|---|---|
| Object identity | The existing stable owning Asset/type/task identifier | Never derived from a mutable name; rename preserves it |
| Display name | Human-readable primary label, owned by that object's Product business | Mutable through the formal API; duplicates are allowed |
| Usage summary | Human-readable explanation of purpose | Editable presentation; cannot redefine calculation, hypothesis or trading semantics |
| Content Revision | One published immutable owning definition | Source, parameter definitions, input/output contracts or formal meaning changes follow the owning publication contract |
| Display version | A readable label for an exact published Revision | Backend-derived; never an independent content identity |
| Fingerprint | The exact identity in its existing domain | Preserved; normally shown under technical details/copy controls |
| Submission name snapshot | What an accepted task called its exact inputs when submitted | Immutable submission fact; independent of later current display names |

Names and summaries do not select code, resolve an implementation, authorize execution or identify Evidence. Renaming does not
create an algorithm Revision, change a StrategyRevision, select another Generation or rebind a result. Parameter values and
data ranges remain explicit task/configuration inputs: changing a period from 20 to 10 is not automatically a new Indicator
algorithm version, but a new task must bind the changed configuration.

Presentation mutations still have owning concurrency/audit identities and Command intent fingerprints where required.
"Display-only" does not mean excluding names from every document hash: an immutable snapshot or exported report can hash its
literal labels under its own contract. Never remove fields from an existing fingerprint preimage or silently reinterpret its
identity. These presentation/document identities do not become a second algorithm or trading Authority.

## Ownership and defaults

Rust backend business modules own current display metadata, its persistence, authorization, concurrency and audit records.
Web collects input and displays authoritative responses; browser storage is not the durable naming Authority. Reuse each
owning module and existing global Command/Receipt semantics for mutations. No generic alias service, separate release unit,
new Kernel responsibility or duplicate global name registry is needed.

| Surface | Default source | Mutable presentation owner |
|---|---|---|
| Installed Indicator/public Factor type | Its exact plugin/type declaration | Product catalog's explicit user display override; plugin definition and bytes remain unchanged |
| Private Factor/Strategy | System-generated object name and summary | Existing Private Asset Product owner, at object level across Revisions |
| Workspace calculation instance | Algorithm name plus selected parameters, e.g. simple moving average (20) | Existing workspace owner, scoped to that configured instance |
| Research/Backtest task | Selected inputs' current names plus useful task context | Existing task owner; title/summary changes do not mutate specification or outputs |

Type-level overrides do not rename every configured instance as if all instances had the same parameters. Effective type
labels follow the explicit Product override, otherwise the exact plugin's default; there is one selected current value.
A semantic research hypothesis, economic rationale or trading rule belongs to its owning version/specification, not an
editable usage summary. UI terminology must make that distinction visible.

Provide a nonempty, understandable default without requiring IDs or hashes. Prefer declared purpose, algorithm parameters
and selected task context; for a new custom object whose meaning is not known, use an honest role-based name such as
"Private Factor 1" and an honest editable summary such as "Custom calculation; purpose not yet specified". Do not invent an
explanation from arbitrary source or imply validation.
Defaults never overwrite a user's chosen name. A task's generated default title is established when it is created and does
not subsequently follow input renames. Name collisions are distinguished with version, time and context, not forced global
uniqueness or fingerprints as the primary label. Exact bounds/DTOs are frozen in the implementing slice's contract, not guessed here.

Concurrent edits must reject stale updates explicitly. Retain actor/change audit through the owning business boundary; an
audit/concurrency revision is not an algorithm publication. No database or internal Python shortcut is a human rename flow.

## Display versions

For a private object's complete, verified linear publication chain, backend returns the stable ordinal "Version 1",
"Version 2", etc. as a projection of that chain. The ordinal is scoped to that object and exact Revision. Draft UI says
"Editing from Version 3"; first unpublished content has no published ordinal. Sorting, filtering, pagination, rename and
failed publication do not renumber history. Replaying an accepted publication Command returns the same Revision and ordinal.
Reject incomplete, forked or corrupt history rather than numbering a convenient partial list. Web must not count visible rows.

Derive this label in the owning verified query; do not add an independent counter/ledger merely for display. If a future
owning history needs another shape, explicitly define its projection before changing the contract. Keep current
`semantic_version` semantics and fingerprint participation unchanged; it is not repurposed as the display ordinal.
Installed algorithms show their declared algorithm version and separate parameters. Backend/frontend/library/plugin release
versions, API versions, publication ordinals and algorithm semantic versions remain distinct. Do not manufacture a public
algorithm version from installation order. Technical details retain the exact IDs and full fingerprints.

## Historical task presentation

When Research or Backtest submission becomes a native Product slice, capture the selected input names and necessary readable
version labels against the exact accepted input references. The owning admission operation must define one coherent capture
point and commit/recover the snapshot with the accepted task; repeated lookup of current names after admission is not a
submission snapshot. Concurrent rename must produce a provable captured state, not a mixture of unbound labels. Exact input
identities and configuration remain the execution authority regardless of the label values.

Historical input panels, legends, comparison and result views primarily show the submission-time labels and versions:

```text
Input Factor: Momentum Factor · Version 3
Current name: Closing-price Trend Strength
```

The current name is a separately labelled optional association resolved by the original stable object identity, never by
searching for a matching name or selecting a latest Revision. Failure to obtain the current name does not erase the captured
label or redirect the input. The snapshot is a past observation, not a second current-name Authority.

The task's own title and usage summary remain editable, with their own audit/concurrency behavior. This does not change its
immutable input snapshot, status, metrics, result, StrategyRevision, Dataset or Evidence bindings. Reopening or restarting
must retain the same historical labels after later renames. Already published immutable report/artifact bytes are not
rewritten when either a task or input is renamed. A newly rendered export identifies its exact source facts; current-name
annotations do not retroactively mutate a prior artifact.

## Existing description and development cutover

Current Factor Draft/Revision `description`, `economic_rationale` and other content metadata participate in the existing
Revision preimage. The native authoring editor uses separate current display metadata; directory consumers must use the same
owning projection rather than treating `description` as a current name. Maintain that display metadata explicitly. Do not silently make `description` mutable, remove
it from the current hash or copy each renamed display value into later Revision payloads. Editing version-bound description
is still content editing under its owning contract. Expose one ordinary naming operation; keep version-bound annotations
clearly separate so users are not editing two competing names.

This is an active-development cutover, not a historical compatibility project. Do not implement old-name initialization from
latest descriptions, missing-snapshot backfill, old-schema loaders, dual DTOs, legacy aliases, identity translation or an
old/new rolling-upgrade matrix. New records must satisfy the new contract; unsupported old development records require an
explicit rebuild through the existing dev lifecycle rules, rather than a read-time fallback. Do not fabricate a submission
name from a current label. This document authorizes no data reset; any later dev reset follows AGENTS.md's exact resource,
lock and coordinated database/files/key/namespace rules.

Not supporting old development data does not permit rewriting immutable bytes, assigning a new meaning to an existing
fingerprint or losing history created under the new model. Keep this cutover separate from the Constitution's permanent
identity, traceability and recovery requirements and unrelated exact-artifact obligations.
