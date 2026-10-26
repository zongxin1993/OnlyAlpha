# Watchlist Product Contract

Watchlists are durable Owner presentation configuration. They own list names, ordered membership with an exact Source reference per member.
They own no Market Data, Research, Runtime, permission, execution or trading facts. The existing authorities remain unchanged.

## Configuration and ownership

One book belongs to the verified deployment semantic-store namespace and its single Owner. Authorized browsers share that book.
A list has a canonical UUID4, a nonempty name and ordered members. Each member binds one exact Integration Revision/type reference
to one canonical Instrument ID. Names and list IDs are unique within a book; members are unique by the full exact Source reference
and Instrument ID within a list. Lists may mix markets and Sources; the same Instrument ID from different Sources remains distinct.
Source is a read context, never Instrument identity.
Current bounds are 20 lists, 100 members per list, 200 total members and 64 characters per name. These are admission/resource bounds.

`GET /api/v2/watchlists` reads the current configuration. Version zero means that this namespace has no configuration revisions.
Missing head with existing history, a stale head, a history gap, malformed data or inconsistent fingerprints/receipts is corruption,
not an empty book. No reader guesses a replacement head. Names/order may evolve; previous committed revisions remain immutable.

`PUT /api/v2/watchlists` submits schema version 2 (list `members` each contain `source` and `instrument_id`), one global Product Command UUID4, expected book version and the intended lists.
The owning transaction verifies the current head/history, inserts the immutable revision, updates the head, and commits the existing
global Product Command Admission/Receipt together. Failed validation/version checks commit no effect. Reusing a Command ID for a
changed intent or another family is a conflict. Exact replay returns the original revision, even after later edits.

`GET /api/v2/watchlists/commands/{command_id}` resolves an uncertain submit through the same global binding and exact revision.
An admission without a verified outcome is UNKNOWN. It must not cause a new identity, blind resubmission or success feedback.
A normal UI action retains its pending Command ID until the owning Query and a refreshed configuration resolve the uncertainty.
Concurrent browser edits require expected-version checks; the losing browser reloads explicitly instead of overwriting another edit.

New Sources/members are verified through existing Source/reference authorities. Unavailable existing references remain retained and
can still be renamed or removed. Changing a member Source creates a different member and requires explicit UI intent and validation; no automatic
latest Revision, alternate Source, first instrument or cross-market substitution is permitted.

## Authorization and HTTP lifecycle

The current Shipping dev entry explicitly grants its single authenticated dev Owner Watchlist configuration access. This policy is
separate from Source read grants; local read bearer credentials do not confer Watchlist read/write permission. Anonymous API
composition cannot issue an Owner session. The browser requires the configured local Owner session and never forwards a read bearer.

The dev ingress checks exact Host/Origin and bounded JSON before PUT admission, rejects duplicate keys, and retains accepted work
behind its existing disconnect/withdrawal fence. A detached response does not roll back an already accepted Command. The write body
is at most 128 KiB and shares existing bounded read/work capacity; the body handshake remains five seconds. This is not a new
production authentication system and grants no Research, acquisition, trading or LIVE authority.

## Search stars and ordinary presentation

The top-left symbol search is the discovery and membership entry. Each result has a star bound to the exact Instrument and Source.
Starring changes only the current list's membership; it does not select a chart or acquire historical Bars. The first star in an
empty book creates the ordinary default list named `自选` in the same owning Command. With multiple lists, the active list is explicit.
The sidebar normally displays symbol, latest operational price and change percentage; Source identity and quote basis/time remain
available in the row details. List creation, rename, deletion and ordering are available through normal menus, not mandatory setup.

## Operational quotes and chart selection

`GET /api/v2/market-data/quotes` is a protected read-only operational Quote projection over an exact Source and at most 25 Instruments.
REALTIME_PREVIEW permission is required independently of CLOSED_HISTORY. A plugin owns its supported quote capability, exact decimal
price, change percentage, basis and event time. The Application validates response membership and finite numeric strings. The Web does
not calculate changes, infer market sessions or substitute historical Bar closes for latest prices. Missing values are `—`; timeout,
unsupported capability, unavailable Source and stale/unobserved values remain distinct from a successful observation.
`ROLLING_24H` identifies the crypto 24-hour basis; `PREVIOUS_CLOSE` identifies the previous trading-session close basis. A plugin must
provide the actual basis rather than the browser assigning it from an asset name. Operational quotes are not sealed Market Data facts,
Research Evidence, certified absence or an execution permission.

Visible rows in the active panel/document are grouped by exact Source, in serialized batches of at most 25. The next cycle begins
15 seconds after completion, not a freshness guarantee. Hiding a row, panel or document cancels observation; retained values are visibly
unrefreshed. Transport failure retains any previous value only with a stale warning and its original event time.
The existing `GET /api/v2/market-data/latest-bar` remains a sealed historical-Bar reader; it is not the sidebar latest-price source.

Selecting a search result or sidebar member preserves chart period/type and Study parameters, then uses the existing chart reader.
The chart reads temporary Provider data into bounded memory through the versioned chart Product API. Selection, quote observation,
adding a member and viewport history do not authorize Acquisition, Recorder/WAL persistence or mixing with retained history.
Formal collection remains an explicit, separate operation through its normal Product UI and owning Authority.
Unsupported periods and stale Source bindings fail visibly without changing period, substituting latest Revision or switching Source.
Already selected healthy exact chart contexts remain unchanged. Replaced contexts fence every late response, including A→B→A.
Command uncertainty is resolved through the owning identity rather than a blind new-effect retry. Loading, partial coverage and failed
observations remain visible; a temporary complete window certifies only its exact display input, never sealed history or Research Evidence.

## Persistence evolution

Migration 0051 requires the exact prior migration prefix. Additive DDL and its checksum commit atomically; a failure rolls back the
migration and a restart uses the existing checksummed ledger. Existing application/market facts are not transformed or deleted.
Older binaries may not write this family. Once revisions exist, rollback requires stopping writers and retaining a current owning
reader or forward-fixing; dropping history or reinitializing a deployment is not rollback. Current repository consumers evolve together.


Migration 0052 requires the exact prefix through 0051 and introduces explicit `representation_version` metadata. Existing rows are
marked representation 1 without changing their payload, fingerprint, Command admission or receipt; new writes explicitly use
representation 2. The column has no write default, so old writers cannot silently append old-format revisions after upgrade.
The current owning reader validates original payload structure, bounds, exact Source, original book fingerprint and original Command
intent/receipt before deterministically projecting an old list Source onto each ordered member. This is the required reader for
immutable historical facts and exact replay, not an old API or old binary compatibility path. The external API rejects schema 1.
An exact committed replay returns the projected original outcome and retains its original receipt, even after later edits.
For outcome-less old admissions, UNKNOWN is retained only when the original fingerprint can be proved from the submitted intent;
missing historical Source on an empty old list cannot be reconstructed and must never be guessed. Such a resubmission conflicts;
the Command Query continues to report UNKNOWN. No resubmission creates a second effect. Migration DDL/checksum are transactional;
restart follows the ledger. Stop writers before upgrading; preserve history/current readers or forward-fix instead of clearing data.
