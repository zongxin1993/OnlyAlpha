# Watchlist Product Contract

Watchlists are durable Owner presentation configuration. They own list names, ordered membership and an exact Source reference.
They own no Market Data, Research, Runtime, permission, execution or trading facts. The existing authorities remain unchanged.

## Configuration and ownership

One book belongs to the verified deployment semantic-store namespace and its single Owner. Authorized browsers share that book.
A list has a canonical UUID4, a nonempty name, one exact Integration Revision/type reference and ordered canonical Instrument IDs.
Names and list IDs are unique within a book; members are unique within a list. Source is a read context, never Instrument identity.
Current bounds are 20 lists, 100 members per list, 200 total members and 64 characters per name. These are admission/resource bounds.

`GET /api/v2/watchlists` reads the current configuration. Version zero means that this namespace has no configuration revisions.
Missing head with existing history, a stale head, a history gap, malformed data or inconsistent fingerprints/receipts is corruption,
not an empty book. No reader guesses a replacement head. Names/order may evolve; previous committed revisions remain immutable.

`PUT /api/v2/watchlists` submits schema version 1, one global Product Command UUID4, expected book version and the intended lists.
The owning transaction verifies the current head/history, inserts the immutable revision, updates the head, and commits the existing
global Product Command Admission/Receipt together. Failed validation/version checks commit no effect. Reusing a Command ID for a
changed intent or another family is a conflict. Exact replay returns the original revision, even after later edits.

`GET /api/v2/watchlists/commands/{command_id}` resolves an uncertain submit through the same global binding and exact revision.
An admission without a verified outcome is UNKNOWN. It must not cause a new identity, blind resubmission or success feedback.
A normal UI action retains its pending Command ID until the owning Query and a refreshed configuration resolve the uncertainty.
Concurrent browser edits require expected-version checks; the losing browser reloads explicitly instead of overwriting another edit.

New Sources/members are verified through existing Source/reference authorities. Unavailable existing references remain retained and
can still be renamed or removed. Rebinding requires an explicit UI action and validation of all retained members; no automatic
latest Revision, alternate Source, first instrument or cross-market substitution is permitted.

## Authorization and HTTP lifecycle

The current Shipping dev entry explicitly grants its single authenticated dev Owner Watchlist configuration access. This policy is
separate from Source read grants; local read bearer credentials do not confer Watchlist read/write permission. Anonymous API
composition cannot issue an Owner session. The browser requires the configured local Owner session and never forwards a read bearer.

The dev ingress checks exact Host/Origin and bounded JSON before PUT admission, rejects duplicate keys, and retains accepted work
behind its existing disconnect/withdrawal fence. A detached response does not roll back an already accepted Command. The write body
is at most 128 KiB and shares existing bounded read/work capacity; the body handshake remains five seconds. This is not a new
production authentication system and grants no Research, acquisition, trading or LIVE authority.

## Price Query and presentation

`GET /api/v2/market-data/latest-bar` is a read-only, protected Market Data Query over an exact Source, Instrument and native Bar semantic.
It selects the most recent sealed scope in the exact range family, then uses the existing owning range reader for Revision/Manifest/
Seal, segment and physical-proof admission. It returns a normal one-Bar `BEFORE_TIME` projection with explicit resolved time and
history evidence. Null means no sealed history for that exact family, not certified absence of external facts. Corrupt or unavailable
proof is an error; it never falls back to an older revision. Querying never starts acquisition or a stream.

List prices preserve exact decimal strings and show Bar end time, history/availability state and explicit stale/unobserved status.
A historical close is never labeled a latest trade or a certified live quote. The semantic is Source-native and independent of the
main chart period. Only visible rows in the active panel/document reobserve; one serialized read bounds list query concurrency.
The next observation is scheduled 15 seconds after completion, not a market-freshness or end-to-end latency guarantee. Hiding a row,
panel or document aborts its request and stops its scheduling; retained values are visibly unrefreshed.

Adding a member never acquires data. Selecting a member preserves chart period/type and Study parameters and loads through the
existing chart reader. Missing history is visible; a separate normal UI preparation action explicitly authorizes the existing
acquisition path. A separate explicit native-price preparation action queries a one-Bar native window and submits only its server-planned missing ranges through the existing acquisition API. It does not alter the chart or acquire on adding/selecting a member. Submitted/incomplete/failed observations remain distinct; no automatic acquisition retry is introduced. Unsupported periods fail visibly instead of silently changing the user's configuration.

## Persistence evolution

Migration 0051 requires the exact prior migration prefix. Additive DDL and its checksum commit atomically; a failure rolls back the
migration and a restart uses the existing checksummed ledger. Existing application/market facts are not transformed or deleted.
Older binaries may not write this family. Once revisions exist, rollback requires stopping writers and retaining a current owning
reader or forward-fixing; dropping history or reinitializing a deployment is not rollback. Current repository consumers evolve together.
