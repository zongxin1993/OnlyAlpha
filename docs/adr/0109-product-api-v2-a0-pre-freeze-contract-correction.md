# ADR 0109: Product API v2 A0 Pre-Freeze Contract Correction

- Status: Accepted
- Date: 2026-09-03
- Decision maker: repository owner through the A0 PLAN_CONFLICT resolution authorization
- Related: ADR 0101, ADR 0103, ADR 0108

## Context

Product API v2 is still under A0 construction. The Strategy and Backtest routes first entered the repository on 2026-09-02 and the
current pre-freeze OpenAPI projection contains proven divergences from the runtime that authored it:

- request validation is handled as `400 ProductErrorEnvelopeDto`, while generated operations advertise `422 HTTPValidationError`;
- the runtime maps Product errors to `400`, `404`, `409`, `500` and `503` instances of `ProductErrorEnvelopeDto`, while those OpenAPI
  responses have no content schema;
- Backtest Evidence is a strict immutable manifest, while the transport projection exposes its manifest as an arbitrary object.

The supported-consumer audit found no external Product API v2 compatibility obligation. The repository has no Git tag or GitHub
Release, the relevant Python and npm package names are not published, the Web package is private, and the architecture intentionally
provides no Product SDK or Product CLI. The only concrete client is the in-repository generated Web client, which is migrated atomically
with the canonical contract. Preserving the false pre-freeze projection would create two descriptions of observable Product behavior.

Comparison of baseline commit `8901fec27faf8599c965df792d07a84b902583f3` with the corrected projection reports exactly 48 breaking
diff entries. They are all required A0 contract corrections: eight Strategy/Backtest operations each remove the false `422` response
and add the actual `application/json` schema to five existing Product error responses. There is no incidental, unrelated or prior
comparison-baseline change in that set. Tightening the Evidence projection is compatible with the old arbitrary-object response schema
under the governed old-client-to-new-server direction.

## Decision

ADR 0103 remains in force. One bounded exception is authorized during A0 pre-freeze Product closure only: Product API v2 may correct
the proven runtime/OpenAPI defects above when all known in-repository consumers migrate atomically, no supported external consumer
depends on the old behavior, every breaking diff is explicitly classified, and no unrelated breaking change is admitted.

The authorized scope is limited to:

- removal of false `422` declarations from Strategy and Backtest Product operations;
- exact `ProductErrorEnvelopeDto` schemas for their existing `400`, `404`, `409`, `500` and `503` responses;
- an exact Backtest Evidence DTO projection;
- generator consequences directly required by those corrections.

`contracts/product-api/v2/authorized-a0-corrections.json` is the one-shot mechanical authorization. It binds the immutable baseline Git
commit, old and corrected canonical Contract SHA256 values, Accepted ADR path, affected operations and exact diff shapes. The verifier
accepts the exception only when every value and the complete sorted breaking-diff set match; any changed contract bytes, different
baseline or unlisted break remain forbidden. It is not a generic allowlist or command-line waiver.

After A0 closure, Product API v2 is frozen under ADR 0103. Any later breaking change requires a new API major with continued support for
the old family.

## Consequences

- Runtime behavior, the canonical OpenAPI projection and the generated in-repository client describe one Product contract.
- All 48 mechanically breaking entries are auditable as one bounded correction; unauthorized breaking changes remain zero.
- ADR 0103's long-term compatibility direction and prohibition on gate waiver flags remain unchanged.
- Product semantic identities remain independent of API version, Git and Contract fingerprints.

## Rejected alternatives

- Silently ignoring or broadly superseding ADR 0103.
- Preserving knowingly false OpenAPI behavior indefinitely.
- Creating Product API v3 without a real supported-consumer compatibility obligation.
- Allowing broad cleanup or a reusable breaking-change allowlist under this exception.

