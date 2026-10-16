-- Precondition: exact checksummed prefix through 0051; stop old writers before upgrade.
-- No immutable payload, fingerprint, admission or receipt is rewritten. Existing facts
-- receive explicit representation 1 metadata; new owning writers must declare version 2.
-- The current reader verifies original evidence before deterministic member projection.
-- DDL/ledger are one transaction: failure rolls back; restart is ledger-idempotent.
-- Old binaries cannot write after migration. Rollback requires stopping writers and
-- preserving this owning reader or a forward fix; never drop or reinitialize history.
ALTER TABLE watchlist_revision ADD COLUMN representation_version SMALLINT NOT NULL DEFAULT 1
    CHECK (representation_version IN (1, 2));
ALTER TABLE watchlist_revision ALTER COLUMN representation_version DROP DEFAULT;
