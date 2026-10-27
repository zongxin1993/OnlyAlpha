# Private Factor authoring

This Product capability derives from ADRs 0104, 0124, 0129 and 0142. PostgreSQL Private Asset tables own mutable Drafts and
immutable Revisions. The backend owns authoring Commands; Web submits intent and displays returned facts. Authoring never
executes source, admits a Calculation, activates a Generation, qualifies a Factor or starts Research/Backtest.

## Content and concurrency

Asset IDs retain `private.factor.<name>`. Web may allocate the suffix while the operator supplies a human-readable description.
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

`SAVE_PRIVATE_FACTOR_DRAFT` and `PUBLISH_PRIVATE_FACTOR_REVISION` use the existing global UUID4 Admission/Receipt Authority.
Commands, the authoring effect and the business outcome snapshot commit in one transaction. Global command lock precedes the
Asset row lock. New Asset capacity is serialized between these locks. Same ID/kind/intent returns the original exact result; a different intent/owner/kind conflicts. Admission without
an outcome remains UNKNOWN. Commit acknowledgement loss is unavailable until an exact Command query proves its result; no
blind resubmission or latest substitution is allowed.

`private_factor_authoring_outcome` stores the immutable business result needed to reconstruct an old accepted draft after later
edits. It has a deferred foreign key to the global Receipt and does not replace Admission or Receipt. Its canonical fingerprint
binds the command ID, Asset ID, full command input and exact result under `ONLYALPHA_PRIVATE_FACTOR_AUTHORING_OUTCOME_V1`.
Receipt reads re-prove kind, intent, owner, result content and outcome identity. Missing/corrupt relations are unavailable, never
accepted, absent or permission to repeat an effect.

## Product API and UI

The normal workstation Factor library exposes authoring. Human local-session, same-origin/CSRF, node readiness and the retained
physical mutation Authority remain mandatory. Private responses retain the issuing session's withdrawal fence and `no-store`.

- `GET /api/v2/private-assets/factors`: bounded authoring inventory including unpublished Assets and the API V1 identity.
- `GET /api/v2/private-assets/factors/{factor_id}`: saved Draft/token, current head and exact oldest-to-newest Revision history.
- `PUT /api/v2/private-assets/factors/{factor_id}/draft`: save/create with `Idempotency-Key`, Draft and expected token.
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

## Implementation boundary

The pure authoring model remains inside backend's Private Asset Application module; PostgreSQL adapts its owning tables and
Commands. The stable Python `calculate(api, inputs, parameters)` SDK is retained. Old Python business/reference consumers may
retire only after their actual callers and assertions migrate; source stored in a Factor is user content, not Python backend
business code eligible for deletion. Research, Strategy authoring, Registry admission and execution remain separate capabilities.
