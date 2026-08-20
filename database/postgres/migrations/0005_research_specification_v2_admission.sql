ALTER TABLE research_run
    DROP CONSTRAINT research_run_specification_schema_version_check;

ALTER TABLE research_run
    ADD CONSTRAINT research_run_specification_schema_version_check
    CHECK (specification_schema_version IN (1, 2));
