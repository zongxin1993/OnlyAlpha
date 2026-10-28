# Private Factor authoring

This Product capability derives from ADRs 0104, 0124, 0129 and 0142. PostgreSQL Private Asset tables own mutable Drafts and
immutable Revisions. The backend owns authoring Commands; Web submits intent and displays returned facts. Authoring never
executes source, admits a Calculation, activates a Generation, qualifies a Factor or starts Research/Backtest.

## Content and concurrency

Asset IDs retain `private.factor.<name>` and are independent of human names. The current Product contract applies
[ADR 0143](adr/0143-product-names-display-versions-and-historical-labels.md) and [Product display identity](product-display-identity.md).
A Factor owns mutable display metadata in `private_factor_display`, separately from immutable content. Backend inventory
supplies new-object defaults such as "私有因子 1" and "自定义计算；用途待完善。"; these are presentation, not validation claims.
The initial saved Draft creates its Asset and selected/default display metadata atomically. Later content saves cannot rename it.

Display records have schema 1, the stable Factor ID, `display_name`, `usage_summary` and `edit_number`. Names are nonblank,
at most 100 Unicode characters/400 UTF-8 bytes without control characters; summaries are nonblank, at most 1000 characters/
4000 bytes, allowing newline/tab but no other controls. `edit_number` is a positive safe JSON integer, advanced by each accepted
metadata update, not an algorithm/publication version. Its canonical `ONLYALPHA_PRIVATE_FACTOR_DISPLAY_V1` fingerprint binds
the full record for concurrency, including ABA protection. Missing/corrupt metadata is unavailable, never inferred from
`description`. No old-row seeding, backfill or compatibility path is provided.

`description` and `economic_rationale` remain version-bound content and keep their existing fingerprint participation.
The ordinary editor separates name/usage from version annotations; renaming does not copy metadata into content or publish a
Revision. Backend returns history as exact `{display_version, revision}` entries only after verifying the complete chain;
ordinals start at 1, stay attached to their exact Revision and are independent of `semantic_version`, filtering and rename.
Revision/source/API identities retain their existing canonical contracts. API V1's frozen fingerprint is
`3265e2397f581705b67c1372483b6629671b68af71f69575c7bd602816d63be9`; the Python algorithm SDK remains its semantic owner and
conformance must prove this exact binding. Mutable Draft identity is the canonical fingerprint of
`{"contract":"ONLYALPHA_PRIVATE_FACTOR_DRAFT_V1","draft":DRAFT}`. It is a concurrency token, never a Revision or runtime identity.

Saving includes the full Draft and expected saved-Draft fingerprint (null for first save), with Draft base equal to the exact
current Revision. The same operation creates a previously absent Asset and its first Draft atomically. Concurrent editors with
an older token fail explicitly. Publishing includes the exact saved-Draft fingerprint and requires its base to remain current.
It creates the canonical immutable Revision and advances the existing Asset head atomically. The saved Draft remains unchanged;
continuing authoring starts from the current Revision with its exact parent, using the still-current saved-Draft token.

Draft input and its stored JSONB representation are bounded to 256 KiB, source to 64 KiB. NUL content/keys are invalid. Tags normalize to sorted unique strings. Canonical nested metadata permits
null/string/boolean/integer/array/object values, never floating financial values. Incomplete/invalid executable code may be stored
as authoring content; storage/publication is explicitly not static, mathematical, security or execution validation.

## Commands and recoverability

`SAVE_PRIVATE_FACTOR_DRAFT`, `PUBLISH_PRIVATE_FACTOR_REVISION` and `UPDATE_PRIVATE_FACTOR_DISPLAY` use the existing global UUID4 Admission/Receipt Authority.
Commands, the authoring effect and the business outcome snapshot commit in one transaction. Global command lock precedes the
Asset row lock. New Asset capacity is serialized between these locks. Same ID/kind/intent returns the original exact result; a different intent/owner/kind conflicts. Admission without
an outcome remains UNKNOWN. Commit acknowledgement loss is unavailable until an exact Command query proves its result; no
blind resubmission or latest substitution is allowed.

`private_factor_authoring_outcome` stores the immutable business result needed to reconstruct an old accepted draft after later
edits. It has a deferred foreign key to the global Receipt and does not replace Admission or Receipt. Its canonical fingerprint
binds the command ID, Asset ID, full command input and exact result under `ONLYALPHA_PRIVATE_FACTOR_AUTHORING_OUTCOME_V1`.
Metadata update intent also binds the authenticated Human actor; the existing immutable outcome and Receipt retain the
accepted name/summary, edit number, command intent and operational timestamp. Content outcomes retain their observed display
record for audit, not as a query of current names. Receipt reads re-prove kind, intent, owner, result content and outcome identity. Missing/corrupt relations are unavailable, never
accepted, absent or permission to repeat an effect.

## Product API and UI

The normal workstation Factor library exposes authoring. Human local-session, same-origin/CSRF, node readiness and the retained
physical mutation Authority remain mandatory. Private responses retain the issuing session's withdrawal fence and `no-store`.

- `GET /api/v2/private-assets/factors`: bounded authoring inventory including unpublished Assets and the API V1 identity.
- `GET /api/v2/private-assets/factors/{factor_id}`: saved Draft/token, current head and exact oldest-to-newest Revision history.
- `PUT /api/v2/private-assets/factors/{factor_id}/draft`: save/create with `Idempotency-Key`, Draft, expected token and required nullable `initial_display`; non-null initial names are allowed only for a newly created Asset.
- `PUT /api/v2/private-assets/factors/{factor_id}/display`: owner-authorized name/summary update with `Idempotency-Key` and the exact expected display fingerprint.
- `POST /api/v2/private-assets/factors/{factor_id}/revisions`: publish the selected saved token with `Idempotency-Key`.
- `GET /api/v2/private-assets/factors/{factor_id}/commands/{command_id}`: exact accepted result, null for proved non-admission,
  or explicit UNKNOWN/unavailable/conflict. A null response never automatically repeats a command.

Authoring inventory/history is bounded (200 Assets, 200 Revisions per Asset, 8 MiB checked history work per Asset); exhaustion is explicit
unavailability, not partial completeness. Writes prove that the resulting state remains readable before committing; capacity
rejection rolls back the effect and Command together. Readers verify the complete parent chain, payload/column identity and saved-Draft base.
Web retains the pending Command ID, Asset ID and operation in session storage before sending; storage failure refuses submission.
Reload preserves exact-result lookup and never allocates a replacement Command automatically. Corrupt/unreadable retained state
blocks new mutations. Accepted effects are reloaded through the owning current-state query before further editing.
Web displays loading/empty/error/conflict/saved/published/UNKNOWN states, preserves unsaved content on failure and offers exact
Command-result lookup. Publication is labelled as authoring only. Normal entry, editing, saving, publishing and historical reads
must work without entering internal fingerprints, database access or debugging tools.

Authoring result records contain required nullable Draft/fingerprint/Revision/display-version fields plus an exact display
record and its fingerprint. Metadata-only results have all content fields null; publish results include their proven ordinal.
The selected operation constrains this shape. Historical Command results remain exact after later content and display edits.
The client retains separate content and display edit bases: saving display metadata preserves unsaved source/JSON input and
must not advance the content CAS token to a concurrently changed Draft. UNKNOWN metadata updates use the same retained-ID
query path as content; no blind retry or invented success is permitted.

## Published Factor directory and exact details

The existing `GET /api/v2/private-assets` response keeps its immutable-content `entries` and
`ONLYALPHA_PRODUCT_ASSET_REGISTRY_V1` preimage unchanged. Its separate required `factor_presentations` array contains one
entry per published Factor, sorted by Factor ID: the same exact `locator`, owning `display` record and `display_fingerprint`,
and backend-derived `display_version`. It contains no Strategy presentation or draft-only Factor. This is a read projection,
not a second current-name Authority, stored search index or new identity. Renaming changes this presentation, not the Registry
fingerprint, Revision/source/API fingerprints or publication count.

A single repeatable-read query transaction obtains the current Registry and reuses the authoring owner's verified state for
Factor presentation. Whole linear history must prove the ordinal and current locator; missing display or corrupt/forked history
is explicit unavailability/corruption, never a guessed description, partial list or successful no-match. Additional aggregate
proof work (published Factor history, display and saved-Draft payloads) is bounded to 8 MiB before materialization. The existing
8 MiB Registry response-work and per-object limits remain; exhaustion is explicit unavailable. Session/withdrawal fences and
no-store behavior remain mandatory.

Shipping directory/search/details present current names and purposes first, with published 第 N 版 labels. Search filters the
existing bounded, fully validated live inventory by name/usage and existing technical/category/tag text; it does not call or
implement the deferred `/private-assets/search` service. A query failure is distinct from a successful empty filter result.
Client validation requires a complete, unique presentation-to-Factor-locator join; it never fills missing labels from content.

Selecting a directory item retains its exact locator and backend-provided ordinal. Later metadata refresh associates a current
name/usage through stable Factor ID only. A newer head may be shown as separate current context but cannot replace the selected
Revision, its ordinal or source content. If current display cannot be refreshed, say so explicitly while retaining exact selected
content; cached display is not presented as a successful current lookup. Version annotations and exact IDs/fingerprints remain
under technical details. The exact Revision endpoint and its immutable response are unchanged.

Legacy Python Product query/search-projection code and its re-export can retire once their current caller closure is removed.
Preserve Registry identity/order/draft exclusion, exact/no-latest/mismatch/failure, projection-only Authority and search-result
semantics at the native owner/client boundaries. Disposable persisted-search-cache rebuild/staleness tests retire with that
unused implementation; do not build a new cache to preserve them. Existing migration ledger/tables/facts are not removed.
Still-used Private Asset models/Store, Revision binding, algorithm SDK and execution/Generation/reference consumers remain.
Reference-chain preparation uses its existing exact imported Revision references, never Product search as execution authority.

Acceptance requires ordinary Web creation/publication, directory discovery by name and purpose, exact selection, rename and a
second publication without retargeting an already open detail, plus reload/restart and clear error/empty states. Prove stable
original Registry/content pins after rename, full-history and aggregate-budget rejection, exact-read mismatch/missing behavior,
complete client joins, and no current import of retired modules. Validate only these owners and their direct consumers; no
public catalog/workspace/Research execution, compatibility shim, new tools or automatic dev/release deployment is introduced.

## Structured contract editing target

[ADR 0144](adr/0144-private-factor-forms-and-lossless-contract-editing.md) records the owner-approved editing decision.
This section specifies target UI behavior; it does not claim the current JSON textareas implement it. Input, parameter and
output contracts remain the existing three objects in the Draft/Revision, not a new schema or a second persisted form model.
The Shipping editor calls them **所需数据**, **可调参数** and **计算结果**. Each has add/remove rows and its own **高级 JSON**
mode. A complex contract keeps only its own section in advanced mode; the other two remain independently editable.

### Fields and defaults

Type selectors present 精确数值 / 整数 / 是或否 / 文本 and map to the existing `DECIMAL` / `INTEGER` / `BOOLEAN` / `STRING`
tokens. This vocabulary does not certify execution support or admit a calculation. Chinese explanatory labels for known keys
(e.g. 收盘价 for `close`, 因子值 for `value`) are UI help, never new contract properties or lookup identities. Custom keys remain
visible with their exact spelling; the editor must not infer a market binding or rewrite Python source after a key rename.

| Section | Ordinary fields | New-object / new-row defaults and expanded controls |
|---|---|---|
| 所需数据 | 代码中的名称, 数据类型 | A new Factor retains the current `close` input with `type: DECIMAL`. A new row has an empty name and DECIMAL selected. Expanded 允许缺失 displays false when neither existing nullable spelling is present; reading this default does not insert a property. |
| 可调参数 | 代码中的名称, 参数类型, 使用时必须填写, 设置默认值 and its typed value | A new Factor retains `{}` and shows 没有可调参数. A new row starts with an empty name, INTEGER, required true and no default. Required and default are independent controls; an explicit required true is never disabled merely because a default exists. |
| 计算结果 | 结果字段名, 数据类型 | A new Factor retains `value` with `type: DECIMAL`. A new row has an empty name and DECIMAL selected. Expanded 允许缺失 displays false and 结果含义 displays the existing default FACTOR_VALUE when absent, without inserting either property. Custom or otherwise unrepresentable semantic metadata stays advanced. |

These are initialization defaults for an explicitly new Factor/row, not read-time normalization. Existing empty `{}` contracts
remain empty and gain no default row. Do not add range, enum, unit, data-source, instrument or period-binding fields that the
current private Factor mapping does not expose. 所需数据 declares inputs, not a Dataset/source selection; 可调参数 declares
parameter definitions/defaults, not parameter values for a submitted run. Source editing remains part of authoring.

For a new default value, INTEGER uses an exact integer literal within the ordinary editor's safely representable range;
DECIMAL uses a finite exact decimal string (e.g. `"0.10"`, preserving its spelling); BOOLEAN uses true/false and STRING uses
literal text. Do not round, coerce or use binary floating point. Reading existing values retains their original JSON type,
including integer versus numeric string; a value beyond the form's lossless capabilities remains advanced. An explicit empty
STRING or BOOLEAN false is a value, not an absent default. Preserve null as distinct from absence even where ordinary
parameter validation cannot accept it.

The current parameter mapping derives omitted `required` as `"default" not in contract`. The UI displays that effective value
without materializing it. With required true, a recorded default does not supply a missing run parameter. With required false,
a valid explicit non-null default is necessary for the ordinary form. If changing default presence would change an omitted
required's effective value, preserve the user's independent required selection through a visible, confirmed combined patch
(e.g. explicitly record required true when adding a default to an implicitly required parameter). Never silently toggle the
selection or silently add the companion property. Removing a necessary default leaves an incomplete editable form with a
specific error; it does not auto-enable required, invent a value or discard the user's edit.

### Validation and visible states

Ordinary field errors are local and actionable: 请输入输入名称 / 请输入参数名称 / 请输入结果名称, 输入名称重复 / 参数名称重复 /
结果名称重复, 请选择数据类型, 默认值与参数类型不符, 非必填参数需要有效默认值. Names must be nonblank and unique within their
own section; the ordinary parameter-name control also respects the existing no-whitespace rule. Names in different sections
may coincide. Key changes warn 请同步检查源码中的输入、参数或结果名称; source is not edited automatically. Type changes retain the
old pending value and request a valid replacement instead of clearing or coercing it. Numeric errors distinguish invalid
integer/decimal from a value that requires advanced editing for exact representation. Deleting a row is an explicit content
edit; changing UI row order must not synthesize an ordered array or rewrite other fields.

Advanced JSON errors identify the affected section and available line/column: malformed JSON, duplicate object key, non-object
root, disallowed number form, or an existing size/depth bound. Never parse duplicate keys by keeping only the last value, round
large integers, accept float/exponent literals through JavaScript conversion, or weaken existing backend guards. Preserve the
entire invalid text for correction. Advanced mode does not bypass existing client/wire numeric and submission bounds; a
retained value outside those bounds remains editable with an explicit error, not silently rounded or newly accepted.
Unknown or form-unrepresentable structure is an advanced-mode reason, not a new backend
rejection: advanced authoring continues to follow the current storage contract, even when execution mapping is unsupported.
Do not impose the narrower ordinary-form rules on all advanced content or present storage acceptance as executable validity.

Keep the existing loading/empty/read-denied/unavailable/conflict/UNKNOWN/accepted states. Ordinary incomplete fields and invalid
advanced JSON prevent submission of that content, while independent name/usage edits retain their existing path without
requiring the unsaved content to validate. All errors are visible near the field/section with keyboard/focus access; normal
forms work on the supported narrow viewport. Display 此处检查填写格式；保存或发布不代表源码已执行或计算结果已验证.

### Lossless form and advanced-mode round trips

1. Keep one pending contract per section, retaining original field presence, JSON value types, unknown structure and raw
   advanced text. Form state is a temporary editing projection, not another durable Authority or API contract.
2. Opening, closing, expanding defaults, focusing controls and switching modes perform no save or publish and apply no patch.
   Preserve omitted versus explicit false, absent versus null/default, `missing` versus `nullable`, exact strings, integer
   values and array order. A form must not reconstruct the whole object from its visible controls.
3. Before advanced-to-form switching, prove that projection and reconstruction preserve every value and field-presence
   distinction. Nested/custom/unknown/unrepresentable content stays advanced with a specific explanation and its full text.
   Do not strip fields, choose one conflicting spelling, flatten nested values or replace the section with a template.
4. Form edits patch only the explicitly edited field/row, retaining all untouched content. If an edit cannot preserve a
   dependent representation, show the exact coordinated change for confirmation or leave that section advanced. Cancelling
   keeps the pending content. Editing and reverting to the original value restores the original omission/representation,
   including any companion field inserted solely for that reverted edit.
5. Form-to-advanced switching shows the same pending content; switching back does not reinitialize defaults. Retain raw text
   unchanged across a no-edit round trip. JSON whitespace/object key layout does not define a new identity; the existing
   canonical algorithm still governs object ordering. Arrays, types, field presence and literal strings remain meaningful.
6. Backend continues to own canonical validation, fingerprints, publication and Command acceptance. For otherwise identical
   Draft inputs, no-op view/mode operations preserve canonical contract values and existing Draft/Revision/source/API identities.
   Deliberate contract edits remain content edits through the existing Save/Publish flow; name/usage edits remain separate.
   Do not add browser-computed official fingerprints, alternate endpoints, eager saves or automatic publication. Pending
   Command recovery and separate content/display concurrency bases remain unchanged.

### Acceptance boundary

Implementation must demonstrate the following through affected deterministic tests and the real Shipping UI, using the
existing formal API and Rust Authority. Tests may observe exact pins; user steps must not require users to enter them.

| Scenario | Required evidence |
|---|---|
| Normal authoring | Create without JSON: see close / no parameters / value defaults, add and edit rows, save, reload and publish content; fields and typed values survive. No execution/Research/Generation/Backtest is triggered or claimed. |
| Independent modes | Keep any one of the three contracts complex in advanced JSON while editing each of the other two as forms. Preserve nested/unknown fields and prove that unsupported-for-form is not labelled invalid-for-storage. |
| No-op and revert | Open/reopen and switch modes repeatedly for empty objects, absent/explicit flags, both existing nullable spellings separately, implicit/explicit required, absent/null/false/empty defaults, exact integers/decimal strings and nested arrays. No hidden command occurs; a save in an otherwise identical context retains canonical content/identity. Edit then undo restores original values and field presence. |
| Required/default independence | Cover all explicit required/default-presence combinations and omitted required with/without default. Adding/removing default never silently changes required; combined patches are shown and cancellable. Required true still requires a supplied parameter; an optional invalid/missing default has an explanatory form error. |
| Failure preservation | Duplicate names/JSON keys, wrong types, malformed JSON, unsafe numeric representation and existing bounds show local errors without losing text/other sections. Content errors do not block independent display updates. Conflict/UNKNOWN retains exact original Command recovery and unsaved content; no blind retry. |
| Content and presentation identity | A real contract edit follows saved-Draft CAS and explicit content publication; old Revision content remains exact. Rename/usage alone and all mode-only operations do not publish or change content pins. No source rewrite, unknown-field loss, numerical coercion or extra schema/version ledger. |
| Usability | Follow the normal discoverable editor entry; labels/help, add/remove, per-section advanced controls and recovery are keyboard accessible and usable on desktop/narrow viewport. Run same-path dogfooding and state the observed interaction/time budget in task context, not a second repository status ledger. |

## Implementation boundary

The pure authoring model remains inside backend's Private Asset Application module; PostgreSQL adapts its owning tables and
Commands. The stable Python `calculate(api, inputs, parameters)` SDK is retained. Old Python business/reference consumers may
retire only after their actual callers and assertions migrate; source stored in a Factor is user content, not Python backend
business code eligible for deletion. Research, Strategy authoring, Registry admission and execution remain separate capabilities.
