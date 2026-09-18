DO $$
BEGIN
    IF EXISTS (SELECT FROM private_alpha_asset LIMIT 1)
       OR EXISTS (SELECT FROM private_alpha_draft LIMIT 1)
       OR EXISTS (SELECT FROM private_alpha_revision LIMIT 1)
       OR EXISTS (SELECT FROM private_strategy_asset LIMIT 1)
       OR EXISTS (SELECT FROM private_strategy_draft LIMIT 1)
       OR EXISTS (SELECT FROM private_strategy_revision LIMIT 1) THEN
        RAISE EXCEPTION 'Private Factor vocabulary migration requires empty development authoring tables; export/reset/re-import through current Authority';
    END IF;
END
$$;

ALTER TABLE private_alpha_draft RENAME TO private_factor_draft;
ALTER TABLE private_alpha_revision RENAME TO private_factor_revision;
ALTER TABLE private_alpha_asset RENAME TO private_factor_asset;

ALTER TABLE private_factor_asset RENAME COLUMN alpha_id TO factor_id;
ALTER TABLE private_factor_draft RENAME COLUMN alpha_id TO factor_id;
ALTER TABLE private_factor_revision RENAME COLUMN alpha_id TO factor_id;

ALTER TABLE private_factor_asset RENAME CONSTRAINT private_alpha_asset_pkey TO private_factor_asset_pkey;
ALTER TABLE private_factor_asset RENAME CONSTRAINT private_alpha_asset_alpha_id_check TO private_factor_asset_factor_id_check;
ALTER TABLE private_factor_asset RENAME CONSTRAINT private_alpha_asset_schema_version_check TO private_factor_asset_schema_version_check;
ALTER TABLE private_factor_asset RENAME CONSTRAINT private_alpha_asset_current_revision_fk TO private_factor_asset_current_revision_fk;

ALTER TABLE private_factor_draft RENAME CONSTRAINT private_alpha_draft_pkey TO private_factor_draft_pkey;
ALTER TABLE private_factor_draft RENAME CONSTRAINT private_alpha_draft_alpha_id_fkey TO private_factor_draft_factor_id_fkey;
ALTER TABLE private_factor_draft RENAME CONSTRAINT private_alpha_draft_base_revision_fk TO private_factor_draft_base_revision_fk;
ALTER TABLE private_factor_draft RENAME CONSTRAINT private_alpha_draft_schema_version_check TO private_factor_draft_schema_version_check;

ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_pkey TO private_factor_revision_pkey;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_alpha_id_fkey TO private_factor_revision_factor_id_fkey;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_alpha_id_revision_fingerprint_key TO private_factor_revision_factor_id_revision_fingerprint_key;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_parent_fk TO private_factor_revision_parent_fk;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_revision_fingerprint_check TO private_factor_revision_revision_fingerprint_check;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_source_sha256_check TO private_factor_revision_source_sha256_check;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_source_text_check TO private_factor_revision_source_text_check;
ALTER TABLE private_factor_revision RENAME CONSTRAINT private_alpha_revision_schema_version_check TO private_factor_revision_schema_version_check;

ALTER TABLE private_factor_asset DROP CONSTRAINT private_factor_asset_factor_id_check;
ALTER TABLE private_factor_asset
    ADD CONSTRAINT private_factor_asset_factor_id_check
    CHECK (factor_id ~ '^private\.factor\.[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$');

ALTER TRIGGER private_alpha_revision_immutable_trigger ON private_factor_revision
    RENAME TO private_factor_revision_immutable_trigger;
