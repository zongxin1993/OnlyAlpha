ALTER TABLE research_run
    ADD COLUMN authoring_provenance JSONB NULL,
    ADD CONSTRAINT research_run_authoring_provenance_object CHECK (
        authoring_provenance IS NULL OR jsonb_typeof(authoring_provenance) = 'object'
    );
